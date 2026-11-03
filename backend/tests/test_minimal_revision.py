"""Opt-in edit gate fails closed without discarding independent verified repairs."""
import json
import pytest

from literature_rag.application.review_diagnosis_v3 import parse_response
from literature_rag.config import Settings
from tests.test_corrective_review import controller, requirement
from tests.test_evidence_review import DRAFT, SOURCES, proposal


def run(checks, issues=None):
    issues = issues or [proposal().issues[0].model_dump()]
    payload = parse_response(json.dumps(dict(issues=issues, claim_checks=[], revision_checks=checks,
        requirements=[requirement('edit', issue_indexes=list(range(len(issues))))])))
    service, provider, _ = controller([payload])
    provider.diagnosis_version = 'v3'
    return service.review('Why?', SOURCES, DRAFT), service


def check(index=0, verdict='supported'):
    return dict(issue_index=index, verdict=verdict, reason='Only restores the tentative source wording.')


@pytest.mark.parametrize('checks', [None, [], [check(verdict='overstated')],
    [check(verdict='unclear')], [check(), check()], [dict(issue_index=0, verdict='supported')]])
def test_missing_invalid_duplicate_or_negative_check_retains_original(checks):
    result, service = run(checks)
    assert result is DRAFT
    assert service.last_summary['status'] == 'incomplete'
    assert service.last_trace['rounds'][0]['rejected_issues']


def test_positive_check_preserves_unaffected_claim():
    result, service = run([check()])
    assert 'might' in result.claims[0].text
    assert result.claims[1] == DRAFT.claims[1]
    assert service.last_summary['status'] == 'completed'
    assert service.last_trace['rounds'][0]['revision_checks'] == [check()]


def test_one_invalid_check_does_not_block_independent_valid_edit():
    issues = [proposal().issues[0].model_dump(), proposal(claim_index=1).issues[0].model_dump()]
    result, service = run([check(), check(1, 'overstated')], issues)
    assert 'might' in result.claims[0].text
    assert result.claims[1] == DRAFT.claims[1]
    trace = service.last_trace['rounds'][0]
    assert trace['accepted_issue_indexes'] == [0]
    assert trace['rejected_issues'] == [dict(issue_index=1, reason_code='revision_not_supported')]


def test_positive_model_check_cannot_override_fake_source_quote():
    bad = proposal(basis=[dict(kind='text', ref='[1]', quote='Invented source quotation')]).issues[0].model_dump()
    result, service = run([check()], [bad])
    assert result is DRAFT
    assert service.last_trace['rounds'][0]['rejected_issues'][0]['reason_code'] == 'quote_not_in_actual_evidence'


def test_default_is_unchanged():
    assert Settings.model_fields['corrective_review_version'].default == 'v1'


def test_v3_snapshot_records_inherited_checks_and_own_source(tmp_path):
    from literature_rag.diagnostics import configuration_snapshot
    p=tmp_path/'settings.env'
    p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
        'RAG_CORRECTIVE_REVIEW_VERSION=v3\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\n'
        'RAG_LLM_PROVIDER=deepseek\nRAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
    result=configuration_snapshot(p)
    for file in ('review_diagnosis_v2.py','review_diagnosis_v3.py','numeric_crosscheck.py'):
        assert 'application/'+file in result['pipeline_source_files']
    assert result['evidence_review']['numeric_crosscheck']
    assert 'not independent' in result['evidence_review']['revision_checks']
    assert 'PRIVATE_TEST' not in json.dumps(result)
