from types import SimpleNamespace as NS
from dataclasses import replace
import pytest

from literature_rag.application.numeric_crosscheck import numeric_verification_requested,plan_crosscheck
from literature_rag.application.review_diagnosis_v2 import validate_diagnosis,DiagnosticPayload,critical_claim_indexes
from literature_rag.application.evidence_review import ReviewRejected
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
from tests.test_corrective_review import SOURCES,DRAFT,requirement

def payload(status='covered',issues=None,**kwargs):
    return DiagnosticPayload.model_validate(dict(requirements=[requirement(status,**kwargs)],issues=issues or [],claim_checks=[]))


def test_default_protocol_preserves_v1_and_v2_requires_explicit_selection():
    from literature_rag.config import Settings
    from literature_rag.application.review_diagnosis import diagnosis_contract
    assert Settings(_env_file=None).corrective_review_version == 'v1'
    assert diagnosis_contract().VERSION == 'bounded-corrective-review-v1'
    assert 'claim_checks' not in diagnosis_contract().DiagnosticPayload.model_fields
    assert diagnosis_contract('v2').VERSION == 'bounded-corrective-review-v2.1'
    assert 'claim_checks' in diagnosis_contract('v2').DiagnosticPayload.model_fields
    with pytest.raises(ValueError):
        diagnosis_contract('unknown')


def test_numeric_policy_is_only_activated_in_experimental_controller(monkeypatch):
    from tests.test_corrective_review import controller, payload as legacy_payload
    import literature_rag.application.numeric_crosscheck as policy
    calls=[]
    def plan(question,evidences,requirements,catalog):
        calls.append(question)
        return requirements,[],dict(triggered=True,status='test')
    monkeypatch.setattr(policy,'plan_crosscheck',plan)
    old,_,_=controller([legacy_payload()])
    old.review('请核实0.9这个系数。',SOURCES,DRAFT)
    assert calls == []
    new,provider,_=controller([payload()])
    provider.diagnosis_version='v2'
    new.review('请核实0.9这个系数。',SOURCES,DRAFT)
    assert len(calls)==1
    assert new.last_trace['version']=='bounded-corrective-review-v2.1'


def test_provider_v2_requests_and_parses_the_experimental_contract():
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash',usage=None,
            choices=[NS(finish_reason='stop',message=NS(content=payload().model_dump_json()))])
    provider=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',diagnostic=True,
        diagnosis_version='v2',client=NS(chat=NS(completions=NS(create=create))))
    result=provider.review('Explain the mechanism',SOURCES,DRAFT)
    assert isinstance(result,DiagnosticPayload)
    assert 'claim_checks' in calls[0]['messages'][0]['content']
    assert 'critical_claim_indexes' in calls[0]['messages'][1]['content']


@pytest.mark.parametrize('q,expected',[
    ('相关系数是0.87吧？可以直接换算吗？',True),
    ('Please verify the reported percentage.',True),
    ('请解释为什么4小时处理会增强纤维。',False),
    ('PFI打浆的机理是什么？',False),
])
def test_trigger_comes_from_question_not_case_id_or_expected_value(q,expected):
    assert numeric_verification_requested(q)==expected


def catalog():
    return NS(mapping={'c':dict(role_status='identified',content_role='body',section_path=['3. Results']),
        'abs':dict(role_status='identified',content_role='abstract',section_path=[])})


def test_body_value_does_not_suppress_program_requested_abstract_check():
    ledger,actions,audit=plan_crosscheck('数值0.87是否正确？',SOURCES,[requirement()],catalog())
    assert [a['lookup']['target'] for a in actions]==['abstract']
    assert actions[0]['lookup']['query']=='数值0.87是否正确？'
    assert audit['observed_regions']==['results'] and ledger[0]['status']=='covered'


def test_both_regions_present_avoid_unnecessary_lookup():
    es=[*SOURCES,replace(SOURCES[0],ref='[2]',chunk_id='abs')]
    _,actions,audit=plan_crosscheck('数值0.87是否正确？',es,[requirement()],catalog())
    assert not actions and audit['status']=='regions_already_supplied'


def test_shared_two_action_budget_keeps_deferred_gap_visible():
    rs=[requirement('lookup',id='R1'),requirement('lookup',id='R2')]
    ledger,actions,audit=plan_crosscheck('数值是否正确？',SOURCES,rs,catalog())
    assert len(actions)==2 and actions[0]['lookup']['target']=='abstract'
    assert audit['deferred_requirement_ids']==['R2']
    assert next(r for r in ledger if r['id']=='R2')['status']=='unresolved'


def test_missing_structural_comparison_cannot_report_success():
    draft=GeneratedAnswer('Hydration causes structural breakage. [1]',
        (GeneratedClaim('Hydration causes structural breakage.',('[1]',)),))
    assert critical_claim_indexes(draft)==[0]
    with pytest.raises(ReviewRejected,match='critical_claim_check_missing'):
        validate_diagnosis(payload(),draft,SOURCES)


def test_claim_check_requires_actual_source_quote_and_a_corrective_action():
    check=dict(claim_index=0,source_ref='[1]',source_quote='might be explained by hydration',
        source_object='interchain interaction',answer_object='backbone',source_change='interaction changes',
        answer_change='covalent cleavage',source_certainty='proposed',answer_certainty='certain',
        verdict='overstated',issue_indexes=[])
    p=DiagnosticPayload.model_validate(dict(requirements=[requirement()],issues=[],claim_checks=[check]))
    with pytest.raises(ReviewRejected,match='claim_check_needs_matching_action'):
        validate_diagnosis(p,DRAFT,SOURCES)
    p.claim_checks[0].verdict='supported';p.claim_checks[0].source_quote='invented source quotation'
    with pytest.raises(ReviewRejected,match='quote_not_in_evidence'):
        validate_diagnosis(p,DRAFT,SOURCES)
