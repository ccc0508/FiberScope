"""Blind Jev grading of all 32 fixed-input corrective-v21 answers, unchanged five-dimension policy."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor,as_completed
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

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/corrective-v21-full-20261103'
PRIOR=ROOT/'.rag-data/evaluations/evidence-review-20261102-v3/review'
BASE=ROOT/'data/literature/qa-evaluation/reports/corrective-v2-20261103'
OUTPUT=ROOT/'.rag-data/evaluations/corrective-v21-grading-20261103'


def prepare():
    require(not OUTPUT.exists(),'Use a fresh immutable grading study')
    summaries=judge.read_json(RUN/'summary.json')
    require(len(summaries)==32 and all(r['status']!='harness_failed' for r in summaries),'Finish all 32 answer attempts')
    meta,jobs,sources,pages=grading.load_import(PRIOR/'import')
    previous=judge.read_json(PRIOR/'judges/study.json')
    settings=grading.configs(['jev'])
    require(grading.public_settings(settings)==previous['requested_judges'],'Judge configuration changed')
    require(previous['policy_sha256']==grading.POLICY_SHA,'Scoring policy changed')
    manifest=judge.read_json(RUN/'manifest.json')
    require(all(judge.digest(ROOT/p)==h for p,h in manifest['source_files'].items()),'Runtime changed during answer study')
    inputs={r['case_id']:r for r in judge.read_json(RUN/'inputs.json')}
    baseline_inputs={r['case_id']:r for r in judge.read_json(ROOT/'.rag-data/evaluations/corrective-v2-full-20261103/inputs.json')}
    require(inputs==baseline_inputs,'Initial input differs from previous v2 full32')
    OUTPUT.mkdir(parents=True);imported=OUTPUT/'import';shutil.copytree(PRIOR/'import',imported)
    hashes={}
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];path=RUN/(tid+'.json');response=judge.read_json(path)
        require(response['question']==job['reference_case']['question'],'Question changed')
        t=response['evidence_review']
        require(t['initial_evidence']==inputs[tid]['evidences'] and t['original_draft']==inputs[tid]['draft'],'Initial evidence/draft changed')
        es=t['final_evidence']
        claims=[dict(id=f'C{i+1}',text=c['text'],citation_refs=c['citation_refs']) for i,c in enumerate(response['claims'])]
        used={ref for c in claims for ref in c['citation_refs']}
        candidate=dict(task_id=tid,answer=response['answer'],claims=claims,
            citations=[rag_citation(e,pages) for e in es if e['ref'] in used],
            available_context=dict(kind='supplied_excerpts',texts=[e['text'] for e in es]))
        job['candidate']=candidate;job['blind_id']=judge.sha(dict(study=OUTPUT.name,task=tid,candidate=candidate))[:20]
        judge.write(imported/'answers'/('rag-'+tid+'.json'),candidate)
        hashes[tid]=judge.digest(path)
        meta['rag_origins'][tid]=dict(source_run_id=RUN.name,result_sha256=hashes[tid],source_run_sha256=judge.digest(RUN/'manifest.json'))
    require(len(hashes)==32,'Incomplete candidate import')
    judge.write(imported/'jobs.json',jobs)
    meta['files']={name:judge.digest(imported/name) for name in meta['files']}
    meta['metadata']=dict(answer_runtime='corrective-v21',initial_primary_generation_calls=0,
        baseline='corrective-v2 full32; separately report raw Jev matched subset')
    judge.write(imported/'import.json',meta)
    grading.prepare(imported,OUTPUT/'judges',settings,['rag'])
    judge.write(OUTPUT/'contract.json',dict(version=OUTPUT.name,controller_sha256=judge.digest(Path(__file__)),
        study_sha256=judge.digest(OUTPUT/'judges/study.json'),policy_sha256=grading.POLICY_SHA,
        answer_hashes=hashes,prior_public_files={p.name:judge.digest(p) for p in BASE.iterdir() if p.is_file()},
        requested_grades=32,retry_policy='first valid; at most 3 attempts only for invalid/failed grades'))
    return dict(prepared=32,judge='jev',model_calls=0)


def verify():
    c=judge.read_json(OUTPUT/'contract.json')
    require(c['controller_sha256']==judge.digest(Path(__file__)),'Grading controller changed')
    require(c['study_sha256']==judge.digest(OUTPUT/'judges/study.json'),'Grading study changed')
    require(all(judge.digest(RUN/(tid+'.json'))==h for tid,h in c['answer_hashes'].items()),'Answers changed')
    require(all(judge.digest(BASE/n)==h for n,h in c['prior_public_files'].items()),'Previous publication changed')
    return c


def grade():
    verify()
    _,_,study,_,_,_,_=scoring.audit(OUTPUT/'import',OUTPUT/'judges')
    cfg=grading.configs(['jev'])['jev']
    require(grading.public_settings({'jev':cfg})==study['requested_judges'],'Judge settings changed')
    stop=threading.Event();statuses={}
    factory=lambda:httpx.Client(timeout=cfg.timeout,trust_env=False,follow_redirects=False,proxy='http://127.0.0.1:10808')
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),ThreadPoolExecutor(max_workers=3) as pool:
        fs={pool.submit(grading.evaluate_one,OUTPUT/'judges',entry,cfg,stop,factory,3):entry['task_id'] for entry in study['jobs']}
        for f in as_completed(fs):
            tid=fs[f];statuses[tid]=f.result();print(judge.encode(dict(task_id=tid,status=statuses[tid])),flush=True)
    scoring.audit(OUTPUT/'import',OUTPUT/'judges')
    result=dict(statuses=statuses,billing_stop=stop.is_set());judge.write(OUTPUT/'grading-progress.json',result)
    return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','grade','verify']);args=p.parse_args()
    print(judge.encode({'prepare':prepare,'grade':grade,'verify':verify}[args.action]()),flush=True)
