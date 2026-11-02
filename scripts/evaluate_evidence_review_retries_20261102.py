"""Grade only the three saved retry answers with the unchanged Jev protocol."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
import shutil
import threading

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from import_qa_system_answers import rag_citation
from validate_qa_eval import require

ROOT = Path(__file__).resolve().parents[1]
PRIOR = ROOT / '.rag-data/evaluations/evidence-review-20261102-v3/review'
RETRY = ROOT / '.rag-data/evaluations/evidence-review-32768-retry-20261102'
BASE = ROOT / 'data/literature/qa-evaluation/reports/evidence-review-20261102-v3'
OUTPUT = ROOT / '.rag-data/evaluations/evidence-review-merged-20261102'
SELECTED = {'PFI2-024', 'PFI2-031', 'PFI2-032'}


def prepare():
    require(not OUTPUT.exists(), 'Keep paid grading studies immutable')
    meta, jobs, sources, pages = grading.load_import(PRIOR / 'import')
    prior_study = judge.read_json(PRIOR / 'judges/study.json')
    settings = grading.configs(['jev'])
    require(grading.public_settings(settings) == prior_study['requested_judges'], 'Judge configuration changed')
    require(prior_study['policy_sha256'] == grading.POLICY_SHA, 'Scoring policy changed')
    require(all(judge.digest(ROOT / 'scripts' / name) == value for name, value in prior_study['harness_files'].items()), 'Grading harness changed')
    OUTPUT.mkdir(parents=True)
    imported = OUTPUT / 'import'
    shutil.copytree(PRIOR / 'import', imported)
    replaced = {}
    for job in jobs:
        if job['system'] != 'rag' or job['task_id'] not in SELECTED:
            continue
        tid = job['task_id']
        path = RETRY / 'results' / (tid + '.json')
        row = judge.read_json(path)
        require(judge.read_json(RETRY / 'attempts' / path.name)['result_sha256'] == judge.digest(path), 'Retry result changed')
        require(row['input_equivalence_verified'] and row['response']['evidence_review']['status'] == 'revised', 'Invalid retry answer')
        response = row['response']
        evidence = {e['ref']: e for e in response['retrieved_evidence']}
        claims = [dict(id=f'C{i + 1}', text=c['text'], citation_refs=c['citation_refs']) for i, c in enumerate(response['claims'])]
        cited = {ref for c in claims for ref in c['citation_refs']}
        candidate = dict(task_id=tid, answer=response['answer'], claims=claims,
                         citations=[rag_citation(e, pages) for e in evidence.values() if e['ref'] in cited],
                         available_context=dict(kind='supplied_excerpts', texts=[e['text'] for e in evidence.values()]))
        require(candidate['available_context'] == job['candidate']['available_context'], 'Answering context changed')
        job['candidate'] = candidate
        job['blind_id'] = judge.sha(dict(study=OUTPUT.name, task=tid, candidate=candidate))[:20]
        judge.write(imported / 'answers' / ('rag-' + tid + '.json'), candidate)
        replaced[tid] = judge.digest(path)
        meta['rag_origins'][tid] = dict(source_run_id=RETRY.name, result_sha256=judge.digest(path), source_run_sha256=judge.digest(RETRY / 'run.json'))
    require(set(replaced) == SELECTED, 'Only three specified answers may change')
    judge.write(imported / 'jobs.json', jobs)
    meta['files'] = {name: judge.digest(imported / name) for name in meta['files']}
    meta['metadata'] = dict(merged_retry_ids=sorted(SELECTED), previous_import_sha256=judge.digest(PRIOR / 'import/import.json'), new_primary_generation_calls=0)
    judge.write(imported / 'import.json', meta)
    grading.prepare(imported, OUTPUT / 'judges', settings, ['rag'])
    study = judge.read_json(OUTPUT / 'judges/study.json')
    # Preparing an input is offline. Only these three jobs are eligible for API calls.
    study['jobs'] = [j for j in study['jobs'] if j['task_id'] in SELECTED]
    study['input_count'] = 3
    require({j['task_id'] for j in study['jobs']} == SELECTED, 'Paid grading subset changed')
    judge.write(OUTPUT / 'judges/study.json', study)
    contract = dict(version=OUTPUT.name, created_at=judge.now(), controller_sha256=judge.digest(Path(__file__)),
                    study_sha256=judge.digest(OUTPUT / 'judges/study.json'), replaced_results=replaced,
                    prior_public_files={p.name: judge.digest(p) for p in BASE.iterdir() if p.is_file()},
                    policy_sha256=grading.POLICY_SHA, new_answer_calls=0, new_review_calls=0,
                    requested_grades=3, maximum_calls=9, retry_policy='First valid, at most three attempts; never replay a valid grade.',
                    unchanged_answer_and_grade_count=29)
    judge.write(OUTPUT / 'contract.json', contract)
    return {'prepared_grades': 3, 'retained_grades': 29, 'policy_sha256': grading.POLICY_SHA}


def verify():
    contract = judge.read_json(OUTPUT / 'contract.json')
    require(judge.digest(Path(__file__)) == contract['controller_sha256'], 'Controller changed')
    require(judge.digest(OUTPUT / 'judges/study.json') == contract['study_sha256'], 'Study changed')
    require(all(judge.digest(BASE / name) == value for name, value in contract['prior_public_files'].items()), 'Prior publication changed')
    require(all(judge.digest(RETRY / 'results' / (tid + '.json')) == value for tid, value in contract['replaced_results'].items()), 'Retry answer changed')
    require(contract['policy_sha256'] == grading.POLICY_SHA, 'Policy changed')
    return contract


def grade():
    verify()
    _, _, study, _, _, _, _ = scoring.audit(OUTPUT / 'import', OUTPUT / 'judges')
    cfg = grading.configs(['jev'])['jev']
    require(grading.public_settings({'jev': cfg}) == study['requested_judges'], 'Judge configuration changed')
    stop = threading.Event()
    factory = lambda: httpx.Client(timeout=cfg.timeout, trust_env=False, follow_redirects=False, proxy='http://127.0.0.1:10808')
    statuses = {}
    with FileLock(str(OUTPUT / '.grading.lock'), timeout=0), ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(grading.evaluate_one, OUTPUT / 'judges', entry, cfg, stop, factory, 3): entry['task_id'] for entry in study['jobs']}
        for f in as_completed(futures):
            tid = futures[f]
            statuses[tid] = f.result()
            print(judge.encode({'task_id': tid, 'status': statuses[tid]}), flush=True)
    scoring.audit(OUTPUT / 'import', OUTPUT / 'judges')
    result = dict(statuses=statuses, billing_stop=stop.is_set())
    judge.write(OUTPUT / 'grading-progress.json', result)
    return result


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'grade', 'verify'])
    args = p.parse_args()
    print(judge.encode({'prepare': prepare, 'grade': grade, 'verify': lambda: {'verified': bool(verify())}}[args.action]()), flush=True)
