"""Opt-in table-row retrieval mapped back to immutable, full source tables."""
from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
import json
from math import fsum, isfinite, sqrt
from pathlib import Path

from literature_rag.domain.errors import InfrastructureError
from literature_rag.domain.models import EvidenceSource, VectorMatch

VERSION = 'table-evidence-v1'
BODY_TABLE_VERSION = 'body-section-table-evidence-v1'


class TableRelations:
    def __init__(self, manifest: dict, metadata, vectors: dict | None = None):
        if manifest.get('version') != VERSION:
            raise InfrastructureError('unsupported table evidence manifest')
        self.manifest = manifest
        self.rows = manifest['rows']
        self.links = manifest['links']
        self.metadata = metadata
        self.by_id = {row['id']: row for row in self.rows}
        if len(self.by_id) != len(self.rows) or len(self.rows) > 10000:
            raise InfrastructureError('invalid table row identifiers or row count')
        expected = manifest['parent_text_sha256']
        ids = set(expected)
        ids.update(link['source_chunk_id'] for link in self.links)
        ids.update(link['target_chunk_id'] for link in self.links)
        chunks = {c.id: c for c in metadata.get_chunks(sorted(ids))}
        if set(chunks) != ids:
            raise InfrastructureError('table links reference missing source chunks')
        for cid, checksum in expected.items():
            if sha256(chunks[cid].text.encode()).hexdigest() != checksum or chunks[cid].kind != 'table':
                raise InfrastructureError('full table differs from sealed row index')
        for row in self.rows:
            if row['parent_chunk_id'] not in expected:
                raise InfrastructureError('row has no sealed full-table parent')
        for link in self.links:
            a, b = chunks[link['source_chunk_id']], chunks[link['target_chunk_id']]
            if a.document_id != b.document_id or {a.kind,b.kind} != {'paragraph','table'}:
                raise InfrastructureError('invalid cross-document or non-table relationship')
        self.chunks = chunks
        self.vectors = vectors or {}
        if vectors is not None and set(vectors) != set(self.by_id):
            raise InfrastructureError('row vectors do not match the row manifest')
        dims = manifest['embedding']['dimensions']
        for vector in self.vectors.values():
            if len(vector) != dims or any(type(x) not in (int,float) or not isfinite(x) for x in vector) or fsum(x*x for x in vector) <= 0:
                raise InfrastructureError('invalid row embedding')

    def validate_body_catalog(self, catalog):
        """A role-aware pipeline must never load legacy links from abstract/metadata."""
        for cid, chunk in self.chunks.items():
            source = catalog.chunks.get(cid)
            if source is None or (source.text, source.document_id, source.page_start, source.page_end,
                    source.kind, source.chunk_index) != (chunk.text, chunk.document_id, chunk.page_start,
                    chunk.page_end, chunk.kind, chunk.chunk_index):
                raise InfrastructureError('table sources differ from the body-section catalog')
        for row in self.rows:
            parent = catalog.mapping[row['parent_chunk_id']]
            if parent['content_role'] != 'table' or parent['role_status'] != 'identified':
                raise InfrastructureError('row retrieval requires an identified source table')
        for link in self.links:
            a, b = (catalog.mapping[link[key]] for key in ('source_chunk_id', 'target_chunk_id'))
            if (a['role_status'] != 'identified' or b['role_status'] != 'identified'
                    or {a['content_role'], b['content_role']} != {'body', 'table'}):
                raise InfrastructureError('table links require identified body and table roles')

    @classmethod
    def load(cls, root: Path, metadata, provider, model, dimensions):
        root = Path(root)
        try:
            manifest = json.loads((root/'table-retrieval.json').read_text(encoding='utf-8'))
            payload = (root/'table-row-vectors.json').read_bytes()
            if sha256(payload).hexdigest() != manifest['row_vectors_sha256']:
                raise InfrastructureError('row embedding checksum mismatch')
            if manifest['embedding'] != dict(provider=provider, model=model, dimensions=dimensions):
                raise InfrastructureError('row embedding model mismatch')
            rows = json.loads(payload)['rows']
            vectors = {row['id']: row['vector'] for row in rows}
            if len(vectors) != len(rows):
                raise InfrastructureError('duplicate row vector')
            return cls(manifest, metadata, vectors)
        except InfrastructureError:
            raise
        except (ValueError, KeyError, OSError, TypeError) as error:
            raise InfrastructureError('cannot load table evidence sidecar') from error

    def targets(self, source_ids):
        selected = set(source_ids)
        seen = set()
        for link in self.links:
            if link['source_chunk_id'] in selected and link['target_chunk_id'] not in seen:
                seen.add(link['target_chunk_id'])
                yield self.chunks[link['target_chunk_id']], link


