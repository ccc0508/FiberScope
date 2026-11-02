"""Controlled BGE/Qwen text embedding evaluation with identical shared rewrites."""
from argparse import ArgumentParser
from contextlib import ExitStack,closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading

from filelock import FileLock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import run_qa_baseline as runner
from grade_qa_rerank_repeats_20261031 import execute_jobs,PROXY
from qa_eval_v2 import task_selection
from validate_qa_eval import require

OUTPUT=ROOT/'.rag-data/evaluations/embedding-20261102'
ARMS=('bge','qwen')
CACHE=OUTPUT/'shared-query-cache.json'


def plan(arm):
    require(arm in ARMS,'Unknown embedding arm')
    return dict(arm=arm,run_dir=ROOT/'.rag-data/evaluations'/f'pfi-embedding-{arm}-20261102-r1',
        import_dir=OUTPUT/arm/'import',study_dir=OUTPUT/arm/'jev')


def prepare_queries():
    from literature_rag.config import Settings
    from literature_rag.adapters.providers.query_rewrite import DeepSeekQueryRewriter
    from literature_rag.application.query_rewrite import SYSTEM_PROMPT
    from literature_rag.domain.errors import ProviderError
    pack=ROOT/'fiberscope-eval-v2';tasks=task_selection(pack,'core_text')
    cases={c['id']:c for c in judge.read_jsonl(pack/'cases.jsonl')}
    settings=Settings(_env_file=ROOT/'backend/.env.aliyun')
    contract=dict(dataset_sha256=judge.digest(pack/'cases.jsonl'),tasks=tasks,
        prompt_sha256=sha256(SYSTEM_PROMPT.encode()).hexdigest(),model=settings.llm_model,
        endpoint_sha256=sha256((settings.llm_base_url or '').encode()).hexdigest(),
        generator_sha256=judge.digest(ROOT/'backend/literature_rag/adapters/providers/query_rewrite.py'))
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with FileLock(str(OUTPUT/'.queries.lock'),timeout=0):
        if CACHE.exists():
            cache=judge.read_json(CACHE);require(cache['contract']==contract,'Shared query contract changed')
        else:cache=dict(version='controlled-embedding-rewrites-v1',contract=contract,queries={})
        provider=DeepSeekQueryRewriter(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
            settings.query_rewrite_timeout_seconds)
        for task in tasks:
            question=cases[task['case_id']]['question'].strip();key=sha256(question.encode()).hexdigest()
            if key in cache['queries']:
                require(cache['queries'][key]['status']!='started','Inspect interrupted rewrite request before replay')
                continue
            row=dict(task_id=task['id'],question=question,status='started');cache['queries'][key]=row
            runner.write_json(CACHE,cache)
            try:row.update(query=provider.rewrite(question),status='completed')
            except ProviderError:row.update(query=None,status='failed_original_only')
            finally:
                row['provider_call']=provider.last_call;runner.write_json(CACHE,cache)
            print(json.dumps(dict(prepared=len(cache['queries']),total=len(tasks),task_id=task['id'],status=row['status'])),flush=True)
        return dict(queries=len(cache['queries']),cache_sha256=judge.digest(CACHE),shared_between_arms=True)


def attach_control(arm):
    entry=plan(arm);root=entry['run_dir'];path=root/'run.json';run=judge.read_json(path)
    require(not list((root/'results').glob('*.json')),'Attach control before any answer generation')
    require('embedding_eval_control' not in run,'Control already attached')
    cache=judge.read_json(CACHE);require(len(cache['queries'])==32,'Prepare all shared rewrites')
    wrapper=root/'backend/embedding_eval_worker.py';shutil.copyfile(ROOT/'scripts/qa_embedding_eval_worker.py',wrapper)
    shutil.copyfile(CACHE,root/'backend/embedding-query-cache.json')
    run['source_files']=runner.source_hashes(root/'backend')
    run['embedding_eval_control']=dict(query_cache_sha256=judge.digest(CACHE),wrapper_sha256=judge.digest(wrapper),
        wrapper_source='scripts/qa_embedding_eval_worker.py',rewrite_calls_per_answer=0,
        shared_rewrite_calls=len(cache['queries']),answer_query='original',rerank_query='original',images_enabled=False)
    run['input_policy']+=' Evaluation-only wrapper supplies one precomputed retrieval rewrite per exact question; no references or grades.'
    runner.write_json(path,run)
    return dict(arm=arm,attached=True,provider_calls=0)


