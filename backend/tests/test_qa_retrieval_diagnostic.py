"""Retrieval diagnostics must not confuse page hits, approximate text or model calls."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'backend'))
import diagnose_qa_retrieval as diag
import qa_retrieval_probe_worker as worker
from qa_retrieval_alignment import locate_segment,normalized_view,numeric_table_target,source_pages,span_coverage


def test_normalization_changes_only_search_view_and_retains_original_offsets():
    text='CI−XI <sup>2</sup> and 4.5&nbsp;nm'
    normalized,positions=normalized_view(text)
    assert normalized=='CI-XI2and4.5nm'
    assert text[positions[0]]=='C' and text[positions[-1]]=='m'
    assert '−' in text and '<sup>' in text


def test_same_page_and_keyword_are_not_enough_for_source_span_coverage():
    target=dict(status='located',spans=[dict(source_id='page_6',start=100,end=120)])
    chunks={'wrong':[dict(source_id='page_6',start=0,end=50)],
            'a':[dict(source_id='page_6',start=95,end=110)],
            'b':[dict(source_id='page_6',start=108,end=125)]}
    assert span_coverage(target,['wrong'],chunks)['status']=='missing'
    partial=span_coverage(target,['a'],chunks)
    assert (partial['status'],partial['covered'],partial['total'])==('partial',10,20)
    complete=span_coverage(target,['a','b','a'],chunks)
    assert (complete['status'],complete['covered'])==('complete',20)


def test_changed_scientific_number_is_flagged_for_review_not_certified_by_fuzzy_match():
    quote='The Pearson correlation coefficient was 0.888 for the softwood fibers in this experiment.'
    parsed=quote.replace('0.888','0.889')
    page=source_pages([dict(source_id='original',page=1,text=parsed)])
    located=locate_segment(dict(quote=quote,pdf_page=1),page)
    assert located['status']=='review_required'
    assert located['scientific_numeric_difference'] is True
    assert quote.endswith('experiment.') and '0.889' not in quote


def test_unmatched_quote_stays_unknown_instead_of_becoming_a_retrieval_miss():
    target=locate_segment(dict(quote='An unrelated verified statement.',pdf_page=1),
        source_pages([dict(source_id='a',page=1,text='Completely different experimental method.')]))
    assert target['status']=='unresolved'
    assert span_coverage(target,[],{})['status']=='unresolved'


def table_fixture(change=False):
    rows=[[0,73.23,40.46,3.2,3.5,4.5],[4000,70.42,37.71,3.1,3.4,4.6],
          [8000,72.54,39.65,3.2,3.4,4.6],[12000,70.93,36.22,3.1,3.7,4.7],[16000,69.82,34.20,3.2,3.5,4.7]]
    quote='(a) CI (%) Crystallite Size (nm) '+ ' '.join(str(x) for row in rows for x in row)
    if change:rows[1][1]=99.99
    text='Table 1. CI and crystal sizes.\n<table>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    return dict(locator='Table 1(a): annotated rows',pdf_page=6,quote=quote),[dict(source_id='table1',page=6,kind='table',text=text)]


def test_table_location_requires_all_numeric_rows_not_one_shared_number():
    reference,units=table_fixture()
    located=numeric_table_target(reference,units)
    assert located['method']=='verified_table_rows' and located['numeric_cells']==30
    wrong_reference,wrong_units=table_fixture(change=True)
    assert numeric_table_target(wrong_reference,wrong_units) is None


def test_probe_payload_allowlist_excludes_gold_answers_and_credentials():
    configuration=dict(embedding_provider='test',embedding_model='test-model',embedding_dimensions=2,
        top_k=8,min_score=.35,context_expansion={},reference_answer='GOLD_CANARY',api_key='SECRET_CANARY')
    study=dict(configuration=configuration,sources={'test':dict(run_id='dummy')})
    payload=diag.probe_payload(study,'test',[dict(task_id='A',question='Question',vector=[.2,.4],reference_answer='GOLD_CANARY')])
    assert 'CANARY' not in str(payload)
    assert set(payload['queries'][0])=={'task_id','question','vector'}


def test_frozen_retrieval_wrapper_records_all_candidates_without_changing_selection(monkeypatch):
    import literature_rag.adapters.chroma.vector_store as vectors
    import literature_rag.adapters.sqlite.metadata_store as metadata
    from literature_rag.domain.models import Chunk,VectorMatch
    chunks={f'c{i}':Chunk(f'c{i}','d','paper.pdf',1,1,i,f'Source text {i}',4,'test',kind='paragraph') for i in range(60)}
    calls=[]
    class Vectors:
        def __init__(self,*args):pass
        def search(self,vector,limit):
            calls.append((vector,limit))
            return [VectorMatch(f'c{i}',1-i*.01) for i in range(50)]
    class Metadata:
        def __init__(self,*args):pass
        def get_chunks(self,ids):return [chunks[cid] for cid in ids]
        def get_context_chunks(self,ids,radius):
            indices={chunks[cid].chunk_index for cid in ids}
            return [c for c in chunks.values() if any(abs(c.chunk_index-i)<=radius for i in indices)]
    monkeypatch.setattr(vectors,'ChromaVectorStore',Vectors)
    monkeypatch.setattr(metadata,'SqliteMetadataStore',Metadata)
    result=worker.run(dict(backend=str(ROOT/'backend'),library='unused',configuration=dict(
        embedding_provider='test',embedding_model='test',embedding_dimensions=2,top_k=8,min_score=.85,
        context_expansion=dict(context_expansion_enabled=True,context_neighbor_radius=1,context_max_evidence_chars=8000,context_max_total_chars=24000)),
        queries=[dict(task_id='A',question=' Question ',vector=[.2,.4])]))
    record=result['records'][0]
    assert calls==[([.2,.4],50)]
    assert len(record['candidates'])==50 and any(not c['passes_threshold'] for c in record['candidates'])
    assert [c['chunk_id'] for c in record['seeds']]==[f'c{i}' for i in range(8)]
    assert {s['chunk_id'] for e in record['final'] for s in e['source_chunks']}=={f'c{i}' for i in range(9)}
    assert result['generation_calls']==result['judge_calls']==result['embedding_provider_calls']==0


def test_bottleneck_distinguishes_ranking_threshold_and_neighbor_recovery():
    stages={name:dict(status='complete') for name in ['library','top50','passing50','top8','final']}
    stages['top8']['status']='missing';stages['final']['status']='missing'
    assert diag.bottleneck(stages)=='outside_top8_or_partial'
    stages['final']['status']='complete'
    assert diag.bottleneck(stages)=='neighbor_recovered'
    stages['passing50']['status']='missing'
    assert diag.bottleneck(stages)=='threshold_or_missing_metadata'


def test_reordering_is_distinguished_from_changed_source_membership():
    a=dict(chunk_id='a',ref='[1]',text='Text A',source_chunks=[dict(chunk_id='a')])
    b=dict(chunk_id='b',ref='[2]',text='Text B',source_chunks=[dict(chunk_id='b')])
    old=dict(retrieval_seed_evidence=[a,b],retrieved_evidence=[a,b])
    same=diag.replay_agreement(dict(seeds=[a,b],final=[a,b]),old)
    assert all(same.values())
    moved=diag.replay_agreement(dict(seeds=[b,a],final=[b,a]),old)
    assert moved['top8_equal_history'] is False and moved['context_equal_history'] is False
    assert moved['top8_members_equal_history'] is True and moved['context_sources_equal_history'] is True
