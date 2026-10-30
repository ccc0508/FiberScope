"""Import and grade only the new repeated RAG answers using the unchanged Jev protocol."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import repeat_qa_rerank_20261031 as repeat
import report_qa_system_benchmark as reporting
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'.rag-data/evaluations/rerank-stability-20261031'
PROXY='http://127.0.0.1:10808'


def plan(round_number):
    require(round_number in [2,3],'Unknown repeat round')
    return [dict(system=s,round=round_number,
        run_dir=ROOT/'.rag-data/evaluations'/f'pfi-{s}-repeat-20261031-r{round_number}',
        import_dir=OUTPUT/'imports'/f'{s}-r{round_number}',study_dir=OUTPUT/'studies'/f'{s}-r{round_number}')
        for s in ['content','rerank']]


def settings_contract(settings):
    for folder in ['content-units-jev-20261030-r1','candidate-rerank-jev-20261030-r1',
                   'candidate-rerank-jev-20261031-proxy-recovery']:
        historical=judge.read_json(ROOT/'.rag-data/evaluations'/folder/'study.json')
        require(grading.public_settings(settings)==historical['requested_judges'],'Judge model or settings changed')
        require(historical['policy_sha256']==grading.POLICY_SHA,'Historical scoring policy changed')
        require(set(historical['harness_files'])==set(grading.HARNESS),'Historical grading harness differs')
        require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in historical['harness_files'].items()),'Historical grading source changed')
    result=dict(version='rerank-stability-grading-v1',policy_sha256=grading.POLICY_SHA,
        requested_judges=grading.public_settings(settings),grader_sha256=judge.digest(Path(__file__)),
        route='Existing local HTTP proxy at 127.0.0.1:10808',new_rounds=[2,3],planned_new_jev_jobs=128,
        max_attempts=3,first_valid_only=True,historical_scores_reused=True,new_luna_calls=0,
        request_context='One independent packet per new answer; no old grades or conversation history.')
    path=OUTPUT/'grading-contract.json'
    if path.exists():require(judge.read_json(path)==result,'Grading contract changed')
    else:judge.write(path,result)
    return result


def validate_study_binding(entry,contract):
    """Refuse stale/wrong-round/other-system packets before scheduling any paid call."""
    run=judge.read_json(entry['run_dir']/'run.json')
    meta=judge.read_json(entry['import_dir']/'import.json')
    expected={t['id'] for t in run['tasks']}
    require(contract.get('selected_systems')==['rag'],'Only new RAG answers may be graded')
    require(set(contract['requested_judges'])=={'jev'} and len(contract['jobs'])==32,'Expected 32 Jev jobs')
    require(all(j['judge']=='jev' and j['system']=='rag' for j in contract['jobs']),'Unexpected answer system or judge')
    require(len(expected)==32 and {j['task_id'] for j in contract['jobs']}==expected,'Grading task set differs')
    require(len({j['name'] for j in contract['jobs']})==32,'Duplicate grading jobs')
    require(contract['import_sha256']==judge.digest(entry['import_dir']/'import.json'),'Answer import changed')
    require(meta['dataset_manifest_sha256']==run['dataset_manifest_sha256'],'Imported question dataset changed')
    require(set(meta['rag_origins'])==expected,'Imported RAG task set differs')
    for tid,origin in meta['rag_origins'].items():
        require(origin['source_run_id']==run['run_id'],'Imported answer belongs to another run')
        require(origin['source_run_sha256']==judge.digest(entry['run_dir']/'run.json'),'Imported run manifest differs')
        require(origin['result_sha256']==judge.digest(entry['run_dir']/'results'/(tid+'.json')),'Imported answer differs')


def prepare_round(round_number):
    repeat.validate_contract()
    settings=grading.configs(['jev']);settings_contract(settings)
    for entry in plan(round_number):
        run=entry['run_dir'];progress=judge.read_json(run/'progress.json')
        require(progress['completed']==32 and progress['status']=='completed','Wait for all 32 new answers')
        require(progress['outcomes']=={'answered':32},'Inspect failed/refused answers separately; do not regenerate them')
        imp=entry['import_dir'];study=entry['study_dir']
        if not imp.exists():
            papers=list((run/'library/papers').glob('*.pdf'));require(len(papers)==1,'Expected one original PDF')
            command=[sys.executable,str(ROOT/'scripts/import_qa_system_answers.py'),
                '--input',str(ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer.txt'),
                '--extra',str(ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer_PFI2-013.json'),
                '--pdf',str(papers[0]),
                '--rag-run',str(run),'--recovery-run',str(run),'--output',str(imp),'--verify-rag-quotes']
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            require(result.returncode==0,'Answer import failed; inspect source fingerprints before retrying')
            judge.write(OUTPUT/f"import-{entry['system']}-r{round_number}.json",dict(
                stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
                stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),returncode=result.returncode))
        if not study.exists():
            study.parent.mkdir(parents=True,exist_ok=True)
            grading.prepare(imp,study,settings,['rag'])
        contract=judge.read_json(study/'study.json')
        validate_study_binding(entry,contract)
        print(json.dumps(dict(prepared=study.name,grading_calls=0)),flush=True)
    return dict(round=round_number,prepared_jobs=64,grading_calls=0)


def execute_jobs(jobs,settings,stop,workers,round_number):
    statuses=Counter();error_type=None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[]
        for entry,job in jobs:
            cfg=settings['jev']
            factory=lambda cfg=cfg:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy=PROXY)
            futures.append(pool.submit(grading.evaluate_one,entry['study_dir'],job,cfg,stop,factory,3))
        for f in as_completed(futures):
            if f.cancelled():statuses['cancelled_before_start']+=1;continue
            try:statuses[f.result()]+=1
            except Exception as error:
                error_type=error_type or type(error).__name__
                stop.set();statuses['executor_error']+=1
                for other in futures:other.cancel()
            if sum(statuses.values())%8==0:
                print(json.dumps(dict(round=round_number,done=sum(statuses.values()),statuses=dict(statuses))),flush=True)
    return dict(statuses=dict(statuses),execution_error_type=error_type)


def grade_round(round_number,workers=4):
    require(type(workers) is int and 1<=workers<=4,'Invalid judge concurrency')
    repeat.validate_contract()
    settings=grading.configs(['jev']);settings_contract(settings)
    entries=plan(round_number);jobs=[];stop=threading.Event()
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ExitStack() as locks:
        for entry in entries:
            output=entry['study_dir'];contract=judge.read_json(output/'study.json')
            validate_study_binding(entry,contract)
            require(contract['policy_sha256']==grading.POLICY_SHA,'Scoring policy changed')
            require(contract['requested_judges']==grading.public_settings(settings),'Scoring model changed')
            require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in contract['harness_files'].items()),'Frozen grading harness changed')
            locks.enter_context(judge.lock(output))
            audit=reporting.audit(entry['import_dir'],output)
            require(all(status!='pending' for _,_,status in audit[5]),'Inspect an interrupted judge call before retrying')
            jobs.extend((entry,j) for j in contract['jobs'])
        jobs.sort(key=lambda pair:judge.sha([round_number,pair[0]['system'],pair[1]['name']]))
        outcome=execute_jobs(jobs,settings,stop,workers,round_number)
        result=dict(round=round_number,selected=64,**outcome,billing_stop=stop.is_set(),max_attempts=3)
        judge.write(OUTPUT/f'grading-progress-r{round_number}.json',result)
        require(outcome['execution_error_type'] is None,'Judge execution stopped; inspect retained request records')
        return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run'])
    p.add_argument('--round',type=int,choices=[2,3],required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    try:result=prepare_round(a.round) if a.action=='prepare' else grade_round(a.round,a.workers)
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Grading halted; preserve all valid answers and existing request records.')));raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False))
