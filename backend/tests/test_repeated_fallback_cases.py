from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from report_repeated_fallback_cases_20261031 import analyze,ARMS,TASKS,TARGETS


def data():
    return dict(version='test',records=[dict(task_id=t,arm=a,round=r,evidence_sha256=a+t,
        review=dict(key_point_scores={TARGETS[t]:1}),generation_calls=[],latency_ms=1000)
        for t in TASKS for a in ARMS for r in range(1,6)],controls=dict(old_answers_included=False,fresh_answers=20),
        accounting={},provenance={})


def test_partial_missing_and_unknown_count_separately_and_missing_not_zero_filled():
    p=data();p['records'][0]['review']['key_point_scores']['P3']=.5
    p['records'][1]['review']['key_point_scores']['P3']=0;p['records'][2]['review']=None
    s=analyze(p)['summaries'][0]
    assert (s['complete'],s['partial'],s['missing'],s['unknown'])==(2,1,1,1)
    assert s['incomplete_rate']==2/4 and s['strict_missing_rate']==1/4


@pytest.mark.parametrize('change',['duplicate','old','context'])
def test_changed_coverage_context_or_old_rounds_rejected(change):
    p=data()
    if change=='duplicate':p['records'][-1]=p['records'][0]
    elif change=='old':p['controls']['old_answers_included']=True
    else:p['records'][0]['evidence_sha256']='changed'
    with pytest.raises(ValueError):analyze(p)
