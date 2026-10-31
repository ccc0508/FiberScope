"""Replay cached question vectors against the combined index; no answer/judge APIs."""
from argparse import ArgumentParser
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['ANONYMIZED_TELEMETRY']='False'
from build_mineru_body_tables import read_catalog
from index_table_evidence import digest,save
from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
from literature_rag.application.context import ContextOptions
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.table_evidence import TableRelations,TableVectorSearch,BODY_TABLE_VERSION
from literature_rag.config import Settings


def verify(library,query_cache,output,env_file):
    library,query_cache,output=Path(library).resolve(),Path(query_cache).resolve(),Path(output).resolve()
    if output.exists():raise ValueError('Preserve previous verification; use a new output path')
    settings=Settings(_env_file=env_file)
    env_hash=digest(env_file);metadata_hash=digest(library/'metadata.sqlite3')
    structure=json.loads((library/'structure.json').read_text('utf-8'))
    queries=json.loads(query_cache.read_text('utf-8'))
    seal=json.loads((query_cache.parent/'embedding-attempt.json').read_text('utf-8'))
    if seal['result_sha256']!=digest(query_cache):raise ValueError('Cached query vectors changed')
    if (queries['requested_model'],queries['dimensions'])!=(settings.embedding_model,settings.embedding_dimensions):
        raise ValueError('Cached question embedding model differs')
    if structure.get('status')!='ready' or not structure.get('vector_index_built'):raise ValueError('Index is not ready')
    if structure['table_evidence']['manifest_sha256']!=digest(library/'table-retrieval.json'):
        raise ValueError('Table manifest differs from completed index')
    metadata,catalog=read_catalog(library)
    relations=TableRelations.load(library,metadata,settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    relations.validate_body_catalog(catalog)
    vectors=TableVectorSearch(ChromaVectorStore(library/'chroma',settings.embedding_provider,
        settings.embedding_model,settings.embedding_dimensions),relations)
    class Cached:
        calls=0
        def embed_query(self,text):
            if text!=self.current['question'].strip():raise ValueError('Question changed')
            self.calls+=1
            return self.current['vector']
    cached=Cached()
    service=RetrievalService(metadata,vectors,cached,ContextOptions(True),relations,body_context_catalog=catalog)
    records=[];decisions=Counter();linked=0;table_seeds=0
    for query in queries['queries']:
        cached.current=query
        result=service.retrieve(query['question'],8,.35)
        seeds=service.last_seed_evidences;info=service.last_context_diagnostics
        primary={e.chunk_id for e in seeds};source_ids=[s.chunk_id for e in result for s in e.source_chunks]
        assert primary<=set(source_ids) and len(source_ids)==len(set(source_ids))
        assert len(seeds)<=8 and vectors.last_diagnostics['parent_candidates']<=50
        assert all(e.text.strip() and len(e.text)<=8000 for e in result) and sum(len(e.text) for e in result)<=24000
        assert all('程序生成的表格行检索表示' not in e.text for e in result)
        for e in seeds:
            m=catalog.mapping[e.chunk_id]
            if m['content_role']=='table':table_seeds+=1
            if m['role_status']!='identified' or m['content_role']!='body':
                own=next(e2 for e2 in result if e.chunk_id in e2.seed_chunk_ids and e2.chunk_id==e.chunk_id)
                assert own.text==e.text and [s.chunk_id for s in own.source_chunks]==[e.chunk_id]
        for cid in set(source_ids)-primary:
            m=catalog.mapping[cid]
            assert m['role_status']=='identified' and m['content_role'] in {'body','table','equation','figure_caption'}
        for d in info['decisions']:decisions[d['mode']]+=1
        linked+=len(info['table_relationship_additions'])
        records.append(dict(task_id=query['task_id'],question=query['question'],seeds=[asdict(e) for e in seeds],
            final=[asdict(e) for e in result],context=info))
    assert digest(env_file)==env_hash and digest(library/'metadata.sqlite3')==metadata_hash
    if len(records)!=32 or len({r['task_id'] for r in records})!=32:raise ValueError('Expected 32 unique cached tasks')
    result=dict(version=BODY_TABLE_VERSION,questions=len(records),chunks=len(catalog.chunks),
        rows=len(relations.rows),links=len(relations.links),decision_counts=dict(decisions),
        table_primary_hit_occurrences=table_seeds,explicit_link_additions=linked,
        all_primary_hits_preserved=True,no_duplicate_sources=True,all_character_budgets_passed=True,
        protected_non_body_hits_standalone=True,source_metadata_unchanged=True,default_configuration_unchanged=True,
        new_embedding_api_calls=0,cached_query_vector_lookups=cached.calls,new_generation_calls=0,new_judge_calls=0,
        quality_scores_produced=False,query_cache_sha256=digest(query_cache),structure_sha256=digest(library/'structure.json'),
        verifier_sha256=digest(Path(__file__)),records=records)
    output.parent.mkdir(parents=True,exist_ok=True);save(output,result)
    return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--query-cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    args=parser.parse_args()
    print(json.dumps(verify(args.library,args.query_cache,args.output,args.env_file),ensure_ascii=False))
