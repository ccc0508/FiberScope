import json
from dataclasses import replace
import pytest
from literature_rag.application import review_diagnosis_comparison as mod
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
from tests.test_corrective_review import controller,requirement
from tests.test_evidence_review import SOURCES

DRAFT=GeneratedAnswer('fixture',(GeneratedClaim('摘要0.888与正文0.912不一致。',('[2]',)),))
ES=[replace(SOURCES[0],ref='[1]',text='Body reports coefficient 0.912 for softwood.'),
    replace(SOURCES[0],ref='[2]',text='Abstract reports coefficient 0.888 for softwood.')]

def payload(**changes):
    c=dict(claim_index=0,original_text=DRAFT.claims[0].text,comparability='same_scope',statement_supported=True,reason='同种纸浆、同指标和统计量。',
        facts=[dict(fact=e.text,source_ref=e.ref,source_quote=e.text) for e in ES]);c.update(changes)
    return mod.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[c])))

def run(p):
    service,provider,_=controller([p]);provider.diagnosis_version='v2_comparison'
    return service.review('Q',ES,DRAFT),service

def test_only_add_missing_reference_without_rewriting():
    result,s=run(payload())
    assert result.claims[0].text==DRAFT.claims[0].text
    assert result.claims[0].citation_refs==('[2]','[1]')
    assert s.last_trace['rounds'][0]['citation_only_repair_indexes']==[0]
    assert s.last_trace['rounds'][0]['model_issues']==[]

@pytest.mark.parametrize('changes',[
    dict(original_text='Wrong target'),dict(comparability='different_scope'),dict(comparability='unclear'),
    dict(statement_supported=False),
    dict(facts=[dict(fact='A',source_ref='[1]',source_quote=ES[0].text)]),
    dict(facts=[dict(fact='A',source_ref='[1]',source_quote='Invented supporting quotation'),dict(fact='B',source_ref='[2]',source_quote=ES[1].text)]),
])
def test_unverified_mapping_cannot_add_citations(changes):
    result,s=run(payload(**changes))
    assert result is DRAFT
    assert s.last_summary['status']=='incomplete'

def test_duplicate_mapping_not_silently_merged():
    p=payload();p.comparison_checks.append(p.comparison_checks[0])
    assert run(p)[0] is DRAFT

def test_missing_mapping_marks_incomplete():
    p=payload();p.comparison_checks=[]
    result,s=run(p)
    assert result is DRAFT and s.last_summary['status']=='incomplete'

def test_already_cited_no_edit():
    p=payload();d=replace(DRAFT,claims=(replace(DRAFT.claims[0],citation_refs=('[1]','[2]')),))
    mod.prepare_payload(p,d,ES)
    assert not p.issues

def test_same_source_two_facts_does_not_invent_second_reference():
    p=payload();p.comparison_checks[0].facts=[p.comparison_checks[0].facts[1]]*2
    assert run(p)[0] is DRAFT


def test_provider_passes_comparison_indexes_and_required_schema():
    from types import SimpleNamespace as NS
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=payload().model_dump_json()))])
    provider=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v2_comparison')
    result=provider.review('Q',ES,DRAFT)
    assert result.comparison_checks[0].statement_supported
    assert 'comparison_claim_indexes: [0]' in calls[0]['messages'][1]['content']
    assert 'statement_supported' in calls[0]['messages'][0]['content']


def test_snapshot_records_comparison_module(tmp_path):
    from literature_rag.diagnostics import configuration_snapshot
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v2_comparison\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['evidence_review']['version']==mod.VERSION
    assert 'application/review_diagnosis_comparison.py' in c['pipeline_source_files']


def test_invalid_response_logs_field_types_without_rejected_values():
    from types import SimpleNamespace as NS
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    from literature_rag.domain.errors import ProviderResponseError
    raw=json.loads(payload().model_dump_json());raw['issues']=[{'claim_index':'PRIVATE_REJECTED_VALUE'}]
    def create(**kwargs):
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(raw)))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v2_comparison')
    with pytest.raises(ProviderResponseError):p.review('Q',ES,DRAFT)
    assert p.last_model_info['response_validation']
    assert 'PRIVATE_REJECTED_VALUE' not in json.dumps(p.last_model_info)
