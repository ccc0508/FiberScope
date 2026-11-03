import json
from types import SimpleNamespace as NS
import pytest
from literature_rag.application import review_diagnosis_relation as full
from literature_rag.application import review_diagnosis_relation_compact as compact
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from tests.test_review_relation import relation
from tests.test_review_edit_binding import edit
from tests.test_corrective_review import requirement, controller
from tests.test_evidence_review import DRAFT, SOURCES


def payload(checks, issues):
    return dict(issues=issues, requirements=[requirement('edit', issue_indexes=[0]) if issues else requirement()],
                claim_checks=[], relation_checks=checks)


def shorten(check):
    return {k:v for k,v in check.items() if k in compact.RelationCheck.model_fields}


@pytest.mark.parametrize('checks,issues',[
    ([], []),
    ([], [edit()]),
    ([relation(claim_index=None,issue_index=0,replacement_index=0)], [edit()]),
    ([relation(claim_index=None,issue_index=0,replacement_index=0,verdict='overstated')], [edit()]),
    ([relation(claim_index=None,issue_index=0,replacement_index=0,source_quote='Invented quotation')], [edit()]),
    ([relation(issue_index=9)], []),
])
def test_shorter_records_preserve_gate_decisions(checks, issues):
    a=full.parse_response(json.dumps(payload(checks,issues)))
    b=compact.parse_response(json.dumps(payload([shorten(c) for c in checks],issues)))
    assert full.inspect_diagnosis(a,DRAFT,SOURCES)==compact.inspect_diagnosis(b,DRAFT,SOURCES)
    outputs=[]
    for version,p in [('v2_relation',a),('v2_relation_compact',b)]:
        service,provider,_=controller([p]);provider.diagnosis_version=version
        outputs.append(service.review('Q',SOURCES,DRAFT))
    assert outputs[0]==outputs[1]


def test_scope_and_judgment_instructions_preserved():
    assert compact.is_relation is full.is_relation
    assert compact.critical_claim_indexes is full.critical_claim_indexes
    assert compact.validate_edit_semantics is full.validate_edit_semantics
    prefix='Return relation_checks alongside issues, requirements and claim_checks. Shape:'
    assert compact.DIAGNOSTIC_PROMPT.split(prefix)[0]==full.DIAGNOSTIC_PROMPT.split(prefix)[0]
    assert compact.DIAGNOSTIC_PROMPT.split('Original checks use')[1]==full.DIAGNOSTIC_PROMPT.split('Original checks use')[1]


def test_missing_fields_or_long_reason_not_silently_accepted():
    for c in [dict(claim_index=0),shorten(relation(reason='x'*201))]:
        parsed=compact.parse_response(json.dumps(payload([c],[])))
        assert not compact.inspect_diagnosis(parsed,DRAFT,SOURCES)['valid']


def test_provider_compact_wire_format_and_old_contract_unchanged():
    calls=[]
    raw=payload([shorten(relation(claim_index=None,issue_index=0,replacement_index=0))],[edit()])
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(raw)))])
    provider=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),
        diagnostic=True,diagnosis_version='v2_relation_compact')
    result=provider.review('Q',SOURCES,DRAFT)
    compact.validate_edit_target(result,0,DRAFT)
    compact.validate_edit_semantics(result,0,DRAFT,SOURCES)
    assert calls[0]['max_tokens']==32768
    assert 'relation_claim_indexes:' in calls[0]['messages'][1]['content']
    assert 'original_text' in calls[0]['messages'][0]['content']
    assert 'source_cause' in full.RelationCheck.model_fields
    assert 'source_cause' not in compact.RelationCheck.model_fields


def test_snapshot_and_default(tmp_path):
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    assert Settings.model_fields['corrective_review_version'].default=='v1'
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v2_relation_compact\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['evidence_review']['version']==compact.VERSION
    assert c['evidence_review']['relation_audit'] and c['evidence_review']['supplement_policy']
    assert 'application/review_diagnosis_relation_compact.py' in c['pipeline_source_files']
