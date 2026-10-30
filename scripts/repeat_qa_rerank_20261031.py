"""Repeat the two frozen QA systems twice with paired, independent question processes."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from filelock import FileLock

import judge_qa_eval as judge
import run_qa_baseline as runner
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'.rag-data/evaluations/rerank-stability-20261031'
SOURCES={
    'content':dict(run='pfi-content-units-v1-20261030-r1',baseline='qa-content-units-v1-20261030',env='content-units-v1-20261030.env'),
    'rerank':dict(run='pfi-candidate-rerank-v1-20261030-r1',baseline='qa-candidate-rerank-v1-20261030',env='candidate-rerank-v1-20261030.env'),
}


def preparation_plan(root=ROOT):
    return [dict(system=system,round=round_number,
        run_dir=str(root/'.rag-data/evaluations'/f'pfi-{system}-repeat-20261031-r{round_number}'),
        baseline=str(root/'.rag-data/baselines'/source['baseline']),
        env_file=str(root/'.rag-data/configs'/source['env']),
        reference_source=str(root/'.rag-data/evaluations'/source['run']/'backend/literature_rag'),
        original_run_dir=str(root/'.rag-data/evaluations'/source['run']))
        for round_number in [2,3] for system,source in SOURCES.items()]


def pair_schedule(task_ids,round_number):
    """Alternate submission order; do not start the next pair until both finish."""
    require(round_number in [2,3] and len(set(task_ids))==len(task_ids),'Invalid round/tasks')
    for index,task_id in enumerate(task_ids):
        order=['content','rerank'] if (index+round_number)%2==0 else ['rerank','content']
        yield task_id,order


def progress(run_dir):
    path=Path(run_dir)/'progress.json'
    return judge.read_json(path) if path.exists() else None


def prepare():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    contract_path=OUTPUT/'experiment.json'
    if contract_path.exists():return validate_contract()
    plan=preparation_plan();tasks=None
    for entry in plan:
        original=judge.read_json(Path(entry['original_run_dir'])/'run.json')
        if tasks is None:tasks=original['tasks']
        require(tasks==original['tasks'],'Original questions differ')
        directory=Path(entry['run_dir'])
        if not (directory/'run.json').is_file():
            require(not directory.exists(),'Inspect partial run preparation before retrying')
            runner.prepare(Path(entry['baseline']),ROOT/'fiberscope-eval-v2',Path(entry['env_file']),directory,
                Path(entry['reference_source']),'core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
        actual=judge.read_json(directory/'run.json')
        require(actual['configuration_probe']==original['configuration_probe'],'Repeated runtime settings differ')
        require(actual['tasks']==original['tasks'] and actual['dataset_manifest_sha256']==original['dataset_manifest_sha256'],'Repeated dataset differs')
        entry.update(run_sha256=judge.digest(directory/'run.json'),original_run_sha256=judge.digest(Path(entry['original_run_dir'])/'run.json'))
        print(json.dumps(dict(prepared=directory.name,provider_calls=0)),flush=True)
    require(len(tasks)==32 and all(t['mode']=='retrieval' for t in tasks),'Expected 32 independent core retrieval tasks')
    contract=dict(version='rerank-system-stability-v1',created_at=judge.now(),runs=plan,task_ids=[t['id'] for t in tasks],
        rounds=[1,2,3],new_rounds=[2,3],planned_new_answers=128,planned_new_jev_jobs=128,
        scheduling=dict(concurrency=2,unit='Same question, one independent process per system; wait for both, then next question.',
            submission_order='Alternate systems by question; reverse order in round 3.',round_order=[2,3]),
        original_run_manifests={s:judge.digest(ROOT/'.rag-data/evaluations'/source['run']/'run.json') for s,source in SOURCES.items()},
        application_env_sha256=judge.digest(ROOT/'backend/.env.literature'),
        orchestrator_sha256=judge.digest(Path(__file__)),runner_sha256=judge.digest(ROOT/'scripts/run_qa_baseline.py'),
        boundaries=['No source, question, generation prompt, model, top-k, threshold or context-budget changes.',
            'Only fresh question/data_dir payloads reach the answer worker; no conversation history or gold answers.',
            'Keep all failed outcomes and first valid grades; never choose the best repeat.',
            'Historical round 1 used separate sequential runs; new rounds use near-simultaneous question pairs.',
            'Remote model aliases do not guarantee unchanged weights across dates.'])
    judge.write(contract_path,contract)
    return dict(prepared_runs=len(plan),new_questions=128,provider_calls=0)


def validate_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(c['version']=='rerank-system-stability-v1','Unknown repeat contract')
    require(judge.digest(Path(__file__))==c['orchestrator_sha256'],'Repeat orchestrator changed after freeze')
    require(judge.digest(ROOT/'scripts/run_qa_baseline.py')==c['runner_sha256'],'Frozen runner changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['application_env_sha256'],'Default application config changed')
    for e in c['runs']:
        require(judge.digest(Path(e['run_dir'])/'run.json')==e['run_sha256'],'Repeated run manifest changed')
        require(judge.digest(Path(e['original_run_dir'])/'run.json')==e['original_run_sha256'],'Historical run manifest changed')
    return c


def next_task(run_dir,task_ids):
    """Completed failures are terminal outcomes, never automatically regenerated."""
    for tid in task_ids:
        if not (Path(run_dir)/'results'/(tid+'.json')).is_file():return tid
    return None


def run_one(entry,task_id,task_ids):
    directory=Path(entry['run_dir']);result=directory/'results'/(task_id+'.json')
    if result.exists():
        seal=judge.read_json(directory/'attempts'/(task_id+'.json'))
        require(judge.digest(result)==seal['result_sha256'],'Repeated saved answer changed')
        return judge.read_json(result)['status']
    require(next_task(directory,task_ids)==task_id,'Paired schedule lost question alignment')
    # Each call executes exactly one unattempted question using the existing frozen runner.
    # Runner progress is emitted as well as the paired orchestration checkpoint.
    runner.run(directory,limit=1)
    require(result.exists(),'The expected question was not executed')
    return judge.read_json(result)['status']


def run(pair_limit=None):
    require(pair_limit is None or type(pair_limit) is int and pair_limit>0,'Invalid pair limit')
    c=validate_contract();by={(e['round'],e['system']):e for e in c['runs']}
    completed=0
    with FileLock(str(OUTPUT/'.repeat.lock'),timeout=0):
        with ThreadPoolExecutor(max_workers=2) as pool:
            for round_number in c['new_rounds']:
                for tid,order in pair_schedule(c['task_ids'],round_number):
                    entries=[by[(round_number,s)] for s in order]
                    already=all((Path(e['run_dir'])/'results'/(tid+'.json')).exists() for e in entries)
                    if not already and pair_limit is not None and completed>=pair_limit:return status()
                    futures={e['system']:pool.submit(run_one,e,tid,c['task_ids']) for e in entries}
                    outcomes={s:f.result() for s,f in futures.items()}
                    checkpoint=dict(round=round_number,task_id=tid,outcomes=outcomes,updated_at=judge.now())
                    judge.write(OUTPUT/'last-pair.json',checkpoint)
                    status()
                    if not already:completed+=1
                    print(json.dumps(dict(pair_complete=checkpoint)),flush=True)
    return status()


def status():
    c=judge.read_json(OUTPUT/'experiment.json');rows=[]
    for e in c['runs']:
        p=progress(e['run_dir']);rows.append(dict(system=e['system'],round=e['round'],progress=p))
    result=dict(runs=rows,completed=sum((e['progress'] or {}).get('completed',0) for e in rows),total=128)
    judge.write(OUTPUT/'progress.json',result)
    return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','status'])
    p.add_argument('--pair-limit',type=int);a=p.parse_args()
    try:result=prepare() if a.action=='prepare' else run(a.pair_limit) if a.action=='run' else status()
    except Exception as error:
        print(json.dumps({'error_type':type(error).__name__,'message':'Repeat halted; keep existing requests and inspect the saved checkpoint.'}));raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False))
