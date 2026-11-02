"""Re-embed existing source chunks and table rows in a separate, resumable library."""
from argparse import ArgumentParser
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from filelock import FileLock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.table_evidence import TableRelations
from literature_rag.config import Settings
from literature_rag.domain.models import VectorRecord
from freeze_qa_baseline import backup_database, library_fingerprint


def digest(path): return sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)


def plan(source):
    source=Path(source).resolve()
    store=SqliteMetadataStore(source/'metadata.sqlite3')
    documents=store.list_documents()
    if not documents or any(d.status.value!='completed' for d in documents):
        raise ValueError('Source must contain only completed documents')
    with closing(sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True)) as conn:
        ids=[row[0] for row in conn.execute('SELECT id FROM chunks ORDER BY document_id,chunk_index')]
    chunks=store.get_chunks(ids)
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    if structure.get('status')!='ready' or len(chunks)!=structure['chunks'] or len(chunks)!=sum(d.chunk_count for d in documents):
        raise ValueError('Source index is incomplete')
    for c in chunks:
        m=structure['mapping'][c.id]
        if m['text_sha256']!=sha256(c.text.encode()).hexdigest():
            raise ValueError('Original source text differs from structure mapping')
    for d in documents:
        p=(source/d.file_path).resolve()
        if not p.is_relative_to((source/'papers').resolve()) or digest(p)!=d.file_hash:
            raise ValueError('Source PDF identity/path changed')
    table=None
    if (source/'table-retrieval.json').exists():
        table=json.loads((source/'table-retrieval.json').read_text(encoding='utf-8'))
        e=table['embedding']
        TableRelations.load(source,store,e['provider'],e['model'],e['dimensions'])
    return documents,chunks,structure,table


