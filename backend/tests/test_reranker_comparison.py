"""Verify comparison metrics and response/index boundaries without API calls."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('reranker_comparison', Path(__file__).parents[2] / 'scripts/compare_rerankers.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def test_scores_align_provider_indexes_to_immutable_input_order():
    assert comparison.score_vector([{'index': 1, 'relevance_score': .9}, {'index': 0, 'relevance_score': .2}], 2) == [.2, .9]


@pytest.mark.parametrize('results', [
    [{'index': 0, 'relevance_score': .9}, {'index': 0, 'relevance_score': .2}],
    [{'index': True, 'relevance_score': .9}, {'index': 0, 'relevance_score': .2}],
    [{'index': 0, 'relevance_score': float('nan')}, {'index': 1, 'relevance_score': .2}],
    [{'index': 0, 'relevance_score': .9}],
])
def test_incomplete_or_ambiguous_provider_rankings_are_not_scored(results):
    with pytest.raises(ValueError):
        comparison.score_vector(results, 2)


def test_page_proxy_separates_missing_recall_from_ranking_loss():
    row = dict(reference_locations=[dict(document_id='A', pages=[1, 2, 3])], candidates=[
        dict(document_id='B', page_start=1, page_end=1),
        dict(document_id='A', page_start=1, page_end=1),
        dict(document_id='A', page_start=2, page_end=2),
    ])
    metrics = comparison.location_metrics(row, [1, 0, 2], k=1)
    assert metrics['reference_page_coverage'] == 1/3
    assert metrics['available_reference_page_retention'] == 1/2
    assert metrics['missing_locations'] == [('A', 2), ('A', 3)]
    assert metrics['reference_page_ndcg'] == 1


def test_no_relevant_location_is_not_reported_as_perfect_ranking():
    row = dict(reference_locations=[dict(document_id='A', pages=[1])],
        candidates=[dict(document_id='B', page_start=1, page_end=1)])
    metrics = comparison.location_metrics(row, [0])
    assert metrics['reference_page_coverage'] == 0
    assert metrics['available_reference_page_retention'] is None
    assert metrics['reference_page_ndcg'] is None


def test_frozen_inputs_cannot_silently_reuse_scores_after_change(tmp_path):
    from argparse import Namespace
    args = Namespace(output=tmp_path)
    comparison.write(tmp_path / 'calls/bge/FS8-001.json', dict(input_sha256='original', status='completed'))
    with pytest.raises(ValueError, match='frozen input changed'):
        comparison.request_one(args, 'bge', dict(id='FS8-001', input_sha256='different'))


def test_jev_does_not_receive_gold_or_other_candidates_and_transient_retry_is_archived(tmp_path, monkeypatch):
    from argparse import Namespace
    args = Namespace(output=tmp_path, retry_transient=True)
    row = dict(id='FS8-001', input_sha256='frozen', question='Which material?',
        candidates=[dict(text='Target evidence'),dict(text='Other candidate')],
        reference_answer='GOLD ANSWER', reference_locations=[dict(document_id='SECRET_GOLD',pages=[9])])
    path = tmp_path/'calls/jev/FS8-001-000.json'
    original = dict(input_sha256='frozen',status='failed',error_type='ReadError',api_calls=1)
    comparison.write(path,original)
    requests=[]
    class Response:
        status_code=200
        def json(self):
            return dict(model='typesafe/jev-1.14',answers=dict(relevance=dict(type='score',score=3)))
        def raise_for_status(self):
            pass
    class Client:
        def __init__(self,**kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def post(self,*args,**kwargs):
            requests.append(kwargs['json'])
            return Response()
    monkeypatch.setattr(comparison,'credentials',lambda *args:('https://example.invalid','dummy-private-key'))
    monkeypatch.setattr(comparison.httpx,'Client',Client)
    result=comparison.request_one(args,'jev',row,0)
    assert result['status']=='completed' and result['score']==1
    assert comparison.read(tmp_path/'attempts/jev/FS8-001-000-original-failure.json')==original
    assert requests[0]['state']==dict(query='Which material?',passage='Target evidence')
    assert 'GOLD' not in str(requests[0]) and 'Other candidate' not in str(requests[0])
    # Successful cached results never cause a second paid call.
    assert comparison.request_one(args,'jev',row,0)==result
    assert len(requests)==1
