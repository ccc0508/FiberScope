"""Fixed-pair stability arithmetic, missing grades, source preservation and safe HTML."""
from copy import deepcopy
import json
from math import sqrt
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_rerank_stability_20261031 as report


def review(point=1,flagged=False,facts=True):
    return dict(key_point_scores={'P1':point},
        claim_assessments=[dict(id='C1',text='A source-backed statement',claim_type='fact',support='supported')] if facts else [],
        citation_assessments=[dict(claim_id='C1',ref='[1]',score=1)] if facts else [],
        citation_group_assessments=[dict(claim_id='C1',coverage='complete')] if facts else [],
        answerability_score=2,reference_concern=flagged)


def payload(tids=('A','B','C')):
    rows=[]
    for tid in tids:
        case=dict(id=tid,question='Question '+tid,reference_answer='Reference '+tid,
            key_points=[dict(id='P1',text='Required point',optional=False,capability='text')])
        for r in report.ROUNDS:
            for s in report.SYSTEMS:
                point=([0,.5,1] if s=='content' else [.5,1,1])[r-1] if tid=='A' else 1
                judge=review(point)
                if (s,r,tid)==('content',1,'B'):judge=None
                if (s,r,tid)==('rerank',2,'C'):judge=review(flagged=True)
                rows.append(dict(system=s,round=r,task_id=tid,reference_case=deepcopy(case),candidate={'answer':'Original '+s},
                    review=judge,metrics=None,grading_status='invalid_scorecard' if judge is None else 'completed'))
    return dict(version='rerank-stability-v1',records=rows,
        runtimes=[dict(system=s,round=r,median_end_to_end_seconds=(10 if s=='content' else 12)+r,
            generation_calls=32,generation_known_tokens={'total_tokens':100*r}) for r in report.ROUNDS for s in report.SYSTEMS],
        accounting={'new':{'reported_cost_usd':'0.123','cost_unknown_calls':1},'historical':{'reused':True}},
        controls={'same_prompt':True},provenance={'frozen_source':'same'},limitations=['Caller-provided limitation'])


def row(data,system,round_id,tid):
    return next(r for r in data['records'] if (r['system'],r['round'],r['task_id'])==(system,round_id,tid))


def test_fixed_six_cell_subset_prevents_changing_denominators_from_becoming_stability():
    result=report.analyze(payload())
    fixed=result['fixed_common']
    assert fixed['task_ids']==['A']
    assert [r['tasks'] for r in result['per_round_maximum_pairs']]==[2,2,3]
    assert [r['task_ids'] for r in fixed['rounds']]==[['A']]*3
    assert fixed['by_system']['content']['point_macro_average']['values']==[0,.5,1]
    assert fixed['by_system']['content']['point_macro_average']['mean']==.5
    assert fixed['by_system']['content']['point_macro_average']['sample_sd']==.5
    delta=fixed['deltas']['point_macro_average']
    assert delta['values']==[.5,.5,0]
    assert delta['mean']==pytest.approx(1/3)
    assert delta['sample_sd']==pytest.approx(sqrt(1/12))
    assert fixed['point_direction_counts']==dict(higher=2,equal=1,lower=0)
    assert result['missing_not_zero'] and result['no_weighted_grand_score']


def test_missing_and_reference_flagged_grades_are_not_counted_as_failures():
    result=report.analyze(payload())
    by={r['task_id']:r for r in result['questions']}
    b=by['B']['systems']['content'];c=by['C']['systems']['rerank']
    assert b['valid_rounds']==[2,3] and b['point_scores']==[None,1,1]
    assert b['all_five_passes']==2 and b['non_pass_rounds']==[]
    assert c['point_scores']==[1,None,1] and c['missing_or_flagged_rounds']==[2]
    assert c['recurrent_failure_dimensions']=={}
    a=by['A']['systems']['content']
    assert a['recurrent_failure_dimensions']=={'key_points':2}
    assert 'invalid_scorecard' in json.dumps(result['fixed_common']['exclusions'])


