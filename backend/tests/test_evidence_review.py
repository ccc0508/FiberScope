"""Source provenance, conservative edits, review failure isolation and actual image delivery."""
from dataclasses import asdict
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from literature_rag.application.answer_question import AnswerService
from literature_rag.application.citations import CitationValidator,RecordingCitationValidator
from literature_rag.application.evidence_review import EvidenceReviewService,ReviewPayload,apply_edits,ReviewRejected,SYSTEM_PROMPT
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import ProviderError,ProviderResponseError
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim,Evidence
from tests.test_visual_evidence import fixture,PNG


DRAFT=GeneratedAnswer('The effect was established. [1]\nA retained fact. [1]',(
    GeneratedClaim('The effect was established.',('[1]',)),GeneratedClaim('A retained fact.',('[1]',))))
SOURCES=[Evidence('[1]','c','doc','paper.pdf',1,1,'The effect might be explained by hydration. A retained fact.',.9)]


def proposal(**overrides):
    item=dict(claim_index=0,category='uncertainty',problem='The tentative explanation became certain.',
        basis=[dict(kind='text',ref='[1]',quote='might be explained by hydration')],
        replacement_claims=[dict(text='The effect might be explained by hydration.',citation_refs=['[1]'])])
    item.update(overrides)
    return ReviewPayload.model_validate(dict(issues=[item]))


def provider(payload):
    return NS(review=lambda *args:payload,last_usage=dict(total_tokens=12),last_latency_ms=10,last_model_info=dict(returned_model='deepseek-flash'))


def test_verified_edit_preserves_untouched_claim_and_saves_original_and_final():
    service=EvidenceReviewService(provider(proposal()))
    result=service.review('Why?',SOURCES,DRAFT)
    assert result.claims[1] is DRAFT.claims[1]
    assert result.claims[0].text.startswith('The effect might')
    assert CitationValidator().validate(result,SOURCES).answer==result.answer
    trace=service.last_trace
    assert trace['status']=='revised' and trace['accepted'] and trace['api_calls']==1
    assert trace['draft']==asdict(DRAFT) and trace['final']==asdict(result)
    assert trace['verified_basis'][0]['quote']=='might be explained by hydration'


