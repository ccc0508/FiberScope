"""Primary-rooted section/link union with one provenance-preserving budget."""
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from index_table_evidence import table_rows
from literature_rag.application.body_context import BodySectionCatalog,assemble_body_context
from literature_rag.application.context import ContextOptions
from literature_rag.application.table_evidence import TableRelations,VERSION
from tests.test_body_context import body_catalog
from tests.test_body_table_context import service
from tests.test_table_evidence import store
from tests.test_section_context import chunk,seed


def table(i,number=1):
    return chunk(i,f'Table {number}. <table><tr><td>Revolutions</td><td>CI (%)</td></tr>'
        '<tr><td>4000</td><td>70.42</td></tr></table>',page=2,kind='table')


def relations(catalog,edges):
    chunks=list(catalog.chunks.values());tables=[c for c in chunks if c.kind=='table']
    rows=[row for c in tables for row in table_rows(c)]
    links=[dict(source_chunk_id=a.id,target_chunk_id=b.id,table_number=1,
        kind='explicit_body_table_reference' if b.kind=='table' else 'table_explicitly_discussed_by_body') for a,b in edges]
    manifest=dict(version=VERSION,rows=rows,links=links,
        parent_text_sha256={c.id:sha256(c.text.encode()).hexdigest() for c in tables},
        embedding=dict(provider='test',model='fake',dimensions=3))
    return TableRelations(manifest,store(*chunks),{r['id']:[1.,-1.,0.] for r in rows})


def assign_sections(catalog,assignments):
    sections={}
    for cid,sid in assignments.items():
        catalog.mapping[cid].update(section_id=sid,section_status='inferred')
        sections[sid]=dict(id=sid,status='inferred',role='section')
    return BodySectionCatalog(list(catalog.chunks.values()),dict(mapping=catalog.mapping,sections=list(sections.values())))


def sources(result):return {s.chunk_id:s.text for e in result for s in e.source_chunks}


def test_newly_linked_table_does_not_trigger_its_explanation_or_section():
    body=chunk(1,'See Table 1.');tab=table(2);explanation=chunk(3,'Table 1 shows the measured trend.',2)
    cat=body_catalog([body,tab,explanation],['body','table','body'])
    cat=assign_sections(cat,{body.id:'a',tab.id:'b',explanation.id:'b'})
    rel=relations(cat,[(body,tab),(tab,explanation)])
    result,info=assemble_body_context([seed(body)],cat,ContextOptions(True),rel)
    assert sources(result)=={body.id:body.text,tab.id:tab.text}
    assert info['assembly_passes']==1 and not info['post_context_expansion']
    assert {r['seed_chunk_id'] for r in info['candidate_origins']}=={body.id}
    assert all(link['source_chunk_id']==body.id for link in info['explicit_link_candidates'])
    # If the table really is a primary hit, its section and explanation qualify.
    result,_=assemble_body_context([seed(tab)],cat,ContextOptions(True),rel)
    assert sources(result)=={tab.id:tab.text,explanation.id:explanation.text}


def test_section_added_paragraph_cannot_follow_its_own_table_reference():
    body=chunk(1,'The main result.');secondary=chunk(2,'See Table 1.');tab=table(3)
    cat=body_catalog([body,secondary,tab],['body','body','table'])
    cat=assign_sections(cat,{body.id:'a',secondary.id:'a',tab.id:'b'})
    rel=relations(cat,[(secondary,tab)])
    result,info=assemble_body_context([seed(body)],cat,ContextOptions(True),rel)
    assert sources(result)=={body.id:body.text,secondary.id:secondary.text}
    assert not info['explicit_link_candidates']


def test_shared_section_and_explicit_link_produce_one_source_with_both_origins():
    body=chunk(1,'See Table 1.');tab=table(2)
    cat=body_catalog([body,tab],['body','table']);rel=relations(cat,[(body,tab)])
    result,info=assemble_body_context([seed(body)],cat,ContextOptions(True),rel)
    assert sources(result)=={body.id:body.text,tab.id:tab.text}
    assert info['added_chunk_ids']==[tab.id] and len(info['selected_explicit_links'])==1
    origin=next(x for x in info['candidate_origins'] if x['chunk_id']==tab.id)
    assert origin['origins']==['explicit_table_link','section']


def test_direct_link_has_priority_over_other_section_content_in_one_budget():
    body=chunk(1,'See Table 1. '+('a'*70));nearby=chunk(2,'b'*220);tab=table(3)
    cat=body_catalog([body,nearby,tab],['body','body','table'])
    cat=assign_sections(cat,{body.id:'a',nearby.id:'a',tab.id:'b'})
    result,info=assemble_body_context([seed(body)],cat,ContextOptions(True,max_evidence_chars=400,max_total_chars=400),
        relations(cat,[(body,tab)]))
    assert sources(result)=={body.id:body.text,tab.id:tab.text}
    assert info['budget_limited'] and nearby.id in info['skipped_candidate_chunk_ids']


