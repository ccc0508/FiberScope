import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS
import pytest
from literature_rag.application import review_diagnosis_unified as u
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from tests.test_evidence_review import DRAFT,SOURCES
from tests.test_review_edit_binding import edit
from tests.test_corrective_review import requirement,controller


def unit(**changes):
    r=dict(claim_index=0,issue_index=None,replacement_index=None,text=DRAFT.claims[0].text,
        checked=['fact','citation','certainty'],sources=[dict(basis=dict(kind='text',ref='[1]',quote='might be explained by hydration'),contribution='Tentative explanation.')],
        verdict='overstated',reason='Proposed explanation was asserted.',repair_issue_indexes=[0])
    r.update(changes);return r


def payload(units=None):
    issue=edit()
    units=units if units is not None else [unit(),unit(claim_index=None,issue_index=0,replacement_index=0,
        text=issue['replacement_claims'][0]['text'],checked=['fact','citation','relation','certainty'],verdict='supported',repair_issue_indexes=[])]
    return u.parse_response(json.dumps(dict(issues=[issue],requirements=[requirement('edit',issue_indexes=[0])],units=units)))


def run(p):
    s,provider,_=controller([p]);provider.diagnosis_version='v3_unified'
    result=s.review('Q',SOURCES,DRAFT)
    return result,s


def test_single_units_apply_supported_replacement_and_keep_unaffected_claim():
    result,s=run(payload())
    assert result.claims[0].text=='The effect might be explained by hydration.'
    assert result.claims[1]==DRAFT.claims[1]
    t=s.last_trace['rounds'][0]
    assert len(t['units'])==2 and t['claim_checks']==[] and t['relation_checks']==[]
    assert s.last_summary['status']=='completed'


@pytest.mark.parametrize('change',[
    dict(text='wrong original'),dict(issue_index=0),dict(claim_index=99),dict(repair_issue_indexes=[99]),
    dict(sources=[dict(basis=dict(kind='text',ref='[1]',quote='Invented source text'),contribution='claim')]),
    dict(sources=[dict(basis=dict(kind='image',ref='[1]',asset_id='missing',observation='value'),contribution='claim')]),
    dict(checked=['certainty']),
])
def test_invalid_original_cannot_authorize_edit(change):
    p=payload();rows=[x.model_dump() for x in p.units];rows[0].update(change)
    result,s=run(payload(rows))
    assert result is DRAFT and s.last_summary['status']=='incomplete'


@pytest.mark.parametrize('kind',['missing','duplicate','unsupported','wrong_index','missing_relation'])
def test_replacement_checked_separately(kind):
    rows=[x.model_dump() for x in payload().units]
    if kind=='missing':rows.pop()
    elif kind=='duplicate':rows.append(deepcopy(rows[1]))
    elif kind=='unsupported':rows[1]['verdict']='unclear'
    elif kind=='wrong_index':rows[1]['replacement_index']=2
    else:rows[1]['checked'].remove('relation')
    assert run(payload(rows))[0] is DRAFT


def test_multiple_sources_share_comparison_unit_and_add_only_missing_citation():
    from tests.test_review_comparison import DRAFT as d,ES
    r=unit(text=d.claims[0].text,checked=['fact','citation','comparison'],verdict='supported',repair_issue_indexes=[],comparison_scope='same_scope',
        sources=[dict(basis=dict(kind='text',ref=e.ref,quote=e.text),contribution=e.text) for e in ES])
    p=u.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],units=[r])))
    s,provider,_=controller([p]);provider.diagnosis_version='v3_unified'
    result=s.review('Q',ES,d)
    assert result.claims[0].text==d.claims[0].text
    assert result.claims[0].citation_refs==('[2]','[1]')


def test_detail_is_inside_same_unit_and_false_outcome_cannot_pass():
    text='Heating causes expansion and softening.'
    d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text=text),))
    es=[replace(SOURCES[0],text=text)]
    r=unit(text=text,checked=['fact','citation','relation','certainty'],verdict='supported',repair_issue_indexes=[],
        sources=[dict(basis=dict(kind='text',ref='[1]',quote=text),contribution='two effects')],
        detail=dict(source_index=0,start=0,end=len(text),outcomes=[dict(effect='expansion',supported=True),dict(effect='softening',supported=True)]))
    p=u.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],units=[r])))
    assert not u.unit_errors(p.units[0],p,d,es)
    p.units[0].detail.outcomes[1].supported=False
    assert 'unit_outcome_contradiction' in u.unit_errors(p.units[0],p,d,es)
    p.units[0].detail=None
    assert 'unit_detail_missing' in u.unit_errors(p.units[0],p,d,es)


