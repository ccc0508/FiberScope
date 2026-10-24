"""Verify aggregation contracts without models, original PDFs or private run data."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
saved_path = sys.path[:]
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('summarize_qa_eval', SCRIPTS / 'summarize_qa_eval.py')
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
finally:
    sys.path[:] = saved_path


def test_absent_denominator_is_unknown_not_perfect():
    assert summary.ratio(0, 0) == {'numerator': 0, 'denominator': 0, 'value': None}


def test_nearest_rank_p95_is_explicit():
    assert summary.percentile_nearest_rank(list(range(1, 31)), .95) == 29
    assert summary.percentile_nearest_rank([], .95) is None


@pytest.fixture
def reviewed(tmp_path):
    (tmp_path / 'dataset').mkdir()
    (tmp_path / 'results').mkdir()
    case = {'id': 'PFI-001', 'category': 'factual', 'question': 'fixture question', 'expected_behavior': 'answer',
            'key_points': [{'id': 'P1', 'kind': 'direct'}]}
    (tmp_path / 'dataset/cases.jsonl').write_text(json.dumps(case) + '\n', encoding='utf-8')
    summary.write_json(tmp_path / 'dataset/manifest.json', {'dataset_id': 'fixture', 'rubric_id': 'fixture'})
    metadata = {'run_id': 'fixture', 'source_commit': 'fixture', 'baseline_id': 'fixture', 'dataset_manifest_sha256': 'fixture'}
    summary.write_json(tmp_path / 'run.json', metadata)
    claim = {'text': 'fixture fact', 'citation_refs': ['[1]']}
    response = {'claims': [claim], 'retrieved_evidence': [{'ref': '[1]', 'chunk_id': 'chunk-1'}],
                'generation_calls': [{'usage': None}], 'embedding_usage': None}
    result = {'run_id': 'fixture', 'case_id': case['id'], 'question': case['question'], 'status': 'answered',
              'response': response, 'end_to_end_ms': 7000}
    path = tmp_path / 'results/PFI-001.json'
    summary.write_json(path, result)
    review = {'run_id': 'fixture', 'case_id': case['id'], 'review_status': 'ai_source_reviewed',
              'response_file_sha256': summary.digest(path), 'key_point_scores': {'P1': 1},
              'point_notes': {'P1': 'fixture justification'}, 'answerability_score': 2, 'observed_behavior': 'answer',
              'critical_errors': [], 'retrieval_point_assessments': {'P1': 'complete'}, 'notes': 'fixture review',
              'claim_assessments': [{'id': 'C1', 'text': claim['text'], 'support': 'supported',
                                     'citation_required': True, 'basis': 'fixture source'}],
              'citation_assessments': [{'claim_id': 'C1', 'ref': '[1]', 'chunk_id': 'chunk-1',
                                        'score': 1, 'basis': 'fixture source'}]}
    reviews = tmp_path / 'reviews.jsonl'
    reviews.write_text(json.dumps(review) + '\n', encoding='utf-8')
    return tmp_path, reviews, review


def rewrite_review(path, review):
    path.write_text(json.dumps(review) + '\n', encoding='utf-8')


def test_unknown_token_usage_does_not_become_zero_cost(reviewed):
    folder, reviews, _ = reviewed
    result = summary.summarize(folder, reviews)
    assert result['strict_pass']['value'] == 1
    assert result['generation']['usage_known_calls'] == 0
    assert result['generation']['known_usage_tokens'] is None
    assert result['embedding']['tokens'] is None


def test_missing_citation_assessment_cannot_hide_a_bad_pair(reviewed):
    folder, reviews, review = reviewed
    review['citation_assessments'] = []
    rewrite_review(reviews, review)
    with pytest.raises(ValueError, match='Incomplete citation'):
        summary.summarize(folder, reviews)


def test_bad_extra_citation_prevents_strict_pass_even_with_correct_content(reviewed):
    folder, reviews, review = reviewed
    review['citation_assessments'][0]['score'] = 0
    rewrite_review(reviews, review)
    result = summary.summarize(folder, reviews)
    assert result['point_macro_average'] == 1
    assert result['citation_precision']['value'] == 0
    assert result['strict_pass']['value'] == 0


def test_modified_answer_invalidates_old_review(reviewed):
    folder, reviews, _ = reviewed
    path = folder / 'results/PFI-001.json'
    result = summary.read_json(path)
    result['response']['claims'][0]['text'] = 'changed fact'
    summary.write_json(path, result)
    with pytest.raises(ValueError, match='Reviewed response was changed'):
        summary.summarize(folder, reviews)


def test_failed_api_call_is_not_counted_as_a_correct_refusal(reviewed):
    folder, reviews, _ = reviewed
    path = folder / 'results/PFI-001.json'
    result = summary.read_json(path)
    result['status'] = 'failed'
    summary.write_json(path, result)
    with pytest.raises(ValueError, match='Execution failure cannot'):
        summary.summarize(folder, reviews)


def test_semantic_refusal_is_not_tied_to_api_status_string(reviewed):
    folder, reviews, review = reviewed
    case_path = folder / 'dataset/cases.jsonl'
    case = summary.read_jsonl(case_path)[0]
    case['expected_behavior'] = 'abstain'
    case_path.write_text(json.dumps(case) + '\n', encoding='utf-8')
    review['observed_behavior'] = 'abstain'
    rewrite_review(reviews, review)
    result = summary.summarize(folder, reviews)
    assert result['runtime_status_counts'] == {'answered': 1}
    assert result['abstention_boundary_correct']['value'] == 1
