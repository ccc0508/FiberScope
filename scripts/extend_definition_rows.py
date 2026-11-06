"""Extend an isolated library's row sidecar, preserving sources and existing vectors."""
import argparse
import json
import shutil
from pathlib import Path
from hashlib import sha256

from index_table_evidence import ROOT, table_rows, save, digest
from literature_rag.config import Settings
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.body_context import BodySectionCatalog
from literature_rag.application.table_evidence import TableRelations
from literature_rag.application.visual_evidence import VisualCatalog


def build(source, output, env_file):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Use a new independent output directory')
    settings = Settings(_env_file=env_file)
    identity = dict(provider=settings.embedding_provider, model=settings.embedding_model,
                    dimensions=settings.embedding_dimensions)
    store = SqliteMetadataStore(source/'metadata.sqlite3')
    catalog = BodySectionCatalog.load(source, store)
    old = TableRelations.load(source, store, **identity)
    old.validate_body_catalog(catalog)
    new, skipped = [], []
    for c in catalog.chunks.values():
        m = catalog.mapping[c.id]
        if c.kind != 'table' or m['content_role'] != 'table' or m['role_status'] != 'identified':
            continue
        # Existing table representations remain frozen; extend previously uncovered tables.
        if c.id in old.manifest['parent_text_sha256']:
            continue
        try:
            new.extend(table_rows(c))
        except ValueError as error:
            skipped.append(dict(chunk_id=c.id, reason=str(error)))
    shutil.copytree(source, output, ignore=shutil.ignore_patterns('*.lock', '*-wal', '*-shm'))
    from freeze_qa_baseline import backup_database
    for name in ['metadata.sqlite3', 'chroma/chroma.sqlite3']:
        backup_database(source/name, output/name)
    save(output/'definition-row-build.json', dict(status='building', new_rows=len(new), skipped=skipped))
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
    cls = DashScopeEmbedder if settings.embedding_provider == 'dashscope' else OpenAIEmbedder
    embedder = cls(settings.embedding_model, settings.embedding_dimensions,
                   settings.embedding_api_key.get_secret_value(), settings.embedding_base_url)
    vectors = json.loads((output/'table-row-vectors.json').read_text('utf-8'))
    calls = []
    for start in range(0, len(new), 20):
        batch = new[start:start+20]
        values = embedder.embed_documents([r['text'] for r in batch])
        calls.append(dict(rows=len(batch), usage=embedder.last_usage))
        vectors['rows'].extend(dict(id=r['id'], vector=v) for r, v in zip(batch, values, strict=True))
        save(output/f'definition-row-batch-{start}.json', dict(rows=[r['id'] for r in batch], vectors=values, usage=embedder.last_usage))
    manifest = old.manifest
    manifest['rows'].extend(new)
    for r in new:
        cid = r['parent_chunk_id']
        manifest['parent_text_sha256'][cid] = sha256(catalog.chunks[cid].text.encode()).hexdigest()
    save(output/'table-row-vectors.json', vectors)
    manifest['row_vectors_sha256'] = digest(output/'table-row-vectors.json')
    save(output/'table-retrieval.json', manifest)
    # Structure and all full sources stay byte-identical; existing image seals remain valid.
    target_store = SqliteMetadataStore(output/'metadata.sqlite3')
    verified = TableRelations.load(output, target_store, **identity)
    verified.validate_body_catalog(BodySectionCatalog.load(output, target_store))
    VisualCatalog.load(output, target_store, **identity)
    result = dict(status='verified', source=str(source), new_rows=len(new), total_rows=len(verified.rows),
                  added_tables=len({r['parent_chunk_id'] for r in new}), skipped=skipped, embedding_calls=calls)
    save(output/'definition-row-build.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--env-file', type=Path, default=ROOT/'backend/.env.literature')
    args = p.parse_args()
    print(json.dumps(build(args.source, args.output, args.env_file), ensure_ascii=False))
