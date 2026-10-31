from dataclasses import replace
from hashlib import sha256

import pytest

from literature_rag.application.context import ContextOptions
from literature_rag.application.section_context import SectionCatalog, assemble_sections
from literature_rag.domain.models import Chunk, Evidence, GeneratedAnswer, GeneratedClaim
from literature_rag.application.citations import CitationValidator


def chunk(i, text, page=1, doc='paper', kind='paragraph'):
    return Chunk(str(i)+doc, doc, doc+'.pdf', page, page, i, text, 1, 'test', kind=kind)


def seed(c, ref='[1]'):
    return Evidence(ref, c.id, c.document_id, c.filename, c.page_start, c.page_end, c.text, .8)


def catalog(chunks, assignments, *, status='inferred'):
    return SectionCatalog(chunks, dict(sections=[dict(id=s, status=status, role='section')
        for s in set(assignments.values()) if s], mapping={c.id:dict(section_id=assignments[c.id],
        section_status=status if assignments[c.id] else 'unassigned', page_start=c.page_start,
        page_end=c.page_end, kind=c.kind, text_sha256=sha256(c.text.encode()).hexdigest()) for c in chunks}))


def test_cross_page_section_restores_table_and_keeps_citation_provenance():
    a=chunk(1,'Table 1 contains the numerical results.'); b=chunk(2,'Table 1: 70.42% -> 72.54%',2,kind='table')
    cat=catalog([a,b],{a.id:'s',b.id:'s'})
    out,info=assemble_sections([seed(a)],cat,ContextOptions(True))
    assert '72.54%' in out[0].text and out[0].page_end==2
    assert [s.chunk_id for s in out[0].source_chunks]==[a.id,b.id]
    assert info['added_chunk_ids']==[b.id]
    answer=GeneratedAnswer('Results increase. [1]',(GeneratedClaim('Results increase.',('[1]',)),))
    assert CitationValidator().validate(answer,out).citations[0].source_chunks==out[0].source_chunks


def test_other_sections_and_documents_are_not_brought_in_by_proximity():
    a=chunk(1,'Original target');b=chunk(2,'Other section');c=chunk(3,'Other paper',doc='other')
    cat=catalog([a,b,c],{a.id:'s',b.id:'t',c.id:'u'})
    out,_=assemble_sections([seed(a)],cat,ContextOptions(True))
    assert out[0].text==a.text


def test_unassigned_and_uncertain_sections_fall_back_to_same_page_only():
    a=chunk(1,'Target');b=chunk(2,'Same-page neighbor');c=chunk(3,'Next page',2)
    for status in ['inferred','parent_unresolved']:
        sid=None if status=='inferred' else 'uncertain'
        cat=catalog([a,b,c],{a.id:sid,b.id:sid,c.id:sid},status=status)
        out,info=assemble_sections([seed(a)],cat,ContextOptions(True))
        assert b.text in out[0].text and c.text not in out[0].text
        assert info['decisions'][0]['mode']=='same_page_fallback'


def test_budget_reserves_every_primary_and_does_not_truncate_table():
    a=chunk(1,'A'*110);b=chunk(2,'Table 1 '+('N'*500),kind='table');c=chunk(3,'C'*110,2)
    cat=catalog([a,b,c],{a.id:'s',b.id:'s',c.id:'t'})
    out,info=assemble_sections([seed(a),seed(c,'[2]')],cat,ContextOptions(True,max_evidence_chars=256,max_total_chars=300))
    assert [e.text for e in out]==[a.text,c.text]
    assert info['budget_limited'] and not info['omitted_seed_chunk_ids']


def test_shared_sections_deduplicate_and_keep_all_primary_hit_ids():
    cs=[chunk(i,'paragraph '+str(i)) for i in range(3)]
    cat=catalog(cs,{c.id:'s' for c in cs})
    out,_=assemble_sections([seed(cs[1]),seed(cs[0],'[2]')],cat,ContextOptions(True))
    assert len(out)==1 and out[0].seed_chunk_ids==(cs[1].id,cs[0].id)
    assert len(out[0].source_chunks)==3


def test_explicit_table_link_can_cross_sections_but_not_documents():
    a=chunk(1,'See Table 2.');b=chunk(9,'Table 2: results',3,kind='table');c=chunk(9,'Table 2: wrong paper',doc='other',kind='table')
    cat=catalog([a,b,c],{a.id:'s',b.id:'t',c.id:'u'})
    out,_=assemble_sections([seed(a)],cat,ContextOptions(True))
    assert b.text in out[0].text and c.text not in out[0].text
    assert '[原文片段不连续]' in out[0].text


def test_corrupt_mapping_or_primary_is_rejected():
    a=chunk(1,'Original');cat=catalog([a],{a.id:'s'})
    with pytest.raises(ValueError,match='authoritative'):
        assemble_sections([replace(seed(a),text='changed')],cat,ContextOptions(True))
    bad=cat.mapping[a.id].copy();bad['text_sha256']='0'*64
    with pytest.raises(ValueError,match='authoritative'):
        SectionCatalog([a],dict(mapping={a.id:bad},sections=list(cat.sections.values())))


def test_oversized_primary_is_an_error_and_no_evidence_is_silently_lost():
    a=chunk(1,'a'*300);cat=catalog([a],{a.id:'s'})
    with pytest.raises(ValueError,match='Primary hit cannot fit'):
        assemble_sections([seed(a)],cat,ContextOptions(True,max_evidence_chars=256))


def test_section_larger_than_single_evidence_splits_without_losing_primary_hits():
    a=chunk(1,'a'*200);b=chunk(2,'b'*200,2);c=chunk(3,'c'*200,3)
    cat=catalog([a,b,c],{n.id:'s' for n in [a,b,c]})
    out,info=assemble_sections([seed(a),seed(b,'[2]'),seed(c,'[3]')],cat,
        ContextOptions(True,max_evidence_chars=256,max_total_chars=700))
    assert len(out)==3 and sum(len(e.text) for e in out)==600
    assert {s.chunk_id for e in out for s in e.source_chunks}=={a.id,b.id,c.id}
    assert not info['omitted_seed_chunk_ids']


def test_supplement_table_number_is_not_confused_with_main_table():
    a=chunk(1,'See Table S1.');b=chunk(5,'Table 1: main',kind='table');c=chunk(9,'Table S1: supplement',kind='table')
    cat=catalog([a,b,c],{a.id:'s',b.id:'t',c.id:'u'})
    out,_=assemble_sections([seed(a)],cat,ContextOptions(True))
    assert c.text in out[0].text and b.text not in out[0].text
