"""One non-thinking DeepSeek request; bounded, observable, no hidden retries."""
from hashlib import sha256
import json
from time import perf_counter

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from literature_rag.application.query_rewrite import SYSTEM_PROMPT, validate_rewrite
from literature_rag.diagnostics import provider_usage
from literature_rag.domain.errors import ProviderError, ProviderResponseError


class _Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: StrictStr


class DeepSeekQueryRewriter:
    def __init__(self, model, api_key, base_url=None, timeout=30, *, client=None):
        self.model_name = model
        self.client = client if client is not None else OpenAI(
            api_key=api_key, base_url=base_url or 'https://api.deepseek.com',
            max_retries=0, timeout=timeout)
        self.last_call = None

    def rewrite(self, question):
        started = perf_counter()
        request = dict(model=self.model_name, messages=[dict(role='system', content=SYSTEM_PROMPT),
            dict(role='user', content=json.dumps({'question': question}, ensure_ascii=False))],
            response_format={'type': 'json_object'}, extra_body={'thinking': {'type': 'disabled'}},
            temperature=0, max_tokens=768)
        self.last_call = dict(status='started', api_calls=1, requested_model=self.model_name,
            request_sha256=sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            usage=None, monetary_cost=None, retry_count=0, thinking_enabled=False)
        try:
            try:
                response = self.client.chat.completions.create(**request)
            except Exception:
                self.last_call['status'] = 'request_failed'
                raise ProviderError('query rewrite request failed; provider details redacted') from None
            self.last_call.update(usage=provider_usage(response), returned_model=getattr(response, 'model', None),
                system_fingerprint=getattr(response, 'system_fingerprint', None))
            try:
                content = response.choices[0].message.content
                if not isinstance(content, str):
                    raise ValueError('missing text')
                payload = _Payload.model_validate_json(content)
                query = validate_rewrite(question, payload.query)
            except (ValidationError, ValueError, AttributeError, IndexError, TypeError, ProviderResponseError):
                self.last_call['status'] = 'invalid_response'
                raise ProviderResponseError('query rewrite response failed validation') from None
            self.last_call.update(status='completed', response_sha256=sha256(content.encode()).hexdigest())
            return query
        finally:
            self.last_call['latency_ms'] = int((perf_counter() - started) * 1000)
