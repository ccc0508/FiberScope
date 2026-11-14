"""Boundaries and provenance of diagnosis -> one supplemental read -> final review."""
from dataclasses import asdict, replace
import json
from time import perf_counter
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from literature_rag.application.answer_question import AnswerService
from literature_rag.application.citations import CitationValidator
from literature_rag.application.context import ContextOptions
from literature_rag.application.corrective_review import CorrectiveReviewService, TargetedEvidenceReader
from literature_rag.application.evidence_review import EvidenceReviewService, ReviewRejected
from literature_rag.application.review_diagnosis import DiagnosticPayload, validate_diagnosis
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from literature_rag.domain.errors import ProviderError, CitationValidationError
from literature_rag.domain.models import Chunk, Evidence, GeneratedAnswer, GeneratedClaim, VectorMatch
from tests.test_evidence_review import SOURCES, DRAFT, proposal


def requirement(status='covered', **kwargs):
    base = dict(id='R1', requirement='Explain the reported effect and its interpretation.',
        status=status, evidence_refs=['[1]'], claim_indexes=[0], issue_indexes=[], reason='Source-based diagnosis.')
    if status == 'lookup':
        base['lookup'] = dict(query='measurement method and interpretation', document_ref='[1]', target='methods', locator='')
    base.update(kwargs)
    return base


def payload(status='covered', issues=None, **kwargs):
    return DiagnosticPayload.model_validate(dict(requirements=[requirement(status, **kwargs)], issues=issues or []))


class Reviewer:
    diagnostic = True
    timeout_seconds = 120

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.last_api_calls = 0
        self.last_usage = None

    def review(self, question, evidences, draft, **kwargs):
        self.calls.append((question, evidences, draft, kwargs))
        self.last_api_calls = 1
        self.last_usage = dict(total_tokens=10)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class Reader:
    def __init__(self, new=True):
        self.calls = []
        self.new = new

    def read(self, *args):
        self.calls.append(args)
        self.last_trace = dict(added_refs=['[2]'] if self.new else [], status='sources_added' if self.new else 'no_new_source')
        return args[2] + ([Evidence('[2]', 'c2', 'doc', 'paper.pdf', 2, 2, 'It measures relative area, not an absolute count.', .8)] if self.new else [])


def controller(responses, reader=None, deadline=None):
    p = Reviewer(responses)
    r = reader or Reader()
    service = CorrectiveReviewService(EvidenceReviewService(p, deadline=deadline), r, deadline=deadline)
    return service, p, r


def test_covered_uses_one_review_no_lookup_and_keeps_draft_bytes():
    service, p, r = controller([payload()])
    assert service.review('Q', SOURCES, DRAFT) is DRAFT
    assert len(p.calls) == 1 and not r.calls
    assert service.last_summary['status'] == 'completed'
    assert service.last_trace['api_calls'] == 1


def test_available_evidence_is_edited_without_lookup():
    issue = proposal().issues[0].model_dump()
    service, p, r = controller([payload('edit', [issue], issue_indexes=[0])])
    result = service.review('Q', SOURCES, DRAFT)
    assert 'might' in result.claims[0].text and result.claims[1] == DRAFT.claims[1]
    assert not r.calls and len(p.calls) == 1


def test_gap_gets_one_lookup_and_second_review_without_primary_regeneration():
    issue = proposal(claim_index=None, category='measurement',
        basis=[dict(kind='text', ref='[2]', quote='relative area, not an absolute count')],
        replacement_claims=[dict(text='This is a relative area, not an absolute count.', citation_refs=['[2]'])]).issues[0].model_dump()
    service, p, reader = controller([payload('lookup'), payload('edit', [issue], issue_indexes=[0], evidence_refs=['[1]', '[2]'])])
    calls = []
    generator = NS(model_name='fixture', generate=lambda *args: calls.append(args) or DRAFT)
    answer_service = AnswerService(NS(retrieve=lambda *_: SOURCES), generator, CitationValidator(), service)
    answer = answer_service.answer('Q', 8, .35)
    assert len(calls) == 1 and len(p.calls) == 2 and len(reader.calls) == 1
    assert answer.citations[-1].chunk_id == 'c2' and answer.citations[-1].ref == '[2]'
    assert 'c2' in answer.retrieved_chunk_ids
    assert answer_service.last_evidences == service.last_evidences
    assert p.calls[1][0] == 'Q' and p.calls[1][3]['context']['remaining_lookup_actions'] == 0
    assert service.last_summary['status'] == 'completed'
    assert service.last_trace['usage']['total_tokens'] == 20
    assert service.last_trace['final_evidence'][1]['text'] == 'It measures relative area, not an absolute count.'


