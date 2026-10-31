"""Five fresh independent answer pairs for PFI2-016 and PFI2-028; unchanged Jev packets."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
import json
import shutil
import sys
import threading

import httpx
from filelock import FileLock
import judge_qa_eval as judge
import run_qa_baseline as baseline
import section_context_20261031 as runner
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import import_qa_system_answers as importer
from collect_rerank_stability_20261031 import scientific_candidate
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
TAG='fallback-two-cases-five-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
SOURCE=ROOT/'.rag-data/evaluations/fallback-ablation-20261031'
TASKS=('PFI2-016','PFI2-028')
ARMS=('control','guidance')
ROUNDS=tuple(range(1,6))
ENGINES=('repeat_fallback_cases_20261031.py','report_repeated_fallback_cases_20261031.py',
    'section_context_20261031.py','context_expansion_worker.py',*grading.HARNESS)


def combinations():
    return [(r,t,a) for r in ROUNDS for t in TASKS for a in ARMS]


def prepare():
    require(not OUTPUT.exists(),'Never overwrite a prepared or paid repeat')
    entries=[];fixtures={};parent=judge.read_json(SOURCE/'experiment.json')
    for a in ARMS:
        fixtures[a]={}
        for tid in TASKS:
            original=SOURCE/'fixtures'/a/(tid+'.json');target=OUTPUT/'fixtures'/a/(tid+'.json')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
            require(judge.digest(original)==parent['fixtures'][tid][a]['fixture_sha256'],'Original fixture seal differs')
            fixtures[a][tid]=judge.digest(target)
    for r in ROUNDS:
        for a in ARMS:
            original=SOURCE/'runs'/a;d=OUTPUT/'runs'/f'{a}-r{r}';old=judge.read_json(original/'run.json')
            for name in ['backend','dataset','harness']:shutil.copytree(original/name,d/name)
            (d/'results').mkdir();(d/'attempts').mkdir()
            run={**old,'run_id':TAG+f'-{a}-r{r}','created_at':judge.now(),
                'tasks':[t for t in old['tasks'] if t['id'] in TASKS],'execution_mode':'fresh_independent_fixed_context_repeat',
                'selection_note':'Only original PFI2-016 and PFI2-028; earlier answers are excluded from these five repeats.'}
            require(len(run['tasks'])==2,'Unexpected selected tasks');runner.save(d/'run.json',run)
            entries.append(dict(round=r,arm=a,run_dir=str(d),run_sha256=judge.digest(d/'run.json'),
                source_files=run['source_files'],configuration_probe=run['configuration_probe']))
    c=dict(version='two-case-five-independent-repeats-v1',created_at=judge.now(),rounds=list(ROUNDS),task_ids=list(TASKS),
        runs=entries,fixtures=fixtures,prior_experiment_sha256=judge.digest(SOURCE/'experiment.json'),
        engine_sha256={n:judge.digest(ROOT/'scripts'/n) for n in dict.fromkeys(ENGINES)},
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),planned_answers=20,planned_jev_jobs=20,
        old_answers_included=False,new_embedding_calls=0,new_rerank_calls=0,default_configuration_changed=False,
        scheduling='Five sequential rounds; each question has two independent worker processes, alternating submission order. No conversation or prior answer in input.')
    runner.save(OUTPUT/'experiment.json',c)
    return dict(prepared=20,independent_processes=20,old_answers_counted=0,provider_calls=0)


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in c['engine_sha256'].items()),'Frozen runtime or grading code changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['app_env_sha256'],'Website configuration changed')
    require(judge.digest(SOURCE/'experiment.json')==c['prior_experiment_sha256'],'Original pure-deletion experiment changed')
    for a in ARMS:
        for tid,h in c['fixtures'][a].items():
            require(judge.digest(OUTPUT/'fixtures'/a/(tid+'.json'))==h==judge.digest(SOURCE/'fixtures'/a/(tid+'.json')),'Fixed context changed')
    for e in c['runs']:
        d=Path(e['run_dir'])
        require(judge.digest(d/'run.json')==e['run_sha256'] and baseline.source_hashes(d/'backend')==e['source_files'],'Frozen run changed')
        require(baseline.configuration_probe(d/'backend')==e['configuration_probe'],'Model/high settings changed')
        require(judge.digest(d/'harness/context_expansion_worker.py')==c['engine_sha256']['context_expansion_worker.py'],'Worker changed')
    return c


def run():
    c=check_contract();lookup={(e['round'],e['arm']):e for e in c['runs']};runner.OUTPUT=OUTPUT
    with FileLock(str(OUTPUT/'.generation.lock'),timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        for r in ROUNDS:
            local=dict(arms={a:lookup[r,a] for a in ARMS})
            for i,tid in enumerate(TASKS):
                order=ARMS if (r+i)%2 else tuple(reversed(ARMS))
                fs={a:pool.submit(runner.one,a,tid,local) for a in order};outcomes={a:f.result() for a,f in fs.items()}
                print(json.dumps(dict(round=r,task_id=tid,outcomes=outcomes)),flush=True)
                require('failed' not in outcomes.values(),'Preserve failed paid results; inspect before continuing')
            for a in ARMS:
                d=Path(lookup[r,a]['run_dir']);rows=[judge.read_json(p) for p in (d/'results').glob('*.json')]
                runner.save(d/'progress.json',dict(status='completed',completed=2,total=2,outcomes=dict(Counter(row['status'] for row in rows))))
    return dict(completed=20)


def job_packet(e,tid):
    """Project one new result into the original scientific packet; no old answer/grade reaches Jev."""
    d=Path(e['run_dir']);run=judge.read_json(d/'run.json');row=judge.read_json(d/'results'/(tid+'.json'))
    require(judge.read_json(d/'attempts'/(tid+'.json'))['result_sha256']==judge.digest(d/'results'/(tid+'.json')),'Answer seal changed')
    require(row['status'] in ['answered','refused'],'Generation failure needs separate handling')
    imp=SOURCE/'imports'/e['arm'];meta,jobs,sources,pages=grading.load_import(imp)
    template=deepcopy(next(j for j in jobs if j['system']=='rag' and j['task_id']==tid))
    candidate=scientific_candidate(row,tid)
    candidate['citations']=[importer.rag_citation(c,pages) for c in candidate['citations']]
    template['candidate']=candidate
    # Stable opaque identity depends on the new scientific answer, never an exposed arm label.
    template['blind_id']=judge.sha([tid,candidate])[:24]
    return template,meta,sources,pages,row


def grade_prepare():
    c=check_contract();cfg=grading.configs(['jev']);public=grading.public_settings(cfg)
    historical=judge.read_json(SOURCE/'studies/control/study.json')
    require(public==historical['requested_judges'] and grading.POLICY_SHA==historical['policy_sha256'],'Judge settings or rules changed')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in historical['harness_files'].items()),'Original grading harness changed')
    study=OUTPUT/'grading';require(not (study/'study.json').exists(),'Do not overwrite frozen scoring inputs')
    (study/'inputs').mkdir(parents=True);(study/'records').mkdir();entries=[]
    for e in c['runs']:
        for tid in TASKS:
            template,meta,sources,pages,row=job_packet(e,tid);state,questions,targets=grading.packet(template,meta,sources,pages)
            request=grading.request_for('jev',cfg['jev'],state,questions)
            name='jev-'+judge.sha([e['round'],e['arm'],tid])[:22];path=study/'inputs'/(name+'.json')
            runner.save(path,dict(request=request,questions=questions,targets=targets,state=state))
            entries.append(dict(name=name,judge='jev',system='rag',task_id=tid,round=e['round'],arm=e['arm'],
                input_sha256=judge.digest(path),request_sha256=judge.sha(request),
                result_sha256=judge.digest(Path(e['run_dir'])/'results'/(tid+'.json'))))
    runner.save(study/'study.json',dict(version='selected-two-case-jev-repeats-v1',created_at=judge.now(),jobs=entries,
        requested_judges=public,policy_sha256=grading.POLICY_SHA,engine_sha256=c['engine_sha256'],
        max_attempts=3,first_valid_only=True,selected_tasks=list(TASKS),planned_jobs=20,
        no_other_30_questions_generated_or_graded=True,prior_scores_in_packets=False))
    return dict(prepared_jobs=20,provider_calls=0)


def grade():
    check_contract();study=OUTPUT/'grading';c=judge.read_json(study/'study.json');cfg=grading.configs(['jev'])
    require(c['requested_judges']==grading.public_settings(cfg) and c['policy_sha256']==grading.POLICY_SHA,'Grading settings changed')
    stop=threading.Event();statuses=Counter()
    with judge.lock(study),ThreadPoolExecutor(max_workers=4) as pool:
        factory=lambda:httpx.Client(timeout=cfg['jev'].timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
        fs=[pool.submit(grading.evaluate_one,study,e,cfg['jev'],stop,factory,3) for e in sorted(c['jobs'],key=lambda e:e['name'])]
        for f in as_completed(fs):
            try:statuses[f.result()]+=1
            except Exception:
                stop.set()
                for other in fs:other.cancel()
                raise
            print(json.dumps(dict(done=sum(statuses.values()),statuses=dict(statuses))),flush=True)
    runner.save(OUTPUT/'grading-progress.json',dict(selected=20,statuses=dict(statuses)))
    return dict(selected=20,statuses=dict(statuses))


def collect():
    c=check_contract();study=OUTPUT/'grading';gc=judge.read_json(study/'study.json');rows=[];calls=[]
    config=scoring.config_from_public('jev',gc['requested_judges']['jev']);lookup={(e['round'],e['arm']):e for e in c['runs']}
    require(len(gc['jobs'])==20 and {(e['round'],e['task_id'],e['arm']) for e in gc['jobs']}==set(combinations()),'Wrong grading coverage')
    for entry in gc['jobs']:
        e=lookup[entry['round'],entry['arm']];tid=entry['task_id']
        template,meta,sources,pages,row=job_packet(e,tid);state,questions,targets=grading.packet(template,meta,sources,pages)
        saved=judge.read_json(study/'inputs'/(entry['name']+'.json'));request=grading.request_for('jev',config,state,questions)
        require(saved==dict(request=request,questions=questions,targets=targets,state=state) and judge.sha(request)==entry['request_sha256'],
            'Scientific judge context changed')
        require(judge.digest(study/'inputs'/(entry['name']+'.json'))==entry['input_sha256'] and
            judge.digest(Path(e['run_dir'])/'results'/(tid+'.json'))==entry['result_sha256'],'Input/result seal changed')
        accepted=None;attempts=[];paths=sorted((study/'records'/entry['name']).glob('*.json'),key=lambda p:int(p.stem))
        require(len(paths)<=3,'Too many grading attempts')
        for i,path in enumerate(paths,1):
            record=judge.read_json(path);require(record['status']!='pending','Wait for pending paid grading request')
            require(int(path.stem)==record['attempt']==i and accepted is None,'Grading sequence changed')
            require(record['request_sha256']==entry['request_sha256'],'Request changed')
            if i>1:require(record['prior_record_sha256']==judge.digest(paths[i-2]),'Prior attempt changed')
            if record.get('raw_response') is not None:require(judge.sha(record['raw_response'])==record['response_sha256'],'Raw response changed')
            if record['status']=='completed':
                accepted=grading.decode('jev',record['raw_response'],request,questions,targets,state)
                require(accepted==record['review'],'Original Jev judgment changed')
            attempts.append(dict(attempt=i,status=record['status'],record_sha256=judge.digest(path)));calls.append(record)
        fixture=judge.read_json(OUTPUT/'fixtures'/entry['arm']/(tid+'.json'));response=row['response']
        require(response['retrieved_evidence']==fixture['evidences'] and response['retrieval_seed_evidence']==fixture['seeds'],'Actual answer context changed')
        rows.append(dict(round=entry['round'],arm=entry['arm'],task_id=tid,reference_case=template['reference_case'],
            candidate=template['candidate'],review=accepted,metrics=scoring.metrics(accepted,template['reference_case'],template['task']['capabilities']) if accepted else None,
            grading_status='completed' if accepted else (attempts[-1]['status'] if attempts else 'missing'),
            answer_status=row['status'],reason_code=row.get('reason_code'),generation_calls=response['generation_calls'],
            latency_ms=row['end_to_end_ms'],attempts=attempts,evidence_sha256=fixture['evidences_sha256'],
            result_sha256=entry['result_sha256'],judge_request_sha256=entry['request_sha256']))
    notes=judge.read_json(OUTPUT/'analysis-notes.json') if (OUTPUT/'analysis-notes.json').exists() else []
    p=dict(version=c['version'],records=rows,accounting=dict(jev=scoring.accounting(calls,'jev')),
        controls=dict(rounds=5,fresh_answers=20,old_answers_included=False,new_embedding_calls=0,new_rerank_calls=0,
            default_configuration_changed=False,fixtures=c['fixtures'],generation_settings={a:c['runs'][0 if a=='control' else 1]['configuration_probe'] for a in ARMS}),
        provenance=dict(experiment_sha256=judge.digest(OUTPUT/'experiment.json'),study_sha256=judge.digest(study/'study.json'),engine_sha256=c['engine_sha256']),analyst_notes=notes)
    runner.save(OUTPUT/'analysis-input.json',p);return dict(records=len(rows),valid_grades=sum(r['review'] is not None for r in rows),provider_calls=0)


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report']);a=p.parse_args()
    try:
        if a.action=='report':
            import report_repeated_fallback_cases_20261031 as rep
            result=rep.publish(ROOT,OUTPUT)
        else:result={'prepare':prepare,'run':run,'grade-prepare':grade_prepare,'grade':grade,'collect':collect}[a.action]()
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Preserve sealed inputs and paid attempts; do not replay successful answers.')));raise SystemExit(1)
