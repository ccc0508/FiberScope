"""Build an isolated role-classified MinerU index plus table rows; never activate it."""
from argparse import ArgumentParser
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['ANONYMIZED_TELEMETRY']='False'

from index_table_evidence import plan,save,digest
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.body_context import BodySectionCatalog
from literature_rag.application.table_evidence import TableRelations,BODY_TABLE_VERSION
from literature_rag.config import Settings
from literature_rag.domain.models import VectorRecord


def read_catalog(source):
    source=Path(source).resolve()
    metadata=SqliteMetadataStore(source/'metadata.sqlite3')
    catalog=BodySectionCatalog.load(source,metadata)
    with sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        ids={r[0] for r in db.execute('select id from chunks')}
    if ids!=set(catalog.chunks):raise ValueError('Role mapping must cover every SQLite chunk')
    return metadata,catalog


def build(source,output,env_file,assets_dir=None):
    source,output,env_file=Path(source).resolve(),Path(output).resolve(),Path(env_file).resolve()
    if output.exists() or output.is_relative_to(source):raise ValueError('Use a new independent output directory')
    source_hashes={p.name:digest(p) for p in (source/'structure.json',source/'metadata.sqlite3')}
    env_hash=digest(env_file)
    settings=Settings(_env_file=env_file)
    structure=json.loads((source/'structure.json').read_text('utf-8'))
    if structure.get('status')!='ready':raise ValueError('Source role library is not ready')
    if (structure['embedding_model'],structure['embedding_dimensions'])!=(settings.embedding_model,settings.embedding_dimensions):
        raise ValueError('Keep the source embedding model and dimensions')
    if not settings.embedding_api_key or not settings.embedding_api_key.get_secret_value().strip():
        raise ValueError('Embedding credentials are required')
    metadata,catalog=read_catalog(source)
    manifest=plan(source)
    if not manifest['rows']:raise ValueError('No verified table rows')
    assets=Path(assets_dir).resolve() if assets_dir else source
    documents=metadata.list_documents()
    for doc in documents:
        if doc.file_path.is_absolute() or '..' in doc.file_path.parts:raise ValueError('Use a relative paper path')
        paper=assets/doc.file_path
        if not paper.is_file() or digest(paper)!=doc.file_hash:raise ValueError('Original paper is missing or differs')
    snapshots=assets/'source-pages.json'
    if structure.get('source_pages_sha256') and (not snapshots.is_file() or digest(snapshots)!=structure['source_pages_sha256']):
        raise ValueError('Native page snapshots are missing or differ')
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    shutil.copytree(source,output)
    for doc in documents:
        target=output/doc.file_path;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(assets/doc.file_path,target)
    if snapshots.is_file() and not (output/'source-pages.json').exists():shutil.copyfile(snapshots,output/'source-pages.json')
    structure.update(status='building',vector_index_built=False,embedding_calls=[],
        pipeline_version=BODY_TABLE_VERSION,parent_role_structure_sha256=source_hashes['structure.json'],
        builder_sha256=digest(Path(__file__)),metadata_sha256=source_hashes['metadata.sqlite3'],
        activation='Independent opt-in body-section and table-row library; default environment unchanged.')
    manifest.update(embedding=dict(provider=settings.embedding_provider,model=settings.embedding_model,
        dimensions=settings.embedding_dimensions),embedding_calls=[])
    save(output/'structure.json',structure);save(output/'table-retrieval.json',manifest)
    try:
        embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,
            settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
        vectors=ChromaVectorStore(output/'chroma',settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
        chunks=sorted(catalog.chunks.values(),key=lambda c:(c.document_id,c.chunk_index))
        for start in range(0,len(chunks),settings.embedding_batch_size):
            batch=chunks[start:start+settings.embedding_batch_size]
            call=dict(status='started',chunk_count=len(batch),usage=None)
            structure['embedding_calls'].append(call);save(output/'structure.json',structure)
            try:
                values=embedder.embed_documents([c.text for c in batch])
                vectors.upsert([VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename) for c in batch],values)
                call['status']='completed'
            finally:
                call['usage']=getattr(embedder,'last_usage',None);save(output/'structure.json',structure)
        row_vectors=[]
        for start in range(0,len(manifest['rows']),settings.embedding_batch_size):
            batch=manifest['rows'][start:start+settings.embedding_batch_size]
            call=dict(status='started',row_count=len(batch),usage=None)
            manifest['embedding_calls'].append(call);save(output/'table-retrieval.json',manifest)
            try:
                values=embedder.embed_documents([r['text'] for r in batch])
                row_vectors.extend(dict(id=r['id'],vector=v) for r,v in zip(batch,values,strict=True))
                call['status']='completed'
            finally:
                call['usage']=getattr(embedder,'last_usage',None);save(output/'table-retrieval.json',manifest)
        save(output/'table-row-vectors.json',dict(rows=row_vectors))
        manifest['row_vectors_sha256']=digest(output/'table-row-vectors.json')
        save(output/'table-retrieval.json',manifest)
        relations=TableRelations.load(output,metadata,settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
        relations.validate_body_catalog(catalog)
        if vectors.collection.count()!=len(chunks):raise ValueError('Vector count differs from source chunks')
        stored=vectors.collection.get(include=['documents'])
        if dict(zip(stored['ids'],stored['documents'],strict=True))!={c.id:c.text for c in chunks}:
            raise ValueError('Vector source text differs from classified chunks')
        if any(digest(source/name)!=value for name,value in source_hashes.items()) or digest(env_file)!=env_hash:
            raise ValueError('Source library or default environment changed during build')
        structure.update(status='ready',vector_index_built=True,table_evidence=dict(version=manifest['version'],
            rows=len(manifest['rows']),links=len(manifest['links']),manifest_sha256=digest(output/'table-retrieval.json'),
            vectors_sha256=manifest['row_vectors_sha256'],source_structure_sha256=manifest['source_structure_sha256']))
        save(output/'structure.json',structure)
    except Exception:
        structure.update(status='failed',vector_index_built=False);save(output/'structure.json',structure)
        raise
    return dict(pipeline_version=BODY_TABLE_VERSION,status='ready',chunks=len(chunks),rows=len(manifest['rows']),
        links=len(manifest['links']),chunk_embedding_calls=structure['embedding_calls'],
        row_embedding_calls=manifest['embedding_calls'],source_unchanged=True,default_configuration_unchanged=True,
        generation_calls=0,judge_calls=0,currency_cost=None)


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--assets-dir',type=Path)
    parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    args=parser.parse_args()
    try:print(json.dumps(build(args.source_dir,args.output,args.env_file,args.assets_dir),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Build failed; previous libraries and settings are unchanged.')))
        raise SystemExit(1)