class TableVectorSearch:
    """Same query embedding; exact cosine for the small row sidecar; max-score parent fusion."""
    def __init__(self, base, relations: TableRelations):
        self.base, self.relations = base, relations
        self.last_diagnostics = {}

    def search(self, query_embedding: Sequence[float], top_k: int):
        if len(query_embedding) != self.relations.manifest['embedding']['dimensions'] or any(type(v) not in (int,float) or not isfinite(v) for v in query_embedding):
            raise InfrastructureError('invalid table query vector')
        norm = sqrt(fsum(v*v for v in query_embedding))
        if not norm:
            raise InfrastructureError('zero table query vector')
        base = self.base.search(query_embedding, top_k)
        parents = {m.chunk_id:m.score for m in base}
        hits = []
        for row in self.relations.rows:
            vector = self.relations.vectors[row['id']]
            score = max(0.,min(1.,fsum(a*b for a,b in zip(query_embedding,vector,strict=True))/(norm*sqrt(fsum(x*x for x in vector)))))
            cid = row['parent_chunk_id']
            parents[cid] = max(score,parents.get(cid,0.))
            hits.append(dict(row_id=row['id'],parent_chunk_id=cid,score=score))
        # Parent deduplication happens before the top50 limit, so 10 rows cannot consume 10 slots.
        candidates = sorted(parents.items(),key=lambda item:(-item[1],item[0]))[:top_k]
        self.last_diagnostics = dict(enabled=True,version=VERSION,base_candidates=len(base),
            row_candidates=len(hits),parent_candidates=len(candidates),
            fusion='maximum cosine per full-table parent; no reranker',
            row_hits=sorted(hits,key=lambda item:(-item['score'],item['row_id'])),
            candidates=[dict(chunk_id=cid,score=score) for cid,score in candidates],
            query_embedding_calls=1)
        return [VectorMatch(cid,score) for cid,score in candidates]


def append_related_tables(evidences, relations: TableRelations, options, diagnostics, *, body_catalog=None):
    """Add complete linked sources after existing context; preserve original hits and budgets."""
    if body_catalog is not None:
        relations.validate_body_catalog(body_catalog)
    result = list(evidences)
    present = {s.chunk_id for e in result for s in e.source_chunks} | {e.chunk_id for e in result}
    total = sum(len(e.text) for e in result)
    additions, omitted = [], []
    # Links originate only in original/neighbor context; do not recursively traverse added sources.
    for evidence in evidences:
        source_ids = [s.chunk_id for s in evidence.source_chunks] or [evidence.chunk_id]
        count = 0
        for chunk, link in relations.targets(source_ids):
            if chunk.id in present:
                continue
            if count >= 2 or len(additions) >= 8:
                omitted.append(dict(chunk_id=chunk.id,reason='relationship_count_limit'))
                continue
            if len(chunk.text) > options.max_evidence_chars or total+len(chunk.text) > options.max_total_chars:
                omitted.append(dict(chunk_id=chunk.id,reason='length_budget'))
                continue
            source = EvidenceSource(chunk.id,chunk.chunk_index,chunk.page_start,chunk.page_end,chunk.text,chunk.kind)
            result.append(replace(evidence,ref=f'[{len(result)+1}]',chunk_id=chunk.id,document_id=chunk.document_id,
                filename=chunk.filename,page_start=chunk.page_start,page_end=chunk.page_end,text=chunk.text,
                source_chunks=(source,),seed_chunk_ids=evidence.seed_chunk_ids or (evidence.chunk_id,),
                context_status='linked_table' if chunk.kind=='table' else 'linked_table_explanation'))
            total += len(chunk.text)
            present.add(chunk.id)
            count += 1
            additions.append(dict(**link,score_policy='inherits triggering evidence score; no independent relevance score'))
    diagnostics.update(result_count=len(result),context_chars=total,
        table_relationship_additions=additions,table_relationship_omissions=omitted)
    diagnostics['added_chunk_ids'] = list(dict.fromkeys([*diagnostics.get('added_chunk_ids',[]),*[a['target_chunk_id'] for a in additions]]))
    diagnostics['budget_limited'] |= any(x['reason']=='length_budget' for x in omitted)
    if body_catalog is not None:
        diagnostics.update(version=BODY_TABLE_VERSION, table_link_policy='identified_body_table_only',
            table_links_recursive=False, table_hit_expansion='explicit_body_links_only',
            non_body_expansion=True, non_body_section_expansion=False, metadata_expansion=False)
    return result, diagnostics
