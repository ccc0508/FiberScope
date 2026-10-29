"""A reported parser comparison must pair the same questions within each judge."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import report_mineru_rag_20261029 as report


def metric(points=1, flagged=False):
    return dict(point_mean=points, reference_concern=flagged,
                support_counts={'supported': 1}, supported_citations=1,
                factual_citations=1, complete_groups=1, factual_claims=1,
                boundary=2, all_five_pass=points == 1)


def test_missing_or_flagged_grade_never_changes_only_one_side_of_a_pair():
    ids = ['A', 'B', 'C', 'D']
    rows = {(kind, system, tid): metric()
            for kind in ['luna', 'jev']
            for system in ['pymupdf', 'mineru'] for tid in ids}
    del rows[('luna', 'mineru', 'B')]
    rows[('luna', 'pymupdf', 'C')] = metric(flagged=True)
    rows[('jev', 'mineru', 'D')] = metric(flagged=True)
    rows[('luna', 'pymupdf', 'A')] = metric(.5)
    rows[('jev', 'mineru', 'B')] = metric(.5)

    actual = report.aggregate_primary(rows, ids)

    assert actual['luna']['task_ids'] == ['A', 'D']
    assert actual['jev']['task_ids'] == ['A', 'B', 'C']
    assert actual['luna']['point_wins'] == ['A']
    assert actual['jev']['point_losses'] == ['B']
    for paired in actual.values():
        assert {s['tasks'] for s in paired['scores'].values()} == {len(paired['task_ids'])}
    assert actual['luna']['scores']['pymupdf']['point_macro_average'] == .75
    assert actual['luna']['scores']['mineru']['point_macro_average'] == 1


def test_no_valid_paired_questions_fails_instead_of_reporting_zero():
    with pytest.raises(ValueError, match='No valid primary'):
        report.aggregate_primary({}, ['A'])


def test_temporary_report_configuration_restores_after_failure():
    module = SimpleNamespace(RUN='original')
    with pytest.raises(RuntimeError):
        with report.override(module, RUN='experiment'):
            assert module.RUN == 'experiment'
            raise RuntimeError('stop')
    assert module.RUN == 'original'
