"""Evaluate one evidence review against the exact saved DeepSeek drafts, with blind Jev grading."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from hashlib import sha256
from pathlib import Path
import json
import shutil
import subprocess
import sys
import threading
from time import perf_counter

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import run_qa_baseline as runner
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
TAG='evidence-review-20261102-v1'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
SOURCE=ROOT/'.rag-data/evaluations/pfi-answer-deepseek-20261102'
RUN=ROOT/'.rag-data/evaluations/pfi-evidence-review-20261102-v1'
WORKTREE=ROOT/'.rag-data/worktrees'/TAG
ARMS=('control','review')
CONFIG=ROOT/'.rag-data/configs/evidence-review-20261102.env'


def command(args,cwd=ROOT):
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,encoding='utf-8',
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    require(p.returncode==0,'Preparation failed: '+p.stdout[-1200:]+p.stderr[-1200:])
    return p.stdout


def prepare():
    require(not OUTPUT.exists(),'Keep prior experiments immutable')
    source,manifest,cases,_=judge.verify_run(SOURCE)
    require(len(source['tasks'])==32,'Use the same 32 core questions')
    commit=command(['git','rev-parse','HEAD']).strip()
    command(['git','worktree','add','--detach',str(WORKTREE),commit])
    OUTPUT.mkdir(parents=True)
    name='qa-'+TAG;baseline=WORKTREE/'.rag-data/baselines'/name
    command([sys.executable,'-X','utf8',str(WORKTREE/'scripts/freeze_qa_baseline.py'),'snapshot',str(baseline),
        '--env-file',str(CONFIG)],WORKTREE)
    frozen=ROOT/'.rag-data/baselines'/name;shutil.copytree(baseline,frozen)
    runner.prepare(frozen,ROOT/'fiberscope-eval-v2',CONFIG,RUN,WORKTREE/'backend/literature_rag',
        'core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
    run=judge.read_json(RUN/'run.json');require(run['tasks']==source['tasks'],'Questions changed')
    require(run['configuration_probe']['evidence_review']['max_review_calls']==1,'Wrong review settings')
    questions={};source_hashes={}
    for task in source['tasks']:
        path,result=judge.read_result(SOURCE,source,cases[task['case_id']],task)
        require(result['status']=='answered','All original drafts must be valid delivered answers')
        r=result['response'];draft=dict(answer=r['answer'],claims=r['claims'])
        questions[sha256(result['question'].strip().encode()).hexdigest()]=dict(question=result['question'].strip(),
            draft=draft,evidences=r['retrieved_evidence'],seed_evidence=r['retrieval_seed_evidence'],
            documents=r['configuration']['documents'],source_result_sha256=judge.digest(path),
            source_answer_sha256=judge.sha(draft),original_citation_validation=r['citation_validation'])
        source_hashes[task['id']]=judge.digest(path)
    cache=RUN/'backend/evidence-review-cache.json';judge.write(cache,dict(questions=questions))
    worker=RUN/'backend/evidence_review_eval_worker.py'
    shutil.copyfile(ROOT/'scripts/qa_evidence_review_worker.py',worker)
    shutil.copyfile(ROOT/'scripts/qa_answer_replay_worker.py',RUN/'backend/qa_answer_replay_worker.py')
    run['evidence_review_control']=dict(cache_sha256=judge.digest(cache),worker_sha256=judge.digest(worker),
        source_run_id=source['run_id'],new_primary_generation_calls=0,new_retrieval_calls=0)
    run['source_files']=runner.source_hashes(RUN/'backend');judge.write(RUN/'run.json',run)
    contract=dict(version=TAG,created_at=judge.now(),source_commit=commit,
        controller_sha256=judge.digest(Path(__file__)),run_sha256=judge.digest(RUN/'run.json'),
        source_run_sha256=judge.digest(SOURCE/'run.json'),source_results=source_hashes,
        dataset_manifest_sha256=source['dataset_manifest_sha256'],website_config_sha256=judge.digest(ROOT/'backend/.env.literature'),
        policy_sha256=grading.POLICY_SHA,review_calls_per_answer=1,primary_generation_calls=0,retrieval_calls=0,
        comparison='32 sealed delivered DeepSeek drafts versus one source-grounded review of each identical draft; no new primary generation.',
        model_context='Only question, same sources/images and that question own draft claims; no gold, prior grades or other answers.',
        grading='Independent fresh Jev requests for both arms, unchanged original text policy, first valid at most three attempts.',
        website_activation='Decide after the matched experiment; keep current default unchanged during evaluation.')
    judge.write(OUTPUT/'contract.json',contract)
    return dict(prepared=32,primary_generations=0,new_review_calls_planned=32)


def verify():
    c=judge.read_json(OUTPUT/'contract.json')
    require(judge.digest(Path(__file__))==c['controller_sha256'],'Controller changed')
    require(judge.digest(RUN/'run.json')==c['run_sha256'],'Run contract changed')
    require(judge.digest(SOURCE/'run.json')==c['source_run_sha256'],'Original run changed')
    require(all(judge.digest(SOURCE/'results'/(tid+'.json'))==h for tid,h in c['source_results'].items()),'Original drafts changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['website_config_sha256'],'Website config changed during evaluation')
    return c


def run(workers=4,limit=None):
    verify();meta=judge.read_json(RUN/'run.json');backend=RUN/'backend';control=meta['evidence_review_control']
    require(runner.source_hashes(backend)==meta['source_files'],'Frozen runtime changed')
    require(runner.configuration_probe(backend)==meta['configuration_probe'],'Private runtime config changed')
    require(judge.digest(backend/'evidence_review_eval_worker.py')==control['worker_sha256'] and
        judge.digest(backend/'evidence-review-cache.json')==control['cache_sha256'],'Frozen review input changed')
    cases={x['id']:x for x in judge.read_jsonl(RUN/'dataset/cases.jsonl')};stop=threading.Event()
    def one(task):
        if stop.is_set():return
        case=cases[task['case_id']];tid=task['id'];ap=RUN/'attempts'/(tid+'.json');rp=RUN/'results'/(tid+'.json')
        require(not ap.exists() and not rp.exists(),'Inspect interrupted paid review before replay')
        row=dict(run_id=meta['run_id'],case_id=case['id'],task_id=tid,question=case['question'],suite=task['suite'],
            capabilities=task['capabilities'],variant=task.get('variant'),started_at=judge.now(),runner_sha256=judge.digest(Path(__file__)))
        judge.write(ap,{**row,'status':'started'});start=perf_counter()
        try:
            p=runner.execute_question(backend/'evidence_review_eval_worker.py',RUN/'library',case['question'],240)
            row.update(worker_returncode=p.returncode,worker_stderr_sha256=judge.sha(p.stderr),worker_stderr_bytes=len(p.stderr.encode()))
            require(p.returncode==0,'Review worker failed; inspect the sealed paid attempt')
            response=json.loads(p.stdout)
            require(response['configuration']['prompt_pipeline_sha256']==meta['configuration_probe']['prompt_pipeline_sha256'],'Review runtime mismatch')
            require(response['retrieved_evidence']==judge.read_json(SOURCE/'results'/(tid+'.json'))['response']['retrieved_evidence'],'Sources changed')
            row.update(status=response['status'],reason_code=response.get('reason_code'),response=response)
            if response['evidence_review'].get('http_status') in {401,402,403}:stop.set()
        except subprocess.TimeoutExpired:
            row.update(status='failed',reason_code='review_worker_timeout',response=None);stop.set()
        row.update(finished_at=judge.now(),end_to_end_ms=round((perf_counter()-start)*1000))
        judge.write(rp,row);judge.write(ap,dict(case_id=case['id'],status='completed',result_sha256=judge.digest(rp)))
    with FileLock(str(RUN/'.runner.lock'),timeout=0):
        todo=[]
        for task in meta['tasks']:
            p=RUN/'results'/(task['id']+'.json');ap=RUN/'attempts'/(task['id']+'.json')
            if p.exists():require(judge.read_json(ap)['result_sha256']==judge.digest(p),'Completed result changed')
            else:
                require(not ap.exists(),'Interrupted paid attempt needs inspection');todo.append(task)
        if limit:todo=todo[:limit]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for f in as_completed([pool.submit(one,t) for t in todo]):
                f.result();rows=[judge.read_json(p) for p in sorted((RUN/'results').glob('*.json'))]
                progress=dict(status='completed' if len(rows)==32 else 'running',completed=len(rows),total=32,
                    outcomes=dict(Counter(x['status'] for x in rows)),
                    reviews=dict(Counter((x.get('response') or {}).get('evidence_review',{}).get('status') for x in rows)),
                    updated_at=judge.now(),billing_stop=stop.is_set())
                judge.write(RUN/'progress.json',progress);print(judge.encode(progress),flush=True)
    return judge.read_json(RUN/'progress.json')


def prepare_grading():
    c=verify();settings=grading.configs(['jev']);require(judge.read_json(RUN/'progress.json')['completed']==32,'Finish reviews first')
    for arm in ARMS:
        out=OUTPUT/arm;out.mkdir(exist_ok=True);imported=out/'import';study=out/'judges'
        if not imported.exists():
            if arm=='control':shutil.copytree(ROOT/'.rag-data/evaluations/answer-models-20261102/deepseek/import',imported)
            else:
                raw=ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw';pdf=next((RUN/'library/papers').glob('*.pdf'))
                command([sys.executable,'-X','utf8',str(ROOT/'scripts/import_qa_system_answers.py'),
                    '--input',str(raw/'answer.txt'),'--extra',str(raw/'answer_PFI2-013.json'),'--pdf',str(pdf),
                    '--rag-run',str(RUN),'--recovery-run',str(RUN),'--output',str(imported),'--verify-rag-quotes'])
        if not study.exists():grading.prepare(imported,study,settings,['rag'])
    c['judges']=grading.public_settings(settings)
    c['studies']={a:dict(study_sha256=judge.digest(OUTPUT/a/'judges/study.json'),import_sha256=judge.digest(OUTPUT/a/'import/import.json')) for a in ARMS}
    judge.write(OUTPUT/'contract.json',c)
    return dict(prepared=64,new_external_judge='jev',old_grades_provided=False)


def grade(workers=4):
    c=verify();settings=grading.configs(['jev']);require(grading.public_settings(settings)==c['judges'],'Judge config changed')
    cfg=settings['jev'];stop=threading.Event();tasks=[];statuses=Counter()
    for arm in ARMS:
        study=OUTPUT/arm/'judges';m=judge.read_json(study/'study.json')
        require(judge.digest(study/'study.json')==c['studies'][arm]['study_sha256'] and
            judge.digest(OUTPUT/arm/'import/import.json')==c['studies'][arm]['import_sha256'],'Study changed')
        require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in m['harness_files'].items()),'Judge harness changed')
        scoring.audit(OUTPUT/arm/'import',study)
        tasks.extend((arm,study,e) for e in m['jobs'])
    factory=lambda:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(grading.evaluate_one,study,e,cfg,stop,factory,3):arm for arm,study,e in
            sorted(tasks,key=lambda row:judge.sha(row[0]+row[2]['name']))}
        for f in as_completed(futures):
            statuses[(futures[f],f.result())]+=1
            if sum(statuses.values())%8==0:print(judge.encode(dict(done=sum(statuses.values()),statuses={a+':'+s:n for (a,s),n in statuses.items()})),flush=True)
    result=dict(statuses={a+':'+s:n for (a,s),n in statuses.items()},billing_stop=stop.is_set())
    judge.write(OUTPUT/'grading-progress.json',result);return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','prepare-grading','grade'])
    p.add_argument('--workers',type=int,choices=range(1,5),default=4);p.add_argument('--limit',type=int);args=p.parse_args()
    try:
        result={'prepare':prepare,'run':lambda:run(args.workers,args.limit),'prepare-grading':prepare_grading,
            'grade':lambda:grade(args.workers)}[args.action]();print(judge.encode(result),flush=True)
    except Exception as error:
        print(judge.encode(dict(error_type=type(error).__name__,message=str(error)[:1600])),file=sys.stderr);raise SystemExit(1)