def test_no_new_source_stops_without_second_call_and_exposes_gap():
    service, p, _ = controller([payload('lookup')], Reader(False))
    assert service.review('Q', SOURCES, DRAFT) is DRAFT
    assert len(p.calls) == 1 and service.last_summary['status'] == 'unresolved'
    assert service.last_summary['unresolved'][0]['id'] == 'R1'


@pytest.mark.parametrize('second', [ProviderError('PRIVATE'), payload('lookup')])
def test_second_failure_or_recursive_request_stops_and_keeps_last_valid_answer(second):
    service, p, r = controller([payload('lookup'), second])
    assert service.review('Q', SOURCES, DRAFT) is DRAFT
    assert len(p.calls) == 2 and len(r.calls) == 1
    assert service.last_summary['status'] == 'incomplete'
    assert service.last_summary['unresolved']
    assert 'PRIVATE' not in json.dumps(service.last_trace)


def test_deadline_skips_without_paid_call():
    service, p, r = controller([], deadline=perf_counter()+1)
    assert service.review('Q', SOURCES, DRAFT) is DRAFT
    assert not p.calls and not r.calls and service.last_summary['status'] == 'incomplete'


def test_insufficient_supplement_budget_preserves_explicit_gap():
    service, p, r = controller([payload('lookup')], deadline=perf_counter()+23)
    service.review('Q', SOURCES, DRAFT)
    assert len(p.calls) == 1 and not r.calls
    assert service.last_trace['stop_reason'] == 'insufficient_correction_time'


def test_empty_coverage_or_unmapped_edit_is_invalid():
    with pytest.raises(ValidationError):
        DiagnosticPayload(issues=[], requirements=[])
    with pytest.raises(ReviewRejected, match='unmapped'):
        validate_diagnosis(payload(issues=[proposal().issues[0].model_dump()]), DRAFT, SOURCES)


def test_second_review_cannot_silently_drop_prior_requirement():
    with pytest.raises(ReviewRejected, match='lost_prior'):
        validate_diagnosis(payload(), DRAFT, SOURCES,
            dict(requirements=[requirement(id='R2')]))


def test_unverified_edit_is_not_labelled_resolved():
    issue = proposal(basis=[dict(kind='text', ref='[1]', quote='not found in the source')]).issues[0].model_dump()
    service, _, _ = controller([payload('edit', [issue], issue_indexes=[0])])
    assert service.review('Q', SOURCES, DRAFT) is DRAFT
    assert service.last_summary['status'] == 'incomplete'
    assert service.last_summary['unresolved']


def make_reader(chunks, *, cached=(), catalog=True, options=None):
    mapping = {c.id: dict(role_status='identified', content_role='body', section_path=['2. Methods']) for c in chunks}
    calls = []

    def rank(query, texts, **kwargs):
        calls.append(('rank', query, texts, kwargs))
        return [1-i*.01 for i in range(len(texts))]

    def embed(query, **kwargs):
        calls.append(('embed', query, kwargs)); return [1., 0.]

    def search(vector, k, **kwargs):
        calls.append(('search', kwargs))
        return [VectorMatch(c.id, .8) for c in chunks]

    retriever = NS(body_context_catalog=NS(chunks={c.id:c for c in chunks}, mapping=mapping) if catalog else None,
        last_candidate_evidences=list(cached), context_options=options or ContextOptions(True),
        embedder=NS(embed_query=embed, last_usage=dict(total_tokens=3)), vectors=NS(search=search),
        metadata=NS(get_chunks=lambda ids: [c for c in chunks if c.id in ids]),
        reranker=NS(rerank=rank), visual_catalog=None, visual_max_images=4, visual_max_total_bytes=12*1024*1024)
    return TargetedEvidenceReader(retriever), calls


def chunk(cid='c2', doc='doc', text='This method measures relative area and does not establish an absolute count.'):
    return Chunk(cid, doc, 'paper.pdf', 2, 2, 2, text, 20, 'fixture', kind='paragraph')


def test_location_read_reuses_catalog_without_embedding_and_enforces_document():
    reader, calls = make_reader([chunk(), chunk('evil', 'other')])
    result = reader.read('Q', [requirement('lookup')], SOURCES, DRAFT)
    assert {e.chunk_id for e in result} == {'c', 'c2'}
    assert [c[0] for c in calls] == ['rank']
    assert reader.last_trace['actions'][0]['strategy'] == 'catalog_location'


def test_gap_search_filters_before_vector_ranking_and_deduplicates_cache():
    cached = Evidence('', 'c2', 'doc', 'paper.pdf', 2, 2, chunk().text, .8)
    reader, calls = make_reader([chunk(), chunk('evil', 'other')], catalog=False, cached=[cached])
    result = reader.read('Q', [requirement('lookup')], SOURCES, DRAFT)
    assert {e.chunk_id for e in result} == {'c', 'c2'}
    assert next(c for c in calls if c[0] == 'search')[1] == {'document_ids':['doc']}
    assert len(next(c for c in calls if c[0] == 'rank')[2]) == 1
    assert reader.last_trace['query_embedding_calls'][0]['usage']['total_tokens'] == 3


