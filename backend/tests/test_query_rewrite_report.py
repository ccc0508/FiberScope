"""Keep distinct stages and count actual embedding calls without double-counting totals."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from report_query_rewrite_20261102 import source_ids, retrieval_diff, runtime_summary


def test_context_source_diff_does_not_count_references_or_shared_chunks_twice():
    response=dict(retrieved_evidence=[dict(chunk_id='a',source_chunks=[dict(chunk_id='a'),dict(chunk_id='b')]),
                                    dict(chunk_id='c',source_chunks=[])])
    assert source_ids(response)=={'a','b','c'}


def test_usage_counts_each_query_embedding_and_rewrite_once():
    r=dict(status='answered',end_to_end_ms=12000,response=dict(
        generation_calls=[dict(usage=dict(prompt_tokens=10,completion_tokens=5,total_tokens=15,reasoning_tokens=3),
                               model_info=dict(returned_model='answer-model'))],rerank_calls=[dict(usage=None)],
        embedding_usage=dict(prompt_tokens=7,total_tokens=7),
        query_embedding_calls=[dict(usage=dict(prompt_tokens=3,total_tokens=3)),dict(usage=dict(prompt_tokens=4,total_tokens=4))],
        query_rewrite_calls=[dict(usage=dict(total_tokens=20),returned_model='rewriter')]))
    summary=runtime_summary([r])
    assert summary['question_embedding']['calls']==2 and summary['question_embedding']['known_tokens']['total_tokens']==7
    assert summary['generation']['known_tokens']['total_tokens']==15
    assert summary['query_rewrite']['calls']==1
    assert summary['rerank']['total_token_unknown_calls']==1


def test_same_source_set_does_not_imply_same_ordered_generation_input():
    evidence=[dict(ref=f'[{i+1}]',filename='paper.pdf',page_start=1,page_end=1,chunk_id=cid,text='Text '+cid)
              for i,cid in enumerate(['a','b'])]
    candidates=[dict(chunk_id='a'),dict(chunk_id='b')]
    original=dict(retrieved_evidence=evidence,retrieval_seed_evidence=candidates,
                  context_assembly=dict(rerank=dict(candidates=candidates)))
    diag=dict(status='rewritten',branches=[dict(branch='original',query='Original',candidates=candidates)],
        original_candidates=2,rewritten_candidates=2,shared_candidates=2,unique_candidates=2,
        candidate_count_after_budget=2,rewrite_only_candidate_ids=[],rewrite_only_selected_ids=[],rewrite_only_final_source_ids=[])
    rewritten=dict(retrieved_evidence=list(reversed(evidence)),retrieval_seed_evidence=list(reversed(candidates)),
                   context_assembly=dict(rerank=dict(candidates=candidates),query_rewrite=diag))
    result=retrieval_diff(original,rewritten)
    assert result['same_final_sources'] and not result['same_initial_generation_input']
    assert not result['added_final_source_ids'] and not result['removed_final_source_ids']
