"""Opt-in, bounded section context assembly; no model calls or query rewriting.

This experimental assembler is deliberately not wired into the default retriever.
The caller supplies authoritative chunks and the sealed MinerU section mapping.
"""
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
import re

from literature_rag.application.context import ContextOptions, join_chunks
from literature_rag.domain.models import Chunk, Evidence, EvidenceSource

VERSION = 'section-context-v1'
TABLE_REF = re.compile(r'\bTable\s*([Ss]?\d+)\b', re.I)


class SectionCatalog:
    def __init__(self, chunks: Sequence[Chunk], structure: Mapping):
        self.chunks = {c.id: c for c in chunks}
        self.mapping = structure['mapping']
        nodes = structure['sections']
        self.sections = {n['id']: n for n in nodes}
        if len(self.chunks) != len(chunks) or len(self.sections) != len(nodes):
            raise ValueError('Duplicate chunk or section')
        if set(self.mapping) != set(self.chunks):
            raise ValueError('Section mapping must exactly cover authoritative chunks')
        self.members = defaultdict(list)
        self.documents = defaultdict(list)
        seen = set()
        owners = {}
        for c in sorted(chunks, key=lambda c: (c.document_id, c.chunk_index)):
            m = self.mapping[c.id]
            if (c.document_id, c.chunk_index) in seen:
                raise ValueError('Duplicate document chunk index')
            seen.add((c.document_id, c.chunk_index))
            if (sha256(c.text.encode()).hexdigest() != m['text_sha256'] or
                    (c.page_start, c.page_end, c.kind) != (m['page_start'], m['page_end'], m['kind'])):
                raise ValueError('Section source does not match authoritative text or locator')
            sid = m.get('section_id')
            if sid is not None:
                if sid not in self.sections:
                    raise ValueError('Unknown section')
                if owners.setdefault(sid, c.document_id) != c.document_id:
                    raise ValueError('Section cannot span documents')
                self.members[(c.document_id, sid)].append(c)
            self.documents[c.document_id].append(c)

    def trusted(self, c):
        m = self.mapping[c.id]
        node = self.sections.get(m.get('section_id'))
        return bool(node and node['status'] == m.get('section_status') == 'inferred'
                    and node.get('role') != 'references' and c.kind != 'reference')

    def candidates(self, seed, radius):
        c = self.chunks[seed.chunk_id]
        if not self.trusted(c):
            neighbors = [n for n in self.documents[c.document_id]
                         if (n.page_start, n.page_end) == (c.page_start, c.page_end)
                         and abs(n.chunk_index-c.chunk_index) <= radius]
            if c.kind == 'table':
                neighbors = [c]
            return None, neighbors, 'same_page_fallback'
        sid = self.mapping[c.id]['section_id']
        members = [n for n in self.members[(c.document_id, sid)] if n.kind != 'reference']
        # Explicit table references are structural links, not inferred scientific claims.
        wanted = {x.upper() for x in TABLE_REF.findall(c.text)} if c.kind != 'table' else set()
        linked = []
        for n in self.documents[c.document_id]:
            label = TABLE_REF.search(n.text) if n.kind == 'table' else None
            if label and label[1].upper() in wanted:
                linked.append(n)
        if c.kind == 'table':
            label = TABLE_REF.search(c.text)
            if label:
                linked += [n for n in members if n.kind == 'paragraph'
                           and label[1].upper() in {v.upper() for v in TABLE_REF.findall(n.text)}]
        priority = {n.id for n in linked}
        unique = {n.id: n for n in [*members, *linked]}
        ordered = sorted(unique.values(), key=lambda n: (
            0 if n.id in priority else 1, abs(n.chunk_index-c.chunk_index), n.chunk_index))
        return sid, ordered, 'section'


