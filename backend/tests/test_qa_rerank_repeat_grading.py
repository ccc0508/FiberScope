"""Freeze the same Jev settings and isolate round-specific grading directories."""
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import grade_qa_rerank_repeats_20261031 as grader
from threading import Event
from types import SimpleNamespace


def test_each_round_has_separate_system_import_and_score_storage():
    plans=[e for r in [2,3] for e in grader.plan(r)]
    assert len({e['study_dir'] for e in plans})==4 and len({e['import_dir'] for e in plans})==4
    assert all(e['study_dir'].name==f"{e['system']}-r{e['round']}" for e in plans)
    with pytest.raises(ValueError):grader.plan(1)


def test_judge_contract_rejects_model_or_settings_changes(tmp_path,monkeypatch):
    (tmp_path/'scripts').mkdir()
    harness={}
    for name in grader.grading.HARNESS:
        p=tmp_path/'scripts'/name;p.write_bytes(b'frozen source');harness[name]=grader.judge.digest(p)
    for folder in ['content-units-jev-20261030-r1','candidate-rerank-jev-20261030-r1','candidate-rerank-jev-20261031-proxy-recovery']:
        historic=tmp_path/'.rag-data/evaluations'/folder;historic.mkdir(parents=True)
        (historic/'study.json').write_text(json.dumps({'requested_judges':{'jev':{'model':'fixed'}},
            'policy_sha256':grader.grading.POLICY_SHA,'harness_files':harness}),encoding='utf-8')
    out=tmp_path/'experiment';out.mkdir()
    monkeypatch.setattr(grader,'ROOT',tmp_path);monkeypatch.setattr(grader,'OUTPUT',out)
    monkeypatch.setattr(grader.grading,'public_settings',lambda settings:settings)
    c=grader.settings_contract({'jev':{'model':'fixed'}})
    assert c['first_valid_only'] is True and c['max_attempts']==3 and c['new_luna_calls']==0
    assert grader.settings_contract({'jev':{'model':'fixed'}})==c
    with pytest.raises(ValueError,match='changed'):
        grader.settings_contract({'jev':{'model':'different'}})


def binding_fixture(tmp_path):
    run=tmp_path/'run';imp=tmp_path/'import';(run/'results').mkdir(parents=True);imp.mkdir()
    tasks=[f'PFI2-{i:03}' for i in range(1,33)]
    (run/'run.json').write_text(json.dumps(dict(run_id='correct-round',dataset_manifest_sha256='same',tasks=[dict(id=t) for t in tasks])),encoding='utf-8')
    origins={}
    for tid in tasks:
        p=run/'results'/(tid+'.json');p.write_text('{}',encoding='utf-8')
        origins[tid]=dict(source_run_id='correct-round',source_run_sha256=grader.judge.digest(run/'run.json'),result_sha256=grader.judge.digest(p))
    (imp/'import.json').write_text(json.dumps(dict(dataset_manifest_sha256='same',rag_origins=origins)),encoding='utf-8')
    contract=dict(selected_systems=['rag'],requested_judges={'jev':{}},import_sha256=grader.judge.digest(imp/'import.json'),
        jobs=[dict(name='job-'+t,task_id=t,judge='jev',system='rag') for t in tasks])
    return dict(run_dir=run,import_dir=imp),contract


@pytest.mark.parametrize('change',['dsh','luna','wrong_run','duplicate_task'])
def test_wrong_system_or_round_is_rejected_before_api_calls(tmp_path,change):
    entry,c=binding_fixture(tmp_path);grader.validate_study_binding(entry,c)
    if change=='dsh':c['jobs'][0]['system']='dsh'
    elif change=='luna':c['jobs'][0]['judge']='luna'
    elif change=='duplicate_task':c['jobs'][0]['task_id']=c['jobs'][1]['task_id']
    else:
        p=entry['import_dir']/'import.json';meta=json.loads(p.read_text('utf-8'))
        meta['rag_origins']['PFI2-001']['source_run_id']='wrong-round'
        p.write_text(json.dumps(meta),encoding='utf-8');c['import_sha256']=grader.judge.digest(p)
    with pytest.raises(ValueError):grader.validate_study_binding(entry,c)


def test_unexpected_worker_error_stops_queued_paid_requests(monkeypatch,tmp_path):
    stop=Event();paid=[]
    jobs=[({'study_dir':tmp_path},{'name':str(i)}) for i in range(64)]
    def evaluate(output,entry,config,signal,*args):
        if entry['name']=='0':raise ValueError('Synthetic preflight failure')
        if signal.is_set():return 'not_started'
        paid.append(entry['name'])
        assert signal.wait(3),'Executor did not signal a stop'
        return 'api_failed'
    monkeypatch.setattr(grader.grading,'evaluate_one',evaluate)
    result=grader.execute_jobs(jobs,{'jev':SimpleNamespace(timeout=1)},stop,4,2)
    assert stop.is_set() and result['execution_error_type']=='ValueError'
    assert len(paid)<=4 and sum(result['statuses'].values())==64
