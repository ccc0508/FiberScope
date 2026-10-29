from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
import sys

import pytest

from literature_rag.application.context import ContextOptions,assemble,join_chunks
from literature_rag.application.structure import split_page,rechunk
from literature_rag.application.retrieve import RetrievalService
from literature_rag.application.citations import CitationValidator
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.domain.models import Chunk,Document,DocumentStatus,Evidence,GeneratedAnswer,GeneratedClaim
from literature_rag.domain.errors import InfrastructureError
from literature_rag.config import Settings
from tests.literature_fakes import InMemoryMetadataStore,InMemoryVectorStore,SpyEmbedder


def chunk(index,text,*,document='doc',page=8,kind='text'):
    return Chunk(f'{document}-{page}-{index}',document,'paper.pdf',page,page,index,text,1,'fake',kind=kind)


def seed(c,score=.9):
    return Evidence('[1]',c.id,c.document_id,c.filename,c.page_start,c.page_end,c.text,score)


def store_for(*chunks):
    store=InMemoryMetadataStore();store.chunks={c.id:c for c in chunks};return store


def test_neighbor_restores_missing_table_row_and_citation_lineage():
    overlap='(b) Hardwood O(3)H O(5) relative content\n4000 33.06 0.99\n'
    first=chunk(24,'Table 2. Relative content\n'+overlap)
    second=chunk(25,overlap+'12000 29.28 0.99\n16000 31.65 0.99')
    evidences,info=assemble([seed(first)],store_for(first,second),ContextOptions(True))
    assert len(evidences)==1 and '33.06' in evidences[0].text and '29.28' in evidences[0].text
    assert evidences[0].text.count('4000 33.06')==1
    assert [s.chunk_id for s in evidences[0].source_chunks]==[first.id,second.id]
    assert evidences[0].seed_chunk_ids==(first.id,) and evidences[0].score==.9
    assert info['added_chunk_ids']==[second.id]
    generated=GeneratedAnswer('The two values are supplied. [1]',(GeneratedClaim('The two values are supplied.',('[1]',)),))
    assert CitationValidator().validate(generated,evidences).citations[0].source_chunks==evidences[0].source_chunks


def test_overlapping_seed_windows_merge_without_duplicate_sources_or_new_scores():
    chunks=[chunk(i,f'Original source paragraph {i}.') for i in range(4)]
    seeds=[seed(chunks[2],.95),replace(seed(chunks[0],.8),ref='[2]')]
    evidences,_=assemble(seeds,store_for(*chunks),ContextOptions(True))
    assert len(evidences)==1 and evidences[0].chunk_id==chunks[2].id and evidences[0].score==.95
    assert evidences[0].seed_chunk_ids==(chunks[2].id,chunks[0].id)
    assert [s.chunk_index for s in evidences[0].source_chunks]==[0,1,2,3]


def test_same_document_and_page_only():
    a=chunk(4,'Target original.')
    unrelated=[chunk(5,'Wrong page.',page=9),chunk(5,'Wrong paper.',document='other')]
    evidences,_=assemble([seed(a)],store_for(a,*unrelated),ContextOptions(True))
    assert evidences[0].text==a.text and len(evidences[0].source_chunks)==1


def test_corrupt_context_reader_is_rejected():
    a=chunk(4,'Target original.');wrong=chunk(5,'Wrong paper.',document='other')
    store=store_for(a,wrong);store.get_context_chunks=lambda *args:[a,wrong]
    with pytest.raises(InfrastructureError,match='unrelated'):
        assemble([seed(a)],store,ContextOptions(True))


def test_budget_preserves_seed_hits_and_never_truncates_a_row():
    a=chunk(2,'A'*150);neighbor=chunk(3,'Complete numeric row 29.28 '+('B'*300));b=chunk(8,'C'*150,page=9)
    seeds=[seed(a),replace(seed(b,.7),ref='[2]')]
    evidences,info=assemble(seeds,store_for(a,b,neighbor),ContextOptions(True,max_evidence_chars=256,max_total_chars=400))
    assert [e.text for e in evidences]==[a.text,b.text]
    assert info['budget_limited'] and info['context_chars']==300
    huge=chunk(1,'Large complete table '+('x'*300),kind='table')
    evidences,info=assemble([seed(huge)],store_for(huge),ContextOptions(True,max_evidence_chars=256))
    assert not evidences and info['omitted_seed_chunk_ids']==[huge.id]


