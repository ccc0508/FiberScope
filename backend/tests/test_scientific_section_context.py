"""Tables/formulas may trigger trusted sections without expanding metadata."""
import pytest

from literature_rag.application.body_context import assemble_body_context,VERSION
from literature_rag.application.context import ContextOptions
from literature_rag.application.citations import CitationValidator
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
from tests.test_body_context import body_catalog
from tests.test_section_context import chunk,seed


@pytest.mark.parametrize('role',['table','equation'])
def test_table_or_formula_seed_expands_its_section_across_pages_and_preserves_sources(role):
    target=chunk(2,'Table 1 <table><tr><td>70.42</td></tr></table>' if role=='table' else '$CI = A / B$',2,kind=role)
    before=chunk(1,'The method and conditions are described here.')
    after=chunk(3,'Where A and B denote the measured quantities.',3)
    funding=chunk(4,'Funding: unsupported metadata.',3)
    ref=chunk(5,'1. Other paper. 2020.',3,kind='reference')
    chunks=[before,target,after,funding,ref]
    catalog=body_catalog(chunks,['body',role,'body','funding','reference'])
    result,info=assemble_body_context([seed(target)],catalog,ContextOptions(True,radius=0))
    assert info['version']==VERSION and info['decisions'][0]['mode']=='section'
    assert result[0].chunk_id==target.id and result[0].seed_chunk_ids==(target.id,)
    assert {s.chunk_id:s.text for s in result[0].source_chunks}=={c.id:c.text for c in [before,target,after]}
    assert (result[0].page_start,result[0].page_end)==(1,3)
    answer=GeneratedAnswer('The source reports the measurement. [1]',
        (GeneratedClaim('The source reports the measurement.',('[1]',)),))
    citation=CitationValidator().validate(answer,result).citations[0]
    assert citation.source_chunks==result[0].source_chunks


@pytest.mark.parametrize('role',['table','equation'])
@pytest.mark.parametrize('status',['unassigned','parent_unresolved','uncertain_role'])
def test_table_or_formula_without_trusted_section_never_uses_neighbor_fallback(role,status):
    target=chunk(1,'The original scientific source',kind=role)
    adjacent=chunk(2,'where adjacent text might look like a continuation.')
    catalog=body_catalog([target,adjacent],[role,'body'],assigned=status!='unassigned')
    if status=='parent_unresolved':
        catalog.sections['s']['status']='parent_unresolved'
        for m in catalog.mapping.values():m['section_status']='parent_unresolved'
    if status=='uncertain_role':catalog.mapping[target.id]['role_status']='uncertain'
    result,info=assemble_body_context([seed(target)],catalog,ContextOptions(True,radius=2))
    assert result[0].text==target.text and not info['added_chunk_ids']
    assert info['decisions'][0]['mode']==('uncertain_standalone' if status=='uncertain_role' else 'unassigned_scientific_standalone')


def test_body_table_and_formula_primary_hits_keep_distinct_anchors_and_share_no_sources():
    body=chunk(1,'See Table 1 and the equation for the conditions.')
    table=chunk(2,'Table 1 <table><tr><td>70.42</td></tr></table>',kind='table')
    equation=chunk(3,'$CI=A/B$',2,kind='equation')
    explanation=chunk(4,'Where A and B denote the measured quantities.',2)
    catalog=body_catalog([body,table,equation,explanation],['body','table','equation','body'])
    for ordered in [[table,equation,body],[body,table,equation]]:
        result,info=assemble_body_context([seed(c,f'[{i+1}]') for i,c in enumerate(ordered)],catalog,ContextOptions(True))
        assert [e.chunk_id for e in result]==[c.id for c in ordered]
        assert all(e.seed_chunk_ids==(c.id,) for e,c in zip(result,ordered,strict=True))
        sources=[s for e in result for s in e.source_chunks]
        assert len(sources)==len({s.chunk_id for s in sources})==4
        assert {s.chunk_id:s.text for s in sources}=={c.id:c.text for c in [body,table,equation,explanation]}
        assert len(info['added_chunk_ids'])==1


@pytest.mark.parametrize('role',['table','equation'])
def test_scientific_expansion_respects_budget_and_never_truncates_or_drops_primary(role):
    target=chunk(1,'Table 1 <table><tr><td>'+('2'*140)+'</td></tr></table>' if role=='table' else '$'+('x'*160)+'$',kind=role)
    large=chunk(2,'A large explanation. '+('b'*300))
    other=chunk(3,'A separate primary source.',2)
    catalog=body_catalog([target,large,other],[role,'body','body'])
    result,info=assemble_body_context([seed(target),seed(other,'[2]')],catalog,
        ContextOptions(True,max_evidence_chars=256,max_total_chars=300))
    assert {s.chunk_id:s.text for e in result for s in e.source_chunks}=={target.id:target.text,other.id:other.text}
    assert info['budget_limited'] and all(d['mode']=='section' for d in info['decisions'])
    assert sum(len(e.text) for e in result)<=300


@pytest.mark.parametrize('role',['table','equation'])
def test_scientific_seed_does_not_pull_other_sections_or_uncertain_sources(role):
    target=chunk(1,'Original source.',kind=role)
    same=chunk(2,'Same-section explanation.')
    other=chunk(3,'Other-section content.')
    uncertain=chunk(4,'Uncertain content.')
    catalog=body_catalog([target,same,other,uncertain],[role,'body','body','body'])
    catalog.mapping[uncertain.id]['role_status']='uncertain'
    catalog.mapping[other.id].update(section_id='other',section_status='inferred')
    catalog.sections['other']=dict(id='other',status='inferred',role='section')
    # Rebuild membership from the authoritative mapping, as the loader does.
    catalog=type(catalog)([target,same,other,uncertain],dict(mapping=catalog.mapping,sections=list(catalog.sections.values())))
    result,_=assemble_body_context([seed(target)],catalog,ContextOptions(True))
    assert {s.chunk_id for e in result for s in e.source_chunks}=={target.id,same.id}
