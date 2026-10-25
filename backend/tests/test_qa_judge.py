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
