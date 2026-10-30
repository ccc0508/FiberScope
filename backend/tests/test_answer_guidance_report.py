"""Fixed-evidence A/B arithmetic, semantic-label preservation and unsafe text rendering."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_answer_guidance_20261031 as report


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
        for arm in report.ARMS:
            judge=review(.5 if arm=='control' and tid=='A' else 1)
            if (arm,tid)==('control','B'):judge=None
            if (arm,tid)==('guidance','C'):judge=review(flagged=True)
            rows.append(dict(arm=arm,task_id=tid,reference_case=deepcopy(case),
                candidate=dict(answer='Original '+arm,claims=[dict(text='Source statement')],citations=[dict(ref='[1]')],
                    available_context=dict(kind='supplied_excerpts',texts=['Original evidence '+tid,'Additional evidence'])),
                review=judge,metrics=None,grading_status='invalid_scorecard' if judge is None else 'completed',
                answer_status='answered',input_evidence_sha256='a'*64))
    return dict(version='synthetic-ab-v1',records=rows,
        runtimes=[dict(arm=arm,generation_calls=32,generation_known_tokens={'total_tokens':123},median_end_to_end_seconds=12) for arm in report.ARMS],
        accounting={'new':{'reported_cost_usd':'0.123','cost_unknown_calls':1}},
        controls={'generation_settings':{arm:{'llm_model':'fixed','top_k':8,'min_score':.35} for arm in report.ARMS}},
        provenance={'frozen_source':'same'},limitations=['Caller-provided limitation'])


def row(data,arm,tid):return next(r for r in data['records'] if r['arm']==arm and r['task_id']==tid)


def test_maximum_common_pairs_preserve_missing_and_flagged_grades_without_zero_filling():
    data=payload();original=deepcopy(data);r=report.analyze(data)
    c=r['comparison']
    assert c['task_ids']==['A'] and c['tasks']==1
    assert c['scores']['control']['point_macro_average']==.5 and c['scores']['guidance']['point_macro_average']==1
    assert c['deltas']['point_macro_average']==.5 and c['point_wins']==['A']
    assert c['all_five_wins']==['A'] and c['all_five_losses']==[]
    assert len(c['exclusions'])==2 and 'invalid_scorecard' in json.dumps(c['exclusions'])
    assert data==original and r['missing_not_zero'] and r['no_weighted_grand_score']


def test_report_checks_supplied_evidence_context_and_locator_fingerprints():
    data=payload(('A',));r=report.analyze(data)
    proof=r['evidence_controls']['per_question'][0]
    assert r['evidence_controls']['all_supplied_contexts_identical'] and r['evidence_controls']['generation_settings_equal']
    assert proof['excerpt_count']==2 and proof['source_chars']==len('Original evidence AAdditional evidence')
    assert len(proof['available_context_sha256'])==64 and proof['full_input_evidence_sha256']=='a'*64


@pytest.mark.parametrize('change',['text','order','scope','context_missing','locator','one_locator_missing','model'])
def test_fixed_evidence_or_model_changes_cannot_be_presented_as_prompt_only(change):
    data=payload(('A',));guided=row(data,'guidance','A');context=guided['candidate']['available_context']
    if change=='text':context['texts'][0]='Changed source'
    elif change=='order':context['texts'].reverse()
    elif change=='scope':context['kind']='supplied_document'
    elif change=='context_missing':guided['candidate'].pop('available_context')
    elif change=='locator':guided['input_evidence_sha256']='b'*64
    elif change=='one_locator_missing':guided.pop('input_evidence_sha256')
    else:data['controls']['generation_settings']['guidance']['llm_model']='different'
    with pytest.raises(ValueError):report.analyze(data)


@pytest.mark.parametrize('change',['duplicate','missing_record','reference','fake_metrics','arm'])
def test_record_contract_rejects_changed_references_fabricated_metrics_and_missing_cells(change):
    data=payload(('A',))
    if change=='duplicate':data['records'].append(deepcopy(data['records'][0]))
    elif change=='missing_record':data['records'].pop()
    elif change=='reference':data['records'][0]['reference_case']['reference_answer']='Different gold'
    elif change=='fake_metrics':data['records'][0]['metrics']={'point_mean':1}
    else:data['records'][0]['arm']='unplanned'
    with pytest.raises(ValueError):report.analyze(data)


def test_unsupported_labels_boundary_regressions_and_program_refusals_are_counted_not_rejudged():
    data=payload(('A','D'));guided=row(data,'guidance','A')
    guided['review']['claim_assessments'][0]['support']='unsupported'
    guided['review']['answerability_score']=1
    refused=row(data,'guidance','D');refused['answer_status']='refused';refused['reason_code']='citation_validation_failed'
    refused['review']=review(.5,facts=False);refused['review']['answerability_score']=0
    r=report.analyze(data)
    assert r['risks']['new_unsupported_or_contradicted_questions']==['A']
    assert r['risks']['new_program_refusals']==['D'] and r['risks']['new_boundary_regressions']==['A','D']
    assert r['risks']['by_arm']['guidance']['factual_labels']=={'unsupported':1}
    assert r['output_diagnostics']['guidance']['answer_statuses']=={'answered':1,'refused':1}
    assert row(data,'guidance','A')['review']['claim_assessments'][0]['support']=='unsupported'


def test_unknown_answer_state_is_not_inferred_from_refusal_wording():
    data=payload(('A',));guided=row(data,'guidance','A');guided.pop('answer_status');guided['candidate']['answer']='无法回答。'
    r=report.analyze(data)
    assert r['risks']['new_program_refusals']==[]
    assert r['output_diagnostics']['guidance']['answer_statuses']=={'unknown':1}


def test_zero_claim_or_citation_denominators_remain_unknown():
    data=payload(('A',))
    for r in data['records']:r['review']=review(facts=False)
    result=report.analyze(data)
    for arm in report.ARMS:
        s=result['comparison']['scores'][arm]
        assert s['fact_support_rate'] is None and s['citation_precision_rate'] is None and s['citation_coverage_rate'] is None
    assert result['comparison']['deltas']['citation_precision_rate'] is None


def test_no_common_grades_produces_unknown_not_fabricated_score():
    r=report.analyze(payload(('B','C')))
    assert r['comparison']['tasks']==0 and r['comparison']['scores']['guidance'] is None
    assert r['comparison']['deltas']['point_macro_average'] is None
    assert '无法比较' in r['conclusion']


def test_sensitivity_removes_pfi2_011_symmetrically_and_preserves_original_judgment():
    data=payload(('PFI2-011','A'));before=deepcopy(data)
    result=report.analyze(data)
    assert result['comparison']['task_ids']==['A','PFI2-011']
    assert result['sensitivity_without_pfi2_011']['task_ids']==['A'] and data==before
    assert any('历史第11题' in c for c in result['limitations'])


def test_html_preserves_both_answers_missing_label_search_and_escapes_model_text(tmp_path):
    data=payload(('A','B'));row(data,'guidance','A')['candidate']['answer']='<script>alert("unsafe")</script>'
    p=tmp_path/'report.html';result=report.analyze(data);report.html_report(p,result,data);text=p.read_text('utf-8')
    assert '<script>alert(' not in text and '&lt;script&gt;alert(' in text
    assert text.count('<article data-search=')==2 and 'id="search"' in text
    assert '有效评分缺失' in text and 'Jev逐项判定（原样保留）' in text
    assert '完整RAG端到端' in text and '不生成自由文字理由' in text


def test_publish_produces_sealed_outputs_and_rejects_tampering(tmp_path):
    data=payload(('A',));source=tmp_path/'input.json';source.write_text(json.dumps(data),encoding='utf-8')
    output=tmp_path/'report';document=tmp_path/'report.md';r=report.publish(source,output,document)
    assert r['model_calls_by_reporter']==0
    seal=json.loads((output/'publication.json').read_text('utf-8'))
    assert seal['model_calls']==0 and 'publication.json' not in seal['files']
    exported=[json.loads(l) for l in (output/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]
    assert len(exported)==1 and len(exported[0]['records'])==2
    report.publish(source,output,document,refresh=True)
    (output/'evidence-controls.json').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):report.publish(source,output,document,refresh=True)
