"""Fresh Qwen text answers, frozen query replay, independent Jev and Luna scoring."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json
import shutil
import subprocess
import sys
import threading

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import run_qa_baseline as runner
from evaluate_embedding_20261102 import comparable_configuration,scientific_sources
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'.rag-data/evaluations/qwen-twojudges-20261102-r2'
RUN=ROOT/'.rag-data/evaluations/pfi-qwen-twojudges-20261102-r2'
IMPORT=OUTPUT/'import'
STUDY=OUTPUT/'judges'
OLD_RUN=ROOT/'.rag-data/evaluations/pfi-embedding-qwen-20261102-r1'
CACHE=ROOT/'.rag-data/evaluations/embedding-20261102/shared-query-cache.json'
PROXY='http://127.0.0.1:10808'
KINDS=('jev','luna')


def attach():
    run=judge.read_json(RUN/'run.json');old=judge.read_json(OLD_RUN/'run.json')
    require(not list((RUN/'results').glob('*.json')) and 'embedding_eval_control' not in run,'Attach once before generation')
    require(comparable_configuration(run['configuration_probe'])==comparable_configuration(old['configuration_probe']),
        'Answer/retrieval policies differ from previous Qwen run')
    require(scientific_sources(RUN/'library')==scientific_sources(OLD_RUN/'library'),'Scientific sources changed')
    require(run['dataset_files']==old['dataset_files'],'Question set changed')
    require(judge.digest(CACHE)==old['embedding_eval_control']['query_cache_sha256'],'Prepared queries changed')
    wrapper=RUN/'backend/embedding_eval_worker.py'
    shutil.copyfile(ROOT/'scripts/qa_embedding_eval_worker.py',wrapper)
    shutil.copyfile(CACHE,RUN/'backend/embedding-query-cache.json')
    run['embedding_eval_control']={**old['embedding_eval_control'],'wrapper_sha256':judge.digest(wrapper),
        'shared_rewrite_calls':0,'reused_from_run_id':old['run_id']}
    run['source_files']=runner.source_hashes(RUN/'backend')
    run['input_policy']+=' Repeat uses the sealed previous per-question rewrite; no gold answers or judge scores.'
    runner.write_json(RUN/'run.json',run)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    return dict(attached=True,new_rewrite_calls=0,new_answer_tasks=32)


def answers():
    run=judge.read_json(RUN/'run.json');control=run['embedding_eval_control']
    require(judge.digest(RUN/'backend/embedding-query-cache.json')==control['query_cache_sha256'],'Replay cache changed')
    require(judge.digest(RUN/'backend/embedding_eval_worker.py')==control['wrapper_sha256'],'Wrapper changed')
    original=runner.execute_question
    def execute(worker,library,question,timeout):
        return original(worker.parent/'embedding_eval_worker.py',library,question,timeout)
    runner.execute_question=execute
    try:return runner.run(RUN)
    finally:runner.execute_question=original


def prepare():
    run=judge.read_json(RUN/'run.json');progress=judge.read_json(RUN/'progress.json')
    require(progress['status']=='completed' and progress['completed']==32,'Wait for 32 answers')
    require(not progress['outcomes'].get('failed'),'Inspect retained failures before grading')
    require(runner.source_hashes(RUN/'backend')==run['source_files'],'Frozen source changed')
    settings=grading.configs(list(KINDS))
    if not IMPORT.exists():
        raw=ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw'
        papers=list((RUN/'library/papers').glob('*.pdf'));require(len(papers)==1,'Expected same original PDF')
        cmd=[sys.executable,str(ROOT/'scripts/import_qa_system_answers.py'),'--input',str(raw/'answer.txt'),
            '--extra',str(raw/'answer_PFI2-013.json'),'--pdf',str(papers[0]),'--rag-run',str(RUN),
            '--recovery-run',str(RUN),'--output',str(IMPORT),'--verify-rag-quotes']
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        judge.write(OUTPUT/'import-process.json',dict(returncode=p.returncode,stdout_sha256=judge.sha(p.stdout),stderr_sha256=judge.sha(p.stderr)))
        require(p.returncode==0,'Import failed; retain generated answers')
    if not STUDY.exists():grading.prepare(IMPORT,STUDY,settings,['rag'])
    study=judge.read_json(STUDY/'study.json');meta=judge.read_json(IMPORT/'import.json')
    require(len(study['jobs'])==64 and set(study['requested_judges'])==set(KINDS),'Expected two judges per answer')
    require(study['selected_systems']==['rag'] and all(o['source_run_id']==run['run_id'] for o in meta['rag_origins'].values()),'Wrong answers imported')
    require(all('citation_validation' not in judge.encode(judge.read_json(STUDY/'inputs'/(e['name']+'.json'))) for e in study['jobs']),
        'Failure diagnostics must not contaminate judge input')
    contract=dict(version='qwen-twojudges-repeat-v1',orchestrator_sha256=judge.digest(Path(__file__)),
        run_sha256=judge.digest(RUN/'run.json'),study_sha256=judge.digest(STUDY/'study.json'),
        import_sha256=judge.digest(IMPORT/'import.json'),policy_sha256=grading.POLICY_SHA,
        judge_settings=grading.public_settings(settings),default_config_sha256=judge.digest(ROOT/'backend/.env.literature'),
        max_attempts=3,first_valid_only=True,new_answer_tasks=32,new_grades=64,new_rewrite_calls=0,new_dsh_calls=0)
    path=OUTPUT/'contract.json'
    if path.exists():require(judge.read_json(path)==contract,'Frozen contract changed')
    else:judge.write(path,contract)
    return dict(prepared=64,model_calls=0,judges=list(KINDS))


def grade(workers=4):
    require(type(workers) is int and 1<=workers<=4,'Invalid concurrency')
    contract=judge.read_json(OUTPUT/'contract.json');settings=grading.configs(list(KINDS));study=judge.read_json(STUDY/'study.json')
    require(judge.digest(Path(__file__))==contract['orchestrator_sha256'],'Orchestrator changed')
    require(judge.digest(RUN/'run.json')==contract['run_sha256'] and judge.digest(STUDY/'study.json')==contract['study_sha256'],'Frozen manifests changed')
    require(judge.digest(IMPORT/'import.json')==contract['import_sha256'],'Answer import changed')
    require(grading.public_settings(settings)==contract['judge_settings'],'Judge settings changed')
    require(judge.digest(ROOT/'backend/.env.literature')==contract['default_config_sha256'],'Website settings changed')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in study['harness_files'].items()),'Grading harness changed')
    stop=threading.Event();statuses=Counter()
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),judge.lock(STUDY):
        audit=scoring.audit(IMPORT,STUDY)
        require(all(status!='pending' for _,_,status in audit[5]),'Inspect interrupted API requests')
        jobs=sorted(study['jobs'],key=lambda e:judge.sha(e['name']))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={}
            for entry in jobs:
                cfg=settings[entry['judge']]
                factory=lambda cfg=cfg:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy=PROXY)
                futures[pool.submit(grading.evaluate_one,STUDY,entry,cfg,stop,factory,3)]=entry
            for future in as_completed(futures):
                try:status=future.result()
                except Exception:
                    stop.set()
                    raise
                statuses[(futures[future]['judge'],status)]+=1
                if sum(statuses.values())%8==0:
                    print(judge.encode(dict(done=sum(statuses.values()),statuses={k+':'+s:n for (k,s),n in statuses.items()})),flush=True)
    result=dict(statuses={k+':'+s:n for (k,s),n in statuses.items()},billing_stop=stop.is_set(),max_attempts=3)
    judge.write(OUTPUT/'grading-progress.json',result)
    return result


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('action',choices=['attach','answers','prepare','grade'])
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    try:result={'attach':attach,'answers':answers,'prepare':prepare,'grade':lambda:grade(args.workers)}[args.action]()
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Preserve saved answers and API attempts; inspect before replay.')))
        raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False))