def test_structured_table_stays_intact_without_unneeded_neighbors():
    a=chunk(2,'Table 2\n4000 33.06\n12000 29.28',kind='table');b=chunk(3,'Following prose.',kind='paragraph')
    evidences,_=assemble([seed(a)],store_for(a,b),ContextOptions(True))
    assert evidences[0].text==a.text and [s.chunk_id for s in evidences[0].source_chunks]==[a.id]
    assert join_chunks([a,replace(a,id='different',chunk_index=3)]).count('4000 33.06')==2


def test_disabled_mode_is_exact_legacy_behavior_and_does_not_read_neighbors():
    a=chunk(1,'Old evidence.');store=store_for(a)
    store.get_context_chunks=lambda *args:pytest.fail('disabled mode looked up neighbors')
    original=[seed(a)];actual,_=assemble(original,store,ContextOptions())
    assert actual==original and actual[0] is original[0]


def test_single_embedding_and_search_after_context_expansion():
    from tests.test_literature_retrieval import ScriptedVectorStore
    from literature_rag.domain.models import VectorMatch
    a=chunk(24,'fiber source');b=chunk(25,'12000 29.28')
    embedder=SpyEmbedder();vectors=ScriptedVectorStore([VectorMatch(a.id,.9)])
    retriever=RetrievalService(store_for(a,b),vectors,embedder,ContextOptions(True))
    result=retriever.retrieve('fiber',8,.35)
    assert '29.28' in result[0].text and embedder.query_count==1 and len(vectors.search_calls)==1
    assert retriever.last_seed_evidences[0].text==a.text


def table_text():
    return ('Introductory sentence.\nTable 2. (a) Softwood. (b) Hardwood relative content (%).\n(a)\n'
            'Revolutions O(3)H O(5) Free OH and relative content\n4000 22.22 0.99\n12000 23.23 0.99\n'
            '(b)\nRevolutions O(3)H O(5) Free OH and relative content\n4000 33.06 0.99\n12000 29.28 0.99\n'
            'The following discussion is a separate paragraph about the observed experimental results.\n')


def test_rechunk_preserves_whole_table_both_subtables_and_source_offsets():
    text=table_text();units,_=split_page(text,8,8,['old-24','old-25'])
    tables=[u for u in units if u.kind=='table']
    assert len(tables)==1 and all(v in tables[0].text for v in ['Softwood','Hardwood','33.06','29.28','22.22','23.23'])
    assert 'following discussion' not in tables[0].text
    assert all(text[u.start:u.end]==u.text for u in units)
    assert all(u.source_chunk_ids==('old-24','old-25') for u in units)


def test_page_boundary_is_disclosed_and_large_table_is_not_silently_cut():
    text=table_text().split('The following discussion')[0]
    units,warnings=split_page(text,8,8,['old'])
    assert 'table_reaches_page_end_cross_page_completeness_unverified' in warnings
    with pytest.raises(ValueError,match='source unit exceeds'):
        split_page(text,8,8,['old'],max_chars=120)


def test_gap_in_legacy_page_blocks_cannot_be_claimed_as_complete():
    with pytest.raises(ValueError,match='missing chunk'):
        rechunk([chunk(1,'First part.'),chunk(3,'Last part.')])


def test_sqlite_legacy_readonly_neighbor_lookup_and_migration(tmp_path):
    from literature_rag.adapters.sqlite.metadata_store import _SCHEMA
    path=tmp_path/'metadata.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA.replace("    kind TEXT NOT NULL DEFAULT 'text',\n",''))
        for c in [chunk(24,'Table start.'),chunk(25,'12000 29.28'),chunk(26,'Other page.',page=9),chunk(25,'Other paper.',document='other')]:
            conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (c.id,c.document_id,c.filename,c.page_start,c.page_end,c.chunk_index,c.text,c.token_count,c.embedding_model,c.created_at.isoformat()))
    class ReadOnly(SqliteMetadataStore):
        def _connect(self):
            c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
    before=path.read_bytes();store=ReadOnly(path)
    got=store.get_context_chunks(['doc-8-24'],1)
    assert [c.chunk_index for c in got]==[24,25] and all(c.kind=='text' for c in got)
    assert path.read_bytes()==before
    SqliteMetadataStore(path).initialize()
    with sqlite3.connect(path) as conn:assert 'kind' in {r[1] for r in conn.execute('PRAGMA table_info(chunks)')}


