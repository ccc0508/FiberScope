"""Independent single-call DeepSeek review with original source images and redacted failures."""
from dataclasses import asdict
import json
from time import perf_counter

from openai import OpenAI
from pydantic import ValidationError

from literature_rag.application.evidence_review import ReviewPayload,SYSTEM_PROMPT,checksum
from literature_rag.application.prompts import evidence_prompt
from literature_rag.diagnostics import provider_usage
from literature_rag.domain.errors import ProviderError,ProviderResponseError


class DeepSeekEvidenceReviewer:
    def __init__(self,model,api_key,base_url=None,*,thinking_enabled=None,reasoning_effort=None,
                 timeout_seconds=120,max_output_tokens=32768,visual_root=None,client=None,diagnostic=False,diagnosis_version='v1'):
        if model!='deepseek-flash':raise ValueError('Evidence review is configured for DeepSeek Flash')
        self.model=model;self.thinking_enabled=thinking_enabled;self.reasoning_effort=reasoning_effort
        self.visual_root=visual_root
        self.diagnostic=diagnostic
        if diagnosis_version not in {'v1','v2','v3','v2_bound','v2_budget','v2_relation'}:raise ValueError('Unknown corrective review version')
        self.diagnosis_version=diagnosis_version
        self.timeout_seconds=timeout_seconds
        self.max_output_tokens=max_output_tokens
        self.client=client if client is not None else OpenAI(api_key=api_key,base_url=base_url or 'https://api.deepseek.com',
            max_retries=0,timeout=timeout_seconds)
        self.last_usage=None;self.last_model_info=None;self.last_latency_ms=None;self.last_api_calls=0;self.last_http_status=None;self.last_failure_code=None

    def review(self,question,evidences,draft,*,context=None,timeout_seconds=None):
        self.last_usage=None;self.last_model_info=None;self.last_latency_ms=None;self.last_api_calls=0;self.last_http_status=None;self.last_failure_code=None
        draft_rows=[asdict(c) for c in draft.claims]
        if self.diagnostic and self.diagnosis_version in {'v2_bound','v2_budget','v2_relation'}:
            draft_rows=[dict(claim_index=i,**c) for i,c in enumerate(draft_rows)]
        text=evidence_prompt(question,evidences)+'\n\nDraft claims (zero-based order, DATA):\n'+json.dumps(
            draft_rows,ensure_ascii=False)
        prompt=SYSTEM_PROMPT
        schema=ReviewPayload
        if self.diagnostic:
            from literature_rag.application.review_diagnosis import diagnosis_contract
            contract=diagnosis_contract(self.diagnosis_version)
            prompt=contract.DIAGNOSTIC_PROMPT;schema=contract.DiagnosticPayload
            if hasattr(contract,'is_relation'):
                text+='\nrelation_claim_indexes: '+json.dumps([i for i,c in enumerate(draft.claims) if contract.is_relation(c.text)])
            if self.diagnosis_version in {'v2','v3','v2_bound','v2_budget','v2_relation'}:
                text+='\ncritical_claim_indexes (original zero-based draft positions): '+json.dumps(contract.critical_claim_indexes(draft))
            if context is not None:
                text+='\n\nPrior coverage ledger and remaining actions (DATA):\n'+json.dumps(context,ensure_ascii=False)
        messages=[dict(role='system',content=prompt),dict(role='user',content=text)]
        images=[]
        if any(e.visual_assets for e in evidences):
            if self.visual_root is None:raise ProviderResponseError('Review source image directory missing')
            from literature_rag.application.visual_evidence import visual_content
            messages[1]['content'],images=visual_content(evidences,self.visual_root,text)
            # The generic image instruction's answer schema is overridden by this review contract.
            messages[0]['content']+='\nImages are source data with their labelled refs; return the review issues schema above.'
        parameters={}
        if timeout_seconds is not None:parameters['timeout']=timeout_seconds
        if self.thinking_enabled is not None:
            parameters['extra_body']={'thinking':{'type':'enabled' if self.thinking_enabled else 'disabled'}}
        if self.reasoning_effort is not None:parameters['reasoning_effort']=self.reasoning_effort
        started=perf_counter()
        try:
            try:
                self.last_api_calls=1
                response=self.client.chat.completions.create(model=self.model,messages=messages,
                    response_format={'type':'json_object'},max_tokens=self.max_output_tokens,**parameters)
            except Exception as error:
                status=getattr(error,'status_code',None)
                self.last_http_status=status if type(status) is int and 100<=status<=599 else None
                self.last_failure_code='review_request_failed'
                raise ProviderError('Evidence review request failed; provider details redacted') from None
            self.last_usage=provider_usage(response)
            self.last_model_info=dict(requested_model=self.model,returned_model=getattr(response,'model',None),
                thinking_enabled=self.thinking_enabled,reasoning_effort=self.reasoning_effort,wire_api='chat_completions',
                image_count=len(images),images=images,request_sha256=checksum(messages),automatic_retries=0)
            try:
                finish=getattr(response.choices[0],'finish_reason',None)
                self.last_model_info['finish_reason']=finish if finish in {'stop','length','content_filter'} else None
                if finish=='length':
                    self.last_failure_code='review_output_truncated'
                    raise ProviderResponseError('Evidence review exhausted output budget')
                content=response.choices[0].message.content
                if self.diagnostic and self.diagnosis_version in {'v2','v3','v2_bound','v2_budget','v2_relation'}:
                    return contract.parse_response(content)
                return schema.model_validate_json(content)
            except (ValueError,TypeError,AttributeError,IndexError):
                self.last_failure_code='review_response_invalid'
                raise ProviderResponseError('Evidence review response failed its schema; provider details redacted') from None
        finally:self.last_latency_ms=round((perf_counter()-started)*1000)