def test_evidence_budget_evicts_only_uncited_preserves_old_ref_and_appends_without_reuse():
    first = replace(SOURCES[0], text='a'*200)
    spare = replace(first, ref='[2]', chunk_id='spare', text='b'*200)
    reader, _ = make_reader([chunk(text='z'*200)], options=ContextOptions(True, 1, 256, 512))
    result = reader.read('Q', [requirement('lookup')], [first, spare], DRAFT)
    assert [e.ref for e in result] == ['[1]', '[3]']
    assert result[0] is first and reader.last_trace['dropped_uncited_refs'] == ['[2]']
    assert sum(len(e.text) for e in result) <= 512
    answer = GeneratedAnswer('A [1]\nZ [3]', (GeneratedClaim('A', ('[1]',)), GeneratedClaim('Z', ('[3]',))))
    assert CitationValidator().validate(answer,result,allow_sparse_refs=True).citations[1].ref == '[3]'
    with pytest.raises(CitationValidationError):
        CitationValidator().validate(answer,result)
    bad = GeneratedAnswer('A [2]', (GeneratedClaim('A', ('[2]',)),))
    with pytest.raises(CitationValidationError,match='unknown'):
        CitationValidator().validate(bad,result,allow_sparse_refs=True)


def test_budget_never_silently_removes_cited_proof_or_cuts_table():
    first = replace(SOURCES[0], text='a'*240)
    second = replace(first, ref='[2]', chunk_id='second', text='b'*240)
    draft = GeneratedAnswer('A [1]\nB [2]', (GeneratedClaim('A', ('[1]',)), GeneratedClaim('B', ('[2]',))))
    reader, _ = make_reader([chunk(text='z'*200)], options=ContextOptions(True, 1, 256, 512))
    result = reader.read('Q', [requirement('lookup')], [first, second], draft)
    assert result == [first, second]
    assert reader.last_trace['actions'][0]['omissions'][0]['reason'] == 'protected_evidence_budget'


def test_already_supplied_sources_do_not_cause_another_model_review():
    c = chunk(cid='c', text=SOURCES[0].text)
    reader, calls = make_reader([c])
    assert reader.read('Q', [requirement('lookup')], SOURCES, DRAFT) == SOURCES
    assert not calls and not reader.last_trace['added_refs']


def test_lookup_errors_are_redacted_and_original_sources_survive():
    reader, _ = make_reader([chunk()], catalog=False)
    def fail(*args, **kwargs):raise ProviderError('PRIVATE_KEY')
    reader.retriever.embedder.embed_query = fail
    assert reader.read('Q', [requirement('lookup')], SOURCES, DRAFT) == SOURCES
    assert reader.last_trace['status'] == 'lookup_failed'
    assert 'PRIVATE_KEY' not in json.dumps(reader.last_trace)


def test_provider_uses_diagnosis_schema_and_bounds_timeout_without_gold():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='deepseek-flash', usage=None,
            choices=[NS(finish_reason='stop', message=NS(content=payload().model_dump_json()))])
    p = DeepSeekEvidenceReviewer('deepseek-flash', 'PRIVATE', diagnostic=True,
        client=NS(chat=NS(completions=NS(create=create))))
    result = p.review('User question', SOURCES, DRAFT, timeout_seconds=25)
    assert result.requirements[0].status == 'covered'
    request = calls[0]
    assert request['timeout'] == 25 and request['max_tokens'] == 32768
    assert 'requirements' in request['messages'][0]['content']
    assert 'key_point_scores' not in json.dumps(request)


def test_scoped_chroma_query_applies_metadata_filter():
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    calls = []
    store = object.__new__(ChromaVectorStore)
    store.dimensions = 2
    store.collection = NS(count=lambda: 5,
        query=lambda **kwargs: calls.append(kwargs) or dict(ids=[['c2']], distances=[[.2]]))
    assert store.search([1, 0], 50, document_ids=['doc'])[0].chunk_id == 'c2'
    assert calls[0]['where'] == {'document_id':{'$in':['doc']}}
    assert store.search([1, 0], 50, document_ids=[]) == []


def test_scoped_visual_search_excludes_other_paper_before_limit(tmp_path):
    from tests.test_visual_evidence import fixture
    from literature_rag.application.visual_evidence import VisualVectorSearch
    catalog, _, _ = fixture(tmp_path)
    seen=[]
    base=NS(search=lambda *args,**kwargs:seen.append(kwargs) or [],last_diagnostics={})
    search=VisualVectorSearch(base,catalog)
    assert search.search([1.,0.,0.],1,document_ids=['another']) == []
    assert seen == [dict(document_ids=['another'])]


