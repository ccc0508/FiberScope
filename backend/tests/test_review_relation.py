import json
from dataclasses import replace
import pytest
from literature_rag.application.review_diagnosis_relation import parse_response,is_relation,inspect_diagnosis
from tests.test_corrective_review import controller,requirement
from tests.test_review_edit_binding import edit
from tests.test_evidence_review import DRAFT,SOURCES


def relation(**kwargs):
    r=dict(claim_index=0,issue_index=None,replacement_index=None,source_ref='[1]',
        source_quote='might be explained by hydration',source_cause='hydration',source_effect='effect',
        answer_cause='hydration',answer_effect='effect',source_relation='proposed_explanation',
        answer_relation='proposed_explanation',conditions_and_certainty='Tentative, same conditions.',
        verdict='supported',reason='Same proposed explanation.',repair_issue_indexes=[])
    r.update(kwargs);return r


def parsed(checks,issues=None):
    return parse_response(json.dumps(dict(issues=issues or [],requirements=[requirement('edit',issue_indexes=[0]) if issues else requirement()],
        claim_checks=[],relation_checks=checks)))


@pytest.mark.parametrize('text',['会因分子链活动性提高而进一步提升柔顺性','润胀有助于结合','A is associated with B',
    'Higher A causes B','相关不等于因果','This may be explained by hydration'])
def test_relation_selection_includes_cautious_and_negative_claims(text):assert is_relation(text)


def test_plain_number_is_not_relation():assert not is_relation('测量值为0.912。')


def test_missing_original_check_is_incomplete():
    draft=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='会因活动性提高而增强柔顺性'),))
    audit=inspect_diagnosis(parsed([]),draft,SOURCES)
    assert any(e['reason_code']=='original_relation_check_missing' for e in audit['errors'])


def test_supported_proposed_explanation_is_kept_without_hedging_or_edit():
    draft=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='The effect might be explained by hydration.'),))
    p=parsed([relation()]);service,provider,_=controller([p]);provider.diagnosis_version='v2_relation'
    assert service.review('Q',SOURCES,draft) is draft
    assert service.last_summary['status']=='completed'


@pytest.mark.parametrize('checks',[[],[relation(claim_index=None,issue_index=0,replacement_index=0,verdict='overstated')],
    [relation(claim_index=None,issue_index=0,replacement_index=0,source_quote='Invented ungrounded quote')]])
def test_unverified_replacement_relation_is_blocked(checks):
    p=parsed(checks,[edit()]);service,provider,_=controller([p]);provider.diagnosis_version='v2_relation'
    assert service.review('Q',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code']=='replacement_relation_not_verified'


def test_supported_replacement_is_applied_and_other_claim_unchanged():
    p=parsed([relation(claim_index=None,issue_index=0,replacement_index=0)],[edit()])
    service,provider,_=controller([p]);provider.diagnosis_version='v2_relation'
    result=service.review('Q',SOURCES,DRAFT)
    assert 'might' in result.claims[0].text and result.claims[1]==DRAFT.claims[1]


def test_no_relation_schema_failure_silently_passes():
    p=parsed([{'claim_index':0}])
    assert not inspect_diagnosis(p,DRAFT,SOURCES)['valid']


def test_baseline_prompt_and_default_remain_unchanged():
    from literature_rag.application.review_diagnosis import diagnosis_contract
    from literature_rag.config import Settings
    assert not hasattr(diagnosis_contract('v2_budget'),'is_relation')
    assert Settings.model_fields['corrective_review_version'].default=='v1'


def test_q31_sentence_is_selected_without_altering_baseline():
    text='较少的分子间氢键和较低的结晶度会因分子链活动性提高而进一步提升纤维素纤维的柔顺性、可及性和保水值'
    assert is_relation(text)


def test_direct_supported_causality_is_not_automatically_downgraded():
    text='Heating causes expansion under the tested conditions.'
    sources=[replace(SOURCES[0],text=text)]
    draft=replace(DRAFT,claims=(replace(DRAFT.claims[0],text=text),))
    p=parsed([relation(source_quote=text,source_cause='heating',source_effect='expansion',
        answer_cause='heating',answer_effect='expansion',source_relation='causal',answer_relation='causal')])
    service,provider,_=controller([p]);provider.diagnosis_version='v2_relation'
    assert service.review('Q',sources,draft) is draft


def test_provider_delivers_relation_indexes_and_parses_schema():
    from types import SimpleNamespace as NS
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=parsed([]).model_dump_json()))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),
        diagnostic=True,diagnosis_version='v2_relation')
    draft=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='会因活动性提高而增强柔顺性'),))
    result=p.review('Q',SOURCES,draft)
    assert hasattr(result,'relation_checks')
    assert 'relation_claim_indexes: [0]' in calls[0]['messages'][1]['content']


def test_snapshot_includes_relation_contract(tmp_path):
    from literature_rag.diagnostics import configuration_snapshot
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v2_relation\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['evidence_review']['relation_audit'] and c['evidence_review']['supplement_policy']
    assert 'application/review_diagnosis_relation.py' in c['pipeline_source_files']
