"""Blind unchanged Jev protocol for each of paired selected-question replays."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import threading
import time

import httpx
from filelock import FileLock

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from import_qa_system_answers import rag_citation
from validate_qa_eval import require
from validate_relation_compact_20261103 import ROOT, STUDY, CASES

PRIOR = ROOT / '.rag-data/evaluations/corrective-v21-grading-20261103'


def prepare(name):
    run = STUDY / name
    out = STUDY / 'grading' / name
    require(not out.exists(), 'Preserve frozen scoring studies')
    summary = judge.read_json(run/'summary.json')
    require(len(summary)==len(CASES) and all(r['status']!='harness_failed' for r in summary), 'Finish all selected attempts')
    plan = judge.read_json(STUDY/'plan.json')
    require(name in [a['directory'] for a in plan['attempts']], 'Unknown attempt')
    manifest = judge.read_json(run/'manifest.json')
    require(manifest['source_files']==plan['source_files'], 'Runtime differs from predeclared plan')
    inputs = {r['case_id']:r for r in judge.read_json(run/'inputs.json')}
    baseline = {r['case_id']:r for r in judge.read_json(ROOT/'.rag-data/evaluations/corrective-v21-full-20261103/inputs.json')}
    require(inputs=={tid:baseline[tid] for tid in CASES}, 'Initial evidence/draft changed')
    meta, jobs, sources, pages = grading.load_import(PRIOR/'import')
    settings = grading.configs(['jev'])
    old = judge.read_json(PRIOR/'judges/study.json')
    require(grading.public_settings(settings)==old['requested_judges'] and grading.POLICY_SHA==old['policy_sha256'], 'Judge policy/config changed')
    imported = out/'import'
    shutil.copytree(PRIOR/'import', imported)
    hashes = {}
    for job in jobs:
        tid = job['task_id']
        if job['system']!='rag' or tid not in CASES:
            continue
        path = run/(tid+'.json'); result = judge.read_json(path); trace = result['evidence_review']
        require(result['question']==job['reference_case']['question'], 'Question changed')
        require(trace['initial_evidence']==inputs[tid]['evidences'] and trace['original_draft']==inputs[tid]['draft'], 'Input mismatch')
        es = trace['final_evidence']
        claims = [dict(id=f'C{i+1}', **c) for i,c in enumerate(result['claims'])]
        used = {ref for c in claims for ref in c['citation_refs']}
        candidate = dict(task_id=tid, answer=result['answer'], claims=claims,
            citations=[rag_citation(e,pages) for e in es if e['ref'] in used],
            available_context=dict(kind='supplied_excerpts', texts=[e['text'] for e in es]))
        job.update(candidate=candidate, blind_id=judge.sha(dict(study=name, task=tid, candidate=candidate))[:20])
        judge.write(imported/'answers'/('rag-'+tid+'.json'), candidate)
        hashes[tid] = judge.digest(path)
    judge.write(imported/'jobs.json', jobs)
    meta['files'] = {n:judge.digest(imported/n) for n in meta['files']}
    meta['metadata'] = dict(selected_tasks=CASES, description='Full frozen source import; only selected selected answers replaced and evaluated.')
    judge.write(imported/'import.json', meta)
    grading.prepare(imported, out/'judges', settings, ['rag'])
    # Freeze the selected subset before any API calls. Other prepared inputs are unused.
    study = judge.read_json(out/'judges/study.json')
    study['jobs'] = [e for e in study['jobs'] if e['task_id'] in CASES]
    study.update(input_count=len(CASES), selected_task_ids=CASES)
    judge.write(out/'judges/study.json', study)
    judge.write(out/'contract.json', dict(answer_hashes=hashes, study_sha256=judge.digest(out/'judges/study.json'),
        policy_sha256=grading.POLICY_SHA, requested_grades=len(CASES), retries='first valid, max 3 only if invalid/failed'))
    return out


def grade(name):
    out = STUDY/'grading'/name
    if not out.exists():
        prepare(name)
    contract = judge.read_json(out/'contract.json')
    require(judge.digest(out/'judges/study.json')==contract['study_sha256'], 'Study changed')
    require(all(judge.digest(STUDY/name/(tid+'.json'))==h for tid,h in contract['answer_hashes'].items()), 'Answer changed')
    _, _, study, _, _, _, _ = scoring.audit(out/'import',out/'judges')
    cfg = grading.configs(['jev'])['jev']
    require(grading.public_settings({'jev':cfg})==study['requested_judges'], 'Judge config changed')
    stop = threading.Event()
    factory = lambda:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
    with FileLock(str(out/'.grading.lock'),timeout=0), ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(grading.evaluate_one,out/'judges',e,cfg,stop,factory,3):e['task_id'] for e in study['jobs']}
        for future in as_completed(futures):
            print(judge.encode(dict(attempt=name,task_id=futures[future],status=future.result())),flush=True)
    scoring.audit(out/'import',out/'judges')
    if stop.is_set():
        raise RuntimeError('Billing/authentication stop; retain valid grades')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('attempt',nargs='*');p.add_argument('--watch',action='store_true');args=p.parse_args()
    names=args.attempt
    if args.watch:
        names=[a['directory'] for a in judge.read_json(STUDY/'plan.json')['attempts']]
    for name in names:
        deadline=time.monotonic()+3600
        while args.watch and not (STUDY/name/'summary.json').exists():
            if time.monotonic()>deadline:raise RuntimeError('Answer wait limit reached')
            time.sleep(5)
        grade(name)