def test_keep_is_byte_identical_and_does_not_expand_correct_answer():
    service=EvidenceReviewService(provider(ReviewPayload(issues=[])))
    assert service.review('Question',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['status']=='unchanged' and service.last_trace['issues']==[]


def test_insufficient_http_budget_skips_review_and_keeps_valid_answer():
    p=NS(review=lambda *_:pytest.fail('no paid call'),timeout_seconds=120)
    service=EvidenceReviewService(p,deadline=0)
    assert service.review('Question',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['api_calls']==0 and service.last_trace['status']=='skipped'


def test_token_exhaustion_is_recorded_without_false_review_success():
    def create(**_):
        return NS(model='deepseek-flash',usage=NS(prompt_tokens=10,completion_tokens=16384,total_tokens=16394),
            choices=[NS(finish_reason='length',message=NS(content=''))])
    p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))))
    service=EvidenceReviewService(p)
    assert service.review('Question',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['reason_code']=='review_output_truncated'
    assert service.last_trace['usage']['total_tokens']==16394


@pytest.mark.parametrize('overrides,reason',[
    (dict(basis=[dict(kind='text',ref='[1]',quote='This passage does not exist')]),'quote_not_in_actual_evidence'),
    (dict(claim_index=20),'invalid_or_duplicate_claim_index'),
    (dict(basis=[dict(kind='text',ref='[2]',quote='might be explained by hydration')]),'unknown_basis_reference'),
    (dict(replacement_claims=[dict(text='Changed',citation_refs=['[2]'])]),'unknown_replacement_reference'),
    (dict(basis=[dict(kind='context')]),'context_cannot_establish_scientific_change'),
    (dict(claim_index=None,replacement_claims=[]),'append_cannot_be_empty'),
])
def test_invalid_proposals_retain_original_with_specific_reason(overrides,reason):
    service=EvidenceReviewService(provider(proposal(**overrides)))
    assert service.review('Question',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['status']=='rejected' and service.last_trace['reason_code']==reason
    assert service.last_trace['accepted'] is False and service.last_trace['issues']


def test_duplicate_changes_and_borrowing_an_uncited_source_are_rejected():
    p=proposal();p.issues.append(p.issues[0])
    with pytest.raises(ReviewRejected,match='invalid_or_duplicate_claim_index'):apply_edits(p,DRAFT,SOURCES)
    es=[*SOURCES,Evidence('[2]','c2','doc','paper.pdf',2,2,'The effect might be explained by hydration.',.9)]
    p=proposal(basis=[dict(kind='text',ref='[2]',quote='might be explained by hydration')])
    with pytest.raises(ReviewRejected,match='basis_not_cited'):apply_edits(p,DRAFT,es)


def test_condition_can_be_appended_with_source_basis_and_comparison_symbols_are_preserved():
    from literature_rag.application.evidence_review import normalized_quote
    p=proposal(claim_index=None,category='conditions')
    result,_=apply_edits(p,DRAFT,SOURCES)
    assert result.claims[:2]==DRAFT.claims and len(result.claims)==3
    assert normalized_quote('p<0.05 and <sup>m</sup>')=='p<0.05andm'


def test_invalid_revised_claim_does_not_trigger_primary_generation_retry():
    p=proposal(replacement_claims=[dict(text='An inline reference [1]',citation_refs=['[1]'])])
    reviewer=EvidenceReviewService(provider(p));calls=[]
    generator=NS(model_name='deepseek-flash',generate=lambda *args:(calls.append(args) or DRAFT))
    retriever=NS(retrieve=lambda *args:SOURCES);validator=RecordingCitationValidator(lambda:len(calls))
    service=AnswerService(retriever,generator,validator,reviewer=reviewer)
    answer=service.answer('Question',8,.35)
    assert len(calls)==1 and len(validator.snapshot()['attempts'])==1
    assert answer.answer==CitationValidator().validate(DRAFT,SOURCES).answer
    assert reviewer.last_trace['status']=='rejected' and reviewer.last_trace['citation_rule']=='inline_claim_reference'


def test_provider_error_does_not_escape_or_mark_review_success():
    def fail(*_):raise ProviderError('PRIVATE_PROVIDER_RESPONSE')
    p=NS(review=fail,last_usage=None,last_model_info=None,last_latency_ms=90,last_api_calls=1,last_http_status=402)
    service=EvidenceReviewService(p)
    assert service.review('Question',SOURCES,DRAFT) is DRAFT
    assert service.last_trace['status']=='failed' and service.last_trace['http_status']==402
    assert 'PRIVATE_PROVIDER_RESPONSE' not in json.dumps(service.last_trace)


def test_review_never_runs_for_no_evidence_or_invalid_final_draft():
    def forbidden(*_):pytest.fail('review must not run')
    reviewer=NS(review=forbidden)
    generator=NS(model_name='fixture',generate=lambda *args:DRAFT)
    assert AnswerService(NS(retrieve=lambda *args:[]),generator,CitationValidator(),reviewer).answer('Q',8,.35).status.value=='refused'
    invalid=GeneratedAnswer('No answer reference',DRAFT.claims)
    generator.generate=lambda *args:invalid
    assert AnswerService(NS(retrieve=lambda *args:SOURCES),generator,CitationValidator(),reviewer).answer('Q',8,.35).status.value=='refused'


def test_accepted_revision_is_actual_displayed_answer_and_final_claims():
    reviewer=EvidenceReviewService(provider(proposal()))
    service=AnswerService(NS(retrieve=lambda *args:SOURCES),NS(model_name='deepseek-flash',generate=lambda *args:DRAFT),
        CitationValidator(),reviewer)
    answer=service.answer('Question',8,.35)
    assert 'might be explained' in answer.answer and 'established' not in answer.answer
    assert service.last_generated_answer.claims[0].text.startswith('The effect might')


def test_reviewer_sees_same_verified_pixels_high_and_no_gold(tmp_path):
    catalog,es,_=fixture(tmp_path);es,_=catalog.attach(es[:1],es[:1],'Figure 1');requests=[]
    def create(**kwargs):
        requests.append(kwargs)
        return NS(model='deepseek-flash',usage=NS(prompt_tokens=20,completion_tokens=3,total_tokens=23),
            choices=[NS(message=NS(content='{"issues": []}'))])
    r=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),
        visual_root=tmp_path,thinking_enabled=True,reasoning_effort='high')
    assert r.review('A user question',es,DRAFT).issues==[]
    q=requests[0];assert q['model']=='deepseek-flash' and q['reasoning_effort']=='high'
    blocks=q['messages'][1]['content'];image=next(x for x in blocks if x['type']=='image_url')
    assert base64.b64decode(image['image_url']['url'].split(',',1)[1])==PNG
    assert DRAFT.claims[0].text in blocks[0]['text'] and 'key_point_scores' not in blocks[0]['text']
    assert r.last_model_info['image_count']==1 and 'base64' not in json.dumps(r.last_model_info)


