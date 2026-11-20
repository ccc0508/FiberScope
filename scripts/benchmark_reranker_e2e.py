"""Independent paired 24-case Agent runs; vary only native reranker configuration.

Snapshot the current working source (including local edits) before paid calls.
Never edit live private configuration or reuse a previous answer as a new run.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from dotenv import dotenv_values

ARMS={'qwen37':dict(provider='dashscope',model='qwen3.7-text-rerank'),
      'jev':dict(provider='jev',model='typesafe/jev-1.14')}


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


def checksum(path):return sha256(Path(path).read_bytes()).hexdigest()


def replacement(path,old,new):
    text=path.read_text(encoding='utf8')
    if text.count(old)!=1:raise ValueError('Cannot apply isolated adapter patch: '+str(path))
    path.write_text(text.replace(old,new),encoding='utf8')


def prepare(a):
    contract=a.output/'manifest.json'
    if contract.exists():return read(contract)
    runtime=a.output/'runtime'
    if runtime.exists():raise ValueError('Inspect incomplete runtime snapshot')
    runtime.mkdir(parents=True)
    original={}
    for folder in ['backend','scripts']:
        for source in (a.source/folder).rglob('*'):
            if not source.is_file() or source.suffix not in {'.py','.json'} or any(p in {'__pycache__','node_modules','tests'} for p in source.relative_to(a.source).parts):continue
            rel=source.relative_to(a.source)
            target=runtime/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            original[str(rel)]=checksum(source)
    for name in ['.env','.env.literature','.env.langfuse']:
        source=a.source/'backend'/name
        if source.exists():shutil.copy2(source,runtime/'backend'/name)
    adapter=Path(__file__).parents[1]/'backend/literature_rag/adapters/providers/alternate_rerank.py'
    shutil.copy2(adapter,runtime/'backend/literature_rag/adapters/providers/alternate_rerank.py')
    replacement(runtime/'backend/literature_rag/config.py',"rerank_provider: Literal['siliconflow'] = 'siliconflow'","rerank_provider: Literal['siliconflow','dashscope','jev'] = 'siliconflow'")
    replacement(runtime/'backend/literature_worker.py',
        'from literature_rag.adapters.providers.rerank import SiliconFlowReranker\n        provider_reranker=SiliconFlowReranker(settings.rerank_model,settings.rerank_api_key.get_secret_value(),\n            settings.rerank_base_url,settings.rerank_timeout_seconds)',
        'from literature_rag.adapters.providers.alternate_rerank import build_reranker\n        provider_reranker=build_reranker(settings)')
    # Snapshot diagnostics must not falsely advertise BGE-specific API options.
    replacement(runtime/'backend/literature_rag/diagnostics.py',
        "sources += ['application/rerank.py','adapters/providers/rerank.py']",
        "sources += ['application/rerank.py','adapters/providers/rerank.py','adapters/providers/alternate_rerank.py']")
    replacement(runtime/'backend/literature_rag/diagnostics.py',
        "    if settings.answer_guidance_enabled:",
        "    if settings.rerank_enabled and settings.rerank_provider!='siliconflow':\n        result['rerank'].pop('max_chunks_per_doc',None)\n        result['rerank'].pop('overlap_tokens',None)\n        result['rerank'].update(api='dashscope_native' if settings.rerank_provider=='dashscope' else 'openrouter_decisions',parallelism=16 if settings.rerank_provider=='jev' else 1)\n    if settings.answer_guidance_enabled:")
    replacement(runtime/'backend/literature_rag/diagnostics.py',"rerank='BGE_text_only_caption_and_body'","rerank=settings.rerank_model+'_text_only_caption_and_body'")
    pack=a.output/'pack';shutil.copytree(a.source/'fiberscope-eval-8papers-v1',pack)
    cases=[r for r in map(json.loads,(pack/'gold.jsonl').read_text(encoding='utf8').splitlines()) if r['group']!='no_paper']
    assert len(cases)==24
    for c in cases:c['input']=(pack/'tasks'/(c['id']+'.md')).read_text(encoding='utf8')
    write(a.output/'cases.json',cases)
    sys.path.insert(0,str(runtime/'backend'))
    from literature_rag.config import Settings
    from literature_rag.application.agent_loop import AgentBudget
    settings=Settings(_env_file=runtime/'backend/.env.literature')
    frozen={str(p.relative_to(runtime)):checksum(p) for p in runtime.rglob('*') if p.is_file()}
    manifest=dict(created_at=time.strftime('%Y-%m-%dT%H:%M:%S'),source_root=str(a.source),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=a.source,text=True).strip(),
        original_source_sha256=original,runtime_sha256=frozen,
        private_config_sha256=checksum(a.source/'backend/.env.literature'),
        metadata_sha256=checksum(a.library/'metadata.sqlite3'),library=str(a.library),
        generation={k:getattr(settings,k) for k in ['llm_provider','llm_model','llm_thinking_enabled','llm_reasoning_effort']},
        budget=asdict(AgentBudget(total_seconds=360,max_model_calls=20,max_tool_calls=12,reserve_seconds=45)),
        arms=ARMS,rerank_timeout_seconds=settings.rerank_timeout_seconds,
        policy='One independent first attempt per question and arm. Same frozen current working source, user task, library, generation and budgets. No forced search or answer selection. Default Qwen instruction, Jev independent Score rubric from prior experiment. Failed attempts retained. All agent-selected queries are fresh; candidate pools may differ after decisions diverge. Evaluation adapter patch only, live configuration unchanged.')
    write(contract,manifest)
    return manifest


def run_one(a,arm,case):
    target=a.output/arm/(case['id']+'.json')
    if target.exists():return read(target)
    runtime=a.output/'runtime';rid='rr-e2e-20261120-'+arm+'-'+case['id']
    statepath=runtime/'.rag-data/agent-runs'/rid/'state.json'
    marker=a.output/arm/'attempts'/(case['id']+'.json')
    if marker.exists() or statepath.parent.exists():raise ValueError('Inspect interrupted attempt '+rid)
    write(marker,dict(status='started',run_id=rid,at=time.time()))
    settings=dotenv_values(a.source/'backend/.env.literature',interpolate=False)
    if arm=='qwen37':base,key=settings['RAG_EMBEDDING_BASE_URL'],settings['RAG_EMBEDDING_API_KEY']
    else:
        jev=dotenv_values(a.source/'backend/.env.jev',interpolate=False)
        base,key=jev['QA_JEV_BASE_URL'],jev['QA_JEV_API_KEY']
    env=dict(os.environ,RAG_RERANK_ENABLED='true',RAG_RERANK_PROVIDER=ARMS[arm]['provider'],RAG_RERANK_MODEL=ARMS[arm]['model'],RAG_RERANK_BASE_URL=base,RAG_RERANK_API_KEY=key)
    started=time.perf_counter()
    args=[sys.executable,'-X','utf8',str(runtime/'scripts/run_literature_agent.py'),'--architecture','specialists',
        '--max-model-calls','20','--max-tools','12','--seconds','360','--question',case['input'],'--library',str(a.library),'--run-id',rid]
    proc=subprocess.run(args,capture_output=True,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (target.parent/(case['id']+'.stdout.log')).write_bytes(proc.stdout)
    (target.parent/(case['id']+'.stderr.log')).write_bytes(proc.stderr)
    result=read(statepath) if statepath.exists() else dict(run_id=rid,status='failed',answer='',model_calls=[],tool_calls=[],stop_reason='worker_no_state')
    sys.path.insert(0,str(runtime/'backend'))
    from literature_rag.application.tools import ToolTraceStore
    store=ToolTraceStore(runtime/'.rag-data/tool-traces.sqlite3')
    result.update(case_id=case['id'],question=case['question'],suite='rag',arm=arm,worker_returncode=proc.returncode,
        end_to_end_ms=round((time.perf_counter()-started)*1000),tool_trace=store.read(rid),evidence=store.evidence(rid))
    link=statepath.parent/'langfuse.json';result['langfuse']=read(link) if link.exists() else None
    write(target,result)
    write(marker,dict(status='finished',result_sha256=checksum(target)))
    return result


def answers(a):
    manifest=read(a.output/'manifest.json');cases=read(a.output/'cases.json')[:a.limit]
    arms=[a.arm] if a.arm else list(ARMS)
    # Rotate pair order between questions to avoid consistently favoring one service.
    jobs=[(arm,c) for i,c in enumerate(cases) for arm in (arms if i%2==0 else list(reversed(arms)))]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(run_one,a,arm,c) for arm,c in jobs]
        for future in as_completed(futures):
            r=future.result();print(json.dumps(dict(arm=r['arm'],id=r['case_id'],status=r['status'],reason=r.get('stop_reason'),seconds=r['end_to_end_ms']/1000),ensure_ascii=False),flush=True)
    integrity(a)


def integrity(a):
    m=read(a.output/'manifest.json');runtime=a.output/'runtime'
    verified=dict(runtime_unchanged=all(checksum(runtime/p)==h for p,h in m['runtime_sha256'].items()),
        metadata_unchanged=checksum(a.library/'metadata.sqlite3')==m['metadata_sha256'],
        live_model_config_unchanged=checksum(a.source/'backend/.env.literature')==m['private_config_sha256'])
    write(a.output/'integrity.json',verified)
    if not all(verified.values()):raise ValueError('Frozen runtime/configuration changed')
    return verified


def judge(a):
    sys.path.insert(0,str(a.source/'scripts'))
    import grade_agent_eightpapers_20261105 as g
    import judge_qa_jev as jev
    config=jev.load_config(a.source/'backend/.env.jev')
    arms=[a.arm] if a.arm else list(ARMS)
    g.LIBRARY=a.library;g.PACK=a.output/'pack'
    g.delivered_refs=lambda x:{r['ref'] for r in x.get('citation_validation',{}).get('available_records',[]) if r.get('citable')}
    for arm in arms:
        g.RUN=a.output/arm
        for c in read(a.output/'cases.json')[:a.limit]:
            target=g.RUN/(c['id']+'.json')
            if not target.exists() or read(target)['status']!='completed':continue
            folder=g.RUN/'judge-jev'/c['id'];folder.mkdir(parents=True,exist_ok=True)
            inp=folder/'input.json'
            if not inp.exists():
                packet=g.prepare(c,config)
                # Keep the previously accepted contextual citation interpretation.
                packet['request']['state']['policy']['citation_context']='A conclusion/summary can inherit explicitly established nearby citations. Do not demand a redundant citation after each repeated summary sentence. Check substantive attribution and evidence support, not merely placement.'
                g.j.write(inp,packet)
            saved=read(inp)
            assert saved['result_sha256']==checksum(target)
            if (folder/'review.json').exists():continue
            for attempt in range(1,4):
                path=folder/f'attempt-{attempt}.json'
                if path.exists():
                    if read(path)['status']=='pending':raise ValueError('Inspect pending billed judge request')
                    continue
                rec=dict(status='pending',request_sha256=g.j.sha(saved['request']),started_at=g.j.now())
                write(path,rec);start=time.perf_counter()
                try:
                    import httpx
                    with httpx.Client(timeout=config.timeout,trust_env=False,follow_redirects=False) as client:
                        response=client.post(config.base_url+'/alpha/decisions',json=saved['request'],headers={'Authorization':'Bearer '+config.api_key})
                    rec['http_status']=response.status_code
                    if response.status_code!=200:rec['status']='api_failed'
                    else:
                        body=response.json();rec.update(raw_response=body,usage=jev.usage(body),status='invalid_response')
                        review=g.decode(saved,body);write(folder/'review.json',review);rec['status']='completed'
                except Exception as ex:rec.update(status='failed',error_type=type(ex).__name__)
                rec['duration_ms']=round((time.perf_counter()-start)*1000);write(path,rec)
                print(json.dumps(dict(arm=arm,id=c['id'],judge_attempt=attempt,status=rec['status']),ensure_ascii=False),flush=True)
                if rec.get('http_status') in {401,402,403}:return
                if rec['status']=='completed':break


def watch_judge(a):
    """Grade newly saved results while the independent answer runner proceeds."""
    cases=read(a.output/'cases.json')[:a.limit];arms=[a.arm] if a.arm else list(ARMS)
    while True:
        judge(a)
        expected=len(cases)*len(arms);recorded=graded=completed=0
        for arm in arms:
            for case in cases:
                p=a.output/arm/(case['id']+'.json')
                if not p.exists():continue
                recorded+=1
                if read(p)['status']=='completed':
                    completed+=1;graded+=(a.output/arm/'judge-jev'/case['id']/'review.json').exists()
        print(json.dumps(dict(recorded_answers=recorded,completed_answers=completed,graded=graded,expected=expected)),flush=True)
        if recorded==expected:
            if graded!=completed:raise ValueError('Some completed answers have no valid judge after bounded attempts')
            return
        # Permission/auth/balance failures must not become an endless polling loop.
        for path in a.output.glob('*/judge-jev/*/attempt-*.json'):
            if read(path).get('http_status') in {401,402,403}:return
        time.sleep(20)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','answers','judge','watch-judge','integrity'])
    p.add_argument('--source',type=Path,required=True);p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=2);p.add_argument('--limit',type=int,default=24);p.add_argument('--arm',choices=list(ARMS))
    a=p.parse_args();a.source=a.source.resolve();a.library=a.library.resolve();a.output=a.output.resolve()
    a.output.mkdir(parents=True,exist_ok=True)
    {'prepare':prepare,'answers':answers,'judge':judge,'watch-judge':watch_judge,'integrity':integrity}[a.action](a)
