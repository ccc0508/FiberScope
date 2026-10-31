"""Archived comparisons must retain paired denominators and reject inconsistent source totals."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import summarize_qa_optimization_history_20261031 as history


def m(point=1,points=1,facts=1,citations=1):
    return dict(point_mean=point,required_point_count=points,required_point_sum=point*points,
        support_counts={'supported':facts} if facts else {},factual_claims=facts,
        factual_citations=citations,supported_citations=citations,complete_groups=facts,
        boundary=2,all_five_pass=point==1,reference_concern=False)


def declared(rows):
    a=history.aggregate(rows)
    return dict(tasks=len(rows),point_macro_average=a['point'],support_counts=a['support_counts'],
        citation_precision={'value':a['citation']},citation_coverage={'value':a['coverage']},
        boundary_mean=a['boundary'],all_five_pass=a['joint_count'])


def fixture(tmp_path):
    base=tmp_path/history.BASE/'synthetic';base.mkdir(parents=True)
    rows=[dict(task_id='PFI2-001',systems={'a':{'metrics':m(0,points=10)},'b':{'metrics':m(1,points=10)}}),
          dict(task_id='PFI2-002',systems={'a':{'metrics':m(1)},'b':{'metrics':m(1)}})]
    pair=dict(task_ids=['PFI2-001','PFI2-002'],scores={s:declared([r['systems'][s]['metrics'] for r in rows]) for s in ['a','b']},
        point_wins=['PFI2-001'],point_losses=[])
    (base/'comparison.json').write_text(json.dumps({'pair':pair}),encoding='utf-8')
    (base/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    return base,rows,pair


def test_macro_mean_is_not_micro_and_citation_rates_keep_actual_denominators():
    first=m(0,points=10);second=m(1,points=1,facts=3,citations=3)
    second['supported_citations']=2
    result=history.aggregate([first,second])
    assert result['point']==.5 and result['point']!=1/11
    assert result['citation']==3/4 and result['citation_counts']==[3,4]
    assert result['joint_count']==1


def test_no_facts_or_citations_is_not_published_as_perfect_support():
    row=m(facts=0,citations=0);a=history.aggregate([row]);q=history.per_question(row)
    assert a['fact'] is a['citation'] is a['coverage'] is None
    assert q['fact'] is q['citation'] is q['coverage'] is None
    assert a['joint']==1  # Preserve the archived joint rule; don't silently add a sixth rule.


def test_same_pairs_are_recomputed_and_unavailable_tasks_remain_excluded(tmp_path):
    base,rows,pair=fixture(tmp_path);before=deepcopy(rows)
    r=history.load_pair(tmp_path,'synthetic','a','b','pair')
    assert r['tasks']==2 and r['directions']['point']['up']==['PFI2-001']
    assert len(r['excluded_task_ids'])==30 and 'PFI2-003' in r['excluded_task_ids']
    assert rows==before and r['scores']['a']['point']==.5
    assert r['deltas']['point']==.5


@pytest.mark.parametrize('fault',['aggregate','task_set','missing_grade','point_direction'])
def test_tampered_or_incompatible_archive_cannot_be_summarized(tmp_path,fault):
    base,rows,pair=fixture(tmp_path)
    if fault=='aggregate':pair['scores']['a']['point_macro_average']=.9
    elif fault=='task_set':pair['task_ids'].append('PFI2-003')
    elif fault=='missing_grade':rows[0]['systems']['a']['metrics']=None
    else:pair['point_wins']=[]
    (base/'comparison.json').write_text(json.dumps({'pair':pair}),encoding='utf-8')
    (base/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    with pytest.raises(ValueError):history.load_pair(tmp_path,'synthetic','a','b','pair')
