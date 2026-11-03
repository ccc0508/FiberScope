from dataclasses import replace
import json
import pytest
from literature_rag.application import review_diagnosis_causal as c
from tests.test_review_relation import relation
from tests.test_review_relation_compact import shorten
from tests.test_corrective_review import requirement
from tests.test_evidence_review import DRAFT,SOURCES
from tests.test_review_edit_binding import edit


def mixed_target_payload(**changes):
    check=shorten(relation(issue_index=0,verdict='overstated',repair_issue_indexes=[0]))
    check.update(changes)
    return c.parse_response(json.dumps(dict(issues=[edit()],requirements=[requirement('edit',issue_indexes=[0])],
        claim_checks=[],relation_checks=[check],comparison_checks=[])))


def test_redundant_original_pointer_is_bound_logged_and_idempotent():
    p=mixed_target_payload()
    before=p.relation_checks[0].model_dump()
    c.prepare_payload(p,DRAFT,SOURCES)
    after=p.relation_checks[0].model_dump()
    assert after==dict(before,issue_index=None)
    assert p._relation_target_repairs==[dict(index=0,reason_code='redundant_original_issue_index',before=before,after=after)]
    c.prepare_payload(p,DRAFT,SOURCES)
    assert len(p._relation_target_repairs)==1


@pytest.mark.parametrize('changes',[
    dict(replacement_index=0),dict(claim_index=None),dict(claim_index=999),dict(issue_index=999),
    dict(repair_issue_indexes=[]),dict(repair_issue_indexes=[0,1]),dict(verdict='supported'),
    dict(source_quote='An invented source quotation'),dict(source_ref='[99]'),
])
def test_ambiguous_or_invalid_targets_are_not_repaired(changes):
    p=mixed_target_payload(**changes);before=p.relation_checks[0].model_dump()
    c.prepare_payload(p,DRAFT,SOURCES)
    assert p.relation_checks[0].model_dump()==before
    assert not p._relation_target_repairs


@pytest.mark.parametrize('field,value',[('original_text','wrong original'),('claim_index',1)])
def test_pointer_repair_requires_exact_original_binding(field,value):
    p=mixed_target_payload();setattr(p.issues[0],field,value)
    c.prepare_payload(p,DRAFT,SOURCES)
    assert p.relation_checks[0].issue_index==0 and not p._relation_target_repairs


def test_repair_is_logged_in_service_without_new_call():
    from tests.test_corrective_review import controller
    p=mixed_target_payload()
    service,provider,_=controller([p]);provider.diagnosis_version='v2_causal'
    service.review('Q',SOURCES,DRAFT)
    t=service.last_trace
    assert t['api_calls']==1
    assert t['rounds'][0]['relation_target_repairs'][0]['before']['issue_index']==0
    assert t['rounds'][0]['relation_target_repairs'][0]['after']['issue_index'] is None


def test_risk_targets_not_every_relation():
    assert c.risk('分子链活动性提高因而进一步提升柔顺性、可及性和保水值')
    assert c.risk('Heating causes expansion and softening.')
    assert not c.risk('相关系数为0.912。')
    assert not c.risk('A is associated with B.')


def test_decimal_and_fragment_boundaries():
    text='The value is 0.912. Heating causes expansion and softening. Incomplete tail'
    parts=[text[a:b] for a,b in c.sentence_spans(text)]
    assert parts==['The value is 0.912.','Heating causes expansion and softening.']


def test_complete_source_multiple_effects_supported_and_wrong_arrow_rejected():
    text='Heating causes expansion and softening.'
    es=[replace(SOURCES[0],text=text)]
    base=shorten(relation(source_quote=text))
    check=c.RelationCheck(**base,sentence_start=0,sentence_end=len(text),outcomes=[dict(effect='expansion',supported=True),dict(effect='softening',supported=True)])
    assert c.detail_valid(check,es)
    check.outcomes[1].supported=False
    assert not c.detail_valid(check,es)
    check.verdict='overstated'
    assert c.detail_valid(check,es)
    check.sentence_end-=1
    assert not c.detail_valid(check,es)


def test_budget_records_unchecked_and_context_does_not_duplicate_source():
    d=replace(DRAFT,claims=tuple(replace(DRAFT.claims[0],text='Heating causes expansion and softening.') for _ in range(5)))
    assert c.targets(d)==dict(selected=[0,1,2],unchecked=[3,4])
    ctx=c.request_context(d,[replace(SOURCES[0],text='Heating causes expansion and softening.')])
    assert ctx['causal_sentence_locations']==[dict(ref='[1]',start=0,end=39)]
    assert 'Heating' not in json.dumps(ctx)


def test_parse_keeps_comparison_and_detail_fields():
    text='Heating causes expansion and softening.'
    check=shorten(relation(source_quote=text))
    check.update(sentence_start=0,sentence_end=len(text),outcomes=[dict(effect='expansion',supported=True),dict(effect='softening',supported=True)])
    raw=dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[check],comparison_checks=[])
    p=c.parse_response(json.dumps(raw))
    assert len(p.relation_checks[0].outcomes)==2
    assert p.comparison_checks==[]


def test_provider_uses_same_single_call_and_budget():
    from types import SimpleNamespace as NS
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        raw=dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[])
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(raw)))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v2_causal')
    d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='Heating causes expansion and softening.'),))
    p.review('Q',SOURCES,d)
    assert len(calls)==1 and calls[0]['max_tokens']==32768
    assert 'causal_detail_targets' in calls[0]['messages'][1]['content']


def test_missing_details_and_over_budget_not_certified():
    d=replace(DRAFT,claims=tuple(replace(DRAFT.claims[0],text='Heating causes expansion and softening.') for _ in range(4)))
    p=c.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[])))
    c.prepare_payload(p,d,SOURCES)
    errors=c.inspect_diagnosis(p,d,SOURCES)['errors']
    assert sum(e['reason_code']=='complete_sentence_or_outcomes_missing' for e in errors)==3
    assert any(e['reason_code']=='detail_budget_unchecked' and e['claim_indexes']==[3] for e in errors)
