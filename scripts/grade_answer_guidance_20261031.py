"""Independent Jev scoring for the fresh fixed-context prompt A/B answers."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import ExitStack
import json
from pathlib import Path
import threading

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import import_qa_system_answers as importer
import run_answer_guidance_20261031 as experiment
from qa_repeat_refusal_compat import compatible_results
from grade_qa_rerank_repeats_20261031 import validate_study_binding
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'.rag-data/evaluations/answer-guidance-20261031'


def entries():
    return [dict(arm=a,run_dir=OUTPUT/'runs'/a,import_dir=OUTPUT/'imports'/a,study_dir=OUTPUT/'studies'/a) for a in ['control','guidance']]


def contract(settings):
    historical=judge.read_json(ROOT/'.rag-data/evaluations/content-units-jev-20261030-r1/study.json')
    require(historical['requested_judges']==grading.public_settings(settings),'Judge settings changed')
    require(historical['policy_sha256']==grading.POLICY_SHA,'Original judge policy changed')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in historical['harness_files'].items()),'Original grading harness changed')
    body=dict(version='answer-guidance-grading-v1',policy_sha256=grading.POLICY_SHA,
        requested_judges=grading.public_settings(settings),grader_sha256=judge.digest(Path(__file__)),
        helper_sha256=judge.digest(ROOT/'scripts/grade_qa_rerank_repeats_20261031.py'),
        result_reader_compat_sha256=judge.digest(ROOT/'scripts/qa_repeat_refusal_compat.py'),
        max_attempts=3,planned_jobs=64,first_valid_only=True,previous_scores_supplied=False,
        route='Existing local HTTP proxy at 127.0.0.1:10808',new_luna_calls=0)
    path=OUTPUT/'grading-contract.json'
    if path.exists():require(judge.read_json(path)==body,'Controlled grading contract changed')
    else:judge.write(path,body)
    return body


def prepare():
    experiment.check_contract();settings=grading.configs(['jev']);contract(settings)
    for e in entries():
        run=e['run_dir'];p=judge.read_json(run/'progress.json')
        require(p['status']=='completed' and p['completed']==32,'Wait for all independent answers')
        require(set(p['outcomes'])<={'answered','refused'},'Preserve and inspect failed answers; do not regenerate them')
        imp,study=e['import_dir'],e['study_dir']
        if not imp.exists():
            pdfs=list((run/'library/papers').glob('*.pdf'));require(len(pdfs)==1,'Expected one sealed original PDF')
            with compatible_results():
                importer.prepare(ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer.txt',
                    [ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer_PFI2-013.json'],
                    pdfs[0],run,run,imp,verify_rag_quotes=True)
        if not study.exists():
            study.parent.mkdir(parents=True,exist_ok=True);grading.prepare(imp,study,settings,['rag'])
        validate_study_binding(e,judge.read_json(study/'study.json'))
        print(json.dumps(dict(prepared=e['arm'],jobs=32,new_provider_calls=0)),flush=True)
    return dict(prepared_jobs=64,new_provider_calls=0)


def run():
    experiment.check_contract();settings=grading.configs(['jev']);contract(settings)
    jobs=[];stop=threading.Event();statuses=Counter();errors=[]
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ExitStack() as stack:
        for e in entries():
            study=e['study_dir'];c=judge.read_json(study/'study.json')
            validate_study_binding(e,c)
            require(c['requested_judges']==grading.public_settings(settings),'Frozen judge settings changed')
            require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in c['harness_files'].items()),'Frozen judge harness changed')
            stack.enter_context(judge.lock(study));audit=scoring.audit(e['import_dir'],study)
            require(all(s!='pending' for _,_,s in audit[5]),'Inspect an interrupted paid score before retrying')
            jobs.extend((e,j) for j in c['jobs'])
        jobs.sort(key=lambda pair:judge.sha([pair[0]['arm'],pair[1]['name']]))
        with ThreadPoolExecutor(max_workers=4) as pool:
            cfg=settings['jev'];factory=lambda:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
            futures=[pool.submit(grading.evaluate_one,e['study_dir'],j,cfg,stop,factory,3) for e,j in jobs]
            for future in as_completed(futures):
                if future.cancelled():statuses['cancelled_before_start']+=1;continue
                try:statuses[future.result()]+=1
                except Exception as error:
                    errors.append(type(error).__name__);stop.set();statuses['execution_error']+=1
                    for other in futures:other.cancel()
                if sum(statuses.values())%8==0:print(json.dumps(dict(done=sum(statuses.values()),statuses=dict(statuses))),flush=True)
        progress=dict(selected=64,statuses=dict(statuses),execution_error_types=errors,billing_stop=stop.is_set(),max_attempts=3)
        judge.write(OUTPUT/'grading-progress.json',progress)
        require(not errors,'Judge halted; preserve completed scorecards and inspect recorded attempts')
        return progress


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run']);a=p.parse_args()
    try:print(json.dumps(prepare() if a.action=='prepare' else run(),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Keep valid answers and request records; no automatic source replay.')));raise SystemExit(1)
