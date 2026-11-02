"""Qwen3-VL embeddings through DashScope's native multimodal HTTP API."""
import base64
from hashlib import sha256
import json
from math import fsum, isfinite
from pathlib import Path
from time import perf_counter

import httpx

from literature_rag.diagnostics import combined_usage
from literature_rag.domain.errors import ProviderError, ProviderResponseError

MODEL = 'qwen3-vl-embedding'
DIMENSIONS = {256, 512, 768, 1024, 1536, 2048, 2560}
DEFAULT_BASE_URL = 'https://dashscope.aliyuncs.com/api/v1'
ENDPOINT = '/services/embeddings/multimodal-embedding/multimodal-embedding'


def image_data_url(path):
    """Send actual local image bytes, not a filename or a text description."""
    payload = Path(path).read_bytes()
    if payload.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif payload.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif payload[:4] == b'RIFF' and payload[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('image input must be PNG, JPEG or WebP')
    if len(payload) > 10 * 1024 * 1024:
        raise ValueError('image input exceeds the application 10 MiB bound')
    return f'data:{mime};base64,' + base64.b64encode(payload).decode('ascii')


class DashScopeEmbedder:
    """Text and images share one model space; no implicit model/provider fallback."""
    def __init__(self, model, dimensions, api_key, base_url=None, *, client=None, timeout=60):
        if model != MODEL or dimensions not in DIMENSIONS or type(dimensions) is not int:
            raise ValueError('unsupported Qwen3-VL embedding model or dimensions')
        base = (base_url or DEFAULT_BASE_URL).rstrip('/')
        if not base.endswith('/api/v1'):
            raise ValueError('use the native DashScope /api/v1 base URL, not the OpenAI-compatible endpoint')
        self.model_name, self.dimensions = model, dimensions
        self.endpoint = base + ENDPOINT
        self.api_key = api_key
        self.client = client if client is not None else httpx.Client(timeout=timeout, follow_redirects=False)
        self.last_usage = None
        self.last_calls = []

    def _request(self, contents, fusion=False):
        started = perf_counter()
        request = dict(model=self.model_name, input=dict(contents=contents),
                       parameters=dict(dimension=self.dimensions, enable_fusion=fusion))
        call = dict(status='started', api_calls=1, model=self.model_name, dimensions=self.dimensions,
            input_count=len(contents), modalities=[next(iter(c)) for c in contents], fusion=fusion,
            request_sha256=sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
            usage=None, monetary_cost=None, retry_count=0)
        self.last_calls.append(call)
        try:
            try:
                response = self.client.post(self.endpoint, json=request,
                    headers={'Authorization': 'Bearer '+self.api_key, 'Content-Type': 'application/json'})
            except Exception:
                call['status'] = 'request_failed'
                raise ProviderError('DashScope embedding transport failed; provider details redacted') from None
            call['http_status'] = response.status_code
            if not 200 <= response.status_code < 300:
                call['status'] = 'request_failed'
                raise ProviderError(f'DashScope embedding request failed (HTTP {response.status_code})') from None
            try:
                body = response.json()
                usage = body.get('usage') or {}
                # For Qwen3-VL, input_tokens is TEXT only; total_tokens includes image_tokens.
                call['usage'] = {k:usage[k] for k in ('input_tokens','image_tokens','total_tokens')
                                 if type(usage.get(k)) is int and usage[k] >= 0} or None
                rows = body['output']['embeddings']
                expected = 1 if fusion else len(contents)
                if len(rows) != expected or any(type(r.get('index')) is not int for r in rows):
                    raise ValueError('wrong indexes/count')
                if sorted(r['index'] for r in rows) != list(range(expected)):
                    raise ValueError('duplicate/missing indexes')
                vectors = []
                for row in sorted(rows, key=lambda r:r['index']):
                    vector = row['embedding']
                    if not isinstance(vector, list) or len(vector) != self.dimensions:
                        raise ValueError('wrong vector dimensions')
                    if any(type(v) not in (int,float) or not isfinite(v) for v in vector):
                        raise ValueError('nonfinite/invalid vector')
                    if fsum(v*v for v in vector) <= 0:
                        raise ValueError('zero vector')
                    vectors.append([float(v) for v in vector])
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError):
                call['status'] = 'invalid_response'
                raise ProviderResponseError('DashScope embedding response failed validation') from None
            call.update(status='completed', response_sha256=sha256(response.content).hexdigest())
            return vectors
        finally:
            call['latency_ms'] = int((perf_counter() - started) * 1000)
            self.last_usage = combined_usage(self.last_calls)

    def _embed(self, contents, batch_size):
        self.last_calls = []; self.last_usage = None
        vectors = []
        for start in range(0, len(contents), batch_size):
            vectors.extend(self._request(contents[start:start+batch_size]))
        return vectors

    def embed_documents(self, texts):
        texts = list(texts)
        if any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError('embedding text must be nonempty')
        return self._embed([dict(text=t) for t in texts], 20)

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    def embed_images(self, paths):
        return self._embed([dict(image=image_data_url(p)) for p in paths], 10)

    def embed_fused(self, text, image_path):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('fusion text must be nonempty')
        self.last_calls = []; self.last_usage = None
        return self._request([dict(text=text),dict(image=image_data_url(image_path))], fusion=True)[0]
