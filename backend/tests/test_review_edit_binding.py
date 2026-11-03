"""Mechanical edit identity, isolation and second-round binding; no paid calls."""
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from literature_rag.application.review_diagnosis_bound import parse_response, validate_edit_target
from literature_rag.application.evidence_review import ReviewRejected
from literature_rag.domain.models import GeneratedAnswer, GeneratedClaim
from tests.test_corrective_review import controller, requirement, Reader
from tests.test_corrective_review_recovery import check
from tests.test_evidence_review import DRAFT, SOURCES, proposal


def edit(index=0, **kwargs):
    return proposal(claim_index=index, original_text=DRAFT.claims[index].text, **kwargs).issues[0].model_dump()


def payload(issues, checks=None, requirements=None):
    return parse_response(json.dumps(dict(issues=issues,claim_checks=checks or [],
        requirements=requirements or [requirement('edit',issue_indexes=list(range(len(issues))))])))


def run(p, draft=DRAFT):
    service,provider,_=controller([p]);provider.diagnosis_version='v2_bound'
    return service.review('Q',SOURCES,draft),service


@pytest.mark.parametrize('text',[None,'','The effect was established. ','The effect was established!','The effect was established. [1]','A retained fact.'])
def test_mismatch_never_guesses_or_retargets(text):
    issue=edit();issue['original_text']=text
    result,service=run(payload([issue]))
    assert result is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues']==[dict(issue_index=0,reason_code='original_text_mismatch')]
    assert service.last_summary['status']=='incomplete'


def test_missing_text_rejects_only_that_edit_and_is_not_covered():
    first=edit();first.pop('original_text')
    second=edit(1)
    rs=[requirement('edit',id='R1',issue_indexes=[0]),requirement('edit',id='R2',claim_indexes=[1],issue_indexes=[1])]
    result,service=run(payload([first,second],requirements=rs))
    assert result.claims[0]==DRAFT.claims[0]
    assert result.claims[1]!=DRAFT.claims[1]
    trace=service.last_trace['rounds'][0]
    assert trace['accepted_issue_indexes']==[1]
    assert trace['rejected_issues']==[dict(issue_index=0,reason_code='original_text_missing')]
    assert [r['id'] for r in service.last_summary['unresolved']]==['R1']


def test_check_target_conflict_blocks_even_with_real_quote_and_matching_original():
    p=payload([edit()],checks=[check(claim_index=1,verdict='overstated',issue_indexes=[0])])
    result,service=run(p)
    assert result is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code']=='claim_check_edit_target_conflict'


def test_q24_style_one_based_offset_keeps_two_untouched_claims():
    # A valid citation is insufficient when the proposal's original text belongs elsewhere.
    draft=GeneratedAnswer('fixture',tuple(GeneratedClaim(f'Original claim {i}',('[1]',)) for i in range(9)))
    issues=[]
    for intended,wrong in [(4,5),(6,7)]:
        item=edit();item.update(claim_index=wrong,original_text=draft.claims[intended].text);issues.append(item)
    result,service=run(payload(issues),draft)
    assert result is draft
    assert len(service.last_trace['rounds'][0]['rejected_issues'])==2


def test_duplicate_text_does_not_retarget_deletion_to_all_matches():
    draft=GeneratedAnswer('fixture',(DRAFT.claims[0],DRAFT.claims[0],DRAFT.claims[1]))
    delete=edit();delete['replacement_claims']=[]
    result,service=run(payload([delete]),draft)
    assert result.claims==draft.claims[1:]
    assert service.last_trace['rounds'][0]['accepted_issue_indexes']==[0]


def test_split_and_append_preserve_unaffected_claim():
    split=edit();split['replacement_claims'].append(dict(text='Hydration is a proposed explanation.',citation_refs=['[1]']))
    append=edit();append.update(claim_index=None,original_text=None,
        replacement_claims=[dict(text='The evidence retains uncertainty.',citation_refs=['[1]'])])
    result,service=run(payload([split,append]))
    assert len(result.claims)==4
    assert result.claims[2]==DRAFT.claims[1]
    assert service.last_trace['rounds'][0]['accepted_issue_indexes']==[0,1]


@pytest.mark.parametrize('missing',[True,False])
def test_append_requires_explicit_null(missing):
    item=edit();item['claim_index']=None
    if missing:item.pop('original_text')
    result,service=run(payload([item]))
    assert result is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code']==('original_text_missing' if missing else 'append_original_text_must_be_null')


def test_second_round_uses_new_draft_not_old_text():
    first=payload([edit()],requirements=[requirement('lookup',issue_indexes=[0])])
    stale=payload([edit()])
    service,provider,reader=controller([first,stale],Reader());provider.diagnosis_version='v2_bound'
    result=service.review('Q',SOURCES,DRAFT)
    assert 'might' in result.claims[0].text
    assert len(provider.calls)==2
    assert service.last_trace['rounds'][1]['rejected_issues'][0]['reason_code']=='original_text_mismatch'
    assert service.last_summary['status']=='incomplete'


def test_correct_binding_still_requires_real_source():
    item=edit(basis=[dict(kind='text',ref='[1]',quote='Invented quotation that is not supplied')])
    result,service=run(payload([item]))
    assert result is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code']=='quote_not_in_actual_evidence'


@pytest.mark.parametrize('version',['v2_bound','v2_budget','v2_relation'])
def test_provider_explicit_indexes_and_no_v3_policy(version):
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(dict(
            issues=[edit()],requirements=[requirement('edit',issue_indexes=[0])],claim_checks=[],
            **({'relation_checks':[]} if version=='v2_relation' else {})))))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),
        diagnostic=True,diagnosis_version=version)
    result=p.review('Q',SOURCES,DRAFT)
    validate_edit_target(result,0,DRAFT)
    messages=calls[0]['messages']
    assert '"claim_index": 0' in messages[1]['content']
    assert 'original_text' in messages[0]['content']
    assert 'Minimal-revision policy' not in messages[0]['content']
    assert 'revision_checks' not in messages[0]['content']
    prompt=messages[0]['content']
    # Inspect the actual complete example delivered to the provider, not just a keyword
    # in a late instruction: this was the conflicting template behind the Q31 failure.
    example,_=json.JSONDecoder().raw_decode(prompt[prompt.index('{"issues": [{'):])
    assert example['issues'][0]['original_text']=='exact complete text of input draft claim 0'
    assert '"claim_index":null,"original_text":null' in prompt
    assert 'check EVERY issues item contains original_text' in prompt


def test_legacy_prompt_is_not_changed_by_binding_contract():
    from literature_rag.application.review_diagnosis_v2 import DIAGNOSTIC_PROMPT
    example,_=json.JSONDecoder().raw_decode(DIAGNOSTIC_PROMPT[DIAGNOSTIC_PROMPT.index('{"issues": [{'):])
    assert 'original_text' not in example['issues'][0]


def test_snapshot_records_binding_but_keeps_default(tmp_path):
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    assert Settings.model_fields['corrective_review_version'].default=='v1'
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v2_bound\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert 'application/review_diagnosis_bound.py' in c['pipeline_source_files']
    assert 'application/review_diagnosis_v3.py' not in c['pipeline_source_files']
    assert c['evidence_review']['edit_binding'] and c['evidence_review']['numeric_crosscheck']
