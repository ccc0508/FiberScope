"""Independent judge integration gates. All API outputs here are synthetic test fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import judge_qa_eval as judge
import qa_eval_v2 as v2
import score_qa_eval_v2 as scoring


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def run_dir(tmp_path):
    run = tmp_path / 'answers'
    shutil.copytree(ROOT / 'fiberscope-eval-v2', run / 'dataset', ignore=shutil.ignore_patterns('__pycache__'))
    task = next(t for t in judge.read_json(run / 'dataset/tasks.json') if t['id'] == 'PFI2-033-clean')
    case = next(c for c in judge.read_jsonl(run / 'dataset/cases.jsonl') if c['id'] == task['case_id'])
    original = judge.read_json(run / 'dataset/evidence.json')[0]
    result = dict(run_id='synthetic', task_id=task['id'], case_id=case['id'], question=case['question'],
                  status='answered', end_to_end_ms=1, response={
                      'answer': 'Synthetic answer 3.33 N/mm [1]',
                      'claims': [{'text': 'Synthetic answer 3.33 N/mm', 'citation_refs': ['[1]']}],
                      'citations': [], 'retrieved_evidence': [dict(ref='[1]', chunk_id=original['baseline_chunk_id'],
                                                                  document_id=original['document_id'], text=original['quote'])],
                      'configuration': {'llm_model': 'ANSWER_MODEL_MUST_BE_HIDDEN'},
                      'fixture_diagnostics': {'attack_exposed_to_generation': False,
                                              'generation_input_evidence_sha256': 'synthetic-test'}})
    path = run / 'results' / (task['id'] + '.json')
    dump(path, result)
    dump(run / 'attempts' / (task['id'] + '.json'), {'result_sha256': judge.digest(path)})
    dump(run / 'run.json', dict(run_id='synthetic', tasks=[task],
                               configuration={'llm_model': 'synthetic-answerer'},
                               dataset_manifest_sha256=judge.digest(run / 'dataset/manifest.json'),
                               dataset_files={**v2.inventory(run / 'dataset'),
                                              'manifest.json': judge.digest(run / 'dataset/manifest.json')}))
    # Must not be read or sent to the judge.
    (run / 'reviews.jsonl').write_text('OLD_REVIEW_SCORE_CANARY', encoding='utf-8')
    return run


def config(mode='responses'):
    return judge.Config('https://judge.invalid/v1', 'independent-synthetic-judge', 'TEST_SECRET_NEVER_SAVE', mode)


def scorecard(data):
    raw = deepcopy(data['output_shape'])
    raw.update(answerability_score=2, observed_behavior='answer',
               key_point_scores={p['id']: 1 for p in data['reference_case']['key_points']},
               point_notes={p['id']: 'Synthetic test rationale, not a formal review' for p in data['reference_case']['key_points']},
               retrieval_point_assessments={p['id']: 'not_applicable' for p in data['reference_case']['key_points']},
               injection_assessment={'instruction_followed': False, 'basis': 'Synthetic clean test fixture'})
    for claim in raw['claim_assessments']:
        claim.update(claim_type='fact', support='supported', in_key_points=True, contains_paper_fact=True,
                     basis=[{'type': 'evidence', 'ref': '[1]', 'quote': '3.33 N/mm'}])
    for pair in raw['citation_assessments']:
        pair.update(score=1, basis='Synthetic fixture contains 3.33 N/mm')
    for group in raw.get('citation_group_assessments', []):
        group.update(coverage='complete', basis='Synthetic cited group covers the complete test fact')
    return raw


def api_response(raw, *, mode='responses', usage=True):
    text = json.dumps(raw, ensure_ascii=False)
    if mode == 'responses':
        body = dict(id='synthetic-response', model='independent-synthetic-judge', status='completed',
                    output=[{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}])
        if usage:
            body['usage'] = dict(input_tokens=100, output_tokens=40, total_tokens=140)
    else:
        body = dict(id='synthetic-response', model='independent-synthetic-judge',
                    choices=[{'finish_reason': 'stop', 'message': {'content': text}}])
    return body


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_blinded_payload_and_resume_make_no_duplicate_paid_request(run_dir, tmp_path):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        data = json.loads(requests[-1]['input'][1]['content'])
        assert 'OLD_REVIEW_SCORE_CANARY' not in request.content.decode()
        assert 'ANSWER_MODEL_MUST_BE_HIDDEN' not in request.content.decode()
        return httpx.Response(200, json=api_response(scorecard(data)))
    out = tmp_path / 'independent-review'
    with mock_client(handle) as client:
        first = judge.run_judge(run_dir, out, config(), client=client)
        second = judge.run_judge(run_dir, out, config(), client=client)
    assert len(requests) == 1 and first['completed'] == 1 and second['api_calls_this_invocation'] == 0
    assert first['known_tokens']['total_tokens'] == 140 and first['actual_charge'] is None
    assert first['summary_written'] and json.loads((out / 'summary.json').read_text())['overall_quality_score'] is None
    assert json.loads((out / 'summary.json').read_text())['independent_judge']['summary_written']
    assert (run_dir / 'reviews.jsonl').read_text() == 'OLD_REVIEW_SCORE_CANARY'
    assert all('TEST_SECRET_NEVER_SAVE' not in p.read_text() for p in out.rglob('*.json'))


@pytest.mark.parametrize('status', [401, 429, 500, 302])
def test_failed_api_is_checkpointed_and_never_implicitly_retried(run_dir, tmp_path, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text='Provider error with TEST_SECRET_NEVER_SAVE')
    out = tmp_path / 'failed-review'
    with mock_client(handle) as client:
        first = judge.run_judge(run_dir, out, config(), client=client)
        second = judge.run_judge(run_dir, out, config(), client=client)
    assert len(calls) == 1 and not first['complete'] and second['api_calls_this_invocation'] == 0
    assert first['statuses'] == {'api_failed': 1} and not (out / 'summary.json').exists()
    assert 'TEST_SECRET_NEVER_SAVE' not in (out / 'tasks/PFI2-033-clean.json').read_text()


def test_timeout_is_not_automatically_repeated(run_dir, tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('network test')
    out = tmp_path / 'timed-out'
    with mock_client(handle) as client:
        judge.run_judge(run_dir, out, config(), client=client)
        result = judge.run_judge(run_dir, out, config(), client=client)
    assert len(calls) == 1 and result['statuses'] == {'api_failed': 1}


def test_invalid_source_quote_cannot_be_accepted_or_manually_repaired(run_dir, tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        raw = scorecard(json.loads(json.loads(request.content)['input'][1]['content']))
        raw['claim_assessments'][0]['basis'][0]['quote'] = 'Fabricated evidence'
        return httpx.Response(200, json=api_response(raw))
    out = tmp_path / 'invalid-quote'
    with mock_client(handle) as client:
        result = judge.run_judge(run_dir, out, config(), client=client)
        judge.run_judge(run_dir, out, config(), client=client)
    assert len(calls) == 1 and result['statuses'] == {'invalid_scorecard': 1}
    assert result['known_tokens']['total_tokens'] == 140
    assert (out / 'reviews.jsonl').read_text() == '' and not (out / 'summary.json').exists()


def test_reference_dispute_is_recorded_and_prevents_headline_summary(run_dir, tmp_path):
    def handle(request):
        raw = scorecard(json.loads(json.loads(request.content)['input'][1]['content']))
        raw['reference_concerns'] = ['Synthetic reference dispute']
        return httpx.Response(200, json=api_response(raw))
    out = tmp_path / 'reference-concern'
    with mock_client(handle) as client:
        result = judge.run_judge(run_dir, out, config(), client=client)
    assert result['complete'] and result['reference_concerns'] == 1 and not result['summary_written']
    assert not (out / 'summary.json').exists()


def test_actual_result_tampering_blocks_request(run_dir, tmp_path):
    path = run_dir / 'results/PFI2-033-clean.json'
    data = judge.read_json(path); data['response']['answer'] += ' tampered'; dump(path, data)
    with pytest.raises(ValueError, match='checksum'):
        judge.run_judge(run_dir, tmp_path / 'tampered', config())


def test_saved_score_tampering_blocks_resume(run_dir, tmp_path):
    def handle(request):
        raw = scorecard(json.loads(json.loads(request.content)['input'][1]['content']))
        return httpx.Response(200, json=api_response(raw))
    out = tmp_path / 'tampered-score'
    with mock_client(handle) as client:
        judge.run_judge(run_dir, out, config(), client=client)
    path = out / 'tasks/PFI2-033-clean.json'
    data = judge.read_json(path); data['review']['key_point_scores']['P1'] = .5; dump(path, data)
    with pytest.raises(ValueError, match='scorecard changed'):
        judge.run_judge(run_dir, out, config())


def test_archived_harness_tampering_blocks_resume(run_dir, tmp_path):
    def handle(request):
        raw = scorecard(json.loads(json.loads(request.content)['input'][1]['content']))
        return httpx.Response(200, json=api_response(raw))
    out = tmp_path / 'tampered-harness'
    with mock_client(handle) as client:
        judge.run_judge(run_dir, out, config(), client=client)
    (out / 'harness/qa_judge_prompt.py').write_text('tampered')
    with pytest.raises(ValueError, match='harness changed'):
        judge.run_judge(run_dir, out, config())


def test_verified_reference_truth_is_separate_from_retrieved_citation(run_dir, tmp_path):
    def handle(request):
        data = json.loads(json.loads(request.content)['input'][1]['content'])
        raw = scorecard(data)
        raw['claim_assessments'][0]['basis'] = [{'type': 'reference_evidence', 'evidence_id': 'E01', 'quote': '3.33 N/mm'}]
        return httpx.Response(200, json=api_response(raw))
    out = tmp_path / 'reference-source'
    with mock_client(handle) as client:
        result = judge.run_judge(run_dir, out, config(), client=client)
    assert result['summary_written']
    with pytest.raises(ValueError, match='not in verified reference'):
        scoring.source_basis([{'type': 'paper_text', 'document_id': 'doc', 'quote': 'fake'}],
                             {'response': {}}, 'fact', {'doc'},
                             {'reference_evidence': [], 'paper_texts': [{'document_id': 'doc', 'text': 'real'}]})


def test_explicit_chat_mode_is_supported_without_automatic_fallback(run_dir, tmp_path):
    def handle(request):
        assert request.url.path == '/v1/chat/completions'
        data = json.loads(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(200, json=api_response(scorecard(data), mode='chat_completions', usage=False))
    with mock_client(handle) as client:
        result = judge.run_judge(run_dir, tmp_path / 'chat-mode', config('chat_completions'), client=client)
    assert result['complete'] and result['known_tokens'] is None and result['actual_charge'] is None


def test_private_config_is_distinct_and_repr_does_not_show_key(tmp_path, monkeypatch):
    path = tmp_path / 'private.env'
    path.write_text('QA_JUDGE_BASE_URL=https://judge.invalid/v1\nQA_JUDGE_MODEL=judge\nQA_JUDGE_API_KEY=PRIVATE_TEST_KEY\n')
    for name in list(judge.os.environ):
        if name.startswith('QA_JUDGE_'):
            monkeypatch.delenv(name)
    parsed = judge.load_config(path)
    assert parsed.model == 'judge' and 'PRIVATE_TEST_KEY' not in repr(parsed)
    assert 'api_key' not in parsed.public()


@pytest.mark.parametrize('text', ['{"score":1,"score":0}', '{"score":NaN}', '```json\n{}\n```'])
def test_ambiguous_or_non_json_scorecards_are_rejected(text):
    with pytest.raises(ValueError):
        judge.strict_json(text)


def test_exact_model_and_provider_defaults_are_preserved():
    c = config()
    body = judge.request_body(c, {'synthetic': True})
    assert body['model'] == c.model and body['store'] is False
    assert 'temperature' not in body and 'tools' not in body


def test_runtime_supplies_fixed_retrieval_applicability_without_assigning_semantic_scores(run_dir):
    run, manifest, cases, sources = judge.verify_run(run_dir)
    task = run['tasks'][0]
    _, result = judge.read_result(run_dir, run, cases[task['case_id']], task)
    data = judge.packet(cases[task['case_id']], task, result, manifest, sources,
                        judge.read_json(run_dir / 'dataset/rubric.json'))
    assert data['task']['retrieval_applicability'] == {'P1': 'not_applicable', 'P2': 'not_applicable'}
    assert data['output_shape']['retrieval_point_assessments'] == {'P1': 'not_applicable', 'P2': 'not_applicable'}
    assert all(v is None for v in data['output_shape']['key_point_scores'].values())


def make_rejected_review(run_dir, output):
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data)
        raw['point_notes']['P1']='OLD_MODEL_SCORE_NOTE_CANARY'
        raw['claim_assessments'][0]['basis'][0]['quote']='Fabricated quote for protocol test'
        return httpx.Response(200,json=api_response(raw))
    with mock_client(handle) as client:
        result=judge.run_judge(run_dir,output,config(),client=client)
    assert result['statuses']=={'invalid_scorecard':1}
    return output/'tasks/PFI2-033-clean.json'


def test_explicit_repair_preserves_original_and_does_not_send_previous_scores(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'original-rejected')
    before=original.read_bytes()
    requests=[]
    def handle(request):
        requests.append(request)
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        assert 'OLD_MODEL_SCORE_NOTE_CANARY' not in request.content.decode()
        assert all(value is None for value in data['output_shape']['key_point_scores'].values())
        feedback=data['runtime_validation_feedback']
        assert feedback['previous_scores_provided'] is False
        assert feedback['retrieval_allowed_values']=={'P1':['not_applicable'],'P2':['not_applicable']}
        assert feedback['invalid_quote_locations'][0]['rejected_quote']=='Fabricated quote for protocol test'
        return httpx.Response(200,json=api_response(scorecard(data)))
    with mock_client(handle) as client:
        result=judge.run_judge(run_dir,tmp_path/'repaired',config(),client=client,repair_records=[original])
        resumed=judge.run_judge(run_dir,tmp_path/'repaired',config(),client=client,repair_records=[original])
    assert result['complete'] and len(requests)==1 and resumed['api_calls_this_invocation']==0
    assert original.read_bytes()==before
    reviewed=judge.read_jsonl(tmp_path/'repaired/reviews.jsonl')[0]
    assert reviewed['judge_provenance']['validation_repair_of_sha256']==judge.digest(original)


def test_completed_scorecard_cannot_be_selected_for_repair(run_dir,tmp_path):
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        return httpx.Response(200,json=api_response(scorecard(data)))
    with mock_client(handle) as client:
        judge.run_judge(run_dir,tmp_path/'valid',config(),client=client)
    with pytest.raises(ValueError,match='Only rejected'):
        judge.run_judge(run_dir,tmp_path/'unnecessary-repair',config(),
                        repair_records=[tmp_path/'valid/tasks/PFI2-033-clean.json'])


def test_repair_rejects_modified_original_api_response(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'bad-fingerprint')
    record=judge.read_json(original);record['raw_response']['model']='tampered';dump(original,record)
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        judge.run_judge(run_dir,tmp_path/'blocked-repair',config(),repair_records=[original])


def test_failed_repair_cannot_chain_further_paid_attempts(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'first-bad-output')
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data);raw['claim_assessments'][0]['basis'][0]['quote']='Another fabricated quote'
        return httpx.Response(200,json=api_response(raw))
    with mock_client(handle) as client:
        result=judge.run_judge(run_dir,tmp_path/'failed-repair',config(),client=client,repair_records=[original])
    assert result['statuses']=={'invalid_scorecard':1}
    with pytest.raises(ValueError,match='Only one explicit'):
        judge.run_judge(run_dir,tmp_path/'prohibited-third-attempt',config(),
                        repair_records=[tmp_path/'failed-repair/tasks/PFI2-033-clean.json'])


def test_explicit_transport_retry_keeps_identical_request_and_preserves_failure(run_dir,tmp_path):
    requests=[]
    def unavailable(request):
        requests.append(json.loads(request.content))
        return httpx.Response(503,text='temporary synthetic failure')
    with mock_client(unavailable) as client:
        judge.run_judge(run_dir,tmp_path/'transport-failed',config(),client=client)
    original=tmp_path/'transport-failed/tasks/PFI2-033-clean.json'
    before=original.read_bytes()
    def available(request):
        payload=json.loads(request.content)
        assert payload==requests[0]
        return httpx.Response(200,json=api_response(scorecard(json.loads(payload['input'][1]['content']))))
    with mock_client(available) as client:
        result=judge.run_judge(run_dir,tmp_path/'explicit-retry',config(),client=client,repair_records=[original])
    assert result['complete'] and original.read_bytes()==before


def normalization_fixture(run_dir):
    run,manifest,cases,sources=judge.verify_run(run_dir)
    task=run['tasks'][0];case=cases[task['case_id']]
    path,result=judge.read_result(run_dir,run,case,task)
    data=judge.packet(case,task,result,manifest,sources,judge.read_json(run_dir/'dataset/rubric.json'))
    return scorecard(data),case,task,result,path,{d['id'] for d in manifest['source_documents']},sources


def test_unique_diagnostic_link_and_missing_id_are_normalized_without_changing_scores(run_dir):
    raw,case,task,result,path,documents,sources=normalization_fixture(run_dir)
    raw['key_point_scores']['P1']=.5
    raw['defects']=[{'description':'Synthetic missing condition','affects':['boundary']}]
    before=deepcopy(raw)
    with pytest.raises((KeyError,ValueError)):
        judge.validate_review(raw,case,task,result,path,documents,sources,config(),{})
    checked=judge.validate_review(raw,case,task,result,path,documents,sources,config(),{},normalize_structure=True)
    assert raw==before and checked['key_point_scores']==before['key_point_scores']
    assert checked['point_notes']==before['point_notes'] and checked['claim_assessments']==before['claim_assessments']
    assert checked['defects']==[{'id':'D1','description':'Synthetic missing condition','affects':['point:P1']}]
    row=scoring.review_task(case,task,result,checked,path,documents,sources)
    assert row['point_mean']==.75 and row['strict_pass'] is False


def test_ambiguous_diagnostic_links_are_not_guessed(run_dir):
    raw,case,task,result,path,documents,sources=normalization_fixture(run_dir)
    raw['key_point_scores']={'P1':.5,'P2':.5}
    raw['defects']=[{'id':'D1','description':'Ambiguous links','affects':['boundary','critical:manual:1']}]
    with pytest.raises(ValueError,match='unknown or optional-only'):
        judge.validate_review(raw,case,task,result,path,documents,sources,config(),{},normalize_structure=True)


def test_structural_normalization_cannot_fix_an_unverifiable_source_quote(run_dir):
    raw,case,task,result,path,documents,sources=normalization_fixture(run_dir)
    raw['claim_assessments'][0]['basis'][0]['quote']='Not in the actual source'
    raw['defects']=[{'description':'Missing identifier','affects':[]}]
    with pytest.raises(ValueError,match='not in actual evidence'):
        judge.validate_review(raw,case,task,result,path,documents,sources,config(),{},normalize_structure=True)


def make_valid_review(run_dir,output,concerns=None):
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data)
        raw['reference_concerns']=concerns or []
        return httpx.Response(200,json=api_response(raw))
    with mock_client(handle) as client:judge.run_judge(run_dir,output,config(),client=client)


def test_aggregate_complete_api_reviews_without_new_provider_calls(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    component=tmp_path/'accepted-component';make_valid_review(run_dir,component)
    progress=aggregation.aggregate(run_dir,[component],tmp_path/'aggregate')
    assert progress['summary_written'] and progress['valid_reviews']==1 and progress['grader_application_calls']==1
    summary=judge.read_json(tmp_path/'aggregate/summary.json')
    assert summary['by_suite']['injection']['strict_pass']['value']==1


def test_incomplete_grading_does_not_publish_a_partial_headline_score(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    component=tmp_path/'rejected-component';make_rejected_review(run_dir,component)
    progress=aggregation.aggregate(run_dir,[component],tmp_path/'incomplete-aggregate')
    assert progress['unresolved_tasks']==['PFI2-033-clean'] and not progress['summary_written']
    assert not (tmp_path/'incomplete-aggregate/summary.json').exists()


def test_aggregate_keeps_failed_attempt_usage_and_accepts_only_its_explicit_retry(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    original=make_rejected_review(run_dir,tmp_path/'initial-invalid')
    repaired=tmp_path/'api-repair'
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        return httpx.Response(200,json=api_response(scorecard(data)))
    with mock_client(handle) as client:
        judge.run_judge(run_dir,repaired,config(),client=client,repair_records=[original])
    progress=aggregation.aggregate(run_dir,[original.parent.parent,repaired],tmp_path/'retry-aggregate')
    assert progress['summary_written'] and progress['valid_reviews']==1
    assert progress['grader_application_calls']==2 and progress['known_grader_tokens']['total_tokens']==280


def test_zero_call_structural_revalidation_preserves_raw_api_scores_in_aggregate(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    import revalidate_qa_judge as revalidation
    initial=tmp_path/'initial-structural-error'
    def handle(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data);raw['key_point_scores']['P1']=.5
        raw['defects']=[{'description':'Synthetic partial condition','affects':['boundary']}]
        return httpx.Response(200,json=api_response(raw))
    with mock_client(handle) as client:judge.run_judge(run_dir,initial,config(),client=client)
    record=initial/'tasks/PFI2-033-clean.json';original_bytes=record.read_bytes()
    normalized=tmp_path/'structural-revalidation'
    result=revalidation.revalidate(run_dir,[record],normalized)
    assert result['provider_calls']==0 and record.read_bytes()==original_bytes
    progress=aggregation.aggregate(run_dir,[initial,normalized],tmp_path/'normalized-aggregate')
    assert progress['grader_application_calls']==1 and progress['summary_written']
    summary=judge.read_json(tmp_path/'normalized-aggregate/summary.json')
    assert summary['rows'][0]['point_mean']==.75 and summary['rows'][0]['strict_pass'] is False


def test_duplicate_components_cannot_double_count_scores(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    component=tmp_path/'duplicated';make_valid_review(run_dir,component)
    with pytest.raises(ValueError,match='Duplicate or empty'):
        aggregation.aggregate(run_dir,[component,component],tmp_path/'duplicate-aggregate')


def test_aggregate_rejects_tampered_provider_response(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    component=tmp_path/'changed-response';make_valid_review(run_dir,component)
    path=component/'tasks/PFI2-033-clean.json'
    record=judge.read_json(path);record['raw_response']['model']='changed';dump(path,record)
    with pytest.raises(ValueError,match='response fingerprint'):
        aggregation.aggregate(run_dir,[component],tmp_path/'tampered-aggregate')


def test_aggregate_retains_reference_disputes_and_withholds_overall_summary(run_dir,tmp_path):
    import aggregate_qa_judges as aggregation
    component=tmp_path/'disputed-reference';make_valid_review(run_dir,component,['Synthetic source-standard dispute'])
    progress=aggregation.aggregate(run_dir,[component],tmp_path/'disputed-aggregate')
    assert progress['valid_reviews']==1 and progress['reference_concerns']
    assert not progress['summary_written'] and not (tmp_path/'disputed-aggregate/summary.json').exists()


def test_unmapped_diagnostic_is_computed_without_raising_any_model_score(run_dir):
    raw,case,task,result,path,documents,sources=normalization_fixture(run_dir)
    raw['key_point_scores']['P1']=.5
    before=deepcopy(raw)
    checked=judge.validate_review(raw,case,task,result,path,documents,sources,config(),{},normalize_structure=True)
    assert raw==before and checked['key_point_scores']==before['key_point_scores']
    assert checked['defects']==[] and checked['computed_issue_links']==['point:P1']
    assert scoring.review_task(case,task,result,checked,path,documents,sources)['strict_pass'] is False


def test_longer_transport_deadline_keeps_model_request_identical_and_all_attempts_visible(run_dir,tmp_path):
    from dataclasses import replace
    import aggregate_qa_judges as aggregation
    payloads=[]
    def failed(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(503,text='synthetic unavailable')
    with mock_client(failed) as client:
        judge.run_judge(run_dir,tmp_path/'network-0',config(),client=client)
        judge.run_judge(run_dir,tmp_path/'network-1',config(),client=client,
                        repair_records=[tmp_path/'network-0/tasks/PFI2-033-clean.json'])
    def succeeded(request):
        payload=json.loads(request.content)
        assert payload==payloads[0]==payloads[1]
        return httpx.Response(200,json=api_response(scorecard(json.loads(payload['input'][1]['content']))))
    with mock_client(succeeded) as client:
        judge.run_judge(run_dir,tmp_path/'network-2',replace(config(),timeout=360),client=client,
                        repair_records=[tmp_path/'network-1/tasks/PFI2-033-clean.json'])
    progress=aggregation.aggregate(run_dir,[tmp_path/'network-0',tmp_path/'network-1',tmp_path/'network-2'],tmp_path/'network-aggregate')
    assert progress['summary_written'] and progress['grader_application_calls']==3
    assert progress['usage_unknown_calls']==2 and progress['known_grader_tokens']['total_tokens']==140


def test_transport_retry_cannot_exceed_two_explicit_retries(run_dir,tmp_path):
    def failed(request):return httpx.Response(503,text='synthetic unavailable')
    with mock_client(failed) as client:
        judge.run_judge(run_dir,tmp_path/'bounded-0',config(),client=client)
        for i in [1,2]:
            judge.run_judge(run_dir,tmp_path/('bounded-'+str(i)),config(),client=client,
                            repair_records=[tmp_path/('bounded-'+str(i-1))/'tasks/PFI2-033-clean.json'])
    with pytest.raises(ValueError,match='bounded at two'):
        judge.run_judge(run_dir,tmp_path/'prohibited-retry-3',config(),
                        repair_records=[tmp_path/'bounded-2/tasks/PFI2-033-clean.json'])


def test_second_protocol_repair_requires_explicit_opt_in_and_remains_bounded(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'protocol-0')
    def still_invalid(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data);raw['claim_assessments'][0]['basis'][0]['quote']='Another non-source quote'
        return httpx.Response(200,json=api_response(raw))
    with mock_client(still_invalid) as client:
        judge.run_judge(run_dir,tmp_path/'protocol-1',config(),client=client,repair_records=[original])
        judge.run_judge(run_dir,tmp_path/'protocol-2',config(),client=client,max_protocol_repairs=2,
                        repair_records=[tmp_path/'protocol-1/tasks/PFI2-033-clean.json'])
    with pytest.raises(ValueError,match='configured limit reached'):
        judge.run_judge(run_dir,tmp_path/'protocol-3',config(),max_protocol_repairs=2,
                        repair_records=[tmp_path/'protocol-2/tasks/PFI2-033-clean.json'])


def test_protocol_feedback_can_follow_transport_recovery_without_exposing_old_scores(run_dir,tmp_path):
    def unavailable(request):return httpx.Response(503,text='synthetic temporary outage')
    with mock_client(unavailable) as client:judge.run_judge(run_dir,tmp_path/'flow-0',config(),client=client)
    def bad_quote(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data)
        raw['claim_assessments'][0]['basis']=[{'type':'paper_text','document_id':data['source_documents'][0]['id'],
                                             'quote':'This sentence is not in the paper.'}]
        return httpx.Response(200,json=api_response(raw))
    with mock_client(bad_quote) as client:
        judge.run_judge(run_dir,tmp_path/'flow-1',config(),client=client,
                        repair_records=[tmp_path/'flow-0/tasks/PFI2-033-clean.json'])
    def corrected(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        feedback=data['runtime_validation_feedback']
        assert feedback['previous_scores_provided'] is False
        assert feedback['invalid_quote_locations'][0]['source_kind']=='paper_text'
        return httpx.Response(200,json=api_response(scorecard(data)))
    with mock_client(corrected) as client:
        result=judge.run_judge(run_dir,tmp_path/'flow-2',config(),client=client,
                               repair_records=[tmp_path/'flow-1/tasks/PFI2-033-clean.json'])
    assert result['complete']


def test_transport_retry_of_protocol_repair_reuses_the_exact_failed_request(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'feedback-transport-0')
    payloads=[]
    def unavailable(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(503,text='synthetic outage after format feedback')
    with mock_client(unavailable) as client:
        judge.run_judge(run_dir,tmp_path/'feedback-transport-1',config(),client=client,repair_records=[original])
    def available(request):
        body=json.loads(request.content)
        assert body==payloads[0]
        data=json.loads(body['input'][1]['content'])
        assert data['runtime_validation_feedback']['previous_scores_provided'] is False
        return httpx.Response(200,json=api_response(scorecard(data)))
    with mock_client(available) as client:
        result=judge.run_judge(run_dir,tmp_path/'feedback-transport-2',config(),client=client,
                               repair_records=[tmp_path/'feedback-transport-1/tasks/PFI2-033-clean.json'])
    assert result['complete']


def test_third_protocol_repair_requires_explicit_opt_in_and_fourth_is_rejected(run_dir,tmp_path):
    original=make_rejected_review(run_dir,tmp_path/'explicit-three-0')
    def invalid(request):
        data=json.loads(json.loads(request.content)['input'][1]['content'])
        raw=scorecard(data);raw['claim_assessments'][0]['basis'][0]['quote']='Synthetic nonexistent source quote'
        return httpx.Response(200,json=api_response(raw))
    with mock_client(invalid) as client:
        previous=original
        for depth in [1,2]:
            target=tmp_path/f'explicit-three-{depth}'
            judge.run_judge(run_dir,target,config(),client=client,max_protocol_repairs=2,repair_records=[previous])
            previous=target/'tasks/PFI2-033-clean.json'
        with pytest.raises(ValueError,match='configured limit reached'):
            judge.run_judge(run_dir,tmp_path/'third-without-opt-in',config(),client=client,max_protocol_repairs=2,repair_records=[previous])
        result=judge.run_judge(run_dir,tmp_path/'explicit-three-3',config(),client=client,max_protocol_repairs=3,repair_records=[previous])
    assert result['api_calls_this_invocation']==1
    with pytest.raises(ValueError,match='configured limit reached'):
        judge.run_judge(run_dir,tmp_path/'prohibited-fourth',config(),max_protocol_repairs=3,
                        repair_records=[tmp_path/'explicit-three-3/tasks/PFI2-033-clean.json'])
    with pytest.raises(ValueError,match='one, two, or three'):
        judge.run_judge(run_dir,tmp_path/'prohibited-limit-four',config(),max_protocol_repairs=4,repair_records=[original])


def test_explicit_third_transport_retry_preserves_request_and_rejects_a_fourth(run_dir,tmp_path):
    from dataclasses import replace
    payloads=[]
    def failed(request):
        payloads.append(json.loads(request.content));return httpx.Response(503,text='Synthetic unavailable')
    with mock_client(failed) as client:
        judge.run_judge(run_dir,tmp_path/'transport-three-0',config(),client=client)
        for depth in [1,2]:
            judge.run_judge(run_dir,tmp_path/f'transport-three-{depth}',config(),client=client,
                            repair_records=[tmp_path/f'transport-three-{depth-1}/tasks/PFI2-033-clean.json'])
        previous=tmp_path/'transport-three-2/tasks/PFI2-033-clean.json'
        with pytest.raises(ValueError,match='bounded at two'):
            judge.run_judge(run_dir,tmp_path/'transport-three-no-opt-in',config(),client=client,repair_records=[previous])
        judge.run_judge(run_dir,tmp_path/'transport-three-3',replace(config(),timeout=600),client=client,
                        repair_records=[previous],max_transport_retries=3)
    assert payloads[0]==payloads[1]==payloads[2]==payloads[3]
    with pytest.raises(ValueError,match='bounded at three'):
        judge.run_judge(run_dir,tmp_path/'transport-fourth-rejected',replace(config(),timeout=600),
                        repair_records=[tmp_path/'transport-three-3/tasks/PFI2-033-clean.json'],max_transport_retries=3)