def comparable_configuration(config):
    ignored={'embedding_provider','embedding_model','embedding_dimensions','embedding_runtime',
        'pipeline_source_files','prompt_pipeline_sha256','provider_endpoint_fingerprints'}
    result={k:v for k,v in config.items() if k not in ignored}
    endpoints=config.get('provider_endpoint_fingerprints',{})
    if endpoints:result['answer_endpoint_sha256']=endpoints['llm_base_url']
    return result


def scientific_sources(root):
    with closing(sqlite3.connect((root/'metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        chunks=conn.execute('SELECT id,document_id,filename,page_start,page_end,chunk_index,text,kind FROM chunks ORDER BY id').fetchall()
        documents=conn.execute('SELECT id,file_hash,page_count,chunk_count FROM documents ORDER BY id').fetchall()
    structure=judge.read_json(root/'structure.json');tables=judge.read_json(root/'table-retrieval.json')
    return dict(chunks=chunks,documents=documents,mapping=structure['mapping'],sections=structure['sections'],
        rows=tables['rows'],links=tables['links'])


def check_pair():
    runs=[judge.read_json(plan(a)['run_dir']/'run.json') for a in ARMS]
    require(runs[0]['source_commit']==runs[1]['source_commit'],'Source commits differ')
    require(runs[0]['source_files']==runs[1]['source_files'],'Worker source bytes differ')
    require(runs[0]['dataset_files']==runs[1]['dataset_files'],'Dataset differs')
    require(runs[0]['embedding_eval_control']==runs[1]['embedding_eval_control'],'Prepared rewrites differ')
    require(comparable_configuration(runs[0]['configuration_probe'])==comparable_configuration(runs[1]['configuration_probe']),
        'Non-embedding configuration differs')
    for arm,run in zip(ARMS,runs):
        cfg=run['configuration_probe'];control=run['embedding_eval_control']
        require(cfg['query_rewrite']['max_queries']==2 and cfg['query_rewrite']['rerank_query']=='original','Wrong retrieval strategy')
        require('visual_retrieval' not in cfg and 'answer_guidance' not in cfg,'Images/guidance must be off')
        require(judge.digest(plan(arm)['run_dir']/'backend/embedding-query-cache.json')==control['query_cache_sha256'],
            'Shared query cache changed')
    require((runs[0]['configuration_probe']['embedding_model'],runs[0]['configuration_probe']['embedding_dimensions'])==('BAAI/bge-m3',1024),'Wrong BGE model')
    require((runs[1]['configuration_probe']['embedding_model'],runs[1]['configuration_probe']['embedding_dimensions'])==('qwen3-vl-embedding',2560),'Wrong Qwen model')
    require(scientific_sources(plan('bge')['run_dir']/'library')==scientific_sources(plan('qwen')['run_dir']/'library'),
        'Original scientific sources/structure/relationships differ')
    return runs


def run_answers(arm):
    entry=plan(arm);run=judge.read_json(entry['run_dir']/'run.json');control=run['embedding_eval_control']
    require(judge.digest(CACHE)==control['query_cache_sha256'],'Prepared rewrites changed')
    require(judge.digest(ROOT/'scripts/qa_embedding_eval_worker.py')==control['wrapper_sha256'],'Wrapper changed')
    original=runner.execute_question
    def execute(worker,library,question,timeout):
        require(judge.digest(worker.parent/'embedding-query-cache.json')==control['query_cache_sha256'],'Worker cache changed')
        return original(worker.parent/'embedding_eval_worker.py',library,question,timeout)
    runner.execute_question=execute
    try:return runner.run(entry['run_dir'])
    finally:runner.execute_question=original


def prepare_grading():
    runs=check_pair();settings=grading.configs(['jev'])
    old=judge.read_json(ROOT/'.rag-data/evaluations/mineru-current-20261101/jev/study.json')
    require(old['policy_sha256']==grading.POLICY_SHA,'Jev policy changed')
    require(old['requested_judges']['jev']==grading.public_settings(settings)['jev'],'Jev settings changed')
    for arm,run in zip(ARMS,runs):
        entry=plan(arm);folder=entry['run_dir'];progress=judge.read_json(folder/'progress.json')
        require(progress['status']=='completed' and progress['completed']==32,'Wait for all 32 answers')
        require(not progress['outcomes'].get('failed'),'Keep failed answers and inspect before grading')
        require(runner.source_hashes(folder/'backend')==run['source_files'],'Frozen worker changed')
        if not entry['import_dir'].exists():
            papers=list((folder/'library/papers').glob('*.pdf'));require(len(papers)==1,'Expected original PDF')
            raw=ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw'
            entry['import_dir'].parent.mkdir(parents=True,exist_ok=True)
            cmd=[sys.executable,str(ROOT/'scripts/import_qa_system_answers.py'),'--input',str(raw/'answer.txt'),
                '--extra',str(raw/'answer_PFI2-013.json'),'--pdf',str(papers[0]),'--rag-run',str(folder),
                '--recovery-run',str(folder),'--output',str(entry['import_dir']),'--verify-rag-quotes']
            p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            judge.write(OUTPUT/arm/'import-process.json',dict(returncode=p.returncode,stdout_sha256=judge.sha(p.stdout),stderr_sha256=judge.sha(p.stderr)))
            require(p.returncode==0,'Import failed; keep saved answers')
        if not entry['study_dir'].exists():grading.prepare(entry['import_dir'],entry['study_dir'],settings,['rag'])
        study=judge.read_json(entry['study_dir']/'study.json');meta=judge.read_json(entry['import_dir']/'import.json')
        require(study['selected_systems']==['rag'] and set(study['requested_judges'])=={'jev'} and len(study['jobs'])==32,'Wrong grading task selection')
        require(all(o['source_run_id']==run['run_id'] for o in meta['rag_origins'].values()),'Grading wrong answer run')
    contract=dict(version='bge-qwen-shared-rewrite-eval-v1',orchestrator_sha256=judge.digest(Path(__file__)),
        runs={a:judge.digest(plan(a)['run_dir']/'run.json') for a in ARMS},
        studies={a:judge.digest(plan(a)['study_dir']/'study.json') for a in ARMS},
        query_cache_sha256=judge.digest(CACHE),policy_sha256=grading.POLICY_SHA,requested_judges=grading.public_settings(settings),
        default_config_sha256=judge.digest(ROOT/'backend/.env.literature'),proxy=PROXY,
        new_answer_tasks=64,new_jev_jobs=64,new_luna_jobs=0,new_dsh_jobs=0,max_attempts=3,first_valid_only=True)
    path=OUTPUT/'contract.json'
    if path.exists():require(judge.read_json(path)==contract,'Frozen grading contract changed')
    else:judge.write(path,contract)
    return dict(prepared=64,provider_calls=0)


def grade(workers=4):
    require(type(workers) is int and 1<=workers<=4,'Invalid concurrency')
    contract=judge.read_json(OUTPUT/'contract.json');settings=grading.configs(['jev'])
    require(judge.digest(Path(__file__))==contract['orchestrator_sha256'],'Grading orchestrator changed')
    require(grading.public_settings(settings)==contract['requested_judges'],'Judge model/settings changed')
    require(judge.digest(ROOT/'backend/.env.literature')==contract['default_config_sha256'],'Website configuration changed')
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ExitStack() as stack:
        jobs=[]
        for arm in ARMS:
            entry=plan(arm);study=judge.read_json(entry['study_dir']/'study.json')
            require(judge.digest(entry['run_dir']/'run.json')==contract['runs'][arm],'Answer manifest changed')
            require(judge.digest(entry['study_dir']/'study.json')==contract['studies'][arm],'Grading manifest changed')
            require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in study['harness_files'].items()),'Jev harness changed')
            stack.enter_context(judge.lock(entry['study_dir']))
            audit=scoring.audit(entry['import_dir'],entry['study_dir'])
            require(all(s!='pending' for _,_,s in audit[5]),'Inspect interrupted score requests')
            jobs.extend((entry,j) for j in study['jobs'])
        jobs.sort(key=lambda pair:judge.sha([pair[0]['arm'],pair[1]['name']]))
        result=execute_jobs(jobs,settings,threading.Event(),workers,1)
        judge.write(OUTPUT/'grading-progress.json',result)
        require(result['execution_error_type'] is None,'Inspect retained grading checkpoints')
    return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['queries','attach','check','answers','prepare-grading','grade'])
    p.add_argument('--arm',choices=ARMS);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    try:
        if a.action=='queries':result=prepare_queries()
        elif a.action=='attach':result=attach_control(a.arm)
        elif a.action=='check':check_pair();result=dict(pair_checks='passed')
        elif a.action=='answers':result=run_answers(a.arm)
        elif a.action=='prepare-grading':result=prepare_grading()
        else:result=grade(a.workers)
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Preserve saved rewrites, answers and scores; do not regenerate valid results.')))
        raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False))