def test_image_basis_must_belong_to_actual_reference(tmp_path):
    catalog,es,assets=fixture(tmp_path);es,_=catalog.attach(es[:1],es[:1],'Figure 1')
    good=proposal(basis=[dict(kind='image',ref='[1]',asset_id=assets[0].id,observation='Visible source')])
    result,verified=apply_edits(good,DRAFT,es,tmp_path)
    assert verified[0]['sha256']==assets[0].sha256
    bad=proposal(basis=[dict(kind='image',ref='[1]',asset_id=assets[-1].id,observation='Different source')])
    with pytest.raises(ReviewRejected,match='image_not_attached'):apply_edits(bad,DRAFT,es,tmp_path)


@pytest.mark.parametrize('response',[None,'{"issues": [], "score": 100}','{"issues": "all good"}'])
def test_malformed_review_response_is_redacted(response):
    def create(**_):
        return NS(usage=None,model='deepseek-flash',choices=[NS(message=NS(content=response))])
    client=NS(chat=NS(completions=NS(create=create)))
    reviewer=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=client)
    with pytest.raises(ProviderResponseError):reviewer.review('Question',SOURCES,DRAFT)


def test_enabled_review_is_fingerprinted_and_only_allows_deepseek(tmp_path):
    with pytest.raises(ValidationError,match='DeepSeek Flash'):
        Settings(_env_file=None,evidence_review_enabled=True,llm_provider='openai',llm_model='gpt-6-astra',llm_api_key='PRIVATE')
    p=tmp_path/'settings.env';p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_KEY_CANARY\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['evidence_review']['max_review_calls']==1 and 'PRIVATE_KEY_CANARY' not in json.dumps(c)
    assert 'application/evidence_review.py' in c['pipeline_source_files']


def test_worker_returns_revised_claims_and_history_preserves_review(monkeypatch,tmp_path,capsys):
    import literature_worker
    import literature_rag.config as config
    import literature_rag.diagnostics as diagnostics
    import literature_rag.adapters.sqlite.metadata_store as metadata
    import literature_rag.adapters.chroma.vector_store as vectors
    import literature_rag.adapters.providers.openai as embeddings
    import literature_rag.adapters.providers.deepseek as generators
    import literature_rag.adapters.providers.evidence_review as reviews
    import literature_rag.application.retrieve as retrieval
    from app.qa_history import HistoryStore
    (tmp_path/'chroma').mkdir();(tmp_path/'chroma/chroma.sqlite3').touch()
    settings=Settings(_env_file=None,llm_provider='deepseek',llm_model='deepseek-flash',llm_api_key='PRIVATE',
        embedding_model='fixture',embedding_dimensions=3,embedding_api_key='PRIVATE',evidence_review_enabled=True)
    class Metadata:
        def __init__(self,*_):pass
        def list_documents(self):return []
    class Retriever:
        def __init__(self,*args,**kwargs):
            self.last_seed_evidences=SOURCES;self.last_context_diagnostics={}
        def retrieve(self,*_):return SOURCES
    monkeypatch.setattr(config,'Settings',lambda **_:settings)
    monkeypatch.setattr(diagnostics,'configuration_snapshot',lambda *_:dict(evidence_review=dict(enabled=True)))
    monkeypatch.setattr(metadata,'SqliteMetadataStore',Metadata)
    monkeypatch.setattr(vectors,'ChromaVectorStore',lambda *_:NS())
    monkeypatch.setattr(embeddings,'OpenAIEmbedder',lambda *_:NS(last_usage=None))
    monkeypatch.setattr(generators,'DeepSeekGenerator',lambda *args,**kwargs:NS(model_name='deepseek-flash',generate=lambda *_:DRAFT))
    monkeypatch.setattr(reviews,'DeepSeekEvidenceReviewer',lambda *args,**kwargs:provider(proposal()))
    monkeypatch.setattr(retrieval,'RetrievalService',Retriever)
    monkeypatch.setattr('sys.stdin',io.StringIO(json.dumps(dict(question='Question',data_dir=str(tmp_path)))))
    literature_worker.main();body=json.loads(capsys.readouterr().out)
    assert 'might be explained' in body['claims'][0]['text']
    assert 'established' not in body['answer'] and body['evidence_review']['status']=='revised'
    assert len(body['generation_calls'])==1 and body['evidence_review']['api_calls']==1
    store=HistoryStore(tmp_path/'history.sqlite3');store.initialize();owner,_=store.session(None)
    row=store.create(owner,'unique','Question',body['configuration']);store.complete(row['id'],body,20)
    saved=store.get('another_visitor',row['id'])['result']
    assert saved['evidence_review']==body['evidence_review'] and saved['claims']==body['claims']
