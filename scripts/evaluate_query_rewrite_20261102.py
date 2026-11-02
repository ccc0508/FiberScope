"""Grade fresh original/dual-query arms, preserving the existing Jev protocol."""
from argparse import ArgumentParser
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import threading

from filelock import FileLock
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as reporting
from grade_qa_rerank_repeats_20261031 import execute_jobs, PROXY
from run_qa_baseline import source_hashes
from validate_qa_eval import require

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'.rag-data/evaluations/query-rewrite-20261102'
ARMS = ('original', 'rewrite')


def plan(arm):
    require(arm in ARMS, 'Unknown experiment arm')
    return dict(arm=arm, run_dir=ROOT/'.rag-data/evaluations'/f'pfi-query-{arm}-20261102-r1',
        import_dir=OUTPUT/arm/'import', study_dir=OUTPUT/arm/'jev')


def check_pair():
    runs = [judge.read_json(plan(a)['run_dir']/'run.json') for a in ARMS]
    require(runs[0]['source_commit'] == runs[1]['source_commit'], 'Different source commits')
    require(runs[0]['source_files'] == runs[1]['source_files'], 'Different answer source bytes')
    require(runs[0]['dataset_files'] == runs[1]['dataset_files'], 'Different question data')
    ignored = {'pipeline_version', 'pipeline_source_files', 'prompt_pipeline_sha256', 'query_rewrite'}
    configs = [{k:v for k,v in r['configuration_probe'].items() if k not in ignored} for r in runs]
    require(configs[0] == configs[1], 'Unexpected shared configuration difference')
    require('query_rewrite' not in runs[0]['configuration_probe'], 'Control enables rewrite')
    require(runs[1]['configuration_probe']['query_rewrite']['enabled'], 'Treatment disables rewrite')
    for name in ['structure.json', 'table-retrieval.json', 'table-row-vectors.json', 'chunk-organization.json']:
        original = plan('original')['run_dir']/'library'/name
        rewritten = plan('rewrite')['run_dir']/'library'/name
        require(original.exists() == rewritten.exists(), 'Different scientific index sidecar sets')
        if original.exists():
            require(judge.digest(original) == judge.digest(rewritten), 'Different scientific index sidecars')
    return runs


def prepare():
    runs = check_pair()
    settings = grading.configs(['jev'])
    previous = judge.read_json(ROOT/'.rag-data/evaluations/mineru-current-20261101/jev/study.json')
    require(previous['policy_sha256'] == grading.POLICY_SHA, 'Scoring policy differs')
    require(previous['requested_judges']['jev'] == grading.public_settings(settings)['jev'], 'Jev settings differ')
    for arm, run in zip(ARMS, runs):
        entry = plan(arm); folder = entry['run_dir']; progress = judge.read_json(folder/'progress.json')
        require(progress['completed'] == 32 and progress['status'] == 'completed', 'Answers incomplete')
        require(not progress['outcomes'].get('failed'), 'Preserve failed answers for inspection')
        require(source_hashes(folder/'backend') == run['source_files'], 'Frozen answer source changed')
        if not entry['import_dir'].exists():
            papers = list((folder/'library/papers').glob('*.pdf'))
            require(len(papers) == 1, 'Expected original paper')
            old = ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw'
            entry['import_dir'].parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(ROOT/'scripts/import_qa_system_answers.py'),
                '--input', str(old/'answer.txt'), '--extra', str(old/'answer_PFI2-013.json'),
                '--pdf', str(papers[0]), '--rag-run', str(folder), '--recovery-run', str(folder),
                '--output', str(entry['import_dir']), '--verify-rag-quotes']
            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            judge.write(OUTPUT/arm/'import-process.json', dict(returncode=process.returncode,
                stdout_sha256=judge.sha(process.stdout), stderr_sha256=judge.sha(process.stderr)))
            require(process.returncode == 0, 'Import failed; preserve answers')
        if not entry['study_dir'].exists():
            grading.prepare(entry['import_dir'], entry['study_dir'], settings, ['rag'])
        study = judge.read_json(entry['study_dir']/'study.json')
        meta = judge.read_json(entry['import_dir']/'import.json')
        require(study['selected_systems'] == ['rag'] and set(study['requested_judges']) == {'jev'}, 'Unexpected grading jobs')
        require(len(study['jobs']) == 32, 'Expected 32 jobs per arm')
        require(all(o['source_run_id'] == run['run_id'] for o in meta['rag_origins'].values()), 'Wrong run imported')
    contract = dict(version='query-rewrite-paired-v1', orchestrator_sha256=judge.digest(Path(__file__)),
        runs={a:judge.digest(plan(a)['run_dir']/'run.json') for a in ARMS},
        studies={a:judge.digest(plan(a)['study_dir']/'study.json') for a in ARMS},
        requested_judges=grading.public_settings(settings), policy_sha256=grading.POLICY_SHA,
        default_config_sha256=judge.digest(ROOT/'backend/.env.literature'), proxy=PROXY,
        new_answer_tasks=64, new_jev_jobs=64, new_dsh_jobs=0, new_luna_jobs=0,
        max_attempts=3, first_valid_only=True, reused_historical_answers=False)
    path = OUTPUT/'contract.json'
    if path.exists(): require(judge.read_json(path) == contract, 'Frozen grading contract changed')
    else: judge.write(path, contract)
    return dict(prepared=64, model_calls=0)


def grade(workers=4):
    require(type(workers) is int and 1 <= workers <= 4, 'Invalid judge concurrency')
    contract = judge.read_json(OUTPUT/'contract.json'); settings = grading.configs(['jev'])
    require(judge.digest(Path(__file__)) == contract['orchestrator_sha256'], 'Orchestrator changed')
    require(grading.public_settings(settings) == contract['requested_judges'], 'Judge settings changed')
    require(judge.digest(ROOT/'backend/.env.literature') == contract['default_config_sha256'], 'Website config changed')
    with FileLock(str(OUTPUT/'.grading.lock'), timeout=0), ExitStack() as stack:
        jobs = []
        for arm in ARMS:
            entry = plan(arm)
            require(judge.digest(entry['run_dir']/'run.json') == contract['runs'][arm], 'Run manifest changed')
            require(judge.digest(entry['study_dir']/'study.json') == contract['studies'][arm], 'Study changed')
            study = judge.read_json(entry['study_dir']/'study.json')
            require(all(judge.digest(ROOT/'scripts'/n) == h for n,h in study['harness_files'].items()), 'Grader source changed')
            stack.enter_context(judge.lock(entry['study_dir']))
            audit = reporting.audit(entry['import_dir'], entry['study_dir'])
            require(all(status != 'pending' for _,_,status in audit[5]), 'Inspect interrupted judge requests')
            jobs.extend((entry, job) for job in study['jobs'])
        jobs.sort(key=lambda pair: judge.sha([pair[0]['arm'], pair[1]['name']]))
        result = execute_jobs(jobs, settings, threading.Event(), workers, 1)
        judge.write(OUTPUT/'grading-progress.json', result)
        require(result['execution_error_type'] is None, 'Judge execution stopped; inspect saved records')
    return result


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__); p.add_argument('action', choices=['prepare', 'grade'])
    p.add_argument('--workers', type=int, default=4); args = p.parse_args()
    try: result = prepare() if args.action == 'prepare' else grade(args.workers)
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__, message='Preserve valid answers and grading checkpoints.')))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))
