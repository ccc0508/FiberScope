import json

import pytest

from literature_rag.application.body_context import BodySectionCatalog,assemble_body_context,VERSION
from literature_rag.application.context import ContextOptions
from literature_rag.application.retrieve import RetrievalService
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import InfrastructureError
from tests.test_role_context import make
from tests.test_section_context import chunk,seed
from tests.literature_fakes import InMemoryMetadataStore,InMemoryVectorStore,SpyEmbedder
from literature_rag.domain.models import VectorMatch


def body_catalog(chunks,roles,*,assigned=True):
    c=make(chunks,roles,assigned=assigned)
    return BodySectionCatalog(chunks,dict(mapping=c.mapping,sections=list(c.sections.values())))


def test_trusted_section_expands_across_pages_without_sentence_continuation_or_fallback():
    a=chunk(1,'A complete result.');b=chunk(2,'An independent explanation.',2)
    c=body_catalog([a,b],['body','body'])
    out,info=assemble_body_context([seed(a)],c,ContextOptions(True,radius=0))
    assert [s.chunk_id for s in out[0].source_chunks]==[a.id,b.id]
    assert info['decisions'][0]['mode']=='section' and info['version']==VERSION


def test_sentence_continuation_in_trusted_section_uses_section_path_only():
    a=chunk(1,'The fibers show');b=chunk(2,'greater accessibility.');c=chunk(3,'A further explanation.',2)
    catalog=body_catalog([a,b,c],['body']*3)
    out,info=assemble_body_context([seed(a)],catalog,ContextOptions(True))
    assert len(out[0].source_chunks)==3 and info['decisions'][0]['mode']=='section'


@pytest.mark.parametrize('role',['abstract','authors','affiliation','dates','keywords','reference','copyright',
    'publisher_note','funding','conflicts','author_contributions','supplementary','figure_caption'])
def test_metadata_and_caption_hits_keep_themselves_even_with_reliable_section(role):
    a=chunk(1,'The matched source');b=chunk(2,'an adjacent source')
    c=body_catalog([a,b],[role,role])
    out,info=assemble_body_context([seed(a)],c,ContextOptions(True))
    assert out[0].text==a.text and not info['added_chunk_ids']
    assert info['decisions'][0]['mode']=='non_body_standalone'


def test_missing_or_unreliable_section_needs_same_page_body_continuation():
    a=chunk(1,'The fibers show');b=chunk(2,'greater accessibility.');other_page=chunk(3,'and further changes',2)
    for assigned in [False,True]:
        c=body_catalog([a,b,other_page],['body']*3,assigned=assigned)
        if assigned:
            c.sections['s']['status']='parent_unresolved'
            for m in c.mapping.values():m['section_status']='parent_unresolved'
        out,info=assemble_body_context([seed(b)],c,ContextOptions(True))
        assert [s.chunk_id for s in out[0].source_chunks]==[a.id,b.id]
        assert info['decisions'][0]['mode']=='body_continuation_fallback'
        c.mapping[a.id]['role_status']='uncertain'
        out,info=assemble_body_context([seed(b)],c,ContextOptions(True))
        assert out[0].text==b.text and info['decisions'][0]['mode']=='unassigned_standalone'


def test_section_budget_exhaustion_does_not_trigger_neighbor_fallback_or_drop_primary():
    a=chunk(1,'a'*150);b=chunk(2,'b'*200)
    c=body_catalog([a,b],['body','body'])
    out,info=assemble_body_context([seed(a)],c,ContextOptions(True,max_evidence_chars=256,max_total_chars=300))
    assert out[0].text==a.text and info['budget_limited'] and info['decisions'][0]['mode']=='section'


def test_body_section_may_include_complete_table_and_caption_without_metadata():
    cs=[chunk(1,'See Table 1 for the results.'),chunk(2,'Table 1: 70.42%',kind='table'),
        chunk(3,'Figure 2: measured trend.',kind='figure_caption'),chunk(4,'Funding: unrelated')]
    c=body_catalog(cs,['body','table','figure_caption','funding'])
    out,_=assemble_body_context([seed(cs[0])],c,ContextOptions(True))
    assert [s.chunk_id for s in out[0].source_chunks]==[n.id for n in cs[:3]]
    # A table already among primary hits remains a separate, intact source.
    out,_=assemble_body_context([seed(cs[0]),seed(cs[1],'[2]')],c,ContextOptions(True))
    assert out[1].text==cs[1].text and out[1].seed_chunk_ids==(cs[1].id,)
    assert len({s.chunk_id for e in out for s in e.source_chunks})==sum(len(e.source_chunks) for e in out)


def test_catalog_loader_rejects_missing_stale_or_unclassified_metadata(tmp_path):
    a=chunk(1,'Author details');c=body_catalog([a],['authors']);store=InMemoryMetadataStore();store.chunks={a.id:a}
    with pytest.raises(InfrastructureError):BodySectionCatalog.load(tmp_path,store)
    structure=dict(mapping=c.mapping,sections=list(c.sections.values()))
    (tmp_path/'structure.json').write_text(json.dumps(structure),encoding='utf-8')
    loaded=BodySectionCatalog.load(tmp_path,store);assert loaded.mapping[a.id]['content_role']=='authors'
    structure['mapping'][a.id]['text_sha256']='0'*64
    (tmp_path/'structure.json').write_text(json.dumps(structure),encoding='utf-8')
    with pytest.raises(InfrastructureError):BodySectionCatalog.load(tmp_path,store)


def test_retriever_uses_new_policy_after_single_vector_search_without_legacy_neighbor_lookup():
    a=chunk(1,'Original abstract.');b=chunk(2,'Author details.')
    c=body_catalog([a,b],['abstract','authors'],assigned=False)
    metadata=InMemoryMetadataStore();metadata.chunks={a.id:a,b.id:b}
    metadata.get_context_chunks=lambda *args:pytest.fail('Legacy neighbor expansion must not run')
    vectors=InMemoryVectorStore();vectors.search=lambda *args:[VectorMatch(a.id,.9)]
    embedder=SpyEmbedder();service=RetrievalService(metadata,vectors,embedder,ContextOptions(True),body_context_catalog=c)
    out=service.retrieve('A question',8,.35)
    assert out[0].text==a.text and service.last_context_diagnostics['strategy']=='body_section'
    assert embedder.query_count==1


def test_configuration_is_explicit_and_default_keeps_legacy_behavior(tmp_path):
    assert Settings(_env_file=None).context_expansion_strategy=='same_page'
    with pytest.raises(ValueError):Settings(_env_file=None,context_expansion_strategy='body_section')
    integrated=Settings(_env_file=None,context_expansion_strategy='body_section',
        context_expansion_enabled=True,table_retrieval_enabled=True)
    assert integrated.table_retrieval_enabled
    env=tmp_path/'.env';env.write_text('RAG_CONTEXT_EXPANSION_ENABLED=true\nRAG_CONTEXT_EXPANSION_STRATEGY=body_section\n',encoding='utf-8')
    snapshot=configuration_snapshot(env)
    assert snapshot['pipeline_version']==VERSION and snapshot['context_expansion']['metadata_expansion'] is False
    assert snapshot['context_expansion']['section_trigger_roles']==['body','table','equation']
    assert 'application/body_context.py' in snapshot['pipeline_source_files']