@pytest.mark.parametrize('corruption',['duplicate','missing_record','changed_reference','fake_metrics','unexpected_round'])
def test_input_guard_rejects_omitted_cells_or_changes_to_reference_and_grades(corruption):
    data=payload(('A',))
    if corruption=='duplicate':data['records'].append(deepcopy(data['records'][0]))
    elif corruption=='missing_record':data['records'].pop()
    elif corruption=='changed_reference':data['records'][0]['reference_case']['reference_answer']='Changed'
    elif corruption=='fake_metrics':data['records'][0]['metrics']={'point_mean':1}
    else:data['records'][0]['round']=4
    with pytest.raises(ValueError):report.analyze(data)


def test_zero_denominator_and_single_observation_remain_unknown():
    data=payload(('A',))
    for r in data['records']:r['review']=review(facts=False)
    result=report.analyze(data)
    for s in report.SYSTEMS:
        stat=result['fixed_common']['by_system'][s]['citation_precision_rate']
        assert stat['values']==[None,None,None] and stat['mean'] is None and stat['n']==0
    assert report.series([None,2,None])['sample_sd'] is None
    with pytest.raises(ValueError):report.series([float('nan')])


def test_no_fixed_common_questions_displays_unknown_without_fabricating_zero_score():
    data=payload(('B',))
    result=report.analyze(data)
    assert result['fixed_common']['tasks']==0
    assert result['fixed_common']['by_system']['content']['point_macro_average']['mean'] is None
    assert result['fixed_common']['rounds'][0]['scores']['content'] is None


def test_sensitivity_omits_pfi2_011_symmetrically_without_changing_primary_or_original_grade():
    data=payload(('PFI2-011','A'))
    original=deepcopy(data)
    result=report.analyze(data)
    assert result['fixed_common']['task_ids']==['A','PFI2-011']
    assert result['sensitivity_without_pfi2_011']['task_ids']==['A']
    assert data==original
    assert any('原分不改' in c for c in result['limitations'])


def test_historical_missing_cases_and_runtime_cache_limitations_are_explicit():
    data=payload(('PFI2-023','PFI2-024'))
    row(data,'content',1,'PFI2-024')['review']=None
    row(data,'rerank',1,'PFI2-023')['review']=None
    result=report.analyze(data)
    notes='\n'.join(result['limitations'])
    assert 'PFI2-023' in notes and 'PFI2-024' in notes and '缓存' in notes
    assert result['runtime']['content']['median_end_to_end_seconds']['values']==[11,12,13]
    assert result['runtime']['median_latency_delta_seconds']['values']==[2,2,2]
    assert result['accounting']==data['accounting']


def test_already_excluded_caveat_question_is_not_presented_as_new_sensitivity_removal():
    data=payload(('PFI2-011','A'))
    row(data,'content',2,'PFI2-011')['review']=None
    result=report.analyze(data)
    assert result['fixed_common']['task_ids']==['A']
    assert result['sensitivity_without_pfi2_011'] is None
    assert any('已因缺失' in c for c in result['limitations'])


def test_safe_html_contains_all_six_original_answers_missing_label_and_search(tmp_path):
    data=payload(('A','B'))
    row(data,'rerank',3,'A')['candidate']['answer']='<script>alert("unsafe")</script>'
    result=report.analyze(data)
    p=tmp_path/'comparison.html';report.html_report(p,result,data);text=p.read_text('utf-8')
    assert '<script>alert(' not in text and '&lt;script&gt;alert(' in text
    assert text.count('<article data-search=')==2
    assert '有效评分缺失' in text and '逐项判定（原样保留）' in text
    assert '固定共同题' in text and '样本SD' in text and '第3轮' in text and 'id="search"' in text


def test_publish_reproduces_arithmetic_and_rejects_tampered_report(tmp_path):
    data=payload(('A',));source=tmp_path/'input.json';source.write_text(json.dumps(data),encoding='utf-8')
    output=tmp_path/'report';document=tmp_path/'report.md'
    result=report.publish(source,output,document)
    assert result['model_calls_by_reporter']==0
    seal=json.loads((output/'publication.json').read_text('utf-8'))
    assert 'publication.json' not in seal['files'] and seal['model_calls']==0
    exported=[json.loads(x) for x in (output/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]
    assert len(exported)==1 and len(exported[0]['records'])==6
    report.publish(source,output,document,refresh=True)
    (output/'comparison.html').write_text('tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):report.publish(source,output,document,refresh=True)
