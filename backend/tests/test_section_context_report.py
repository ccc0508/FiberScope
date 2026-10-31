"""Context A/B allows different excerpts, preserves missing grades, and escapes source text."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'backend/tests'))
import report_section_context_20261031 as report
from test_answer_guidance_report import payload as make_payload


def payload():
    p=make_payload(tuple(f'PFI2-{i:03}' for i in range(1,33)))
    p['controls'].update(same_primary_hits=True,same_107_block_index=True)
    p['traces']={a:{f'PFI2-{i:03}':dict(source_chunks=[a+str(i)],context=dict(context_chars=100,budget_limited=False))
        for i in range(1,33)} for a in report.ARMS}
    p['analyst_notes']=[];p['limitations']=report.LIMITATIONS
    for r in p['records']:
        if r['arm']=='guidance':r['candidate']['available_context']['texts']=['Different expanded original source']
    return p


def test_missing_is_excluded_not_zero_and_expanded_excerpts_may_differ():
    p=payload();row=p['records'][0];row['review']=None;row['metrics']=None;row['grading_status']='invalid_scorecard'
    original=deepcopy(p);r=report.analyze(p)
    assert r['comparison']['tasks']==31 and len(r['comparison']['exclusions'])==1
    assert r['context_diagnostics']['guidance']['different_sources_from_other_arm']==32
    assert r['missing_not_zero'] and p==original
    p['controls']['same_primary_hits']=False
    with pytest.raises(ValueError):report.analyze(p)


def test_imported_but_unselected_dsh_answers_are_excluded_and_duplicates_fail():
    jobs=[dict(system=s,task_id=f'PFI2-{i:03}') for s in ['dsh','rag'] for i in range(1,33)]
    chosen=report.selected_jobs(jobs)
    assert len(chosen)==32 and all(j['system']=='rag' for j in chosen)
    with pytest.raises(ValueError):report.selected_jobs(jobs+[dict(system='rag',task_id='PFI2-001')])


def test_html_retains_32_pairs_and_original_labels_escapes_script_and_refuses_overwrite(tmp_path):
    p=payload();p['records'][0]['candidate']['answer']='<script>alert(1)</script>'
    private=tmp_path/'private';private.mkdir();(tmp_path/'docs').mkdir()
    (private/'analysis-input.json').write_text(json.dumps(p),encoding='utf-8')
    r=report.publish(tmp_path,private)
    assert r['common_tasks']==32 and r['provider_calls']==0
    dest=tmp_path/'data/literature/qa-evaluation/reports'/report.TAG
    text=(dest/'comparison.html').read_text('utf-8')
    assert text.count('<article data-search=')==32
    assert '<script>alert(' not in text and '&lt;script&gt;alert(' in text
    rows=[json.loads(line) for line in (dest/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]
    assert len(rows)==32 and all(len(r['records'])==2 for r in rows)
    with pytest.raises(ValueError):report.publish(tmp_path,private)
