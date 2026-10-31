from dataclasses import replace
from copy import deepcopy

from literature_rag.application.fallback_ablation import remove_fallback_extras
from literature_rag.application.context import ContextOptions
from literature_rag.application.section_context import assemble_sections
from tests.test_section_context import chunk,seed,catalog


def test_only_fallback_extra_sources_removed_sections_unchanged_and_primary_preserved():
    a=chunk(1,'Matched reference',kind='reference');b=chunk(2,'Extra adjacent reference',kind='reference')
    c=chunk(4,'Scientific primary',2);d=chunk(5,'Scientific extra',2)
    cat=catalog([a,b,c,d],{a.id:None,b.id:None,c.id:'s',d.id:'s'})
    seeds=[seed(a),seed(c,'[2]')];old,info=assemble_sections(seeds,cat,ContextOptions(True));before=deepcopy(info)
    new,diag=remove_fallback_extras(old,seeds,info)
    assert len(new)==len(old)==2 and [e.ref for e in new]==[e.ref for e in old]
    assert new[1]==old[1] and new[0].text==a.text
    assert diag['fallback_ablation']['removed_chunk_ids']==[b.id]
    assert info==before and diag['fallback_ablation']['no_replacement_or_budget_redistribution']


def test_neighbor_that_is_also_a_primary_hit_is_never_removed():
    a=chunk(1,'Reference A',kind='reference');b=chunk(2,'Reference B',kind='reference')
    cat=catalog([a,b],{a.id:None,b.id:None});seeds=[seed(a),seed(b,'[2]')]
    old,info=assemble_sections(seeds,cat,ContextOptions(True));new,diag=remove_fallback_extras(old,seeds,info)
    assert new==old and not diag['fallback_ablation']['removed_chunk_ids']


def test_no_fallback_keeps_complete_inputs_identical():
    a=chunk(1,'Scientific primary');b=chunk(2,'Scientific extra')
    cat=catalog([a,b],{a.id:'s',b.id:'s'});seeds=[seed(a)]
    old,info=assemble_sections(seeds,cat,ContextOptions(True));new,diag=remove_fallback_extras(old,seeds,info)
    assert new==old and diag['context_chars']==info['context_chars']


def test_removal_does_not_use_freed_space_to_recover_skipped_candidates():
    a=chunk(1,'r'*100,kind='reference');b=chunk(2,'e'*100,kind='reference')
    c=chunk(4,'p'*100,2);d=chunk(5,'q'*150,2)
    cat=catalog([a,b,c,d],{a.id:None,b.id:None,c.id:'s',d.id:'s'})
    seeds=[seed(a),seed(c,'[2]')];old,info=assemble_sections(seeds,cat,ContextOptions(True,max_evidence_chars=256,max_total_chars=310))
    assert d.id in info['skipped_candidate_chunk_ids']
    new,diag=remove_fallback_extras(old,seeds,info)
    assert new[1]==old[1] and d.id not in {s.chunk_id for e in new for s in e.source_chunks}
    assert diag['skipped_candidate_chunk_ids']==info['skipped_candidate_chunk_ids']