def test_no_parallel_model_fields_and_conditional_prompt():
    prompt,ctx=u.request_prompt('Q',DRAFT,SOURCES)
    assert u.RELATION_PROMPT not in prompt and u.COMPARISON_PROMPT not in prompt
    d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='A causes B and C.'),))
    assert u.RELATION_PROMPT in u.request_prompt('Q',d,SOURCES)[0]
    with pytest.raises(ValueError):u.parse_response(json.dumps(dict(issues=[],requirements=[],units=[],claim_checks=[])))


def test_unknown_aspect_is_reported_and_cannot_authorize_replacement():
    rows=[x.model_dump() for x in payload().units]
    rows[1]['checked'].append('inference')
    p=payload(rows)
    assert any(e['reason_code']=='invalid_unit' for e in p._parse_errors)
    result,s=run(p)
    assert result is DRAFT and s.last_summary['status']=='incomplete'


def test_provider_one_call_no_legacy_instructions():
    calls=[]
    def create(**kw):
        calls.append(kw)
        content=json.dumps(dict(issues=[],requirements=[requirement()],units=[]))
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=content))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v3_unified')
    p.review('Q',SOURCES,DRAFT)
    assert len(calls)==1 and calls[0]['max_tokens']==32768
    assert 'audit_routing' in calls[0]['messages'][1]['content']
    assert 'Also return claim_checks' not in calls[0]['messages'][0]['content']


def test_display_normalization_preserves_scientific_differences():
    from literature_rag.application.evidence_review import normalized_quote as n
    source=r'The band (3 0 0 0 { - } 3 7 0 0 \mathrm { c m } ^ { - 1 })'
    assert n('$'+source+'$')==n('the band (3000–3700 cm−1)')
    for a,b in [('0.888','0.889'),('p<0.05','p>0.05'),('not increased','increased'),
                ('cm−1','cm1'),('CI-XI','CI-XA'),('WRV','wrv'),('x^{2}','x2'),
                (r'\frac{1}{2}','12')]:
        assert n(a)!=n(b)


@pytest.mark.parametrize('bad',['none','context_only','global','fact_as_context','invalid_quote'])
def test_context_can_only_support_local_evidence_limit_with_real_fact_sources(bad):
    text='所给证据无法确定因素排名；存在可能的水合作用解释。'
    d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text=text),))
    sources=[dict(basis=dict(kind='text',ref='[1]',quote='might be explained by hydration'),contribution='水合作用的可能解释。'),
             dict(basis=dict(kind='context'),contribution='所给证据没有因素排名。')]
    if bad=='context_only':sources=sources[1:]
    if bad=='global':sources[1]['contribution']='整篇论文没有因素排名。'
    if bad=='fact_as_context':sources[1]['contribution']='水合作用导致所有因素增强。'
    if bad=='invalid_quote':sources[0]['basis']['quote']='invented scientific fact'
    row=unit(text=text,checked=['fact','citation','relation','certainty','ranking','comparison'],
        comparison_scope='not_comparison',sources=sources,verdict='supported',repair_issue_indexes=[])
    p=u.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],units=[row])))
    errors=u.unit_errors(p.units[0],p,d,SOURCES)
    if bad=='none':assert not errors
    else:assert errors


def test_review_budget_accepts_64k_and_rejects_unbounded_output():
    from literature_rag.config import Settings
    from pydantic import ValidationError
    assert Settings(_env_file=None,evidence_review_max_output_tokens=65536).evidence_review_max_output_tokens==65536
    with pytest.raises(ValidationError):Settings(_env_file=None,evidence_review_max_output_tokens=65537)


@pytest.mark.parametrize('text',[
    '所给摘录未给出共同口径的定量贡献。',
    '现有结果未提供换算公式。',
    '所给局部摘录未出现计算式；不推断全文绝无公式。',
])
def test_local_scope_variants(text):
    assert u.local_evidence_limit(text)


@pytest.mark.parametrize('text',[
    '全文没有公式。', '所给摘录未给出公式，因此整篇论文没有公式。',
    '所给摘录未给出公式；不推断全文绝无公式，但全文没有公式。',
    '所给摘录说明处理导致强度增加。',
])
def test_scope_gate_does_not_license_global_or_positive_assertions(text):
    assert not u.local_evidence_limit(text)