def assemble_sections(seeds: Sequence[Evidence], catalog: SectionCatalog, options: ContextOptions):
    if not options.enabled:
        raise ValueError('Section experiment requires context assembly enabled')
    if len({e.chunk_id for e in seeds}) != len(seeds):
        raise ValueError('Duplicate primary hit')
    groups = {}
    decisions = []
    for rank, e in enumerate(seeds):
        c = catalog.chunks.get(e.chunk_id)
        if c is None or (e.text, e.document_id, e.page_start, e.page_end) != (
                c.text, c.document_id, c.page_start, c.page_end):
            raise ValueError('Primary hit differs from authoritative source')
        if not c.text.strip() or len(c.text) > options.max_evidence_chars:
            raise ValueError('Primary hit cannot fit; never truncate or silently discard it')
        sid, candidates, mode = catalog.candidates(e, options.radius)
        key = (e.document_id, sid or e.chunk_id)
        group = groups.setdefault(key, dict(hits=[], candidates=[]))
        group['hits'].append((rank, e))
        group['candidates'].extend(candidates)
        decisions.append(dict(seed_chunk_id=e.chunk_id, section_id=sid, mode=mode,
                              candidate_chunk_ids=[n.id for n in candidates]))
    ordered = sorted(groups.values(), key=lambda g: g['hits'][0][0])
    # A large section with several primary hits may need several evidence entries.
    split = []
    for g in ordered:
        primary = [catalog.chunks[e.chunk_id] for _, e in g['hits']]
        if len(join_chunks(sorted(primary, key=lambda n: n.chunk_index))) > options.max_evidence_chars:
            split.extend(dict(hits=[h], candidates=g['candidates']) for h in g['hits'])
        else:
            split.append(g)
    split.sort(key=lambda g: min(rank for rank, _ in g['hits']))
    order = lambda ns: sorted(ns, key=lambda n: n.chunk_index)
    selections = [[catalog.chunks[e.chunk_id] for _, e in g['hits']] for g in split]
    sizes = [len(join_chunks(order(ns))) for ns in selections]
    total = sum(sizes)
    if total > options.max_total_chars:
        raise ValueError('Primary hits exceed total budget; do not lose source evidence')
    occupied = {e.chunk_id for e in seeds}
    skipped = set()
    # All primary hits have already reserved their full space before expansion.
    for i, g in enumerate(split):
        for c in g['candidates']:
            if c.id in occupied:
                continue
            proposed = len(join_chunks(order([*selections[i], c])))
            if proposed > options.max_evidence_chars or total-sizes[i]+proposed > options.max_total_chars:
                skipped.add(c.id)
                continue
            selections[i].append(c)
            occupied.add(c.id)
            total += proposed-sizes[i]
            sizes[i] = proposed
    results = []
    for group, selected in zip(split, selections):
        chunks = order(selected)
        hits = sorted(group['hits'])
        anchor = hits[0][1]
        results.append(replace(anchor, ref=f'[{len(results)+1}]', text=join_chunks(chunks),
            page_start=min(c.page_start for c in chunks), page_end=max(c.page_end for c in chunks),
            source_chunks=tuple(EvidenceSource(c.id, c.chunk_index, c.page_start, c.page_end, c.text, c.kind)
                                for c in chunks),
            seed_chunk_ids=tuple(e.chunk_id for _, e in hits), context_status='section_expanded'))
    primary_ids = {e.chunk_id for e in seeds}
    info = dict(version=VERSION, enabled=True, radius=options.radius,
                max_evidence_chars=options.max_evidence_chars, max_total_chars=options.max_total_chars,
                seed_chunk_ids=[e.chunk_id for e in seeds], omitted_seed_chunk_ids=[],
                result_count=len(results), context_chars=total, budget_limited=bool(skipped-occupied),
                added_chunk_ids=[s.chunk_id for e in results for s in e.source_chunks if s.chunk_id not in primary_ids],
                skipped_candidate_chunk_ids=sorted(skipped-occupied), decisions=decisions)
    return results, info
