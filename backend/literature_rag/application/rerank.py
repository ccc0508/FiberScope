"""Reorder authoritative parent sources; retain cosine scores and immutable source text."""
from dataclasses import replace
from hashlib import sha256
from math import isfinite

from literature_rag.domain.errors import ProviderResponseError

VERSION='candidate-rerank-v1'


def rank_candidates(question,evidences,reranker,top_k):
    if not evidences:return [],dict(enabled=True,version=VERSION,status='empty',candidates=[],selected_chunk_ids=[])
    scores=reranker.rerank(question,[e.text for e in evidences])
    if len(scores)!=len(evidences) or any(type(s) not in (int,float) or not isfinite(s) or not 0<=s<=1 for s in scores):
        raise ProviderResponseError('rerank scores do not match candidate sources')
    order=sorted(range(len(evidences)),key=lambda i:(-scores[i],i))
    ranked=[replace(evidences[i],ref=f'[{rank+1}]') for rank,i in enumerate(order)]
    diagnostics=dict(enabled=True,version=VERSION,status='completed',
        input_policy='Unmodified question and full parent chunk text; no gold evidence, query rewrite, type filter or truncation.',
        score_policy='Cosine only for prefilter; rank by rerank score; original cosine retained in evidence.score; no rerank threshold.',
        selected_chunk_ids=[e.chunk_id for e in ranked[:top_k]],
        candidates=[dict(chunk_id=evidences[i].chunk_id,vector_rank=i+1,rerank_rank=rank+1,
            vector_score=evidences[i].score,rerank_score=scores[i],selected=rank<top_k,
            source_text_sha256=sha256(evidences[i].text.encode()).hexdigest(),source_chars=len(evidences[i].text))
            for rank,i in enumerate(order)])
    return ranked,diagnostics
