"""Evidence coverage counts reviewed facts, with exact source identities."""
import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('evidence_audit',Path(__file__).parents[2]/'scripts/audit_reranker_evidence.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_two_different_sources_can_jointly_cover_a_comparison():
    point=dict(atoms=[dict(candidates=[2,5]),dict(candidates=[9])])
    assert audit.score_point(point,{5,9})==1
    assert audit.score_point(point,{5})==.5


def test_same_page_or_related_topic_does_not_substitute_for_reviewed_fact():
    point=dict(atoms=[dict(candidates=[3])])
    assert audit.score_point(point,{0,1,2})==0


def test_partial_evidence_does_not_become_complete_when_all_candidates_selected():
    point=dict(atoms=[dict(candidates=[],partial_candidates=[4])])
    assert audit.score_point(point,set(range(50)))==.5
    assert audit.failure_stage(0,.5)=='candidate_pool_incomplete_and_rerank_loss'


def test_response_behavior_is_not_mislabeled_as_missing_paper_evidence():
    point=dict(atoms=[],not_applicable='Only answer style')
    assert audit.score_point(point,set()) is None


def test_distinguish_pool_missing_and_reranker_omission():
    assert audit.failure_stage(0,0)=='missing_from_frozen_candidate_pool'
    assert audit.failure_stage(.5,1)=='rerank_omitted_available_evidence'
    assert audit.failure_stage(1,1)=='covered'


def test_annotation_pool_identity_is_required_before_applying_indices():
    with pytest.raises(ValueError,match='different frozen pool'):
        audit.validate_annotations(dict(rows=[]),{},dict(frozen_pool_sha256='other'),{})


def test_silent_empty_annotations_cannot_count_as_full_coverage():
    with pytest.raises(ValueError,match='at least one'):
        audit.score_point(dict(atoms=[]),set())
