"""Full table provenance, merged headers, same-document links and bounded context expansion."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from index_table_evidence import table_rows,table_references
from literature_rag.application.table_evidence import VERSION,TableRelations,TableVectorSearch,append_related_tables
from literature_rag.application.context import ContextOptions,assemble
from literature_rag.application.retrieve import RetrievalService
from literature_rag.domain.models import Chunk,VectorMatch,Evidence,GeneratedAnswer,GeneratedClaim
from literature_rag.application.citations import CitationValidator
from tests.literature_fakes import InMemoryMetadataStore,SpyEmbedder


def chunk(cid,text,kind='paragraph',page=1,index=0,document='doc'):
    return Chunk(cid,document,'paper.pdf',page,page,index,text,1,'fake',kind=kind)


def table_text():
    return ('Table 1. (a) Softwood. (b) Hardwood.\n'
        '<table><tr><td colspan="3">(a)</td></tr>'
        '<tr><td rowspan="2">Revolutions</td><td colspan="2">CI (%)</td></tr>'
        '<tr><td>CI-XI</td><td>CI-XA</td></tr>'
        '<tr><td>4000</td><td>70.42</td><td>37.71</td></tr>'
        '<tr><td colspan="3">(b)</td></tr>'
        '<tr><td rowspan="2">Revolutions</td><td colspan="2">CI (%)</td></tr>'
        '<tr><td>CI-XI</td><td>CI-XA</td></tr>'
        '<tr><td>4000</td><td>73.01</td><td>36.26</td></tr></table>')


def store(*chunks):
    value=InMemoryMetadataStore();value.chunks={c.id:c for c in chunks};return value


def relations(table,body=None,row_vectors=None):
    rows=table_rows(table)
    links=[] if body is None else [dict(source_chunk_id=body.id,target_chunk_id=table.id,kind='explicit_body_table_reference',table_number=1)]
    manifest=dict(version=VERSION,rows=rows,links=links,parent_text_sha256={table.id:sha256(table.text.encode()).hexdigest()},embedding=dict(provider='test',model='fake',dimensions=3))
    vectors=row_vectors or {r['id']:[1.,0.,0.] for r in rows}
    return TableRelations(manifest,store(table,*([body] if body else [])),vectors)


def seed(c,score=.7):
    return Evidence('[1]',c.id,c.document_id,c.filename,c.page_start,c.page_end,c.text,score)


def test_rows_attach_multilevel_header_group_units_and_verbatim_parent_offsets():
    table=chunk('table',table_text(),'table')
    rows=table_rows(table)
    assert len(rows)==2
    assert rows[0]['group']=='a' and rows[1]['group']=='b'
    assert 'Softwood' in rows[0]['text'] and 'Hardwood' in rows[1]['text']
    assert rows[0]['assignments']==[dict(header='Revolutions',value='4000'),dict(header='CI (%) > CI-XI',value='70.42'),dict(header='CI (%) > CI-XA',value='37.71')]
    assert '非原文引文' in rows[0]['text']
    for row in rows:
        assert table.text[row['parent_text_start']:row['parent_text_end']]==row['parent_raw_row']
        assert row['parent_chunk_id']==table.id


def test_missing_headers_malformed_spans_and_ambiguous_tables_fail_without_inventing_metadata():
    for text in [
        'Table 1.<table><tr><td>1</td><td>3.14</td></tr></table>',
        'Table 1.<table><tr><td colspan="200">label</td></tr></table>',
        table_text()+table_text(),
    ]:
        with pytest.raises(ValueError):table_rows(chunk('table',text,'table'))


def test_supplementary_and_figure_references_do_not_create_false_table_one_links():
    assert table_references('Table S1 and Figure 1 describe other data.')==set()
    assert table_references('See Tables 1a,b and 2, and Table 3.')=={1,2,3}


def test_parent_fusion_counts_full_table_once_and_retains_best_row_score():
    table=chunk('table',table_text(),'table')
    rel=relations(table)
    wrapped=TableVectorSearch(NS(search=lambda vector,k:[VectorMatch('paragraph',.8),VectorMatch('table',.2)]),rel)
    got=wrapped.search([1.,0.,0.],50)
    assert [(m.chunk_id,m.score) for m in got]==[('table',1.),('paragraph',.8)]
    assert len(wrapped.last_diagnostics['row_hits'])==2
    assert all(m.chunk_id not in rel.by_id for m in got)


def test_foreign_document_links_and_modified_parent_are_rejected():
    table=chunk('table',table_text(),'table');body=chunk('body','See Table 1.',document='other')
    with pytest.raises(Exception,match='cross-document'):relations(table,body)
    rel=relations(table)
    bad=store(replace(table,text=table.text+'altered'))
    with pytest.raises(Exception,match='sealed'):TableRelations(rel.manifest,bad,rel.vectors)


def test_linked_table_can_cross_pages_with_correct_citation_and_no_generated_row_text():
    body=chunk('body','The result is shown in Table 1.',page=5)
    table=chunk('table',table_text(),'table',page=6,index=12)
    rel=relations(table,body)
    evidence,diagnostics=assemble([seed(body)],store(body,table),ContextOptions(True))
    expanded,info=append_related_tables(evidence,rel,ContextOptions(True),diagnostics)
    assert len(expanded)==2 and expanded[1].page_start==expanded[1].page_end==6
    assert expanded[1].text==table.text and '非原文引文' not in expanded[1].text
    assert expanded[1].source_chunks[0].chunk_id==table.id
    assert expanded[1].seed_chunk_ids==(body.id,) and expanded[1].context_status=='linked_table'
    answer=GeneratedAnswer('The original source supports a comparison. [2]',(GeneratedClaim('The original source supports a comparison.',('[2]',)),))
    cite=CitationValidator().validate(answer,expanded).citations[0]
    assert cite.chunk_id==table.id and cite.page_start==6
    assert info['table_relationship_additions'][0]['target_chunk_id']=='table'


def test_linked_table_budget_omits_whole_source_and_keeps_all_original_hits():
    body=chunk('body','See Table 1. '+('a'*140),page=5)
    table=chunk('table',table_text(),'table',page=6,index=12)
    rel=relations(table,body)
    options=ContextOptions(True,max_evidence_chars=8000,max_total_chars=256)
    original,diagnostics=assemble([seed(body)],store(body,table),options)
    got,info=append_related_tables(original,rel,options,diagnostics)
    assert got==original and info['budget_limited']
    assert info['table_relationship_omissions']==[dict(chunk_id='table',reason='length_budget')]


def test_table_row_hit_uses_one_query_embedding_and_full_parent_evidence():
    table=chunk('table',table_text(),'table')
    rel=relations(table)
    base=NS(search=lambda vector,k:[])
    vector=TableVectorSearch(base,rel)
    embedder=SpyEmbedder()
    retrieve=RetrievalService(store(table),vector,embedder,ContextOptions(True),rel)
    result=retrieve.retrieve('What are the crystallinity values?',8,.35)
    assert embedder.query_count==1 and result[0].text==table.text
    assert result[0].chunk_id=='table' and retrieve.last_context_diagnostics['table_retrieval']['row_candidates']==2


def test_table_mode_requires_bounded_context_and_default_stays_off():
    from literature_rag.config import Settings
    assert Settings(_env_file=None).table_retrieval_enabled is False
    with pytest.raises(ValueError,match='bounded'):
        Settings(_env_file=None,table_retrieval_enabled=True)
