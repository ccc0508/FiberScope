"""A single rewrite branch is audited against an independent control, never a hidden search."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from report_rewrite_only_20261102 import retrieval_diff


def fixture():
    def evidence(cid):
        return dict(ref='[1]',filename='paper.pdf',page_start=1,page_end=1,chunk_id=cid,text='Text '+cid)
    before=dict(retrieved_evidence=[evidence('a')],retrieval_seed_evidence=[dict(chunk_id='a')],
        context_assembly=dict(rerank=dict(candidates=[dict(chunk_id='a'),dict(chunk_id='b')])))
    diag=dict(mode='rewrite_only',status='rewritten',original_query_searched=False,
        branches=[dict(branch='rewritten',query='Rephrased query',candidates=[dict(chunk_id='b'),dict(chunk_id='c')])],
        candidate_count_after_budget=2)
    after=dict(retrieved_evidence=[evidence('c')],retrieval_seed_evidence=[dict(chunk_id='c')],
        context_assembly=dict(query_rewrite=diag,rerank=dict(query_source='rewritten',query_text='Rephrased query')))
    return before,after


def test_novelty_is_computed_across_arms_and_rewritten_rerank_is_checked():
    before,after=fixture();d=retrieval_diff(before,after)
    assert d['rewrite_only_candidate_ids']==['c'] and d['rewrite_only_selected_ids']==['c']
    assert d['added_final_source_ids']==['c'] and d['removed_final_source_ids']==['a']
    assert d['shared_candidates']==1 and d['candidate_union_across_arms']==3
    assert not d['same_initial_generation_input']


@pytest.mark.parametrize('corrupt',['hidden_original','wrong_rerank_query'])
def test_report_rejects_a_hidden_original_search_or_original_rerank(corrupt):
    before,after=fixture()
    if corrupt=='hidden_original':
        after['context_assembly']['query_rewrite']['branches'].append(dict(branch='original'))
    else:
        after['context_assembly']['rerank']['query_text']='Original query'
    with pytest.raises(ValueError):retrieval_diff(before,after)
