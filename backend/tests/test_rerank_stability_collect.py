"""Offline seal, source-binding, missing-grade and all-attempt accounting checks."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import collect_rerank_stability_20261031 as collect


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def review():
    return dict(key_point_scores={'P1':1},claim_assessments=[dict(id='C1',claim_type='fact',support='supported')],
        citation_assessments=[dict(score=1)],citation_group_assessments=[dict(coverage='complete')],
        answerability_score=2,reference_concern=False)


def case(tid):
    return dict(id=tid,question='Question '+tid,key_points=[dict(id='P1',optional=False,capability='text')])


def run_data():
    return dict(run_id='test-run',tasks=[dict(id=t,case_id=t,capabilities=['text']) for t in collect.TASK_IDS],
        dataset_manifest_sha256='dataset',dataset_files={'manifest.json':'dataset'},configuration={'threshold':.35},
        configuration_probe={'model':'frozen','rerank':{'enabled':False}},source_files={},
        initial_library_files={'chroma/data':'identical-vectors'},baseline_manifest_sha256='baseline',
        archive_sha256='archive',timeout_seconds=120)


def bundle_fixture():
    run=run_data();results={}
    for tid in collect.TASK_IDS:
        results[tid]=dict(response=dict(answer='Fact [1]',claims=[dict(text='Fact',citation_refs=['[1]'])],
            retrieved_evidence=[dict(ref='[1]',page_start=1,page_end=1,text='Source fact')]))
    bundle=dict(run=run,cases={t:case(t) for t in collect.TASK_IDS},results=results,
        run_sha256='manifest',result_sha256={t:'result-'+t for t in collect.TASK_IDS})
    jobs=[]
    for task in run['tasks']:
        candidate=collect.scientific_candidate(results[task['id']],task['id'])
        candidate['citations'][0]['verification']=dict(status='needs_source_review')
        jobs.append(dict(system='rag',task_id=task['id'],task=task,
            reference_case=bundle['cases'][task['case_id']],candidate=candidate))
    meta=dict(dataset_manifest_sha256='dataset',rag_origins={t:dict(source_run_id='test-run',
        source_run_sha256='manifest',result_sha256='result-'+t) for t in collect.TASK_IDS})
    study=dict(policy_sha256=collect.grading.POLICY_SHA,requested_judges={'jev':{'requested_model':'frozen'}},
        jobs=[dict(task_id=t,judge='jev',system='rag',name='jev-'+t) for t in collect.TASK_IDS])
    audit=(meta,jobs,study,{('jev','rag',t):review() for t in collect.TASK_IDS},{'jev':[]},Counter(),[])
    return bundle,audit


def contract_fixture(tmp_path):
    return dict(version='rerank-system-stability-v1',task_ids=list(collect.TASK_IDS),rounds=[1,2,3],new_rounds=[2,3],
        planned_new_answers=128,planned_new_jev_jobs=128,scheduling=dict(concurrency=2,round_order=[2,3]),
        original_run_manifests={s:'seal-'+s for s in collect.SYSTEMS},
        runs=[dict(system=s,round=r,run_dir=str(tmp_path/f'pfi-{s}-repeat-20261031-r{r}'),
            original_run_dir=str(tmp_path/collect.ORIGINAL_RUNS[s]),original_run_sha256='seal-'+s)
            for r in (2,3) for s in collect.SYSTEMS])


def test_frozen_contract_rejects_duplicate_or_reordered_experiment(tmp_path):
    contract=contract_fixture(tmp_path)
    assert len(collect.validate_contract(contract))==4
    for mutate in [lambda c:c['runs'].__setitem__(1,c['runs'][0]),
                   lambda c:c['task_ids'].reverse(),
                   lambda c:c['scheduling'].update(round_order=[3,2]),
                   lambda c:c['runs'][0].update(original_run_sha256='different')]:
        changed=deepcopy(contract);mutate(changed)
        with pytest.raises(ValueError):collect.validate_contract(changed)


@pytest.mark.parametrize('field',['configuration_probe','source_files','tasks','dataset_files','initial_library_files'])
def test_exact_same_system_controls_reject_any_settings_or_evidence_drift(field):
    original=run_data();repeated=deepcopy(original)
    assert collect.equal_run_controls(repeated,original)['configuration_probe_equal']
    repeated[field]=['changed']
    with pytest.raises(ValueError,match=field):collect.equal_run_controls(repeated,original)


@pytest.mark.parametrize('mutate',[
    lambda b,a:a[0]['rag_origins']['PFI2-001'].update(result_sha256='changed'),
    lambda b,a:a[0]['rag_origins']['PFI2-001'].update(source_run_sha256='changed'),
    lambda b,a:a[1][0]['candidate'].update(answer='Altered answer'),
    lambda b,a:a[1][0]['candidate']['citations'][0].update(text='Altered citation'),
    lambda b,a:a[1][0]['candidate']['available_context'].update(texts=['Altered context']),
    lambda b,a:a[1][0].update(reference_case={'question':'Altered reference'}),
])
def test_import_is_bound_to_the_actual_answer_and_reference(mutate):
    bundle,audit=bundle_fixture();collect.verify_import_binding(audit,bundle)
    mutate(bundle,audit)
    with pytest.raises(ValueError):collect.verify_import_binding(audit,bundle)


def test_original_review_is_preserved_and_missing_judgment_never_becomes_zero():
    bundle,audit=bundle_fixture();audit[3].pop(('jev','rag','PFI2-024'))
    before=deepcopy(audit)
    rows=collect.audit_records('content',1,audit,{'PFI2-024':'invalid_scorecard'})
    missing=next(r for r in rows if r['task_id']=='PFI2-024')
    assert missing['review'] is None and missing['metrics'] is None
    assert missing['grading_status']=='invalid_scorecard' and missing['capabilities']==['text']
    assert rows[0]['review']==audit[3][('jev','rag','PFI2-001')]
    assert rows[0]['metrics']['point_mean']==1 and audit==before


def test_only_jev_and_completed_or_explicitly_missing_studies_are_accepted():
    _,audit=bundle_fixture();collect.validate_study(audit)
    audit[5][('jev','rag','pending')]=1
    with pytest.raises(ValueError,match='interrupted'):collect.validate_study(audit)
    audit[5].clear();audit[2]['requested_judges']['luna']={}
    with pytest.raises(ValueError,match='Only Jev'):collect.validate_study(audit)


def test_all_invalid_and_failed_attempts_are_kept_and_unknown_billing_is_not_free(tmp_path):
    _,audit=bundle_fixture();save(tmp_path/'study.json',audit[2])
    calls=[dict(status='invalid_scorecard',api_calls=1,attempt=1,request_sha256='request',duration_ms=10,
        usage=dict(input_tokens=100,output_tokens=5,total_tokens=105,reported_cost_usd=.01)),
        dict(status='api_failed',api_calls=1,attempt=2,request_sha256='request',duration_ms=20)]
    for record in calls:save(tmp_path/'records/jev-PFI2-001'/f"{record['attempt']}.json",record)
    details,statuses=collect.attempt_details(tmp_path,max_attempts=3)
    assert len(details)==2 and statuses['PFI2-001']=='api_failed' and statuses['PFI2-002']=='missing'
    assert all(d['record_sha256'] for d in details)
    bundle,_=bundle_fixture();audit[4]['jev'].extend(calls)
    group=collect.accounting_group([dict(system='content',round=2,audit=audit,bundle=bundle,attempts=details,statuses=statuses)])
    assert group['jev']['calls']==2 and group['jev']['reported_cost_usd']=='0.01'
    assert group['jev']['cost_unknown_calls']==group['jev']['usage_unknown_calls']==1
    assert group['by_run'][0]['attempts']==details
    save(tmp_path/'records/jev-PFI2-001/3.json',dict(status='pending',attempt=3,request_sha256='request'))
    with pytest.raises(ValueError,match='interrupted'):collect.attempt_details(tmp_path)


def test_frozen_answer_result_and_runtime_source_tampering_is_rejected(tmp_path,monkeypatch):
    bundle,_=bundle_fixture();run=bundle['run'];run['run_id']='saved'
    (tmp_path/'backend').mkdir();source=tmp_path/'backend/worker.py';source.write_text('frozen',encoding='utf-8')
    run['source_files']={'worker.py':collect.judge.digest(source)}
    save(tmp_path/'run.json',run);manifest_sha=collect.judge.digest(tmp_path/'run.json')
    for task in run['tasks']:
        tid=task['id'];result=dict(run_id='saved',task_id=tid,case_id=tid,question=case(tid)['question'],
            status='answered',runner_sha256='runner')
        save(tmp_path/'results'/f'{tid}.json',result)
        save(tmp_path/'attempts'/f'{tid}.json',dict(result_sha256=collect.judge.digest(tmp_path/'results'/f'{tid}.json')))
    monkeypatch.setattr(collect.judge,'verify_run',lambda directory:(run,{},bundle['cases'],{}))
    assert len(collect.verify_run(tmp_path,manifest_sha,'runner')['results'])==32
    save(tmp_path/'results/PFI2-001.json',dict(run_id='saved',task_id='PFI2-001',case_id='PFI2-001',
        question=case('PFI2-001')['question'],status='answered',answer='changed'))
    with pytest.raises(ValueError,match='checksum'):collect.verify_run(tmp_path,manifest_sha,'runner')
    source.write_text('altered',encoding='utf-8')
    with pytest.raises(ValueError,match='source'):collect.verify_run(tmp_path,manifest_sha,'runner')


def test_historical_public_rows_must_match_original_judgments_exactly():
    rows=[]
    for system,tid in [('content','PFI2-024'),('rerank','PFI2-023')]:
        _,audit=bundle_fixture();audit[3].pop(('jev','rag',tid))
        rows+=collect.audit_records(system,1,audit,{tid:'invalid_scorecard'})
    public=[dict(task_id=t,reference_case=case(t),systems={r['system']:{k:r[k] for k in ('candidate','review','metrics')}
        for r in rows if r['task_id']==t}) for t in collect.TASK_IDS]
    public=deepcopy(public)
    collect.validate_public_round(rows,public)
    public[0]['systems']['rerank']['metrics']['point_mean']=.5
    with pytest.raises(ValueError,match='metrics'):collect.validate_public_round(rows,public)


def test_rerank_usage_counts_all_answer_calls_without_inventing_money_or_probe():
    results=[dict(response=dict(rerank_calls=[dict(status='completed',latency_ms=100,usage={'total_tokens':20})])),
        dict(response=dict(rerank_calls=[dict(status='failed',latency_ms=200,usage=None)]))]
    actual=collect.rerank_accounting(results)
    assert actual['calls']==2 and actual['known_tokens']=={'total_tokens':20}
    assert actual['usage_unknown_calls']==1 and actual['actual_billing_usd'] is None
    assert actual['independent_probe_calls_included']==0 and actual['median_call_seconds']==.15


def test_concurrent_wall_span_is_separate_from_question_time_sum():
    results=[dict(started_at='2026-10-31T00:00:00+00:00',finished_at='2026-10-31T00:00:10+00:00',end_to_end_ms=10000),
        dict(started_at='2026-10-31T00:00:01+00:00',finished_at='2026-10-31T00:00:11+00:00',end_to_end_ms=10000)]
    timing=collect.answer_timing(results)
    assert timing['first_start_to_last_finish_seconds']==11 and timing['sum_question_end_to_end_seconds']==20
    results.append({'end_to_end_ms':1000})
    assert collect.answer_timing(results)['first_start_to_last_finish_seconds'] is None


def test_observed_models_do_not_invent_missing_returned_identifiers():
    results=[dict(response=dict(generation_calls=[dict(model_info=dict(requested_model='alias',returned_model='actual',reasoning_effort='high')),
        dict(model_info=None)],configuration=dict(llm_model='alias',top_k=8,api_key='MUST_NOT_EXPORT')))]
    observation=collect.model_observations(results)
    assert observation['generation_model_info'][0]['model_info']['returned_model']=='actual'
    assert observation['model_info_unknown_calls']==1 and 'MUST_NOT_EXPORT' not in json.dumps(observation)


def test_full_collection_combines_six_cells_without_network_or_output_writes(tmp_path,monkeypatch):
    private=tmp_path/'.rag-data/evaluations';output=private/'rerank-stability-20261031'
    contract=contract_fixture(private);bundles={};audits={};historical_rows=[]
    for name in ('repeat_qa_rerank_20261031.py','run_qa_baseline.py','grade_qa_rerank_repeats_20261031.py',
                 'qa_repeat_refusal_compat.py','judge_qa_eval.py'):
        p=tmp_path/'scripts'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('frozen',encoding='utf-8')
    digest=collect.judge.digest
    contract.update(orchestrator_sha256=digest(tmp_path/'scripts/repeat_qa_rerank_20261031.py'),
        runner_sha256=digest(tmp_path/'scripts/run_qa_baseline.py'))
    for round_number in (1,2,3):
        for system in collect.SYSTEMS:
            bundle,audit=bundle_fixture()
            run_dir=private/(collect.ORIGINAL_RUNS[system] if round_number==1 else f'pfi-{system}-repeat-20261031-r{round_number}')
            run_sha='seal-'+system if round_number==1 else f'{system}-{round_number}'
            bundle['run_sha256']=run_sha;bundle['run']['run_id']=run_dir.name
            for origin in audit[0]['rag_origins'].values():origin.update(source_run_sha256=run_sha,source_run_id=run_dir.name)
            if round_number==1:
                missing='PFI2-024' if system=='content' else 'PFI2-023';audit[3].pop(('jev','rag',missing))
            for job in audit[2]['jobs']:job['request_sha256']='scientific-request-'+job['task_id']
            imp=private/collect.ORIGINAL_IMPORTS[system] if round_number==1 else output/'imports'/f'{system}-r{round_number}'
            study=private/collect.ORIGINAL_STUDIES[system] if round_number==1 else output/'studies'/f'{system}-r{round_number}'
            save(imp/'import.json',audit[0]);save(study/'study.json',audit[2])
            statuses={}
            for job in audit[2]['jobs']:
                tid=job['task_id'];status='completed' if ('jev','rag',tid) in audit[3] else 'invalid_scorecard'
                record=dict(status=status,api_calls=1,attempt=1,request_sha256=job['request_sha256'])
                save(study/'records'/job['name']/'1.json',record);audit[4]['jev'].append(record);statuses[tid]=status
                save(study/'inputs'/(job['name']+'.json'),dict(scientific_packet=tid))
            bundles[str(run_dir)]=bundle;audits[str(study)]=audit
            if round_number==1:historical_rows+=collect.audit_records(system,1,audit,statuses)
            else:
                next(e for e in contract['runs'] if e['system']==system and e['round']==round_number)['run_sha256']=run_sha
    direct=private/collect.ORIGINAL_STUDIES['rerank'];recovery=private/collect.RECOVERY
    recovery_audit=deepcopy(audits[str(direct)])
    recovery_audit=list(recovery_audit);recovery_audit[3]={};recovery_audit[4]={'jev':[]};recovery_audit=tuple(recovery_audit)
    save(recovery/'study.json',recovery_audit[2]);audits[str(recovery)]=recovery_audit
    for job in recovery_audit[2]['jobs']:
        save(recovery/'inputs'/(job['name']+'.json'),dict(scientific_packet=job['task_id']))
    save(recovery/'recovery-manifest.json',dict(original_study_sha256=digest(direct/'study.json'),recovery_study_sha256=digest(recovery/'study.json')))
    save(output/'experiment.json',contract)
    save(output/'refusal-import-compat-r3.json',dict(original_status_preserved=True,new_generation_calls=0,
        compat_source_sha256=digest(tmp_path/'scripts/qa_repeat_refusal_compat.py'),
        original_read_result_source_sha256=digest(tmp_path/'scripts/judge_qa_eval.py'),policy_sha256=collect.grading.POLICY_SHA))
    save(output/'grading-contract.json',dict(version='rerank-stability-grading-v1',policy_sha256=collect.grading.POLICY_SHA,
        new_rounds=[2,3],planned_new_jev_jobs=128,max_attempts=3,first_valid_only=True,new_luna_calls=0,
        historical_scores_reused=True,requested_judges=audits[str(direct)][2]['requested_judges'],
        grader_sha256=digest(tmp_path/'scripts/grade_qa_rerank_repeats_20261031.py')))
    public=tmp_path/collect.PUBLIC_REPORT;public.mkdir(parents=True)
    rows=[dict(task_id=t,reference_case=case(t),systems={r['system']:{k:r[k] for k in ('candidate','review','metrics')}
        for r in historical_rows if r['task_id']==t}) for t in collect.TASK_IDS]
    public_file=public/'questions-answers-reviews.jsonl'
    public_file.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    save(public/'publication.json',dict(files={public_file.name:digest(public_file)}))
    monkeypatch.setattr(collect,'verify_run',lambda directory,*args:bundles[str(directory)])
    monkeypatch.setattr(collect.scoring,'audit',lambda imp,study:audits[str(study)])
    monkeypatch.setattr(collect.runtime_report,'runtime',lambda:dict(questions=32,per_question=['private-detail'],generation_calls=32))
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected network/configuration access')
    monkeypatch.setattr(collect.grading,'configs',forbidden)
    payload=collect.collect(tmp_path)
    assert len(payload['records'])==192 and len(payload['runtimes'])==6
    assert sum(r['review'] is None for r in payload['records'])==2
    assert payload['accounting']['new']['jev']['calls']==128
    assert payload['accounting']['historical']['jev']['calls']==64
    assert payload['provenance']['provider_calls_by_collector']==0
    assert all('per_question' not in r for r in payload['runtimes'])
    assert not (output/'analysis-input.json').exists()
