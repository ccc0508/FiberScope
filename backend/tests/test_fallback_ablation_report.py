from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'backend/tests'))
import report_fallback_ablation_20261031 as report
from test_section_context_report import payload


def data():
    p=payload();affected=[f'PFI2-{i:03}' for i in range(1,11)];unchanged=[f'PFI2-{i:03}' for i in range(11,33)]
    p['controls'].update(no_budget_redistribution=True,same_group_count_refs_and_primary=True,affected_tasks=affected,unaffected_tasks=unchanged)
    for row in p['records']:
        if row['task_id'] in unchanged:row['candidate']['available_context']['texts']=['Identical frozen text '+row['task_id']]
    return p


def test_changed_and_unchanged_inputs_reported_separately_and_contract_checked():
    p=data();r=report.analyze(p)
    assert r['affected_comparison']['tasks']==10 and r['unchanged_input_comparison']['tasks']==22
    p['records'][-1]['candidate']['available_context']['texts']=['unexpected text']
    with pytest.raises(ValueError):report.analyze(p)


def test_report_contains_both_subgroups_and_no_false_regrouping_claim(tmp_path):
    p=data();r=report.analyze(p);out=tmp_path/'report.html';report.render(out,r,p);text=out.read_text('utf-8')
    assert text.count('<article data-search=')==32
    assert '输入完全相同的题目（波动观察）' in text and '实际删块的题目' in text
    assert '仅删除原25次回退' in text
