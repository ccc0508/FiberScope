from copy import deepcopy
from dataclasses import replace

from literature_rag.application.context import ContextOptions
from literature_rag.application.role_context import RoleSectionCatalog,assemble_roles
from tests.test_section_context import chunk,seed,catalog


def make(chunks,roles,*,assigned=True):
    original=catalog(chunks,{c.id:'s' if assigned else None for c in chunks})
    mapping=deepcopy(original.mapping)
    for c,role in zip(chunks,roles):
        mapping[c.id].update(content_role=role,role_status='uncertain' if role in {'unknown','mixed'} else 'identified',
            body_text=c.text,role_group='abstract:test' if role=='abstract' else None)
    return RoleSectionCatalog(chunks,dict(mapping=mapping,sections=list(original.sections.values())))


def test_reference_and_metadata_do_not_expand_to_neighbor_entries():
    for role in ['reference','authors','affiliation','keywords','copyright','unknown','mixed']:
        a=chunk(1,'Original matched content.');b=chunk(2,'Unrelated neighbor.')
        c=make([a,b],[role,'body'])
        out,info=assemble_roles([seed(a)],c,ContextOptions(True))
        assert out[0].text==a.text and not info['added_chunk_ids']
        assert info['decisions'][0]['mode'] in {'metadata_standalone','uncertain_standalone'}


def test_abstract_only_adds_parts_of_the_same_abstract_not_authors_keywords():
    cs=[chunk(i,t) for i,t in enumerate(['Author details','First abstract part.','Second abstract part.','Keywords: fibers'])]
    c=make(cs,['authors','abstract','abstract','keywords'],assigned=False)
    out,_=assemble_roles([seed(cs[1])],c,ContextOptions(True))
    assert [s.chunk_id for s in out[0].source_chunks]==[cs[1].id,cs[2].id]


def test_scientific_section_expansion_excludes_administrative_content():
    cs=[chunk(i,t) for i,t in enumerate(['Scientific conclusion.','Author Contributions: data collection','Funding: grant','Related scientific evidence.'])]
    c=make(cs,['body','author_contributions','funding','body'])
    out,_=assemble_roles([seed(cs[0])],c,ContextOptions(True))
    assert [s.chunk_id for s in out[0].source_chunks]==[cs[0].id,cs[3].id]


def test_only_real_body_continuation_triggers_neighbor_fallback():
    cs=[chunk(1,'The cellulose fibers show'),chunk(2,'increased accessibility.'),chunk(3,'Another complete sentence.')]
    c=make(cs,['body']*3,assigned=False)
    out,info=assemble_roles([seed(cs[1])],c,ContextOptions(True))
    assert [s.chunk_id for s in out[0].source_chunks]==[cs[0].id,cs[1].id]
    assert info['decisions'][0]['mode']=='body_continuation_fallback'
    c.mapping[cs[0].id]['role_status']='uncertain'
    out,info=assemble_roles([seed(cs[1])],c,ContextOptions(True))
    assert out[0].text==cs[1].text and info['decisions'][0]['mode']=='unassigned_standalone'
