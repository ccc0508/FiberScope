"""One explicit rerank API probe on the combined MinerU pipeline, without QA generation."""
from argparse import ArgumentParser
from dataclasses import asdict
from datetime import datetime,timezone
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
from literature_rag.adapters.providers.rerank import SiliconFlowReranker
from literature_rag.application.context import ContextOptions
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.table_evidence import TableRelations,TableVectorSearch
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot


def probe(library,query_cache,task_id,env_file,output):
    library,query_cache,env_file,output=map(lambda p:Path(p).resolve(),(library,query_cache,env_file,output))
    if output.exists():raise ValueError('Keep prior calls; use a new output path for a deliberate new probe')
    settings=Settings(_env_file=env_file)
    if not (settings.rerank_enabled and settings.table_retrieval_enabled
            and settings.context_expansion_enabled and settings.context_expansion_strategy=='body_section'):
        raise ValueError('Enable reranking, table rows and unified scientific context')
    cache=json.loads(query_cache.read_text('utf-8'))
    seal=json.loads((query_cache.parent/'embedding-attempt.json').read_text('utf-8'))
    if digest(query_cache)!=seal['result_sha256']:raise ValueError('Cached questions differ')
    if (cache['requested_model'],cache['dimensions'])!=(settings.embedding_model,settings.embedding_dimensions):
        raise ValueError('Query vector model differs from configuration')
    matches=[q for q in cache['queries'] if q['task_id']==task_id]
    if len(matches)!=1:raise ValueError('Choose exactly one cached task')
    query=matches[0]
    structure=json.loads((library/'structure.json').read_text('utf-8'))
    if structure.get('status')!='ready' or not structure.get('vector_index_built'):raise ValueError('Index is not ready')
    if digest(library/'table-retrieval.json')!=structure['table_evidence']['manifest_sha256']:
        raise ValueError('Table manifest changed')
    metadata,catalog=read_catalog(library)
    relations=TableRelations.load(library,metadata,settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    vectors=TableVectorSearch(ChromaVectorStore(library/'chroma',settings.embedding_provider,
        settings.embedding_model,settings.embedding_dimensions),relations)
    class Cached:
        calls=0
        def embed_query(self,text):
            if text!=query['question'].strip():raise ValueError('Question changed')
            self.calls+=1
            return query['vector']
    cached=Cached()
    reranker=SiliconFlowReranker(settings.rerank_model,settings.rerank_api_key.get_secret_value(),
        settings.rerank_base_url,settings.rerank_timeout_seconds)
    service=RetrievalService(metadata,vectors,cached,ContextOptions(settings.context_expansion_enabled,
        settings.context_neighbor_radius,settings.context_max_evidence_chars,settings.context_max_total_chars),
        relations,reranker,body_context_catalog=catalog)
    default=ROOT/'backend/.env.literature'
    default_hash=digest(default);env_hash=digest(env_file);metadata_hash=digest(library/'metadata.sqlite3')
    record=dict(status='started',task_id=task_id,question=query['question'],
        started_at=datetime.now(timezone.utc).isoformat(),configuration=configuration_snapshot(env_file),
        source_structure_sha256=digest(library/'structure.json'),query_cache_sha256=digest(query_cache),
        candidate_configuration_sha256=env_hash,probe_source_sha256=digest(Path(__file__)),
        provider_calls=[],new_embedding_api_calls=0,new_generation_calls=0,new_judge_calls=0,quality_scores_produced=False)
    output.parent.mkdir(parents=True,exist_ok=True);save(output,record)
    try:
        final=service.retrieve(query['question'],settings.top_k,settings.min_score)
        seeds=service.last_seed_evidences;info=service.last_context_diagnostics
        primary={e.chunk_id for e in seeds};sources=[s for e in final for s in e.source_chunks]
        assert primary<={s.chunk_id for s in sources} and len(sources)==len({s.chunk_id for s in sources})
        assert info['assembly_passes']==1 and info['candidate_roots_only'] and not info['post_context_expansion']
        assert info['candidate_root_chunk_ids']==[e.chunk_id for e in seeds]
        assert all(x['seed_chunk_id'] in primary for x in info['candidate_origins'])
        assert all(len(e.text)<=settings.context_max_evidence_chars for e in final)
        assert sum(len(e.text) for e in final)<=settings.context_max_total_chars
        assert info['rerank']['selected_chunk_ids']==[e.chunk_id for e in seeds]
        assert all(next(s for s in sources if s.chunk_id==e.chunk_id).text==e.text for e in seeds)
        record.update(status='completed',seeds=[asdict(e) for e in seeds],final=[asdict(e) for e in final],
            context=info,checks=dict(rerank_before_primary_selection=True,all_primary_hits_preserved=True,
                source_text_unchanged=True,no_duplicate_sources=True,unified_context_once=True,all_budgets_passed=True))
    except Exception as error:
        record.update(status='failed',error_type=type(error).__name__)
    finally:
        record.update(provider_calls=[reranker.last_call] if reranker.last_call is not None else [],
            cached_query_lookups=cached.calls,finished_at=datetime.now(timezone.utc).isoformat(),
            default_configuration_unchanged=digest(default)==default_hash,
            candidate_configuration_unchanged=digest(env_file)==env_hash,
            source_metadata_unchanged=digest(library/'metadata.sqlite3')==metadata_hash)
        save(output,record)
    return {k:record[k] for k in ['status','task_id','checks','provider_calls','new_embedding_api_calls',
        'new_generation_calls','new_judge_calls','quality_scores_produced','default_configuration_unchanged'] if k in record}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--query-cache',type=Path,required=True)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=probe(args.library,args.query_cache,args.task_id,args.env_file,args.output)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result['status']=='completed' else 1)