def test_link_from_second_primary_in_shared_body_group_precedes_first_primary_section_candidates():
    a=chunk(1,'An original primary.');nearby=chunk(2,'b'*240);b=chunk(3,'See Table 1.');tab=table(4)
    cat=body_catalog([a,nearby,b,tab],['body','body','body','table'])
    cat=assign_sections(cat,{a.id:'a',nearby.id:'a',b.id:'a',tab.id:'b'})
    result,info=assemble_body_context([seed(a),seed(b,'[2]')],cat,
        ContextOptions(True,max_evidence_chars=350,max_total_chars=350),relations(cat,[(b,tab)]))
    assert sources(result)=={a.id:a.text,b.id:b.text,tab.id:tab.text}
    assert result[0].seed_chunk_ids==(a.id,b.id) and info['budget_limited']


def test_split_body_group_keeps_cross_section_link_with_the_primary_that_requested_it():
    a=chunk(1,'a'*200);b=chunk(2,'See Table 1. '+('b'*65));tab=table(3)
    cat=body_catalog([a,b,tab],['body','body','table'])
    cat=assign_sections(cat,{a.id:'a',b.id:'a',tab.id:'b'})
    result,_=assemble_body_context([seed(a),seed(b,'[2]')],cat,
        ContextOptions(True,max_evidence_chars=256,max_total_chars=800),relations(cat,[(b,tab)]))
    assert len(result)==2 and result[0].text==a.text
    assert {s.chunk_id for s in result[1].source_chunks}=={b.id,tab.id}
    assert result[1].seed_chunk_ids==(b.id,)


def test_link_cannot_use_a_second_evidence_entry_to_bypass_per_evidence_budget():
    body=chunk(1,'See Table 1. '+('a'*170));tab=table(2)
    cat=body_catalog([body,tab],['body','table'],assigned=False)
    result,info=assemble_body_context([seed(body)],cat,ContextOptions(True,max_evidence_chars=256,max_total_chars=1000),
        relations(cat,[(body,tab)]))
    assert sources(result)=={body.id:body.text} and info['budget_limited']
    assert info['omitted_explicit_links'][0]['reason']=='length_budget'


def test_primary_space_is_reserved_before_any_direct_link_or_section_supplement():
    a=chunk(1,'See Table 1. '+('a'*100));b=chunk(2,'b'*120);tab=table(3)
    cat=body_catalog([a,b,tab],['body','body','table'],assigned=False)
    result,info=assemble_body_context([seed(a),seed(b,'[2]')],cat,
        ContextOptions(True,max_evidence_chars=400,max_total_chars=300),relations(cat,[(a,tab)]))
    assert sources(result)=={a.id:a.text,b.id:b.text} and info['budget_limited']
    assert not info['omitted_seed_chunk_ids']


def test_supplements_cover_other_papers_before_spending_more_on_the_first_paper():
    a = chunk(1, 'a' * 30, doc='first')
    near_a = chunk(2, 'x' * 80, doc='first')
    farther_a = chunk(3, 'y' * 80, doc='first')
    b = chunk(1, 'b' * 30, doc='second')
    near_b = chunk(8, 'z' * 80, doc='second')
    cat = body_catalog([a, near_a, farther_a, b, near_b], ['body'] * 5, assigned=False)
    cat = assign_sections(cat, {a.id: 'a', near_a.id: 'a', farther_a.id: 'a', b.id: 'b', near_b.id: 'b'})

    result, info = assemble_body_context([seed(a), seed(b)], cat,
        ContextOptions(True, max_evidence_chars=256, max_total_chars=256))

    assert [[part.chunk_id for part in e.source_chunks] for e in result] == [[a.id, near_a.id], [b.id, near_b.id]]
    assert info['skipped_candidate_chunk_ids'] == [farther_a.id]
    assert info['context_chars'] <= 256


def test_each_round_gives_groups_a_turn_and_prioritizes_their_own_explicit_links():
    a = chunk(1, 'a' * 30)
    near_a = chunk(2, 'x' * 60)
    farther_a = chunk(3, 'y' * 60)
    b = chunk(5, 'See Tables 1 and 2.')
    tab1 = table(6)
    tab2 = table(7, 2)
    cat = body_catalog([a, near_a, farther_a, b, tab1, tab2], ['body'] * 4 + ['table'] * 2, assigned=False)
    cat = assign_sections(cat, {a.id: 'a', near_a.id: 'a', farther_a.id: 'a', b.id: 'b', tab1.id: 'b', tab2.id: 'b'})

    result, info = assemble_body_context([seed(a), seed(b)], cat,
        ContextOptions(True, max_evidence_chars=400, max_total_chars=380), relations(cat, [(b, tab1), (b, tab2)]))

    assert [[part.chunk_id for part in e.source_chunks] for e in result] == [[a.id, near_a.id, farther_a.id], [b.id, tab1.id]]
    assert info['skipped_candidate_chunk_ids'] == [tab2.id]


