import copy
import csv
from io import StringIO
import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import extraction
from tests.test_extraction import configured, app_for, submit, finish, success, BASE


@pytest.fixture
def candidate(configured,monkeypatch):
    monkeypatch.setattr(extraction,'run_worker',success)
    app=app_for(configured)
    with TestClient(app) as client:
        task=finish(client,submit(client).json()['id'])
        yield client,task,app


def payload(task,record=0,**changes):
    m=task['snapshot']['result']['measurements'][record]
    return {'expected_revision':0,'raw_material':m['raw_material'],'metric':m['metric'],
            'measurement_state':m['measurement_state'],'raw_value':m['raw_value'],'raw_unit':m['raw_unit'],
            'experiment_condition':'','condition_source':'','status':'confirmed','suitability':'unassessed','note':'',**changes}


def review_url(task,record=0):
    return f"{BASE}/{task['id']}/reviews/{task['snapshot']['result']['measurements'][record]['record_id']}"


def test_confirmation_does_not_imply_suitability_and_snapshot_immutable(candidate):
    client,task,_=candidate
    original=copy.deepcopy(task['snapshot'])
    result=client.post(review_url(task),json=payload(task))
    assert result.status_code==200,result.text
    reviewed=result.json()
    assert reviewed['revision']==1 and reviewed['status']=='confirmed' and not reviewed['approved_for_training']
    current=client.get(f"{BASE}/{task['id']}").json()
    assert current['snapshot']==original
    assert current['review_summary']=={'total':2,'confirmed':1,'pending':1,'rejected':0,'suitable':0}
    events=client.get(review_url(task)+'/events').json()['data']
    assert len(events)==1 and events[0]['previous']['revision']==0
    assert events[0]['current']['revision']==1


def test_edit_reject_restore_history_and_optimistic_concurrency(candidate):
    client,task,_=candidate
    body=payload(task,raw_value='1.40',note='原文复核修改示例')
    assert client.post(review_url(task),json=body).json()['revision']==1
    assert client.post(review_url(task),json=body).status_code==409
    body.update(expected_revision=1,status='rejected',note='需要进一步核实')
    assert client.post(review_url(task),json=body).json()['revision']==2
    assert client.get(f"{BASE}/{task['id']}/confirmed").content==b''
    body.update(expected_revision=2,status='confirmed',suitability='suitable',note='已核查适用的实验条件')
    reviewed=client.post(review_url(task),json=body).json()
    assert reviewed['revision']==3 and reviewed['approved_for_training']
    events=client.get(review_url(task)+'/events').json()['data']
    assert [e['revision'] for e in events]==[3,2,1]
    assert events[-1]['previous']['current']['raw_value']=='1.36'
    assert events[-1]['current']['current']['raw_value']=='1.40'
    assert client.post(review_url(task),json={**body,'expected_revision':3}).json()['revision']==3
    assert len(client.get(review_url(task)+'/events').json()['data'])==3


@pytest.mark.parametrize('change',[
    {'raw_value':'nan'}, {'raw_value':'1.2±0.1'}, {'raw_value':'1e200'},
    {'status':'pending','suitability':'suitable','note':'test'},
    {'suitability':'suitable'}, {'status':'rejected'},
    {'raw_value':'9'}, {'experiment_condition':'40°SR'},
    {'metric':'unknown; DROP TABLE'}, {'expected_revision':-1}, {'source_bbox_pt':[1,2,3,4]},
])
def test_invalid_or_unexplained_reviews_rejected(candidate,change):
    client,task,_=candidate
    assert client.post(review_url(task),json=payload(task,**change)).status_code==422
    assert client.get(review_url(task)+'/events').json()['data']==[]


