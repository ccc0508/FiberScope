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
from literature_rag.application.body_context import SECTION_TRIGGER_ROLES
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.table_evidence import TableRelations,TableVectorSearch,BODY_TABLE_VERSION
from literature_rag.config import Settings


def verify(library,query_cache,output,env_file):
    library,query_cache,output=Path(library).resolve(),Path(query_cache).resolve(),Path(output).resolve()
    if output.exists():raise ValueError('Preserve previous verification; use a new output path')
    settings=Settings(_env_file=env_file)
    if settings.rerank_enabled:
        raise ValueError('This offline verifier excludes reranking; use probe_mineru_unified_rerank.py for an explicit API probe')
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
    records=[];decisions=Counter();section_roles=Counter();linked=0;link_candidates=0;table_seeds=0;formula_seeds=0
    for query in queries['queries']:
        cached.current=query
        result=service.retrieve(query['question'],8,.35)
        seeds=service.last_seed_evidences;info=service.last_context_diagnostics
        primary={e.chunk_id for e in seeds};source_ids=[s.chunk_id for e in result for s in e.source_chunks]
        assert primary<=set(source_ids) and len(source_ids)==len(set(source_ids))
        assert len(seeds)<=8 and vectors.last_diagnostics['parent_candidates']<=50
        assert all(e.text.strip() and len(e.text)<=8000 for e in result) and sum(len(e.text) for e in result)<=24000
        assert all('程序生成的表格行检索表示' not in e.text for e in result)
        assert info['assembly_passes']==1 and info['candidate_roots_only'] and not info['post_context_expansion']
        assert info['candidate_root_chunk_ids']==[e.chunk_id for e in seeds]
        candidates={x['chunk_id'] for x in info['candidate_origins']}
        assert set(source_ids)<=candidates
        assert all(x['seed_chunk_id'] in primary for x in info['candidate_origins'])
        for link in info['explicit_link_candidates']:
            assert link['source_chunk_id']==link['seed_chunk_id'] and link['seed_chunk_id'] in primary
        for e in seeds:
            m=catalog.mapping[e.chunk_id]
            if m['content_role']=='table':table_seeds+=1
            if m['content_role']=='equation':formula_seeds+=1
            actual=next(s for out in result for s in out.source_chunks if s.chunk_id==e.chunk_id)
            assert (actual.text,actual.page_start,actual.page_end)==(e.text,e.page_start,e.page_end)
            if m['role_status']!='identified' or m['content_role'] not in SECTION_TRIGGER_ROLES:
                own=next(e2 for e2 in result if e.chunk_id in e2.seed_chunk_ids and e2.chunk_id==e.chunk_id)
                assert own.text==e.text and [s.chunk_id for s in own.source_chunks]==[e.chunk_id]
            elif catalog.trusted(catalog.chunks[e.chunk_id]):
                decision=next(d for d in info['decisions'] if d['seed_chunk_id']==e.chunk_id)
                assert decision['mode']=='section'
                section_roles[m['content_role']]+=1
        for cid in set(source_ids)-primary:
            m=catalog.mapping[cid]
            assert m['role_status']=='identified' and m['content_role'] in {'body','table','equation','figure_caption'}
        for d in info['decisions']:decisions[d['mode']]+=1
        linked+=len(info['selected_explicit_link_chunk_ids'])
        link_candidates+=len(info['explicit_link_candidates'])
        records.append(dict(task_id=query['task_id'],question=query['question'],seeds=[asdict(e) for e in seeds],
            final=[asdict(e) for e in result],context=info))
    assert digest(env_file)==env_hash and digest(library/'metadata.sqlite3')==metadata_hash
    if len(records)!=32 or len({r['task_id'] for r in records})!=32:raise ValueError('Expected 32 unique cached tasks')
    result=dict(version=BODY_TABLE_VERSION,questions=len(records),chunks=len(catalog.chunks),
        rows=len(relations.rows),links=len(relations.links),decision_counts=dict(decisions),
        section_trigger_counts=dict(section_roles),source_index_pipeline_version=structure.get('pipeline_version'),
        table_primary_hit_occurrences=table_seeds,formula_primary_hit_occurrences=formula_seeds,
        explicit_link_candidate_edges=link_candidates,selected_explicit_link_chunk_occurrences=linked,
        only_primary_hits_collect_candidates=True,assembly_passes_per_question=1,post_context_expansion=False,
        all_primary_hits_preserved=True,primary_text_and_pages_unchanged=True,no_duplicate_sources=True,all_character_budgets_passed=True,
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