def test_measurement_limit_requires_actual_method_quote_and_measurement_tag():
    text='相对含量是归一化峰面积分数，不等同于绝对氢键数量。'
    method='The relative content was calculated based on area proportion of the band.'
    es=[replace(SOURCES[0],text=method)]
    row=unit(text=text,checked=['fact','citation','measurement'],verdict='supported',repair_issue_indexes=[],
        sources=[dict(basis=dict(kind='text',ref='[1]',quote=method),contribution='峰面积比例。'),
                 dict(basis=dict(kind='context'),contribution='所供方法未提供绝对数量校准。')])
    x=u.Unit.model_validate(row)
    assert u.measurement_limit(x,x.sources[1],es)
    assert not u.measurement_limit(x,x.sources[1],SOURCES)
    x.checked.remove('measurement')
    assert not u.measurement_limit(x,x.sources[1],es)


def test_unique_sentence_relocation_preserves_outcomes_and_rejects_ambiguity():
    text='Heating causes expansion and softening.'
    d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text=text),))
    source='Introduction. '+text
    row=unit(text=text,checked=['fact','citation','relation','certainty'],verdict='supported',repair_issue_indexes=[],
        sources=[dict(basis=dict(kind='text',ref='[1]',quote=text),contribution='two effects')],
        detail=dict(source_index=0,start=0,end=3,outcomes=[dict(effect='expansion',supported=False)]))
    p=u.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],units=[row])))
    es=[replace(SOURCES[0],text=source)]
    u.prepare_payload(p,d,es)
    assert p._mechanical_repairs and p.units[0].detail.start==14
    assert 'unit_outcome_contradiction' in u.unit_errors(p.units[0],p,d,es)
    p.units[0].detail.start=0;p.units[0].detail.end=3
    es=[replace(SOURCES[0],text=source+' '+text)]
    u.prepare_payload(p,d,es)
    assert 'unit_detail_sentence_invalid' in u.unit_errors(p.units[0],p,d,es)


@pytest.mark.parametrize('scope', ['same_scope','unclear','different_scope','extra_field','bad_json','length','network'])
def test_comparison_completion_is_bounded_and_never_rewrites_answer(scope):
    from time import perf_counter
    p=payload()
    p.units[1].text='A is higher than B.'
    p.issues[0].replacement_claims[0].text=p.units[1].text
    calls=[]
    def create(**kw):
        calls.append(kw)
        if scope=='network':raise RuntimeError('private')
        patch=dict(unit_index=1,comparison_scope=scope if scope in {'same_scope','unclear','different_scope'} else 'same_scope',reason='Compared source scope.')
        if scope=='extra_field':patch['text']='malicious rewrite'
        content='bad' if scope=='bad_json' else json.dumps(dict(patches=[patch]))
        return NS(usage=NS(prompt_tokens=4,completion_tokens=6,total_tokens=10),choices=[NS(finish_reason='length' if scope=='length' else 'stop',message=NS(content=content))])
    provider=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v3_unified')
    provider.last_model_info={};provider.last_usage=dict(total_tokens=5);provider.last_api_calls=1
    before=[x.model_dump() for x in p.issues]
    provider._complete_comparisons(p,u,DRAFT,SOURCES,[], '{}',{},perf_counter())
    assert len(calls)==1 and provider.last_api_calls==2 and calls[0]['max_tokens']==8192
    assert [x.model_dump() for x in p.issues]==before
    if scope in {'same_scope','unclear','different_scope'}:
        assert p.units[1].comparison_scope==scope
        if scope!='same_scope':assert 'replacement_comparison_unresolved' in u.unit_errors(p.units[1],p,DRAFT,SOURCES)
    else:assert p.units[1].comparison_scope is None


def test_comparison_completion_skips_expired_budget():
    from time import perf_counter
    p=payload();p.units[1].text='A is higher than B.'
    p.issues[0].replacement_claims[0].text=p.units[1].text
    provider=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(),diagnostic=True,diagnosis_version='v3_unified')
    provider.last_model_info={};provider.last_api_calls=1
    provider._complete_comparisons(p,u,DRAFT,SOURCES,[], '{}',{'timeout':1},perf_counter())
    assert provider.last_api_calls==1
    assert provider.last_model_info['comparison_completion']['status']=='skipped_deadline'


@pytest.mark.parametrize('text,expected',[
    ('所给证据没有定量排序，因此不能判断谁最大。而纤维长度与湿纸幅强度有关，WRV与结合有关。',False),
    ('因为处理而提高柔顺性和保水值。',True),
    ('处理导致柔顺性和保水值提高。',True),
    ('因为数据不足，不能排序。而长度和强度有关。',False),
])
def test_causal_detail_does_not_join_therefore_to_later_but(text,expected):
    assert u.causal.risk(text) is expected
