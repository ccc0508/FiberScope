"""Evaluation-only worker: replay the same retrieval rewrite for both embedding arms.

This harness reads only the user's question and a frozen rewrite, never references
or scorecards. It replaces the rewrite dependency, leaving the QA worker unchanged.
"""
from hashlib import sha256
import json
from pathlib import Path
import sys


def replay_rewriter(cache,cache_sha256):
    from literature_rag.application.query_rewrite import validate_rewrite
    from literature_rag.domain.errors import ProviderError

    class FrozenQueryRewriter:
        def __init__(self,*args,**kwargs):self.last_call=None
        def rewrite(self,question):
            key=sha256(question.strip().encode()).hexdigest()
            row=cache['queries'].get(key)
            if row is None or row['question']!=question.strip():
                raise ValueError('Question does not match the frozen rewrite input')
            self.last_call=dict(status='replayed_for_controlled_evaluation',api_calls=0,usage=None,
                cache_sha256=cache_sha256,question_sha256=key,original_call_status=row['status'],
                original_response_sha256=row.get('provider_call',{}).get('response_sha256'))
            if row['status']!='completed':raise ProviderError('Frozen rewrite was unavailable; use original retrieval')
            return validate_rewrite(question,row['query'])
    return FrozenQueryRewriter


def main():
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root))
    run=json.loads((root.parent/'run.json').read_text(encoding='utf-8'))
    control=run['embedding_eval_control']
    cache_path=root/'embedding-query-cache.json';raw=cache_path.read_bytes()
    if sha256(raw).hexdigest()!=control['query_cache_sha256']:
        raise ValueError('Frozen rewrite cache changed')
    if sha256(Path(__file__).read_bytes()).hexdigest()!=control['wrapper_sha256']:
        raise ValueError('Frozen evaluation wrapper changed')
    from literature_rag.adapters.providers import query_rewrite
    query_rewrite.DeepSeekQueryRewriter=replay_rewriter(json.loads(raw),control['query_cache_sha256'])
    import literature_worker
    literature_worker.main()


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
