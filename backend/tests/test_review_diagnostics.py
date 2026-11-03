import json
from types import SimpleNamespace as NS
import pytest
from literature_rag.application.review_diagnostics import archive_response,review_outcome
from literature_rag.application import review_diagnosis_v2 as v2
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from literature_rag.domain.errors import ProviderResponseError
from tests.test_evidence_review import DRAFT,SOURCES


@pytest.mark.parametrize('content,finish,stage',[
    ('{"issues":','stop','response_parse'),
    ('{"unexpected":true}','stop','response_parse'),
    ('{"issues":','length','output_limit')])
def test_failure_response_private_archive(tmp_path,content,finish,stage):
    def create(**kwargs):
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason=finish,message=NS(content=content))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE_KEY',client=NS(chat=NS(completions=NS(create=create))),
        diagnostic=True,diagnosis_version='v2',diagnostics_dir=tmp_path)
    with pytest.raises(ProviderResponseError):p.review('Q',SOURCES,DRAFT)
    artifact=p.last_model_info['failure_artifact']
    body=json.loads((tmp_path/(artifact['artifact_id']+'.json')).read_text(encoding='utf-8'))
    assert body['response']==content and body['metadata']['stage']==stage
    assert 'PRIVATE_KEY' not in json.dumps(body)
    assert str(tmp_path) not in json.dumps(p.last_model_info)


def test_archive_io_failure_does_not_replace_review_failure(tmp_path):
    file=tmp_path/'file';file.write_text('x')
    assert archive_response(file,'x',{})['status']=='write_failed'


def test_auxiliary_field_error_has_location_without_value():
    raw=dict(issues=[],requirements=[dict(id='R1',status='PRIVATE_VALUE')],claim_checks=[])
    p=v2.parse_response(json.dumps(raw))
    e=p._parse_errors[0]
    assert any(f['location']==['status'] for f in e['fields'])
    assert 'PRIVATE_VALUE' not in json.dumps(e)


def test_applied_original_error_is_not_claimed_semantically_resolved():
    old=dict(text='Old comparison',citation_refs=['[1]'])
    new=dict(text='New comparison',citation_refs=['[1]','[2]'])
    r=dict(status='revised',accepted=True,accepted_issue_indexes=[0],draft=dict(claims=[old]),
        issues=[dict(claim_index=0,category='citation',replacement_claims=[new])],
        diagnosis_errors=[dict(claim_index=0,reason_code='comparison_statement_unsupported')])
    trace=dict(rounds=[r],status='incomplete',summary=dict(unresolved=[]))
    out=review_outcome(trace,dict(claims=[dict(text=new['text'],citation_refs=tuple(new['citation_refs']))]))
    assert out['findings'][0]['status']=='applied_present'
    assert out['findings'][1]['scope']=='original_claim_changed_needs_recheck'
    assert out['pipeline_status']=='incomplete'
    assert out['semantic_quality']=='not_guaranteed'


def test_deferred_edit_not_reported_as_applied():
    r=dict(status='revised',accepted=True,accepted_issue_indexes=[0],issues=[dict(claim_index=0,category='citation',replacement_claims=[])])
    t=dict(rounds=[r],status='incomplete',summary=dict(unresolved=[dict(id='R2')]),
        first_round_commit=dict(accepted_issue_indexes=[],deferred_issues=[dict(issue_index=0)]))
    out=review_outcome(t,dict(claims=[]))
    assert out['findings'][0]['status']=='deferred'
    assert out['remaining_requirements']==[dict(id='R2')]


def test_requirement_history_keeps_changed_and_unresolved_states():
    t=dict(rounds=[dict(status='revised',requirements=[dict(id='R2',requirement='Limit',status='edit',reason='Needs qualification',issue_indexes=[0])]),
        dict(status='failed',reason_code='review_response_invalid')],status='incomplete',summary=dict(unresolved=[dict(id='R2')]))
    out=review_outcome(t,dict(claims=[]))
    assert out['rounds'][1]['stage']=='response_parse'
    assert out['requirement_history'][0]['final_state']=='unresolved'
    assert out['requirement_history'][0]['history'][0]['reported_status']=='edit'
