"""Freeze and execute fresh control/guidance A/B answers on identical historical contexts."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

from filelock import FileLock

import judge_qa_eval as judge
import run_qa_baseline as baseline
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'.rag-data/evaluations/answer-guidance-20261031'
SOURCE=ROOT/'.rag-data/evaluations/pfi-content-units-v1-20261030-r1'


def canonical_sha(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prepare():
    require(not (OUTPUT/'experiment.json').exists(),'Experiment already prepared')
    source,_,cases,_=judge.verify_run(SOURCE)
    OUTPUT.mkdir(parents=True,exist_ok=True);fixtures=OUTPUT/'fixtures';fixtures.mkdir(exist_ok=True)
    documents=None;sealed={}
    for task in source['tasks']:
        path,result=judge.read_result(SOURCE,source,cases[task['case_id']],task)
        require(result['status']=='answered','Use the preregistered answered control-source run')
        response=result['response'];evidence=response['retrieved_evidence']
        if documents is None:documents=response['configuration']['documents']
        require(documents==response['configuration']['documents'],'Original corpus changed')
        fixture=dict(version='answer-guidance-fixed-evidence-v1',task_id=task['id'],question=result['question'],
            evidences=evidence,documents=documents,source_result_sha256=judge.digest(path),evidence_sha256=canonical_sha(evidence))
        target=fixtures/(task['id']+'.json')
        if target.exists():require(judge.read_json(target)==fixture,'Original fixture changed')
        else:judge.write(target,fixture)
        sealed[task['id']]=dict(fixture_sha256=judge.digest(target),evidence_sha256=fixture['evidence_sha256'],source_result_sha256=judge.digest(path))
    arms={}
    for arm in ['control','guidance']:
        directory=OUTPUT/'runs'/arm
        require(not directory.exists(),'Controlled run already exists; inspect partial preparation')
        baseline.prepare(ROOT/'.rag-data/baselines'/f'qa-answer-guidance-{arm}-20261031',ROOT/'fiberscope-eval-v2',
            ROOT/'.rag-data/configs'/f'answer-guidance-{arm}-20261031.env',directory,
            ROOT/'.rag-data/eval-checkouts/answer-guidance-20261031/backend/literature_rag',
            'core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
        require(judge.read_json(directory/'run.json')['tasks']==source['tasks'],'New task list differs')
        harness=directory/'harness/answer_guidance_worker.py';shutil.copyfile(ROOT/'scripts/answer_guidance_worker.py',harness)
        run=judge.read_json(directory/'run.json')
        run.update(input_policy='Only question, frozen backend path and fixed source-evidence fixture reach the worker; no gold answers or prior output.',
            execution_mode='fixed_retrieved_evidence',controlled_harness=dict(worker_sha256=judge.digest(harness),fixtures=sealed),
            source_evidence_run_sha256=judge.digest(SOURCE/'run.json'))
        baseline.write_json(directory/'run.json',run)
        arms[arm]=dict(run_dir=str(directory),run_sha256=judge.digest(directory/'run.json'),
            configuration_probe=run['configuration_probe'],source_files=run['source_files'])
    a,b=[arms[s]['configuration_probe'] for s in ['control','guidance']]
    require({k:v for k,v in a.items() if k!='answer_guidance'}=={k:v for k,v in b.items() if k!='answer_guidance'},'Only guidance flag may differ')
    require('answer_guidance' not in a and b['answer_guidance']['enabled'],'Guidance A/B setup is wrong')
    contract=dict(version='answer-guidance-fixed-evidence-v1',created_at=judge.now(),source_run_sha256=judge.digest(SOURCE/'run.json'),
        arms=arms,fixtures=sealed,task_ids=[t['id'] for t in source['tasks']],
        runner_sha256=judge.digest(Path(__file__)),worker_sha256=judge.digest(ROOT/'scripts/answer_guidance_worker.py'),
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),
        policy='Fresh independent A/B generations; exact same question/evidence; unchanged model/schema/citation validation and max-two repairs; no embedding/retrieval/rerank calls.',
        total_new_questions=64,source_contexts=32)
    judge.write(OUTPUT/'experiment.json',contract)
    return dict(prepared=2,questions=64,source_contexts=32,provider_calls=0)


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(c['runner_sha256']==judge.digest(Path(__file__)),'Fixed-context runner changed')
    require(c['worker_sha256']==judge.digest(ROOT/'scripts/answer_guidance_worker.py'),'Fixed-context worker changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['app_env_sha256'],'Default application configuration changed')
    for arm,entry in c['arms'].items():
        directory=Path(entry['run_dir']);r=judge.read_json(directory/'run.json')
        require(judge.digest(directory/'run.json')==entry['run_sha256'],'Frozen run manifest changed')
        require(baseline.source_hashes(directory/'backend')==r['source_files'],'Controlled source changed')
        require(baseline.configuration_probe(directory/'backend')==r['configuration_probe'],'Controlled configuration changed')
        require(judge.digest(directory/'harness/answer_guidance_worker.py')==c['worker_sha256'],'Archived replay worker changed')
    for tid,s in c['fixtures'].items():require(judge.digest(OUTPUT/'fixtures'/(tid+'.json'))==s['fixture_sha256'],'Original evidence fixture changed')
    return c


def one(arm,tid,contract):
    directory=Path(contract['arms'][arm]['run_dir']);run=judge.read_json(directory/'run.json')
    task=next(t for t in run['tasks'] if t['id']==tid);fixture=judge.read_json(OUTPUT/'fixtures'/(tid+'.json'))
    result_path=directory/'results'/(tid+'.json');attempt_path=directory/'attempts'/(tid+'.json')
    if result_path.exists():
        require(judge.read_json(attempt_path)['result_sha256']==judge.digest(result_path),'Saved controlled result changed')
        return judge.read_json(result_path)['status']
    require(not attempt_path.exists(),'Interrupted paid attempt requires inspection; no automatic replay')
    result=dict(run_id=run['run_id'],task_id=tid,case_id=task['case_id'],question=fixture['question'],
        started_at=judge.now(),runner_sha256=judge.digest(Path(__file__)),suite=task['suite'],capabilities=task['capabilities'],
        variant=task.get('variant'),execution_timeout_seconds=run['timeout_seconds'])
    judge.write(attempt_path,{**result,'status':'started'});started=perf_counter()
    payload=dict(backend_dir=str(directory/'backend'),fixture_file=str(OUTPUT/'fixtures'/(tid+'.json')),question=fixture['question'])
    try:
        process=subprocess.run([sys.executable,'-I','-X','utf8',str(directory/'harness/answer_guidance_worker.py')],
            input=json.dumps(payload,ensure_ascii=False),env=baseline.clean_environment(),capture_output=True,text=True,
            encoding='utf-8',timeout=run['timeout_seconds'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result.update(worker_returncode=process.returncode,worker_stderr_sha256=sha256(process.stderr.encode()).hexdigest(),worker_stderr_bytes=len(process.stderr.encode()))
        if process.returncode:result.update(status='failed',reason_code='controlled_worker_error',response=None)
        else:
            response=json.loads(process.stdout)
            require(response['status'] in ['answered','refused','failed'],'Invalid answer status')
            diag=response['fixed_evidence_diagnostics']
            require(diag['generation_input_evidence_sha256']==fixture['evidence_sha256'],'Actual generation evidence changed')
            require(response['retrieved_evidence']==fixture['evidences'],'Source evidence identity changed')
            require(response['configuration']['prompt_pipeline_sha256']==run['configuration_probe']['prompt_pipeline_sha256'],'Unexpected prompt pipeline')
            result.update(status=response['status'],reason_code=response.get('reason_code'),response=response)
    except subprocess.TimeoutExpired:result.update(status='failed',reason_code='controlled_worker_timeout',response=None)
    result.update(finished_at=judge.now(),end_to_end_ms=round((perf_counter()-started)*1000))
    judge.write(result_path,result);judge.write(attempt_path,dict(status='completed',result_sha256=judge.digest(result_path)))
    all_results=[judge.read_json(p) for p in (directory/'results').glob('*.json')]
    judge.write(directory/'progress.json',dict(status='completed' if len(all_results)==32 else 'running',completed=len(all_results),total=32,outcomes=dict(Counter(r['status'] for r in all_results))))
    return result['status']


def run():
    c=check_contract()
    with FileLock(str(OUTPUT/'.generation.lock'),timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        for i,tid in enumerate(c['task_ids']):
            order=['control','guidance'] if i%2==0 else ['guidance','control']
            futures={arm:pool.submit(one,arm,tid,c) for arm in order}
            try:outcomes={arm:f.result() for arm,f in futures.items()}
            except Exception:
                for f in futures.values():f.cancel()
                raise
            record=dict(task_id=tid,outcomes=outcomes,finished_at=judge.now());judge.write(OUTPUT/'last-pair.json',record)
            print(json.dumps(record),flush=True)
    return dict(completed=64)


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run']);a=p.parse_args()
    try:print(json.dumps(prepare() if a.action=='prepare' else run(),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Experiment halted; preserve existing paid attempts for inspection.')));sys.exit(1)
