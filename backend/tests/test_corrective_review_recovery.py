"""Regression tests for multi-source checks, isolated diagnosis failures and bounded recovery."""
from dataclasses import replace
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from literature_rag.application.evidence_review import EvidenceReviewService
from literature_rag.application.review_diagnosis_v2 import parse_response, inspect_diagnosis
from literature_rag.application.numeric_crosscheck import plan_crosscheck
from literature_rag.domain.errors import ProviderError
from tests.test_corrective_review import controller, requirement, Reader
from tests.test_evidence_review import DRAFT, SOURCES, proposal
from tests.test_numeric_crosscheck import payload, catalog


def check(**kwargs):
    value=dict(claim_index=0,source_ref='[1]',source_quote='might be explained by hydration',
        source_object='effect',answer_object='effect',source_change='explanation',answer_change='explanation',
        source_certainty='proposed',answer_certainty='certain',verdict='supported',issue_indexes=[])
    value.update(kwargs)
    return value


def v2_controller(responses,reader=None):
    service,provider,reader=controller(responses,reader)
    provider.diagnosis_version='v2'
    return service,provider,reader


def parsed(requirements=None,checks=None,issues=None):
    return parse_response(json.dumps(dict(requirements=requirements if requirements is not None else [requirement()],
        claim_checks=checks or [],issues=issues or [])))


def test_same_claim_can_compare_two_sources_or_two_distinct_spans():
    sources=[*SOURCES,replace(SOURCES[0],ref='[2]',chunk_id='other',text='A different report uses another value.')]
    p=parsed(checks=[check(),check(source_ref='[2]',source_quote='different report uses another value'),
        check(source_quote='A retained fact.')])
    audit=inspect_diagnosis(p,DRAFT,sources)
    assert audit['valid']
    p.claim_checks.append(p.claim_checks[0])
    assert inspect_diagnosis(p,DRAFT,sources)['errors'][0]['reason_code']=='duplicate_claim_check'


@pytest.mark.parametrize('defect',['bad_quote','bad_location','bad_schema','missing_check','unmapped_edit'])
def test_auxiliary_failure_retains_independently_verified_edit_but_not_clean_status(defect):
    r=requirement('edit',issue_indexes=[0]);checks=[]
    if defect=='bad_quote':checks=[check(source_quote='Invented quotation does not occur here')]
    if defect=='bad_location':r['claim_indexes']=[99]
    if defect=='bad_schema':r['status']='invalid'
    if defect=='missing_check':checks=[check(claim_index=99)]
    if defect=='unmapped_edit':r=requirement()
    service,_,_=v2_controller([parsed([r],checks,issues=[proposal().issues[0].model_dump()])])
    result=service.review('Why?',SOURCES,DRAFT)
    assert 'might' in result.claims[0].text
    assert result.claims[1]==DRAFT.claims[1]
    trace=service.last_trace['rounds'][0]
    assert trace['accepted_issue_indexes']==[0] and trace['diagnosis_errors']
    assert service.last_summary['status']=='incomplete'


