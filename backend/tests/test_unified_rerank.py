"""Reranking selects primary roots before the single bounded context pass."""
from io import StringIO
import json
from types import SimpleNamespace as NS
import sys

import pytest

from tests.test_unified_context import table,relations,assign_sections,sources
from tests.test_body_context import body_catalog
from tests.test_body_table_context import source_library
from tests.test_table_evidence import store
from tests.test_section_context import chunk
from tests.literature_fakes import SpyEmbedder
from index_table_evidence import plan,save,digest
from literature_rag.application.context import ContextOptions
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.table_evidence import TableVectorSearch,BODY_TABLE_VERSION
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import ProviderError
from literature_rag.domain.models import VectorMatch,GeneratedAnswer,GeneratedClaim


def combined(reranker):
    a=chunk(1,'An unrelated original result.');b=chunk(2,'See Table 1 for the measured result.')
    tab=table(3);eq=chunk(4,'$CI=A/B$',2,kind='equation')
    cat=body_catalog([a,b,tab,eq],['body','body','table','equation'])
    cat=assign_sections(cat,{a.id:'a',b.id:'b',eq.id:'b',tab.id:'c'})
    rel=relations(cat,[(b,tab)])
    vectors=TableVectorSearch(NS(search=lambda *_:[VectorMatch(a.id,.9),VectorMatch(b.id,.4)]),rel)
    embedder=SpyEmbedder()
    return RetrievalService(store(a,b,tab,eq),vectors,embedder,ContextOptions(True),rel,reranker,
        body_context_catalog=cat),(a,b,tab,eq),embedder


def test_reranker_sees_full_unexpanded_candidates_and_only_new_roots_trigger_context():
    calls=[]
    def rank(question,texts):calls.append((question,texts));return [.01,.02]
    service,(a,b,tab,eq),embedder=combined(NS(rerank=rank))
    result=service.retrieve('  Measured result?  ',1,.35)
    assert calls==[('Measured result?',[a.text,b.text])]
    assert embedder.query_count==1 and service.last_seed_evidences[0].chunk_id==b.id
    assert service.last_seed_evidences[0].score==.4
    assert sources(result)=={b.id:b.text,tab.id:tab.text,eq.id:eq.text}
    info=service.last_context_diagnostics
    assert info['assembly_passes']==1 and info['candidate_root_chunk_ids']==[b.id]
    assert {x['seed_chunk_id'] for x in info['candidate_origins']}=={b.id}
    assert info['rerank']['candidates'][0]['rerank_score']==.02


def test_rerank_failure_stops_before_context_and_keeps_failure_diagnostics(monkeypatch):
    def fail(*args):raise ProviderError('unavailable')
    service,_,_=combined(NS(rerank=fail))
    monkeypatch.setattr('literature_rag.application.body_context.assemble_body_context',
        lambda *_args,**_kwargs:pytest.fail('Context cannot run after a failed rerank'))
    with pytest.raises(ProviderError):service.retrieve('Result?',1,.35)
    assert not service.last_seed_evidences and service.last_rerank_diagnostics['status']=='started'


def test_combined_snapshot_reports_both_reranking_and_unified_context(tmp_path):
    env=tmp_path/'.env';env.write_text('RAG_CONTEXT_EXPANSION_ENABLED=true\nRAG_CONTEXT_EXPANSION_STRATEGY=body_section\n'
        'RAG_TABLE_RETRIEVAL_ENABLED=true\nRAG_RERANK_ENABLED=true\nRAG_RERANK_BASE_URL=https://api.example/v1\n'
        'RAG_RERANK_API_KEY=private-test-token\n',encoding='utf-8')
    snapshot=configuration_snapshot(env)
    assert snapshot['pipeline_version']=='mineru-unified-rerank-v1'
    assert snapshot['rerank']['context_pipeline_version']==BODY_TABLE_VERSION
    assert snapshot['context_expansion']['assembly_passes']==1
    assert snapshot['rerank']['position']=='before_primary_selection_and_unified_context'
    assert 'private-test-token' not in json.dumps(snapshot)
    # Offline replay must not silently ignore an enabled reranker or call paid APIs.
    from verify_mineru_body_tables import verify
    with pytest.raises(ValueError,match='explicit API probe'):
        verify(tmp_path/'missing-library',tmp_path/'missing-cache',tmp_path/'output.json',env)


def test_worker_applies_row_search_rerank_and_unified_context_together(tmp_path,monkeypatch,capsys):
    import literature_worker
    source,chunks=source_library(tmp_path);manifest=plan(source)
    manifest['embedding']=dict(provider='openai',model='fake',dimensions=3)
    save(source/'table-row-vectors.json',dict(rows=[dict(id=r['id'],vector=[1.,0.,0.]) for r in manifest['rows']]))
    manifest['row_vectors_sha256']=digest(source/'table-row-vectors.json');save(source/'table-retrieval.json',manifest)
    (source/'chroma').mkdir();(source/'chroma/chroma.sqlite3').touch()
    settings=Settings(_env_file=None,context_expansion_enabled=True,context_expansion_strategy='body_section',
        table_retrieval_enabled=True,rerank_enabled=True,rerank_api_key='private-test-token',
        rerank_base_url='https://api.example/v1',embedding_model='fake',embedding_dimensions=3,
        embedding_api_key='test-only',llm_provider='openai',llm_model='fake-generator',llm_api_key='test-only',top_k=1)
    calls=[]
    class Embedder:
        def __init__(self,*args):pass
        def embed_query(self,text):return [1.,1.,1.]
    class Reranker:
        def __init__(self,*args):self.last_call=None
        def rerank(self,question,texts):
            calls.append((question,texts));assert texts==[chunks[1].text,chunks[2].text]
            self.last_call=dict(status='completed',api_calls=1,usage=None,monetary_cost=None)
            return [.01,.02]
    class Generator:
        model_name='fake-generator'
        def __init__(self,*args,**kwargs):pass
        def generate(self,question,evidence,feedback=None):
            assert evidence[0].chunk_id==chunks[2].id and chunks[1].text in evidence[0].text
            return GeneratedAnswer('The table reports measured values. [1]',
                (GeneratedClaim('The table reports measured values.',('[1]',)),))
    monkeypatch.setattr('literature_rag.config.Settings',lambda **kwargs:settings)
    monkeypatch.setattr('literature_rag.diagnostics.Settings',lambda **kwargs:settings)
    monkeypatch.setattr('literature_rag.adapters.providers.openai.OpenAIEmbedder',Embedder)
    monkeypatch.setattr('literature_rag.adapters.providers.openai.OpenAIGenerator',Generator)
    monkeypatch.setattr('literature_rag.adapters.providers.rerank.SiliconFlowReranker',Reranker)
    monkeypatch.setattr('literature_rag.adapters.chroma.vector_store.ChromaVectorStore',
        lambda *args:NS(search=lambda *_:[VectorMatch(chunks[1].id,.9)]))
    monkeypatch.setattr(sys,'stdin',StringIO(json.dumps(dict(data_dir=str(source),question='Measured values?'))))
    literature_worker.main();result=json.loads(capsys.readouterr().out)
    assert result['status']=='answered' and len(calls)==1 and len(result['rerank_calls'])==1
    assert result['configuration']['pipeline_version']=='mineru-unified-rerank-v1'
    assert result['retrieval_seed_evidence'][0]['chunk_id']==chunks[2].id
    assert result['context_assembly']['candidate_root_chunk_ids']==[chunks[2].id]
    assert result['context_assembly']['assembly_passes']==1
