"""Missing-part coverage study using unchanged sealed replay, grading and offline reporting engines."""
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace
import json
import shutil

import judge_qa_eval as judge
import run_qa_baseline as baseline
import run_answer_guidance_20261031 as replay
import grade_answer_guidance_20261031 as grader
import collect_answer_guidance_20261031 as collector
import report_answer_guidance_20261031 as report
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
TAG='answer-guidance-v3-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
ARMS=('control','guidance')
VERSION='answer-completeness-v3'
ENGINES=('run_answer_guidance_20261031.py','answer_guidance_worker.py','grade_answer_guidance_20261031.py',
    'run_qa_baseline.py','freeze_qa_baseline.py','qa_system_judge.py','qa_repeat_refusal_compat.py',
    'collect_answer_guidance_20261031.py','report_answer_guidance_20261031.py')


def prepare():
    require(not (OUTPUT/'experiment.json').exists(),'Study already prepared; never overwrite paid results')
    source,_,cases,_=judge.verify_run(replay.SOURCE)
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/'fixtures').mkdir(exist_ok=True)
    sealed={};documents=None
    for task in source['tasks']:
        path,result=judge.read_result(replay.SOURCE,source,cases[task['case_id']],task)
        require(result['status']=='answered','Preregistered source must be answered')
        response=result['response'];evidence=response['retrieved_evidence']
        if documents is None:documents=response['configuration']['documents']
        require(documents==response['configuration']['documents'],'Original document corpus changed')
        fixture=dict(version='answer-guidance-fixed-evidence-v1',task_id=task['id'],question=result['question'],
            evidences=evidence,documents=documents,source_result_sha256=judge.digest(path),evidence_sha256=replay.canonical_sha(evidence))
        target=OUTPUT/'fixtures'/(task['id']+'.json')
        if target.exists():require(judge.read_json(target)==fixture,'Prepared evidence changed')
        else:judge.write(target,fixture)
        sealed[task['id']]=dict(fixture_sha256=judge.digest(target),evidence_sha256=fixture['evidence_sha256'],source_result_sha256=judge.digest(path))
    arms={}
    for arm in ARMS:
        directory=OUTPUT/'runs'/arm
        baseline.prepare(ROOT/'.rag-data/baselines'/f'qa-answer-guidance-v3-{arm}-20261031',ROOT/'fiberscope-eval-v2',
            ROOT/'.rag-data/configs'/f'answer-guidance-v3-{arm}-20261031.env',directory,
            ROOT/'.rag-data/eval-checkouts'/TAG/'backend/literature_rag','core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
        run=judge.read_json(directory/'run.json');require(run['tasks']==source['tasks'],'Questions changed')
        harness=directory/'harness/answer_guidance_worker.py';shutil.copyfile(ROOT/'scripts/answer_guidance_worker.py',harness)
        run.update(input_policy='Only question, frozen backend path and fixed source-evidence fixture; no gold/prior answers.',
            execution_mode='fixed_retrieved_evidence',controlled_harness=dict(worker_sha256=judge.digest(harness),fixtures=sealed),
            source_evidence_run_sha256=judge.digest(replay.SOURCE/'run.json'))
        baseline.write_json(directory/'run.json',run)
        arms[arm]=dict(run_dir=str(directory),run_sha256=judge.digest(directory/'run.json'),
            configuration_probe=run['configuration_probe'],source_files=run['source_files'])
    a,b=[arms[arm]['configuration_probe'] for arm in ARMS]
    collector.compare_settings({'control':a,'guidance':b},source['configuration_probe'])
    require(b['answer_guidance']['version']==VERSION,'Wrong missing-part-guidance version')
    contract=dict(version='answer-guidance-fixed-evidence-v1',created_at=judge.now(),source_run_sha256=judge.digest(replay.SOURCE/'run.json'),
        arms=arms,fixtures=sealed,task_ids=[t['id'] for t in source['tasks']],
        runner_sha256=judge.digest(ROOT/'scripts/run_answer_guidance_20261031.py'),
        worker_sha256=judge.digest(ROOT/'scripts/answer_guidance_worker.py'),
        controller_sha256=judge.digest(Path(__file__)),engine_sha256={name:judge.digest(ROOT/'scripts'/name) for name in ENGINES},
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),guidance_version=VERSION,
        policy='Fresh independent original/missing-part-guidance A/B; identical historical evidence, original model/High/schema/validation/max-two calls; no retrieval or rerank.',
        total_new_questions=64,source_contexts=32)
    judge.write(OUTPUT/'experiment.json',contract)
    return dict(prepared=64,provider_calls=0)


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(c['controller_sha256']==judge.digest(Path(__file__)) and c['guidance_version']==VERSION,'Study controller changed')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in c['engine_sha256'].items()),'Original execution engines changed')
    replay.OUTPUT=OUTPUT
    replay.check_contract()
    return c


def collect(notes_file=None):
    c=check_contract()
    notes=[] if notes_file is None else judge.read_json(notes_file)
    require(isinstance(notes,list) and all(isinstance(n,str) for n in notes),'Analyst notes must be a list of text; never change scorecards')
    payload=collector.collect(ROOT,OUTPUT,analyst_notes=notes)
    payload['controls'].update(guidance_version=VERSION,controller_sha256=c['controller_sha256'])
    payload['provenance'].update(controller_sha256=c['controller_sha256'],engine_sha256=c['engine_sha256'])
    judge.write(OUTPUT/'analysis-input.json',payload)
    return dict(records=len(payload['records']),provider_calls=0)


def execute(action,notes_file=None,refresh=False):
    if action=='prepare':return prepare()
    check_contract()
    if action=='run':return replay.run()
    if action in ('grade-prepare','grade'):
        grader.OUTPUT=OUTPUT;grader.experiment=SimpleNamespace(check_contract=check_contract)
        return grader.prepare() if action=='grade-prepare' else grader.run()
    if action=='collect':return collect(notes_file)
    if action=='report':
        result=report.publish(OUTPUT/'analysis-input.json',ROOT/'data/literature/qa-evaluation/reports'/TAG,
            ROOT/'docs/QA_ANSWER_GUIDANCE_V3_REPORT_20261031.md',refresh=refresh)
        return dict(common_tasks=result['comparison']['tasks'],deltas=result['comparison']['deltas'],provider_calls=0)
    raise ValueError('Unsupported study operation')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report'])
    p.add_argument('--notes',type=Path);p.add_argument('--refresh',action='store_true');args=p.parse_args()
    try:print(json.dumps(execute(args.action,args.notes,args.refresh),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Study halted; preserve sealed inputs and paid attempts.')));raise SystemExit(1)
