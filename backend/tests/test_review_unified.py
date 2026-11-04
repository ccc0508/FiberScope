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