def test_reviews_history_and_exports_are_public_but_writes_are_owned(candidate, configured):
    client,task,app=candidate
    stranger=TestClient(app)
    assert client.post(review_url(task),json=payload(task)).status_code==200
    page=configured.root/'extraction/jobs'/task['id']/'page-1.png'
    page.write_bytes(b'page-preview-fixture')
    for url in [review_url(task)+'/events',f"{BASE}/{task['id']}/confirmed",f"{BASE}/{task['id']}/page"]:
        assert stranger.get(url).status_code==200
    assert len(stranger.get(review_url(task)+'/events').json()['data'])==1
    assert len(stranger.get(f"{BASE}/{task['id']}/confirmed").text.splitlines())==1
    assert stranger.post(review_url(task),json=payload(task)).status_code==403
    assert client.get(f"{BASE}/{task['id']}").json()['reviews']==stranger.get(f"{BASE}/{task['id']}").json()['reviews']
    assert client.post(review_url(task),json=payload(task),headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post(f"{BASE}/{task['id']}/reviews/invented",json=payload(task)).status_code==404


def test_exports_only_confirmed_and_safe_csv_preserves_negative_numbers(candidate):
    client,task,_=candidate
    body=payload(task,raw_material='=SUM(1,2)',raw_value='-1.20',raw_unit='cm',note='测试文本导出与负数精度',
                 experiment_condition='40°SR',condition_source='第3页方法段')
    assert client.post(review_url(task),json=body).status_code==200
    rejected=payload(task,1,status='rejected',note='尚不能确认')
    assert client.post(review_url(task,1),json=rejected).status_code==200
    exported=client.get(f"{BASE}/{task['id']}/confirmed")
    assert int(exported.headers['content-length'])==len(exported.content)
    rows=[json.loads(r) for r in exported.text.splitlines()]
    assert len(rows)==1 and rows[0]['review']['current']['raw_value']=='-1.20'
    assert rows[0]['original']['raw_value']=='1.36'
    assert not rows[0]['review']['approved_for_training']
    csv_response=client.get(f"{BASE}/{task['id']}/confirmed?format=csv")
    assert csv_response.headers['cache-control']=='no-store'
    values=list(csv.DictReader(StringIO(csv_response.content.decode('utf-8-sig'))))
    assert len(values)==1 and values[0]['raw_material']=="'=SUM(1,2)"
    assert values[0]['raw_value']=='-1.20' and values[0]['condition_source']=='第3页方法段'
    assert values[0]['original_raw_unit']=='mm' and values[0]['raw_unit']=='cm'
    assert values[0]['original_raw_material']=='bagasse' and values[0]['original_metric']=='fiber_length'
    assert client.get(f"{BASE}/{task['id']}/confirmed?format=xlsx").status_code==422


def test_v1_database_upgrade_preserves_tasks_and_reviews_survive_reinitialization(candidate,configured):
    client,task,_=candidate
    p=configured.root/'extraction/records.sqlite3'
    store=extraction.ExtractionStore(p)
    # Simulate the previous schema before review was introduced.
    with sqlite3.connect(p) as conn:
        conn.execute('DROP TABLE extraction_review_events')
        conn.execute('DROP TABLE extraction_reviews')
        conn.execute('PRAGMA user_version=1')
    store.initialize()
    with sqlite3.connect(p) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==2
        assert conn.execute('SELECT count(*) FROM extraction_tasks').fetchone()[0]==1
    assert client.post(review_url(task),json=payload(task)).status_code==200
    store.initialize()
    assert store.reviews(task['id'])
    assert len(store.review_events(task['id'],task['snapshot']['result']['measurements'][0]['record_id']))==1


def test_task_search_is_literal(candidate):
    client,task,_=candidate
    assert client.get(BASE,params={'q':'paper.pdf'}).json()['pagination']['total']==1
    assert client.get(BASE,params={'q':'TABLE 3'}).json()['pagination']['total']==1
    for q in ['%', '_',"' OR 1=1--"]:
        assert client.get(BASE,params={'q':q}).json()['pagination']['total']==0


def test_processing_task_cannot_be_reviewed(configured):
    runner=extraction.ExtractionRunner(configured)
    runner.ensure()
    try:
        owner,_=runner.store.session(None)
        task_id=runner.store.create(owner,str(uuid4()),'fingerprint',{})
        from app.extraction_review import ReviewInput
        from fastapi import HTTPException
        body=ReviewInput(**{'expected_revision':0,'raw_material':'test','metric':'fiber_length','measurement_state':'raw_material','raw_value':'1','raw_unit':'mm','status':'confirmed'})
        with pytest.raises(HTTPException) as e:
            runner.store.review(owner,task_id,'test',body)
        assert e.value.status_code==409
    finally:runner.close()
