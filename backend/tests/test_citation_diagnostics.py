"""Synthetic failures only; no model calls or retrospective benchmark repairs."""
from dataclasses import replace
from hashlib import sha256
import io
import json
from types import SimpleNamespace as NS

import pytest

from literature_rag.application.answer_question import AnswerService, CITATION_RETRY_FEEDBACK
from literature_rag.application.citations import CitationValidator, RecordingCitationValidator
from literature_rag.domain.errors import CitationValidationError, ProviderError, ProviderResponseError
from literature_rag.domain.models import GeneratedAnswer, GeneratedClaim
from tests.test_literature_answers import SequenceGenerator, StubRetriever, make_evidence


VALID=GeneratedAnswer('Synthetic answer [1]',(GeneratedClaim('Synthetic claim',('[1]',)),))


@pytest.mark.parametrize('draft,evidences,code,field',[
    (VALID,[make_evidence('[2]')],'evidence_reference_sequence','evidences.ref'),
    (replace(VALID,answer=' '),[make_evidence()],'empty_answer_or_claims','answer'),
    (replace(VALID,claims=()),[make_evidence()],'empty_answer_or_claims','claims'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim(' ',('[1]',)),)),[make_evidence()],'empty_claim_text','claims[0].text'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('First\nSecond',('[1]',)),)),[make_evidence()],'multiline_claim_text','claims[0].text'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Claim [1]',('[1]',)),)),[make_evidence()],'inline_claim_reference','claims[0].text'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Claim',()),)),[make_evidence()],'missing_claim_reference','claims[0].citation_refs'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Claim',(2,)),)),[make_evidence()],'non_string_claim_reference','claims[0].citation_refs'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Claim',('[1]','[1]')),)),[make_evidence()],'duplicate_claim_reference','claims[0].citation_refs'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Claim',('[99]',)),)),[make_evidence()],'unknown_claim_reference','claims[0].citation_refs'),
    (GeneratedAnswer('Answer [1]',(GeneratedClaim('Same',('[1]',)),GeneratedClaim('Same',('[1]',)))),[make_evidence()],'duplicate_claim','claims[1].text'),
    (replace(VALID,answer='Answer ［１］'),[make_evidence()],'noncanonical_answer_reference','answer'),
    (replace(VALID,answer='Answer'),[make_evidence()],'missing_answer_reference','answer'),
    (replace(VALID,answer='Answer [99]'),[make_evidence()],'unknown_answer_reference','answer'),
    (replace(VALID,answer='Answer [2]'),[make_evidence(),make_evidence('[2]','chk2')],'undeclared_answer_reference','answer'),
])
def test_each_rule_records_original_draft_field_and_stable_code(draft,evidences,code,field):
    recorder=RecordingCitationValidator()
    with pytest.raises(CitationValidationError) as error:
        recorder.validate(draft,evidences)
    trace=recorder.snapshot()
    row=trace['attempts'][0]
    assert error.value.rule_code==row['rule_code']==code and row['field']==field
    assert row['draft']['answer']==draft.answer
    assert row['draft']['claims']==[dict(text=c.text,citation_refs=list(c.citation_refs)) for c in draft.claims]
    assert row['draft_sha256']==sha256(json.dumps(row['draft'],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    assert trace['first_failure_only'] and trace['scope']=='structural_validation_only'
    # Reading or mutating an export cannot overwrite the retained diagnostic snapshot.
    row['draft']['answer']='Changed outside recorder'
    assert recorder.snapshot()['attempts'][0]['draft']['answer']==draft.answer


@pytest.mark.parametrize('second', [VALID, replace(VALID,answer='Second failed draft')])
def test_retry_success_and_final_refusal_both_keep_failed_drafts_without_changing_behavior(second,caplog):
    bad=replace(VALID,answer='First failed draft')
    generator=SequenceGenerator([bad,second]);recorder=RecordingCitationValidator(attempt_number=lambda:len(generator.calls))
    service=AnswerService(StubRetriever([make_evidence()]),generator,recorder)
    result=service.answer('Synthetic question?',8,.35)
    attempts=recorder.snapshot()['attempts']
    assert [a['attempt'] for a in attempts]==[1,2]
    assert attempts[0]['draft']['answer']=='First failed draft'
    assert generator.calls[1][2]==CITATION_RETRY_FEEDBACK
    if second==VALID:
        assert result.status=='answered' and result.answer=='Synthetic claim [1]'
        assert attempts[1]['status']=='passed' and attempts[1]['draft'] is None
    else:
        assert result.status=='refused' and result.reason_code=='citation_validation_failed'
        assert result.rationale==result.citations==()
        assert attempts[1]['draft']['answer']=='Second failed draft'
    assert 'First failed draft' not in caplog.text


def test_generation_error_does_not_invent_a_draft_or_lose_real_attempt_number(caplog):
    bad=replace(VALID,answer='Structured draft')
    generator=SequenceGenerator([ProviderResponseError('PRIVATE_PROVIDER_BODY'),bad])
    recorder=RecordingCitationValidator(attempt_number=lambda:len(generator.calls))
    result=AnswerService(StubRetriever([make_evidence()]),generator,recorder).answer('Question?',8,.35)
    trace=recorder.snapshot()
    assert result.reason_code=='citation_validation_failed'
    assert len(trace['attempts'])==1 and trace['attempts'][0]['attempt']==2
    assert 'PRIVATE_PROVIDER_BODY' not in json.dumps(trace) and 'PRIVATE_PROVIDER_BODY' not in caplog.text
    # A fresh request never inherits the previous failed draft.
    fresh=RecordingCitationValidator()
    assert fresh.snapshot()['attempts']==[]
    assert fresh.validate(VALID,[make_evidence()])==CitationValidator().validate(VALID,[make_evidence()])


@pytest.mark.parametrize('last',[VALID,replace(VALID,answer='Still missing citation'),ProviderError('PRIVATE_PROVIDER_BODY')])
def test_worker_serializes_failed_drafts_even_after_success_refusal_or_provider_failure(tmp_path,monkeypatch,capsys,last):
    import literature_worker
    import literature_rag.config as config
    import literature_rag.diagnostics as diagnostics
    import literature_rag.adapters.sqlite.metadata_store as metadata
    import literature_rag.adapters.chroma.vector_store as vectors
    import literature_rag.adapters.providers.openai as providers
    import literature_rag.application.retrieve as retrieval
    (tmp_path/'chroma').mkdir();(tmp_path/'chroma/chroma.sqlite3').touch()
    secret=NS(get_secret_value=lambda:'SYNTHETIC_ENV_SECRET')
    settings=NS(embedding_provider='openai',llm_provider='openai',embedding_model='fixture',embedding_dimensions=3,
        embedding_api_key=secret,llm_api_key=secret,llm_model='fixture',embedding_base_url='https://example.invalid',
        llm_base_url='https://example.invalid',llm_reasoning_effort=None,llm_timeout_seconds=60,
        llm_actor_authorization=None,llm_proxy_url=None,table_retrieval_enabled=False,visual_retrieval_enabled=False,
        answer_guidance_enabled=False,query_rewrite_enabled=False,rerank_enabled=False,
        context_expansion_enabled=False,context_neighbor_radius=1,context_max_evidence_chars=8000,
        context_max_total_chars=24000,context_expansion_strategy='neighbor',top_k=8,min_score=.35,
        visual_max_images=4,visual_max_total_bytes=12000000)
    generator=SequenceGenerator([replace(VALID,answer='First worker draft'),last])
    class FakeMetadata:
        def __init__(self,*_):pass
        def list_documents(self):return [NS(id='doc-chk1',filename='paper.pdf',file_hash='f'*64,status=NS(value='completed'))]
    class FakeRetriever:
        def __init__(self,*args,**kwargs):
            self.last_seed_evidences=[make_evidence()];self.last_context_diagnostics={}
        def retrieve(self,*args):return [make_evidence()]
    monkeypatch.setattr(config,'Settings',lambda **_:settings)
    monkeypatch.setattr(diagnostics,'configuration_snapshot',lambda *_:dict(pipeline_version='synthetic-test'))
    monkeypatch.setattr(metadata,'SqliteMetadataStore',FakeMetadata)
    monkeypatch.setattr(vectors,'ChromaVectorStore',lambda *_:NS())
    monkeypatch.setattr(providers,'OpenAIEmbedder',lambda *_:NS(last_usage=None))
    monkeypatch.setattr(providers,'OpenAIGenerator',lambda *args,**kwargs:generator)
    monkeypatch.setattr(retrieval,'RetrievalService',FakeRetriever)
    monkeypatch.setattr('sys.stdin',io.StringIO(json.dumps(dict(question='Synthetic question?',data_dir=str(tmp_path)))))
    literature_worker.main()
    body=json.loads(capsys.readouterr().out)
    trace=body['citation_validation']
    assert trace['attempts'][0]['rule_code']=='missing_answer_reference'
    assert trace['attempts'][0]['draft']['answer']=='First worker draft'
    assert body['status']==('failed' if isinstance(last,Exception) else 'answered' if last==VALID else 'refused')
    assert 'First worker draft' not in body['answer'] and 'SYNTHETIC_ENV_SECRET' not in json.dumps(body)
    assert 'PRIVATE_PROVIDER_BODY' not in json.dumps(body)
    assert len(body['generation_calls'])==2