def test_invalid_edit_basis_still_cannot_change_answer():
    bad=proposal(basis=[dict(kind='text',ref='[1]',quote='An invented unsupported quotation')]).issues[0].model_dump()
    service,_,_=v2_controller([parsed([requirement('edit',issue_indexes=[0])],issues=[bad])])
    assert service.review('Why?',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code']=='quote_not_in_actual_evidence'
    assert service.last_summary['status']=='incomplete'


def test_invalid_edit_schema_is_not_silently_repaired():
    with pytest.raises(ValidationError):parsed(issues=[{'claim_index':0}])
    with pytest.raises(ValueError):parse_response('{"issues":[],"unexpected":"data"}')


def test_only_valid_diagnostic_actions_can_be_executed():
    bad=requirement('lookup',id='R2');bad['lookup']['document_ref']='[99]'
    audit=inspect_diagnosis(parsed([requirement('lookup'),bad]),DRAFT,SOURCES)
    assert not audit['valid']
    assert [r['id'] for r in audit['requirements'] if r['status']=='lookup']==['R1']
    assert audit['requirements'][1]['status']=='unresolved'
    assert 'lookup' not in audit['requirements'][1]


def test_duplicate_requirement_ids_never_authorize_a_lookup():
    audit=inspect_diagnosis(parsed([requirement('lookup'),requirement('lookup')]),DRAFT,SOURCES)
    assert not audit['valid'] and len(audit['requirements'])==1
    assert audit['requirements'][0]['status']=='unresolved'


def test_numeric_check_survives_first_provider_failure_and_stops_after_second():
    reader=Reader();reader.retriever=NS(body_context_catalog=catalog())
    second=payload(id='R90',requirement='核对同篇论文摘要与已提供材料中涉及用户问题的数值及统计口径。')
    service,p,reader=v2_controller([ProviderError('PRIVATE'),second],reader)
    service.review('这个系数0.9正确吗？',SOURCES,DRAFT)
    assert len(reader.calls)==1 and len(p.calls)==2
    assert reader.calls[0][1][0]['lookup']['target']=='abstract'
    assert service.last_trace['numeric_crosscheck']['triggered']
    assert service.last_summary['status']=='completed'
    assert 'PRIVATE' not in json.dumps(service.last_trace)


def test_second_failure_does_not_relabel_successful_first_edit_as_unapplied():
    reader=Reader();reader.retriever=NS(body_context_catalog=catalog())
    first=parsed([requirement('edit',issue_indexes=[0])],issues=[proposal().issues[0].model_dump()])
    service,p,_=v2_controller([first,ProviderError('failed')],reader)
    result=service.review('这个系数0.9正确吗？',SOURCES,DRAFT)
    assert len(p.calls)==2 and 'might' in result.answer
    assert [r['id'] for r in service.last_summary['unresolved']]==['R90']
    assert p.calls[1][3]['context']['requirements'][0]['status']=='covered'
    assert p.calls[1][3]['context']['requirements'][0]['issue_indexes']==[]


def test_second_round_invalid_lookup_cannot_recurse_but_safe_edit_survives():
    second=parsed([requirement('lookup',issue_indexes=[0])],issues=[proposal().issues[0].model_dump()])
    service,p,reader=v2_controller([payload('lookup'),second])
    result=service.review('Q',SOURCES,DRAFT)
    assert 'might' in result.answer and len(reader.calls)==1 and len(p.calls)==2
    assert service.last_summary['status']=='incomplete'
    assert service.last_trace['rounds'][1]['diagnosis_errors'][0]['reason_code']=='second_review_cannot_request_lookup'


def test_program_id_allocation_cannot_crash_when_high_ids_are_taken():
    rs=[requirement(id=f'R{i}') for i in range(90,100)]
    ledger,actions,_=plan_crosscheck('数值0.9是否正确？',SOURCES,rs,catalog())
    assert actions[0]['id']=='R1' and len({r['id'] for r in ledger})==len(ledger)


def test_next_ledger_remaps_split_and_appended_claims_without_old_edit_indexes():
    from literature_rag.application.corrective_review import settled_requirements
    from dataclasses import asdict
    first=proposal(replacement_claims=[dict(text='First.',citation_refs=['[1]']),
        dict(text='Second.',citation_refs=['[1]'])]).issues[0].model_dump()
    appended=proposal(claim_index=None).issues[0].model_dump()
    trace=dict(draft=asdict(DRAFT),accepted=True,accepted_issue_indexes=[0,1],issues=[first,appended],
        requirements=[requirement('edit',id='R1',issue_indexes=[0]),
            requirement(id='R2',claim_indexes=[1]),
            requirement('edit',id='R3',claim_indexes=[],issue_indexes=[1])])
    rows=settled_requirements(trace)
    assert [r['claim_indexes'] for r in rows]==[[0,1],[2],[3]]
    assert all(r['status']=='covered' and not r['issue_indexes'] for r in rows)


def test_missing_prior_requirement_remains_unresolved_after_partial_diagnosis():
    context=dict(requirements=[requirement(id='R2')])
    audit=inspect_diagnosis(parsed(),DRAFT,SOURCES,context)
    assert not audit['valid']
    assert audit['requirements'][-1]['id']=='R2'
    assert audit['requirements'][-1]['status']=='unresolved'