@pytest.mark.parametrize('budget, expected_counts', [(300, [3, 3]), (400, [4, 4])])
def test_round_robin_continues_after_first_round_despite_candidate_distance(budget, expected_counts):
    first = [chunk(i, 'a' * 40, doc='first') for i in range(1, 5)]
    second = [chunk(i, 'b' * 40, doc='second') for i in (1, 21, 41, 61)]
    cat = body_catalog(first + second, ['body'] * 8, assigned=False)
    cat = assign_sections(cat, {**{c.id: 'a' for c in first}, **{c.id: 'b' for c in second}})

    result, info = assemble_body_context([seed(first[0]), seed(second[0])], cat,
        ContextOptions(True, max_evidence_chars=256, max_total_chars=budget))

    assert [len(e.source_chunks) for e in result] == expected_counts
    assert info['context_chars'] <= budget
    assert info['supplement_allocation'] == ['evidence_round_robin', 'candidate_priority_within_evidence']


def test_round_robin_skips_oversized_and_shared_candidates_and_redistributes_unused_turns():
    from literature_rag.application.unified_context import PrimaryCandidateCatalog
    a = chunk(1, 'Primary A.')
    b = chunk(5, 'Primary B.')
    shared = chunk(2, 'Shared supplement.')
    oversized = chunk(6, 'x' * 300)
    later = chunk(7, 'Later supplement.')
    last = chunk(8, 'Final supplement.')
    chunks = [a, b, shared, oversized, later, last]
    cat = body_catalog(chunks, ['body'] * 6)
    allocator = PrimaryCandidateCatalog([seed(a), seed(b)], cat)
    allocator.origins = {
        a.id: {shared.id: {'section'}},
        b.id: {shared.id: {'section'}, oversized.id: {'section'}, later.id: {'section'}, last.id: {'section'}},
    }
    accepted = []
    occupied = {a.id, b.id}

    def try_add(group, c):
        if c.id in occupied or c.id == oversized.id:
            return False
        occupied.add(c.id)
        accepted.append((group, c.id))
        return True

    allocator.allocate_supplements([([seed(a)], [shared]), ([seed(b)], [shared, oversized, later, last])], try_add)

    assert accepted == [(0, shared.id), (1, later.id), (1, last.id)]


def test_link_candidates_are_bounded_per_primary_and_globally():
    bodies=[chunk(i,'See the numbered tables.') for i in range(1,6)]
    tables=[table(i+10,i) for i in range(1,16)]
    cat=body_catalog(bodies+tables,['body']*5+['table']*15,assigned=False)
    rel=relations(cat,[(body,tab) for i,body in enumerate(bodies) for tab in tables[3*i:3*i+3]])
    result,info=assemble_body_context([seed(c,f'[{i+1}]') for i,c in enumerate(bodies)],cat,ContextOptions(True),rel)
    assert len(info['selected_explicit_link_chunk_ids'])==8
    assert all(sum(link['seed_chunk_id']==c.id for link in info['explicit_link_candidates'])<=2 for c in bodies)
    assert len(info['omitted_explicit_links'])==7
    assert len(sources(result))==13


def test_retriever_never_calls_legacy_post_expansion_in_scientific_mode(monkeypatch):
    from literature_rag.domain.models import VectorMatch
    body=chunk(1,'See Table 1.');tab=table(2)
    cat=body_catalog([body,tab],['body','table'],assigned=False);rel=relations(cat,[(body,tab)])
    retrieve,_,_=service([body,tab],['body','table'],[VectorMatch(body.id,.9)],rel)
    monkeypatch.setattr('literature_rag.application.table_evidence.append_related_tables',
        lambda *_args,**_kwargs:pytest.fail('A second expansion pass must not run'))
    result=retrieve.retrieve('Measurements?',8,.35)
    assert sources(result)=={body.id:body.text,tab.id:tab.text}
    assert retrieve.last_context_diagnostics['assembly_passes']==1


def test_legacy_post_expansion_rejects_role_catalog_to_prevent_accidental_stacking():
    from literature_rag.application.table_evidence import append_related_tables
    body=chunk(1,'See Table 1.');tab=table(2);cat=body_catalog([body,tab],['body','table'])
    with pytest.raises(ValueError,match='unified primary'):
        append_related_tables([],relations(cat,[(body,tab)]),ContextOptions(True),{},body_catalog=cat)
