"""Each control comparison must retain its own matched task set and missing grades."""
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_mineru_sections_20261030 as report


def row(points=1,flag=False):
    return dict(point_mean=points,reference_concern=flag,support_counts={'supported':1},
        supported_citations=1,factual_citations=1,complete_groups=1,factual_claims=1,boundary=2,all_five_pass=points==1)


def test_control_sets_do_not_silently_share_different_denominators():
    ids=['A','B','C']
    metrics={(k,s,t):row() for k in ['luna','jev'] for s in ['native','sections','pymupdf'] for t in ids}
    del metrics[('jev','native','A')]
    del metrics[('jev','pymupdf','B')]
    metrics[('luna','sections','C')]=row(flag=True)
    metrics[('jev','sections','C')]=row(.5)
    native=report.paired(metrics,ids,'native')
    pymupdf=report.paired(metrics,ids,'pymupdf')
    assert native['jev']['task_ids']==['B','C']
    assert pymupdf['jev']['task_ids']==['A','C']
    assert native['luna']['task_ids']==pymupdf['luna']['task_ids']==['A','B']
    assert native['jev']['point_losses']==['C']
    assert native['jev']['scores']['sections']['point_macro_average']==.75
    assert native['jev']['exclusions']==[dict(task_id='A',unavailable=['native'])]


def test_entirely_missing_comparison_is_not_published_as_a_zero_score():
    with pytest.raises(ValueError,match='No valid matched'):
        report.paired({},['A'],'native')
