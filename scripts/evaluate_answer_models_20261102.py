"""Matched Astra/DeepSeek image-enabled answers with immutable inputs and Jev grading."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'.rag-data/evaluations/answer-models-20261102'
ARMS = ('astra', 'deepseek')
CACHE = ROOT/'.rag-data/evaluations/embedding-20261102/shared-query-cache.json'
WORKTREE = ROOT/'.rag-data/worktrees/qa-answer-models-20261102'


def run_path(arm):
    require(arm in ARMS, 'Unknown answer arm')
    return ROOT/('.rag-data/evaluations/pfi-answer-'+arm+'-20261102')


def arm_path(arm):
    return OUTPUT/arm


def command(args, cwd=ROOT):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(p.returncode == 0, 'Preparation failed: '+p.stdout[-1800:]+p.stderr[-1800:])
    return p.stdout


def prepare():
    require(not OUTPUT.exists(), 'Use a new frozen study')
    commit = command(['git', 'rev-parse', 'HEAD']).strip()
    command(['git', 'worktree', 'add', '--detach', str(WORKTREE), commit])
    OUTPUT.mkdir(parents=True)
    for arm in ARMS:
        env = ROOT/f'.rag-data/configs/answer-model-{arm}-20261102.env'
        name = 'qa-answer-'+arm+'-20261102'
        baseline = WORKTREE/'.rag-data/baselines'/name
        command([sys.executable, '-X', 'utf8', str(WORKTREE/'scripts/freeze_qa_baseline.py'),
            'snapshot', str(baseline), '--env-file', str(env)], WORKTREE)
        target = ROOT/'.rag-data/baselines'/name
        shutil.copytree(baseline, target)
        runner.prepare(target, ROOT/'fiberscope-eval-v2', env, run_path(arm),
            WORKTREE/'backend/literature_rag', 'core_text', ROOT/'.rag-data/baselines/qa-v1-20261024')
    r = run_path('astra'); meta = judge.read_json(r/'run.json')
    wrapper = r/'backend/embedding_eval_worker.py'
    shutil.copyfile(ROOT/'scripts/qa_embedding_eval_worker.py', wrapper)
    shutil.copyfile(CACHE, r/'backend/embedding-query-cache.json')
    meta['embedding_eval_control'] = dict(query_cache_sha256=judge.digest(CACHE),
        wrapper_sha256=judge.digest(wrapper), shared_rewrite_calls=0)
    meta['source_files'] = runner.source_hashes(r/'backend')
    runner.write_json(r/'run.json', meta)
    contract = dict(version='matched-answer-models-visual-v1', source_commit=commit,
        orchestrator_sha256=judge.digest(Path(__file__)),
        dataset_manifest_sha256=meta['dataset_manifest_sha256'], query_cache_sha256=judge.digest(CACHE),
        source_policy='Current MinerU/Qwen image-enabled retrieval once per question; both models see identical final text, refs and image bytes.',
        answer_context='Fresh independent worker per question. No reference answers, labels, grades or other model answers.',
        answer_guidance_enabled=False, model_reasoning_effort='high',
        website_config_sha256=judge.digest(ROOT/'backend/.env.literature'),
        max_generation_attempts=2, raw_judge_policy_sha256=grading.POLICY_SHA,
        final_authority='Codex source-based adjudication, separately logged; never overwrite raw Jev.',
        arms={a:dict(run_id=run_path(a).name, run_manifest_sha256=judge.digest(run_path(a)/'run.json')) for a in ARMS})
    judge.write(OUTPUT/'contract.json', contract)
    return dict(prepared=True, questions=32, answer_arms=2, website_changed=False)


def verify_contract():
    c = judge.read_json(OUTPUT/'contract.json')
    require(judge.digest(Path(__file__)) == c['orchestrator_sha256'], 'Frozen orchestrator changed')
    require(judge.digest(ROOT/'backend/.env.literature') == c['website_config_sha256'], 'Website config changed')
    for a in ARMS:
        require(judge.digest(run_path(a)/'run.json') == c['arms'][a]['run_manifest_sha256'], 'Run contract changed')
    return c


def answers(arm, workers=4, limit=None):
    verify_contract()
    r = run_path(arm); meta = judge.read_json(r/'run.json'); backend = r/'backend'
    require(runner.source_hashes(backend) == meta['source_files'], 'Frozen runtime changed')
    require(runner.configuration_probe(backend) == meta['configuration_probe'], 'Runtime configuration changed')
    require({p.relative_to(r/'dataset').as_posix():judge.digest(p) for p in (r/'dataset').rglob('*') if p.is_file()}
            == meta['dataset_files'], 'Dataset changed')
    tasks = meta['tasks']; cases = {c['id']:c for c in judge.read_jsonl(r/'dataset/cases.jsonl')}
    wrapper = backend/('embedding_eval_worker.py' if arm == 'astra' else 'answer_replay_worker.py')
    control = meta['embedding_eval_control'] if arm == 'astra' else meta['answer_replay_control']
    require(judge.digest(wrapper) == control['wrapper_sha256'], 'Wrapper changed')
    cache = backend/('embedding-query-cache.json' if arm == 'astra' else 'answer-evidence-cache.json')
    require(judge.digest(cache) == control.get('query_cache_sha256', control.get('cache_sha256')), 'Input cache changed')
    stop = threading.Event()
    def one(task):
        if stop.is_set():return
        case = cases[task['case_id']];tid = task['id'];p = r/'results'/(tid+'.json');ap = r/'attempts'/(tid+'.json')
        require(not ap.exists() and not p.exists(), 'Interrupted attempt requires review before any paid replay')
        require(runner.source_hashes(backend) == meta['source_files'], 'Runtime source changed')
        started = perf_counter()
        row = dict(run_id=meta['run_id'],case_id=case['id'],task_id=tid,question=case['question'],
            suite=task['suite'],capabilities=task['capabilities'],variant=task.get('variant'),
            started_at=judge.now(),execution_timeout_seconds=600,runner_sha256=judge.digest(Path(__file__)))
        judge.write(ap,{**row,'status':'started'})
        try:
            pworker = runner.execute_question(wrapper,r/'library',case['question'],600)
            row.update(worker_stderr_sha256=judge.sha(pworker.stderr),worker_stderr_bytes=len(pworker.stderr.encode()),worker_returncode=pworker.returncode)
            if pworker.returncode:
                row.update(status='failed',reason_code='worker_error',response=None)
            else:
                response = json.loads(pworker.stdout)
                require(response.get('status') in {'answered','refused','failed'}, 'Invalid worker result')
                require(all(response['configuration'].get(k) == meta['configuration_probe'][k] for k in
                    ('llm_model','embedding_model','top_k','min_score','prompt_pipeline_sha256')), 'Worker configuration mismatch')
                row.update(status=response['status'],reason_code=response.get('reason_code'),response=response)
        except subprocess.TimeoutExpired:
            row.update(status='failed',reason_code='timeout',response=None)
        row.update(finished_at=judge.now(),end_to_end_ms=round((perf_counter()-started)*1000))
        judge.write(p,row);judge.write(ap,dict(case_id=case['id'],status='completed',result_sha256=judge.digest(p)))
        if row['status'] == 'failed':stop.set()
        return tid
    with FileLock(str(r/'.runner.lock'),timeout=0):
        todo = []
        for task in tasks:
            p = r/'results'/(task['id']+'.json');ap = r/'attempts'/(task['id']+'.json')
            if p.exists():
                require(judge.read_json(p)['question'] == cases[task['case_id']]['question'] and
                    judge.read_json(ap).get('result_sha256') == judge.digest(p), 'Saved result changed')
            else:
                require(not ap.exists(), 'Interrupted paid attempt requires review')
                todo.append(task)
        if limit:todo = todo[:limit]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one,t) for t in todo]
            for f in as_completed(futures):
                f.result()
                rows = [judge.read_json(p) for p in sorted((r/'results').glob('*.json'))]
                progress = dict(status='completed' if len(rows)==32 else 'running',completed=len(rows),total=32,
                    outcomes=dict(Counter(x['status'] for x in rows)),updated_at=judge.now())
                judge.write(r/'progress.json',progress)
                print(judge.encode(dict(arm=arm,**progress)),flush=True)
    return judge.read_json(r/'progress.json')


def seal_replay():
    c = verify_contract(); target = run_path('deepseek');meta = judge.read_json(target/'run.json')
    require('answer_replay_control' not in meta, 'Replay already sealed')
    rows = {}
    for p in sorted((run_path('astra')/'results').glob('*.json')):
        r = judge.read_json(p);require(r['status'] in {'answered','refused'}, 'Resolve transport failure first')
        v = r['response'];es = v['retrieved_evidence']
        rows[sha256(r['question'].strip().encode()).hexdigest()] = dict(question=r['question'].strip(),
            top_k=v['configuration']['top_k'],min_score=v['configuration']['min_score'],evidences=es,
            seed_evidence=v['retrieval_seed_evidence'],source_result_sha256=judge.digest(p),
            input_sha256=sha256(json.dumps(es,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
    require(len(rows)==32, 'Need all 32 sealed scientific inputs')
    cache = target/'backend/answer-evidence-cache.json';judge.write(cache,dict(questions=rows))
    wrapper = target/'backend/answer_replay_worker.py';shutil.copyfile(ROOT/'scripts/qa_answer_replay_worker.py',wrapper)
    meta['answer_replay_control'] = dict(cache_sha256=judge.digest(cache),wrapper_sha256=judge.digest(wrapper),
        source_arm='astra',answer_text_replayed=False,query_embedding_calls=0,rerank_calls=0)
    meta['source_files'] = runner.source_hashes(target/'backend');judge.write(target/'run.json',meta)
    c['arms']['deepseek']['run_manifest_sha256']=judge.digest(target/'run.json')
    c['replay_sealed_at']=judge.now();judge.write(OUTPUT/'contract.json',c)
    return dict(sealed_inputs=32, answer_text_replayed=False)


def prepare_grading():
    verify_contract(); settings=grading.configs(['jev'])
    for arm in ARMS:
        r=run_path(arm); out=arm_path(arm);out.mkdir(exist_ok=True)
        require(judge.read_json(r/'progress.json')['completed']==32, 'Answers incomplete')
        imported=out/'import';study=out/'judges'
        if not imported.exists():
            raw=ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw'
            pdf=next((r/'library/papers').glob('*.pdf'))
            command([sys.executable,'-X','utf8',str(ROOT/'scripts/import_qa_system_answers.py'),
                '--input',str(raw/'answer.txt'),'--extra',str(raw/'answer_PFI2-013.json'),
                '--pdf',str(pdf),'--rag-run',str(r),'--recovery-run',str(r),'--output',str(imported),'--verify-rag-quotes'])
        if not study.exists():grading.prepare(imported,study,settings,['rag'])
        require(len(judge.read_json(study/'study.json')['jobs'])==32, 'Only 32 new arm answers may be graded')
    c=judge.read_json(OUTPUT/'contract.json')
    c['grading']={a:dict(study_sha256=judge.digest(arm_path(a)/'judges/study.json'),
        import_sha256=judge.digest(arm_path(a)/'import/import.json')) for a in ARMS}
    c['judge_settings']=grading.public_settings(settings);judge.write(OUTPUT/'contract.json',c)
    return dict(prepared=64,external_judge='jev',legacy_dsh_answers_graded=0)


def grade(workers=4):
    c=verify_contract();settings=grading.configs(['jev']);require(grading.public_settings(settings)==c['judge_settings'],'Judge config changed')
    cfg=settings['jev'];stop=threading.Event();todo=[]
    for arm in ARMS:
        out=arm_path(arm);study=out/'judges';meta=judge.read_json(study/'study.json')
        require(judge.digest(study/'study.json')==c['grading'][arm]['study_sha256'],'Study changed')
        require(judge.digest(out/'import/import.json')==c['grading'][arm]['import_sha256'],'Answer import changed')
        scoring.audit(out/'import',study)
        require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in meta['harness_files'].items()),'Judge harness changed')
        todo.extend((arm,study,e) for e in meta['jobs'])
    statuses=Counter()
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ThreadPoolExecutor(max_workers=workers) as pool:
        factory=lambda:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
        futures={pool.submit(grading.evaluate_one,study,e,cfg,stop,factory,3):(arm,e) for arm,study,e in
            sorted(todo,key=lambda row:judge.sha(row[0]+row[2]['name']))}
        for f in as_completed(futures):
            status=f.result();arm,e=futures[f];statuses[(arm,status)]+=1
            if sum(statuses.values())%4==0:print(judge.encode(dict(done=sum(statuses.values()),statuses={a+':'+s:n for (a,s),n in statuses.items()})),flush=True)
    result=dict(statuses={a+':'+s:n for (a,s),n in statuses.items()},billing_stop=stop.is_set())
    judge.write(OUTPUT/'grading-progress.json',result);return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','answers','seal-replay','prepare-grading','grade'])
    p.add_argument('--arm',choices=ARMS,default='astra');p.add_argument('--workers',type=int,choices=range(1,5),default=4)
    p.add_argument('--limit',type=int);args=p.parse_args()
    try:
        result={'prepare':prepare,'answers':lambda:answers(args.arm,args.workers,args.limit),
            'seal-replay':seal_replay,'prepare-grading':prepare_grading,'grade':lambda:grade(args.workers)}[args.action]()
        print(judge.encode(result),flush=True)
    except Exception as error:
        print(judge.encode(dict(error_type=type(error).__name__,message=str(error)[:2000])),file=sys.stderr)
        raise SystemExit(1)