def test_structure_builder_never_overwrites_original_library(tmp_path):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
    import reindex_literature_structure as builder
    source=tmp_path/'source';source.mkdir();(source/'papers').mkdir()
    pdf=source/'papers/paper.pdf';pdf.write_bytes(b'%PDF fixture')
    doc=Document('doc','paper.pdf',Path('papers/paper.pdf'),sha256(pdf.read_bytes()).hexdigest(),len(pdf.read_bytes()),DocumentStatus.COMPLETED)
    store=SqliteMetadataStore(source/'metadata.sqlite3');store.initialize();store.upsert_document(doc)
    old=chunk(0,table_text());store.complete_document('doc',8,[old])
    before=(source/'metadata.sqlite3').read_bytes();vectors=InMemoryVectorStore();embedder=SpyEmbedder()
    settings=Settings(_env_file=None,embedding_model=embedder.model_name,embedding_dimensions=3)
    output=tmp_path/'new'
    result=builder.build(source,output,settings,embedder=embedder,vector_factory=lambda p:vectors)
    assert result['status']=='ready' and result['chunk_kinds']['table']==1
    new_store=SqliteMetadataStore(output/'metadata.sqlite3')
    got=new_store.get_chunks(list(result['mapping']))
    assert any(c.kind=='table' and '29.28' in c.text for c in got)
    assert (source/'metadata.sqlite3').read_bytes()==before
    assert len(vectors.records)==len(got)
    with pytest.raises(ValueError,match='new separate'):
        builder.build(source,output,settings,embedder=embedder,vector_factory=lambda p:vectors)


def test_library_switch_keeps_history_and_old_source_snapshot(tmp_path,monkeypatch):
    import shutil
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import literature
    from tests.test_literature_api import finished
    root=tmp_path/'data';root.mkdir();(root/'papers').mkdir();(root/'papers/paper.pdf').write_bytes(b'%PDF fixture')
    with sqlite3.connect(root/'metadata.sqlite3') as conn:
        conn.execute('CREATE TABLE documents (id TEXT,filename TEXT,file_path TEXT,status TEXT,page_count INTEGER,chunk_count INTEGER)')
        conn.execute("INSERT INTO documents VALUES ('doc','paper.pdf','papers/paper.pdf','completed',14,44)")
    config=literature.LiteratureSettings(_env_file=None,enabled=True,data_dir=root)
    def answer(config,question):
        return dict(status='answered',answer=question,citations=[],retrieved_evidence=[dict(text='saved '+question)],configuration={})
    monkeypatch.setattr(literature,'run_answer',answer)
    app=FastAPI();app.include_router(literature.router(config))
    with TestClient(app) as client:
        old=finished(client,client.post('/api/v1/literature/ask',json=dict(question='原索引的问题')).json()['id'])
    version=tmp_path/'version';version.mkdir();shutil.copytree(root/'papers',version/'papers');shutil.copy2(root/'metadata.sqlite3',version/'metadata.sqlite3')
    with sqlite3.connect(version/'metadata.sqlite3') as conn:conn.execute('UPDATE documents SET chunk_count=81')
    new_config=config.model_copy(update=dict(library_dir=version));app=FastAPI();app.include_router(literature.router(new_config))
    with TestClient(app) as client:
        assert client.get('/api/v1/literature/documents').json()['documents'][0]['chunk_count']==81
        assert client.get('/api/v1/literature/documents/doc/pdf').content==b'%PDF fixture'
        assert client.get('/api/v1/literature/history/'+old['id']).json()['result']==old['result']
        finished(client,client.post('/api/v1/literature/ask',json=dict(question='新索引的问题')).json()['id'])
        assert client.get('/api/v1/literature/history').json()['pagination']['total']==2
    assert (root/'qa_history.sqlite3').is_file() and not (version/'qa_history.sqlite3').exists()


def test_embedding_usage_is_preserved_for_index_build_accounting():
    from types import SimpleNamespace
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    response=SimpleNamespace(data=[SimpleNamespace(index=0,embedding=[.1,.2,.3])],usage=SimpleNamespace(prompt_tokens=7,total_tokens=7))
    client=SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs:response))
    embedder=OpenAIEmbedder('fake',3,'synthetic',client=client)
    assert embedder.embed_documents(['fiber'])==[[.1,.2,.3]]
    assert embedder.last_usage==dict(prompt_tokens=7,total_tokens=7)
