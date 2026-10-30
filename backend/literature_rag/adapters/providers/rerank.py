"""Bounded SiliconFlow rerank API; no automatic retry, fallback or source rewriting."""
from collections.abc import Sequence
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter

import httpx

from literature_rag.domain.errors import ProviderError, ProviderResponseError

VERSION='candidate-rerank-v1'


def digest_json(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def usage_snapshot(body):
    meta=body.get('meta')
    meta=meta if isinstance(meta,dict) else {}
    source=body.get('usage') or meta.get('tokens')
    if not isinstance(source,dict):return None
    values={k:v for k in ['input_tokens','output_tokens','total_tokens','prompt_tokens','completion_tokens']
        if type(v:=source.get(k)) is int and v>=0}
    return values or None


class SiliconFlowReranker:
    def __init__(self,model,api_key,base_url,timeout=60,client=None):
        self.model_name=model
        self._api_key=api_key
        self.base_url=base_url.rstrip('/')
        self.timeout=timeout
        self.client=client
        self.last_call=None

    def rerank(self,question:str,texts:Sequence[str])->list[float]:
        if not isinstance(question,str) or not question.strip() or not 1<=len(texts)<=50 or any(not isinstance(t,str) or not t.strip() for t in texts):
            raise ValueError('invalid rerank inputs')
        request=dict(model=self.model_name,query=question,documents=list(texts),top_n=len(texts),return_documents=False,
            max_chunks_per_doc=1024,overlap_tokens=80)
        call=dict(version=VERSION,model=self.model_name,status='started',api_calls=1,
            candidate_count=len(texts),request_sha256=digest_json(request),usage=None,monetary_cost=None,
            max_chunks_per_doc=1024,overlap_tokens=80,application_truncation=False)
        self.last_call=call;started=perf_counter()
        try:
            try:
                def post(client):
                    return client.post(self.base_url+'/rerank',json=request,
                        headers={'Authorization':'Bearer '+self._api_key},timeout=self.timeout)
                if self.client is None:
                    with httpx.Client(trust_env=False,follow_redirects=False) as client:response=post(client)
                else:response=post(self.client)
            except httpx.HTTPError:
                call.update(status='request_failed',reason_code='transport_error')
                raise ProviderError('rerank request failed') from None
            call['http_status']=response.status_code
            call['response_sha256']=sha256(response.content).hexdigest()
            if not response.is_success:
                call.update(status='request_failed',reason_code='http_'+str(response.status_code))
                raise ProviderError('rerank provider returned an error') from None
            try:
                body=response.json()
                if not isinstance(body,dict):raise ValueError
                call['usage']=usage_snapshot(body)
                results=body['results']
                if not isinstance(results,list) or len(results)!=len(texts):raise ValueError
                scores=[None]*len(texts)
                for result in results:
                    index=result['index'];score=result['relevance_score']
                    if type(index) is not int or not 0<=index<len(texts) or scores[index] is not None:raise ValueError
                    if type(score) not in (int,float) or not isfinite(score) or not 0<=score<=1:raise ValueError
                    scores[index]=float(score)
                if any(s is None for s in scores):raise ValueError
            except (ValueError,KeyError,TypeError,IndexError,OverflowError):
                call.update(status='invalid_response',reason_code='invalid_scores_or_indexes')
                raise ProviderResponseError('rerank response has invalid scores or indexes') from None
            call.update(status='completed',scores=scores)
            return scores
        finally:call['latency_ms']=round((perf_counter()-started)*1000)
