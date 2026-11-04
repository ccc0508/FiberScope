"""Blind unchanged Jev policy for fresh unchecked end-to-end answers."""
from pathlib import Path
import shutil
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
import evaluate_unified_v31_20261104 as shared
from import_qa_system_answers import rag_citation
from evaluate_unchecked_e2e_20261104 import ROOT,RUN
OUTPUT=ROOT/'.rag-data/evaluations/unchecked-e2e-grading-20261104'
PRIOR=ROOT/'.rag-data/evaluations/evidence-review-20261102-v3/review/import'

def verify():
    c=j.read_json(OUTPUT/'contract.json')
    assert j.digest(OUTPUT/'judges/study.json')==c['study_sha256']
    assert all(j.digest(RUN/(tid+'.json'))==h for tid,h in c['answer_hashes'].items())
    return c

def prepare():
    assert not OUTPUT.exists()
    import run_qa_baseline as runner
    manifest=j.read_json(RUN/'manifest.json')
    assert runner.source_hashes(RUN/'backend')==manifest['source_files'],'Frozen runtime changed'
    assert j.digest(ROOT/'backend/.env.literature')==manifest['website_env_sha256'],'Website config changed'
    rows=j.read_json(RUN/'summary.json');assert len(rows)==32 and all(x['status']=='answered' for x in rows)
    meta,jobs,sources,pages=g.load_import(PRIOR)
    OUTPUT.mkdir();imported=OUTPUT/'import';shutil.copytree(PRIOR,imported);hashes={}
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];p=RUN/(tid+'.json');x=j.read_json(p)
        assert x['question']==job['reference_case']['question']
        es=x['retrieved_evidence'];claims=[dict(id=f'C{i+1}',**c) for i,c in enumerate(x['claims'])]
        used={ref for c in claims for ref in c['citation_refs']}
        candidate=dict(task_id=tid,answer=x['answer'],claims=claims,
            citations=[rag_citation(e,pages) for e in es if e['ref'] in used],
            available_context=dict(kind='supplied_excerpts',texts=[e['text'] for e in es]))
        # Unknown model refs remain in claims; never invent their source to improve scores.
        job['candidate']=candidate;job['blind_id']=j.sha(dict(study=OUTPUT.name,task=tid,candidate=candidate))[:20]
        j.write(imported/'answers'/('rag-'+tid+'.json'),candidate);hashes[tid]=j.digest(p)
        meta['rag_origins'][tid]=dict(source_run_id=RUN.name,result_sha256=hashes[tid],source_run_sha256=j.digest(RUN/'manifest.json'))
    j.write(imported/'jobs.json',jobs)
    meta['files']={name:j.digest(imported/name) for name in meta['files']}
    meta['metadata']=dict(answer_runtime='unchecked-e2e',fresh_retrieval=True,fresh_generation=True)
    j.write(imported/'import.json',meta)
    g.prepare(imported,OUTPUT/'judges',g.configs(['jev']),['rag'])
    j.write(OUTPUT/'contract.json',dict(study_sha256=j.digest(OUTPUT/'judges/study.json'),answer_hashes=hashes,
        policy_sha256=g.POLICY_SHA,retries='first valid, maximum three invalid/failed attempts'))
    return dict(prepared=32)

def grade():
    shared.OUTPUT=OUTPUT;shared.verify=verify
    return shared.grade()

def inspection():
    verify();meta,jobs,study,reviews,records,statuses,proofs=s.audit(OUTPUT/'import',OUTPUT/'judges')
    rows=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];raw=reviews.get(('jev','rag',tid))
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference=job['reference_case'],
            candidate=job['candidate'],raw_review=raw,
            metrics=s.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None))
    j.write(OUTPUT/'inspection.json',rows)
    return dict(valid=sum(r['raw_review'] is not None for r in rows))

if __name__=='__main__':
    import sys
    print(j.encode(dict(prepare=prepare,grade=grade,inspection=inspection,verify=verify)[sys.argv[1]]()),flush=True)
