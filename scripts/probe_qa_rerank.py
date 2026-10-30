"""Replay a sealed candidate pool with reranking only; never load gold answers or regenerate QA."""
from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.providers.rerank import SiliconFlowReranker
from literature_rag.application.rerank import rank_candidates
from literature_rag.config import Settings
from literature_rag.domain.errors import ProviderError
from literature_rag.domain.models import Evidence
from judge_qa_eval import digest,read_json,write,now


def probe(run_dir,task_id,env_file,output):
    run_dir,output=Path(run_dir).resolve(),Path(output).resolve()
    if output.exists():raise ValueError('Existing probe record; do not replay paid calls')
    source=run_dir/'results'/(task_id+'.json')
    row=read_json(source);contract=read_json(run_dir/'run.json')
    seal=read_json(run_dir/'attempts'/(task_id+'.json'))
    if digest(source)!=seal['result_sha256']:raise ValueError('Sealed answer changed')
    settings=Settings(_env_file=env_file)
    if not settings.rerank_enabled:raise ValueError('Reranking is disabled')
    candidates=row['response']['context_assembly']['table_retrieval']['candidates']
    if len(candidates)>50:raise ValueError('Invalid candidate pool')
    with sqlite3.connect((run_dir/'library/metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        chunks={c['id']:dict(c) for c in conn.execute('SELECT * FROM chunks')}
    sources=[]
    for c in candidates:
        if c['score']<contract['configuration_probe']['min_score'] or c['chunk_id'] not in chunks:continue
        s=chunks[c['chunk_id']]
        sources.append(Evidence(f'[{len(sources)+1}]',s['id'],s['document_id'],s['filename'],s['page_start'],s['page_end'],s['text'],c['score']))
    provider=SiliconFlowReranker(settings.rerank_model,settings.rerank_api_key.get_secret_value(),settings.rerank_base_url,settings.rerank_timeout_seconds)
    output.parent.mkdir(parents=True,exist_ok=True)
    record=dict(status='pending',task_id=task_id,started_at=now(),source_result_sha256=digest(source),
        model=settings.rerank_model,input_question=row['question'],source_candidates=[asdict(e) for e in sources],
        provider_call=None,independent_probe=True,embedding_calls=0,generation_calls=0,gold_loaded=False)
    write(output,record)
    try:
        ranked,diagnostics=rank_candidates(row['question'],sources,provider,settings.top_k)
        record.update(status='completed',diagnostics=diagnostics,top_ids=[e.chunk_id for e in ranked[:settings.top_k]])
    except ProviderError:record.update(status='failed',reason_code='rerank_provider_error')
    finally:
        record.update(provider_call=provider.last_call,finished_at=now());write(output,record)
    return dict(status=record['status'],task_id=task_id,top_ids=record.get('top_ids'),provider_call=record['provider_call'])


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--task-id',required=True)
    parser.add_argument('--env-file',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(probe(args.run_dir,args.task_id,args.env_file,args.output),ensure_ascii=False))