def build(source,output,settings,*,resume=False,embedder=None,vector_factory=None):
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Use a separate independent output directory')
    if not settings.embedding_model or not settings.embedding_dimensions:
        raise ValueError('Embedding model and dimensions are required')
    if embedder is None:
        if not settings.embedding_api_key or not settings.embedding_api_key.get_secret_value().strip():
            raise ValueError('Configure the private embedding API key before building')
        if settings.embedding_provider=='dashscope':
            from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
            cls=DashScopeEmbedder
        elif settings.embedding_provider=='openai':
            from literature_rag.adapters.providers.openai import OpenAIEmbedder
            cls=OpenAIEmbedder
        else: raise ValueError('Unsupported embedding provider')
        embedder=cls(settings.embedding_model,settings.embedding_dimensions,
                     settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    if vector_factory is None:
        from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
        vector_factory=lambda p:ChromaVectorStore(p,settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    identity=dict(provider=settings.embedding_provider,model=settings.embedding_model,dimensions=settings.embedding_dimensions)
    with FileLock(str(source/'.import.lock'),timeout=0):
        documents,chunks,structure,table=plan(source)
        before=library_fingerprint(source)
        batch_size=min(settings.embedding_batch_size,20) if settings.embedding_provider=='dashscope' else settings.embedding_batch_size
        contract=dict(version='same-source-reembedding-v1',source_fingerprint=before,embedding=identity,
                      batch_size=batch_size,endpoint_sha256=sha256((settings.embedding_base_url or '').encode()).hexdigest(),
                      chunks=len(chunks),table_rows=len(table['rows']) if table else 0)
        ledger_path=output/'embedding-reindex.json'
        if output.exists():
            if not resume or not ledger_path.is_file(): raise ValueError('Existing destination requires explicit resume and a matching ledger')
            ledger=json.loads(ledger_path.read_text(encoding='utf-8'))
            if ledger['contract']!=contract: raise ValueError('Source or embedding configuration changed since build')
            if any(c['status']=='started' for c in ledger['calls']):
                raise ValueError('Interrupted paid request needs inspection; automatic replay refused')
            if ledger['status']=='ready':
                if (digest(output/'structure.json')!=ledger['output_structure_sha256'] or
                    digest(output/'metadata.sqlite3')!=ledger['output_metadata_sha256']):
                    raise ValueError('Completed output metadata or structure changed')
                return ledger
        else:
            output.mkdir(parents=True);(output/'papers').mkdir();(output/'embedding-cache').mkdir()
            backup_database(source/'metadata.sqlite3',output/'metadata.sqlite3')
            with closing(sqlite3.connect(output/'metadata.sqlite3')) as conn:
                with conn:
                    conn.execute('UPDATE chunks SET embedding_model=?',(settings.embedding_model,))
                    for d in documents:
                        relative=Path('papers')/(d.file_hash+'.pdf')
                        shutil.copy2(source/d.file_path,output/relative)
                        conn.execute('UPDATE documents SET file_path=? WHERE id=?',(relative.as_posix(),d.id))
            for name in ['source-pages.json','quality-ledger.json','native-source.json','chunk-organization.json']:
                if (source/name).exists(): shutil.copy2(source/name,output/name)
            structure.update(status='building',embedding_model=settings.embedding_model,
                embedding_dimensions=settings.embedding_dimensions,embedding_provider=settings.embedding_provider,
                embedding_migration=dict(source_structure_sha256=digest(source/'structure.json'),
                    preserved_chunk_ids=True,preserved_text=True,preserved_sections=True,preserved_roles=True,
                    images_indexed=False,version='same-source-reembedding-v1'))
            save(output/'structure.json',structure)
            if table is not None:
                table.update(embedding=identity,embedding_calls=[],row_vectors_sha256=None)
                save(output/'table-retrieval.json',table)
            ledger=dict(contract=contract,status='building',calls=[],text_only_index=True,source_unchanged=True)
            save(ledger_path,ledger)
        with FileLock(str(output/'.embedding.lock'),timeout=0):
            vectors=vector_factory(output/'chroma')
            try:
                groups=[('chunks',[dict(id=c.id,text=c.text) for c in chunks])]
                if table is not None: groups.append(('rows',table['rows']))
                row_vectors=[]
                for kind,items in groups:
                    for start in range(0,len(items),batch_size):
                        batch=items[start:start+batch_size];job=f'{kind}-{start:05}'
                        cache=output/'embedding-cache'/(job+'.json')
                        previous=[c for c in ledger['calls'] if c['job']==job]
                        good=next((c for c in previous if c['status']=='completed'),None)
                        if good:
                            if not cache.is_file() or digest(cache)!=good['cache_sha256']:
                                raise ValueError('Completed embedding cache changed')
                            data=json.loads(cache.read_text(encoding='utf-8'))
                        else:
                            call=dict(job=job,status='started',count=len(batch),usage=None,provider_calls=[])
                            ledger['calls'].append(call);save(ledger_path,ledger)
                            try:
                                values=embedder.embed_documents([item['text'] for item in batch])
                                if len(values)!=len(batch): raise ValueError('Embedding count mismatch')
                                data=dict(ids=[item['id'] for item in batch],vectors=values)
                                save(cache,data)
                                call.update(status='completed',cache_sha256=digest(cache))
                            except Exception:
                                call['status']='failed';raise
                            finally:
                                call.update(usage=getattr(embedder,'last_usage',None),provider_calls=getattr(embedder,'last_calls',[]))
                                save(ledger_path,ledger)
                        if data['ids']!=[item['id'] for item in batch]:raise ValueError('Embedding source IDs changed')
                        if kind=='chunks':
                            by_id={c.id:c for c in chunks}
                            records=[VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename)
                                     for c in (by_id[item['id']] for item in batch)]
                            vectors.upsert(records,data['vectors'])
                        else:
                            row_vectors.extend(dict(id=item['id'],vector=v) for item,v in zip(batch,data['vectors'],strict=True))
                current=json.loads((output/'structure.json').read_text(encoding='utf-8'))
                stored=vectors.collection.get(include=['documents','embeddings'])
                if (vectors.collection.count()!=len(chunks) or
                    dict(zip(stored['ids'],stored['documents'],strict=True))!={c.id:c.text for c in chunks} or
                    any(len(v)!=settings.embedding_dimensions for v in stored['embeddings'])):
                    raise ValueError('New vector count, text or dimensions differ from the source')
                if table is not None:
                    table=json.loads((output/'table-retrieval.json').read_text(encoding='utf-8'))
                    save(output/'table-row-vectors.json',dict(rows=row_vectors))
                    table.update(row_vectors_sha256=digest(output/'table-row-vectors.json'),
                        embedding_calls=[c for c in ledger['calls'] if c['job'].startswith('rows-')])
                    save(output/'table-retrieval.json',table)
                    TableRelations.load(output,SqliteMetadataStore(output/'metadata.sqlite3'),**identity)
                    current['table_evidence'].update(manifest_sha256=digest(output/'table-retrieval.json'),
                        vectors_sha256=table['row_vectors_sha256'])
                if library_fingerprint(source)!=before:raise ValueError('Source changed during re-embedding')
                current.update(status='ready',metadata_sha256=digest(output/'metadata.sqlite3'))
                save(output/'structure.json',current)
                ledger.update(status='ready',output_structure_sha256=digest(output/'structure.json'),
                              output_metadata_sha256=digest(output/'metadata.sqlite3'))
                save(ledger_path,ledger)
            except Exception:
                ledger['status']='failed';save(ledger_path,ledger);raise
    return ledger


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--output',type=Path)
    p.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.aliyun')
    p.add_argument('--embed',action='store_true');p.add_argument('--resume',action='store_true')
    a=p.parse_args()
    try:
        if a.embed:
            if a.output is None:raise ValueError('Provide an output directory')
            r=build(a.source_dir,a.output,Settings(_env_file=a.env_file),resume=a.resume)
            result=dict(status=r['status'],chunks=r['contract']['chunks'],table_rows=r['contract']['table_rows'],
                        embedding=r['contract']['embedding'],paid_batches=len(r['calls']))
        else:
            ds,cs,s,t=plan(a.source_dir)
            result=dict(chunks=len(cs),table_rows=len(t['rows']) if t else 0,documents=len(ds),provider_calls=0)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(status='failed',error_type=type(error).__name__,message='Inspect checkpoints; credentials and provider details are not printed.')))
        raise SystemExit(1)
