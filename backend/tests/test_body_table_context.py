"""Combined row retrieval and role-aware expansion, without external model calls."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace as NS
from io import StringIO
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from index_table_evidence import plan
from build_mineru_body_tables import build
from literature_rag.application.context import ContextOptions
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.table_evidence import TableRelations,TableVectorSearch,BODY_TABLE_VERSION
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import InfrastructureError
from literature_rag.domain.models import Document,DocumentStatus,VectorMatch
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from tests.test_body_context import body_catalog
from tests.test_table_evidence import table_text,relations,store
from tests.test_section_context import chunk
from tests.literature_fakes import SpyEmbedder


def table_fixture():
    body=chunk(1,'The measurements are reported in Table 1.',page=2)
    table=chunk(2,table_text(),page=3,kind='table')
    return body,table


def service(chunks,roles,hits,rel,*,options=None):
    catalog=body_catalog(chunks,roles,assigned=False)
    metadata=store(*chunks)
    metadata.get_context_chunks=lambda *args:pytest.fail('Legacy neighbors must not run')
    vectors=TableVectorSearch(NS(search=lambda *_:hits),rel)
    embedder=SpyEmbedder()
    return RetrievalService(metadata,vectors,embedder,options or ContextOptions(True),rel,
        body_context_catalog=catalog),catalog,embedder


def test_row_hit_returns_full_table_and_explicit_cross_page_body_with_one_query_embedding():
    body,table=table_fixture();rel=relations(table,body)
    # The compiled manifest has both explicit forward and bounded reverse links.
    rel.links.append(dict(source_chunk_id=table.id,target_chunk_id=body.id,
        kind='table_explicitly_discussed_by_body',table_number=1))
    retrieve,_,embedder=service([body,table],['body','table'],[],rel)
    result=retrieve.retrieve('Crystallinity at 4000 revolutions?',8,.35)
    assert embedder.query_count==1 and result[0].text==table.text
    assert result[0].source_chunks[0].chunk_id==table.id
    assert result[1].text==body.text and result[1].page_start==2
    assert [e.ref for e in result]==['[1]','[2]']
    assert all('非原文引文' not in e.text for e in result)
    info=retrieve.last_context_diagnostics
    assert info['version']==BODY_TABLE_VERSION and info['table_hit_expansion']=='explicit_body_links_only'
    assert info['metadata_expansion'] is False and info['table_retrieval']['row_candidates']==2


def test_link_supplements_body_without_section_and_never_duplicates_an_existing_table_seed():
    body,table=table_fixture();rel=relations(table,body)
    # Keep row scores below threshold to isolate the body-to-table relation.
    rel.vectors={key:[1.,-1.,0.] for key in rel.vectors}
    retrieve,_,_=service([body,table],['body','table'],[VectorMatch(body.id,.9)],rel)
    result=retrieve.retrieve('The results?',8,.35)
    assert [e.chunk_id for e in result]==[body.id,table.id]
    retrieve,_,_=service([body,table],['body','table'],[VectorMatch(body.id,.9),VectorMatch(table.id,.8)],rel)
    result=retrieve.retrieve('The results?',8,.35)
    ids=[s.chunk_id for e in result for s in e.source_chunks]
    assert len(ids)==len(set(ids))==2
    assert not retrieve.last_context_diagnostics['table_relationship_additions']


def test_section_table_already_added_is_not_appended_again():
    body,table=table_fixture();rel=relations(table,body)
    rel.vectors={key:[1.,-1.,0.] for key in rel.vectors}
    retrieve,_,_=service([body,table],['body','table'],[VectorMatch(body.id,.9)],rel)
    retrieve.body_context_catalog=body_catalog([body,table],['body','table'])
    result=retrieve.retrieve('The results?',8,.35)
    assert len(result)==1 and {s.chunk_id for s in result[0].source_chunks}=={body.id,table.id}
    assert not retrieve.last_context_diagnostics['table_relationship_additions']


@pytest.mark.parametrize('role',['abstract','reference','authors','affiliation','dates','keywords','unknown','mixed'])
def test_non_body_roles_cannot_enter_table_relationships_even_with_explicit_table_text(role):
    body,table=table_fixture();rel=relations(table,body)
    with pytest.raises(InfrastructureError,match='identified body and table'):
        service([body,table],[role,'table'],[VectorMatch(body.id,.9)],rel)


def test_abstract_stays_standalone_and_body_links_do_not_recurse():
    body,table=table_fixture();abstract=chunk(0,'Abstract: See Table 1.')
    other=chunk(3,'More results in Table 1.',page=4)
    rel=relations(table,body);rel.vectors={key:[1.,-1.,0.] for key in rel.vectors}
    rel.chunks[other.id]=other
    rel.links.append(dict(source_chunk_id=table.id,target_chunk_id=other.id,
        kind='table_explicitly_discussed_by_body',table_number=1))
    retrieve,_,_=service([abstract,body,table,other],['abstract','body','table','body'],
        [VectorMatch(abstract.id,.95),VectorMatch(body.id,.9)],rel)
    result=retrieve.retrieve('The results?',8,.35)
    assert result[0].text==abstract.text
    assert {s.chunk_id for e in result for s in e.source_chunks}=={abstract.id,body.id,table.id}
    assert all(other.id!=e.chunk_id for e in result)


def test_table_budget_omits_whole_link_without_discarding_primary_or_adding_neighbors():
    body,table=table_fixture();rel=relations(table,body)
    rel.vectors={key:[1.,-1.,0.] for key in rel.vectors}
    retrieve,_,_=service([body,table],['body','table'],[VectorMatch(body.id,.9)],rel,
        options=ContextOptions(True,max_total_chars=256))
    result=retrieve.retrieve('The results?',8,.35)
    assert len(result)==1 and result[0].text==body.text
    assert retrieve.last_context_diagnostics['table_relationship_omissions']==[dict(chunk_id=table.id,reason='length_budget')]
    assert retrieve.last_context_diagnostics['budget_limited']


def test_mismatched_table_catalog_is_rejected():
    body,table=table_fixture();rel=relations(table,body)
    with pytest.raises(InfrastructureError,match='differ'):
        service([body,replace(table,text=table.text+' changed')],['body','table'],[],rel)


def test_config_and_snapshot_expose_combined_mode_without_changing_defaults(tmp_path):
    assert Settings(_env_file=None).table_retrieval_enabled is False
    env=tmp_path/'.env'
    env.write_text('RAG_CONTEXT_EXPANSION_ENABLED=true\nRAG_CONTEXT_EXPANSION_STRATEGY=body_section\nRAG_TABLE_RETRIEVAL_ENABLED=true\n',encoding='utf-8')
    result=configuration_snapshot(env)
    assert result['pipeline_version']==BODY_TABLE_VERSION
    assert result['table_retrieval']['link_policy']=='identified_body_table_only'
    assert result['context_expansion']['metadata_expansion'] is False


def test_worker_combines_row_search_and_body_context_in_its_actual_entrypoint(tmp_path,monkeypatch,capsys):
    import literature_worker
    from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
    from index_table_evidence import save
    source,chunks=source_library(tmp_path)
    manifest=plan(source)
    manifest['embedding']=dict(provider='openai',model='fake',dimensions=3)
    save(source/'table-row-vectors.json',dict(rows=[dict(id=r['id'],vector=[1.,0.,0.]) for r in manifest['rows']]))
    manifest['row_vectors_sha256']=sha256((source/'table-row-vectors.json').read_bytes()).hexdigest()
    save(source/'table-retrieval.json',manifest)
    (source/'chroma').mkdir();(source/'chroma/chroma.sqlite3').touch()
    settings=Settings(_env_file=None,context_expansion_enabled=True,context_expansion_strategy='body_section',
        table_retrieval_enabled=True,embedding_model='fake',embedding_dimensions=3,embedding_api_key='test-only',
        llm_provider='openai',llm_model='fake-generator',llm_api_key='test-only')
    class Embedder:
        def __init__(self,*args):pass
        def embed_query(self,question):return [1.,0.,0.]
    class Generator:
        model_name='fake-generator'
        def __init__(self,*args,**kwargs):pass
        def generate(self,question,evidence,feedback=None):
            assert evidence[0].text==chunks[2].text
            return GeneratedAnswer('The table reports crystallinity values. [1]',
                (GeneratedClaim('The table reports crystallinity values.',('[1]',)),))
    monkeypatch.setattr('literature_rag.config.Settings',lambda **kwargs:settings)
    monkeypatch.setattr('literature_rag.diagnostics.Settings',lambda **kwargs:settings)
    monkeypatch.setattr('literature_rag.adapters.providers.openai.OpenAIEmbedder',Embedder)
    monkeypatch.setattr('literature_rag.adapters.providers.openai.OpenAIGenerator',Generator)
    monkeypatch.setattr('literature_rag.adapters.chroma.vector_store.ChromaVectorStore',lambda *args:NS(search=lambda *_:[]))
    monkeypatch.setattr(sys,'stdin',StringIO(json.dumps(dict(data_dir=str(source),question='Crystallinity?'))))
    literature_worker.main()
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='answered' and result['configuration']['pipeline_version']==BODY_TABLE_VERSION
    assert result['context_assembly']['table_relationship_additions'][0]['target_chunk_id']==chunks[1].id
    assert result['retrieved_evidence'][0]['text']==chunks[2].text
    assert result['citations'][0]['page_start']==3


def source_library(tmp_path):
    source=tmp_path/'source';source.mkdir()
    body,table=table_fixture();abstract=chunk(0,'Abstract: Table 1.');author=chunk(3,'Authors: See Table 1.')
    chunks=[abstract,body,table,author]
    catalog=body_catalog(chunks,['abstract','body','table','authors'])
    metadata=SqliteMetadataStore(source/'metadata.sqlite3');metadata.initialize()
    pdf=b'%PDF test fixture';paper=source/'papers'/'paper.pdf';paper.parent.mkdir();paper.write_bytes(pdf)
    doc=Document('paper','paper.pdf',Path('papers/paper.pdf'),sha256(pdf).hexdigest(),len(pdf),DocumentStatus.PENDING)
    metadata.upsert_document(doc);metadata.complete_document(doc.id,4,chunks)
    structure=dict(version='role-test',status='ready',chunks=len(chunks),mapping=catalog.mapping,
        sections=list(catalog.sections.values()),embedding_model='fake',embedding_dimensions=3,vector_index_built=False)
    (source/'structure.json').write_text(json.dumps(structure),encoding='utf-8')
    return source,chunks


def test_role_aware_manifest_only_links_identified_body_and_keeps_exact_row_offsets(tmp_path):
    source,chunks=source_library(tmp_path)
    manifest=plan(source)
    assert len(manifest['rows'])==2 and len(manifest['links'])==2
    assert {l['source_chunk_id'] for l in manifest['links']}=={chunks[1].id,chunks[2].id}
    assert manifest['content_role_policy']=='identified_body_table_only'
    assert all(chunks[2].text[r['parent_text_start']:r['parent_text_end']]==r['parent_raw_row'] for r in manifest['rows'])


@pytest.mark.parametrize('fail',[False,True])
def test_isolated_builder_creates_complete_index_or_marks_failure_without_touching_source(tmp_path,monkeypatch,fail):
    source,chunks=source_library(tmp_path)
    originals={p.name:p.read_bytes() for p in source.iterdir() if p.is_file()}
    env=tmp_path/'.env';env.write_text('RAG_EMBEDDING_MODEL=fake\nRAG_EMBEDDING_DIMENSIONS=3\nRAG_EMBEDDING_API_KEY=test-only\n',encoding='utf-8')
    env_before=env.read_bytes();calls=[]
    class Embedder:
        def __init__(self,*args):self.last_usage=None
        def embed_documents(self,texts):
            calls.append(list(texts))
            if fail:raise RuntimeError('fixture failure')
            self.last_usage=dict(total_tokens=len(texts))
            return [[1.,0.,0.] for _ in texts]
    class Vectors:
        def __init__(self,*args):self.texts={};self.collection=self
        def upsert(self,records,values):self.texts.update({r.chunk_id:r.text for r in records})
        def count(self):return len(self.texts)
        def get(self,**kwargs):return dict(ids=list(self.texts),documents=list(self.texts.values()))
    monkeypatch.setattr('literature_rag.adapters.providers.openai.OpenAIEmbedder',Embedder)
    monkeypatch.setattr('literature_rag.adapters.chroma.vector_store.ChromaVectorStore',Vectors)
    target=tmp_path/'new'
    if fail:
        with pytest.raises(RuntimeError):build(source,target,env)
        result=json.loads((target/'structure.json').read_text('utf-8'))
        assert result['status']=='failed' and result['vector_index_built'] is False
    else:
        result=build(source,target,env)
        assert result['status']=='ready' and result['chunks']==4 and result['rows']==2 and result['links']==2
        assert [len(c) for c in calls]==[4,2]
        assert (target/'papers'/'paper.pdf').read_bytes()==(source/'papers'/'paper.pdf').read_bytes()
        metadata=SqliteMetadataStore(target/'metadata.sqlite3')
        loaded=TableRelations.load(target,metadata,'openai','fake',3)
        loaded.validate_body_catalog(body_catalog(chunks,['abstract','body','table','authors']))
    assert env.read_bytes()==env_before
    assert all((source/name).read_bytes()==value for name,value in originals.items())
    with pytest.raises(ValueError,match='new independent'):build(source,target,env)
