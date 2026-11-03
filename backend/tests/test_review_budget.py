"""Supplement-first commits preserve original citations and survive second-review failure."""
from dataclasses import replace
import pytest
from literature_rag.application.context import ContextOptions
from literature_rag.domain.errors import ProviderError
from tests.test_corrective_review import controller, requirement, make_reader, chunk
from tests.test_review_edit_binding import edit, payload
from tests.test_evidence_review import DRAFT,SOURCES


def setup(version='v2_budget', oversized=False):
    sources=[replace(SOURCES[0],text=SOURCES[0].text+'a'*140),
             replace(SOURCES[0],ref='[2]',chunk_id='spare',text='A new method explanation. '+'b'*175)]
    reader,_=make_reader([chunk(text='z'*(600 if oversized else 200))],options=ContextOptions(True,1,700,512))
    first=edit(basis=[dict(kind='text',ref='[2]',quote='A new method explanation.')],
        replacement_claims=[dict(text='A new method explanation.',citation_refs=['[2]'])])
    response=payload([first],requirements=[requirement('edit',issue_indexes=[0]),requirement('lookup',id='R2')])
    service,provider,_=controller([response,ProviderError('PRIVATE')],reader)
    provider.diagnosis_version=version
    return service,provider,sources


def test_new_reference_cannot_evict_original_proof_and_second_failure_is_safe():
    service,provider,sources=setup()
    result=service.review('Q',sources,DRAFT)
    assert len(provider.calls)==2
    assert provider.calls[1][2] is DRAFT
    assert result is DRAFT
    assert service.last_evidences[0]==sources[0]
    assert [e.ref for e in service.last_evidences]==['[1]','[3]']
    commit=service.last_trace['first_round_commit']
    assert commit['deferred_issues'][0]['missing_refs']==['[2]']
    assert service.last_summary['status']=='incomplete'
    assert {r['id'] for r in service.last_summary['unresolved']}=={'R1','R2'}
    ledger=provider.calls[1][3]['context']['requirements']
    assert all('[2]' not in r['evidence_refs'] for r in ledger)


def test_no_room_keeps_provisional_answer_and_reports_found_but_blocked():
    service,provider,sources=setup(oversized=True)
    result=service.review('Q',sources,DRAFT)
    assert len(provider.calls)==1
    assert result.claims[0].citation_refs==('[2]',)
    assert service.last_evidences==sources
    assert service.last_trace['stop_reason']=='supplement_evidence_budget_blocked'
    assert '已找到' in service.last_summary['unresolved'][0]['reason']


def test_no_gap_does_not_defer_valid_edit():
    service,provider,_=controller([payload([edit()])]);provider.diagnosis_version='v2_budget'
    result=service.review('Q',SOURCES,DRAFT)
    assert 'might' in result.answer
    assert len(provider.calls)==1 and 'first_round_commit' not in service.last_trace


def test_compatible_repair_survives_supplement_and_second_failure():
    reader,_=make_reader([chunk()])
    first=payload([edit()],requirements=[requirement('edit',issue_indexes=[0]),requirement('lookup',id='R2')])
    service,provider,_=controller([first,ProviderError('PRIVATE')],reader);provider.diagnosis_version='v2_budget'
    result=service.review('Q',SOURCES,DRAFT)
    assert 'might' in result.answer
    assert service.last_trace['first_round_commit']['accepted_issue_indexes']==[0]
    assert [r['id'] for r in service.last_summary['unresolved']]==['R2']


def test_default_and_baseline_do_not_enable_supplement_first():
    from literature_rag.application.review_diagnosis import diagnosis_contract
    from literature_rag.config import Settings
    assert Settings.model_fields['corrective_review_version'].default=='v1'
    for v in ['v1','v2','v3','v2_bound']:
        assert not getattr(diagnosis_contract(v),'prioritize_supplement',False)


def test_snapshot_and_prompt_do_not_change_model_instructions(tmp_path):
    from literature_rag.application.review_diagnosis import diagnosis_contract
    from literature_rag.diagnostics import configuration_snapshot
    assert diagnosis_contract('v2_budget').DIAGNOSTIC_PROMPT==diagnosis_contract('v2_bound').DIAGNOSTIC_PROMPT
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v2_budget\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['evidence_review']['supplement_policy']
    for f in ['review_diagnosis_bound.py','review_diagnosis_budget.py','review_commit.py']:
        assert 'application/'+f in c['pipeline_source_files']