def test_supplement_images_preserve_previous_image_refs_and_limit(tmp_path):
    from tests.test_visual_evidence import fixture
    cat, evidences, assets = fixture(tmp_path)
    old, _ = cat.attach(evidences[:1],evidences[:1],'Figure 1')
    new = chunk(cid='c2',text='Figure 2. Caption')
    reader, _ = make_reader([new], catalog=False)
    reader.retriever.visual_catalog=cat
    reader.retriever.visual_max_images=1
    draft=GeneratedAnswer('A [1]',(GeneratedClaim('A',('[1]',)),))
    result=reader.read('Figure 2',[requirement('lookup')],old,draft)
    assert result[0].visual_assets == old[0].visual_assets
    assert sum(len(e.visual_assets) for e in result) == 1
    assert result[-1].visual_assets == ()


def test_worker_publishes_new_evidence_and_history_keeps_both_rounds(monkeypatch,tmp_path,capsys):
    import literature_worker
    import literature_rag.config as config
    import literature_rag.diagnostics as diagnostics
    import literature_rag.adapters.sqlite.metadata_store as metadata
    import literature_rag.adapters.chroma.vector_store as vectors
    import literature_rag.adapters.providers.openai as embeddings
    import literature_rag.adapters.providers.deepseek as generators
    import literature_rag.adapters.providers.evidence_review as reviews
    import literature_rag.application.retrieve as retrieval
    import literature_rag.application.corrective_review as correction
    from app.qa_history import HistoryStore
    from literature_rag.config import Settings
    (tmp_path/'chroma').mkdir();(tmp_path/'chroma/chroma.sqlite3').touch()
    settings=Settings(_env_file=None,llm_provider='deepseek',llm_model='deepseek-flash',llm_api_key='PRIVATE',
        embedding_model='fixture',embedding_dimensions=3,embedding_api_key='PRIVATE',evidence_review_enabled=True,
        corrective_review_enabled=True,rerank_enabled=True,rerank_api_key='PRIVATE',rerank_base_url='https://example.test/v1')
    issue=proposal(claim_index=None,category='measurement',
        basis=[dict(kind='text',ref='[2]',quote='relative area, not an absolute count')],
        replacement_claims=[dict(text='It measures relative area, not an absolute count.',citation_refs=['[2]'])]).issues[0].model_dump()
    p=Reviewer([payload('lookup'),payload('edit',[issue],issue_indexes=[0],evidence_refs=['[2]'])])
    class Metadata:
        def __init__(self,*_):pass
        def list_documents(self):return []
    class Retriever:
        def __init__(self,*args,**kwargs):
            self.last_seed_evidences=SOURCES;self.last_context_diagnostics={};self.last_rerank_diagnostics={}
            self.last_query_embedding_calls=[]
        def retrieve(self,*_):return SOURCES
    monkeypatch.setattr(config,'Settings',lambda **_:settings)
    monkeypatch.setattr(diagnostics,'configuration_snapshot',lambda _path,*,settings:{})
    monkeypatch.setattr(metadata,'SqliteMetadataStore',Metadata)
    monkeypatch.setattr(vectors,'ChromaVectorStore',lambda *_:NS())
    monkeypatch.setattr(embeddings,'OpenAIEmbedder',lambda *_:NS(last_usage=None))
    monkeypatch.setattr(generators,'DeepSeekGenerator',lambda *args,**kwargs:NS(model_name='deepseek-flash',generate=lambda *_:DRAFT))
    monkeypatch.setattr(reviews,'DeepSeekEvidenceReviewer',lambda *args,**kwargs:p)
    monkeypatch.setattr(retrieval,'RetrievalService',Retriever)
    monkeypatch.setattr(correction,'TargetedEvidenceReader',lambda *_:Reader())
    literature_worker.main(dict(question='Question',data_dir=str(tmp_path)))
    body=json.loads(capsys.readouterr().out)
    assert body['status']=='answered' and body['review_summary']['review_rounds']==2
    assert body['citations'][-1]['ref']=='[2]' and body['citations'][-1]['excerpt'].startswith('It measures')
    assert len(body['retrieved_evidence'])==2 and len(body['generation_calls'])==1
    store=HistoryStore(tmp_path/'history.sqlite3');store.initialize();owner,_=store.session(None)
    row=store.create(owner,'unique','Question',{});store.complete(row['id'],body,20)
    saved=store.get('visitor',row['id'])['result']
    assert saved['evidence_review']['rounds']==body['evidence_review']['rounds']
    assert saved['review_summary']==body['review_summary']
