from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'backend/tests'))
import report_role_context_20261031 as report
from test_section_context_report import payload


def data():
    p=payload();p['controls'].update(same_original_primary_spans=True,same_vector_index_claimed=False)
    for arm in report.ARMS:
        for v in p['traces'][arm].values():v['context']['decisions']=[{'mode':'metadata_standalone'}]
    p['analyst_notes']=[];return p


def test_missing_scores_stay_missing_and_changed_primary_span_controls_are_rejected():
    p=data();r=p['records'][0];r['review']=None;r['metrics']=None
    result=report.analyze(p);assert result['comparison']['tasks']==31 and result['missing_not_zero']
    p['controls']['same_original_primary_spans']=False
    with pytest.raises(ValueError):report.analyze(p)


def test_html_uses_new_labels_and_does_not_claim_identical_index(tmp_path):
    p=data();r=report.analyze(p);path=tmp_path/'comparison.html'
    report.render(path,r,p);text=path.read_text('utf-8')
    assert text.count('<article data-search=')==32 and '分类后113块' in text
    assert '同一107块索引' not in text and '同页前后邻块' not in text
