"""End-to-end reports allow different retrieved evidence and preserve all missing judgments."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'backend/tests'))
import report_full_stack_20261031 as report
from test_answer_guidance_report import payload as make_payload


def data():
    p=make_payload(tuple(f'PFI2-{i:03}' for i in range(1,33)))
    p['controls']['execution_mode']='live_retrieval_normal_worker'
    p['traces']={arm:{r['task_id']:{'rerank_calls':1 if arm=='guidance' else 0} for r in p['records'] if r['arm']==arm} for arm in ['control','guidance']}
    for r in p['runtimes']:r['embedding_known_tokens']=32
    p['accounting']['jev']={'reported_cost_usd':'0.1','calls':64}
    p['limitations']=report.LIMITATIONS
    for r in p['records']:
        if r['arm']=='guidance':r['candidate']['available_context']['texts']=['Different live retrieval '+r['task_id']]
    return p


def test_different_live_retrieval_is_allowed_and_missing_grades_not_zero_filled():
    p=data();before=deepcopy(p);r=p['records'][0];r['review']=None;r['metrics']=None;r['grading_status']='invalid_scorecard'
    result=report.analyze(p)
    assert result['comparison']['tasks']==31 and len(result['comparison']['exclusions'])==1
    assert result['missing_not_zero'] and result['no_weighted_total_score']
    assert p['records'][1:]==before['records'][1:]


def test_export_contains_all_pairs_sources_correct_live_labels_and_safe_model_text(tmp_path):
    p=data();p['records'][0]['candidate']['answer']='<script>alert(1)</script>'
    out=tmp_path/'private';out.mkdir();(tmp_path/'docs').mkdir()
    (out/'analysis-input.json').write_text(json.dumps(p),encoding='utf-8')
    r=report.publish(tmp_path,out)
    assert r['common_tasks']==32 and r['provider_calls']==0
    dest=tmp_path/'data/literature/qa-evaluation/reports/full-stack-20261031'
    text=(dest/'comparison.html').read_text('utf-8')
    assert text.count('<article data-search=')==32 and '全部既有优化叠加' in text
    assert '<script>alert(' not in text and '&lt;script&gt;alert(' in text
    assert '原提示词与新提示词' not in text and '固定证据回放' in text
    rows=[json.loads(s) for s in (dest/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]
    assert len(rows)==32 and all(len(s['records'])==2 for s in rows)
    report.publish(tmp_path,out,refresh=True)
    (dest/'comparison.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):report.publish(tmp_path,out,refresh=True)
