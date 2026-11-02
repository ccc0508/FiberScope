"""Native multimodal contract, source ordering, costs and sanitized errors."""
import json
from math import nan
from pathlib import Path

import httpx
import pytest

from literature_rag.adapters.providers.dashscope import DashScopeEmbedder, MODEL
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import ProviderError, ProviderResponseError


def provider(handler):
    return DashScopeEmbedder(MODEL,256,'private-test-token',
        client=httpx.Client(transport=httpx.MockTransport(handler)))


def response(request,*,reverse=False):
    body=json.loads(request.content); contents=body['input']['contents']
    count=1 if body['parameters']['enable_fusion'] else len(contents)
    rows=[dict(index=i,embedding=[float(i+1)]*body['parameters']['dimension'],type='vl') for i in range(count)]
    return dict(output=dict(embeddings=list(reversed(rows)) if reverse else rows),
                usage=dict(input_tokens=13,image_tokens=5,total_tokens=18))


def test_text_is_sent_to_native_endpoint_and_out_of_order_indexes_are_restored():
    calls=[]
    def handler(request):
        calls.append(request);return httpx.Response(200,json=response(request,reverse=True))
    p=provider(handler);vectors=p.embed_documents(['first','second'])
    assert [v[0] for v in vectors]==[1.,2.]
    request=calls[0];body=json.loads(request.content)
    assert str(request.url).endswith('/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding')
    assert body['input']['contents']==[{'text':'first'},{'text':'second'}]
    assert body['parameters']==dict(dimension=256,enable_fusion=False)
    assert p.last_usage==dict(input_tokens=13,image_tokens=5,total_tokens=18)
    assert p.last_calls[0]['status']=='completed' and 'private-test-token' not in json.dumps(p.last_calls)


def test_twenty_element_batches_preserve_all_text_and_usage():
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json=response(request))
    p=provider(handler);assert len(p.embed_documents([f'text{i}' for i in range(45)]))==45
    assert [len(json.loads(r.content)['input']['contents']) for r in calls]==[20,20,5]
    assert p.last_usage==dict(input_tokens=39,image_tokens=15,total_tokens=54)
    p.embed_query('new query')
    assert len(p.last_calls)==1 and p.last_usage['total_tokens']==18
    assert p.embed_documents([])==[] and p.last_usage is None and p.last_calls==[]


def test_images_and_fusion_send_real_image_bytes_and_keep_separate_mode(tmp_path):
    image=tmp_path/'plot.png';image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'image contents')
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json=response(request))
    p=provider(handler)
    assert len(p.embed_images([image]))==1
    payload=json.loads(calls[-1].content)
    assert payload['input']['contents'][0]['image'].startswith('data:image/png;base64,')
    assert payload['parameters']['enable_fusion'] is False
    assert len(p.embed_fused('Figure caption',image))==256
    payload=json.loads(calls[-1].content)
    assert payload['input']['contents'][0]=={'text':'Figure caption'}
    assert payload['parameters']['enable_fusion'] is True and p.last_calls[0]['fusion']
    assert 'image contents' not in json.dumps(p.last_calls)


@pytest.mark.parametrize('kind',['duplicate_index','bool_index','missing_vector','wrong_dimension','nan','boolean','zero','invalid_json'])
def test_malformed_responses_are_rejected_without_raw_content(kind):
    def handler(request):
        body=response(request)
        rows=body['output']['embeddings']
        if kind=='duplicate_index':rows[1]['index']=0
        if kind=='bool_index':rows[0]['index']=False
        if kind=='missing_vector':del rows[0]['embedding']
        if kind=='wrong_dimension':rows[0]['embedding']=[1.]
        if kind=='nan':rows[0]['embedding'][0]=nan
        if kind=='boolean':rows[0]['embedding'][0]=True
        if kind=='zero':rows[0]['embedding']=[0.]*256
        if kind=='invalid_json':return httpx.Response(200,text='private-test-token invalid response')
        return httpx.Response(200,text=json.dumps(body))
    p=provider(handler)
    with pytest.raises(ProviderResponseError) as error:p.embed_documents(['first','second'])
    assert p.last_calls[0]['status']=='invalid_response'
    assert 'private-test-token' not in str(error.value)


@pytest.mark.parametrize('status',[401,402,429,503])
def test_http_failure_is_counted_with_no_retry_or_error_body_leak(status):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,text='private-test-token provider secret')
    p=provider(handler)
    with pytest.raises(ProviderError) as error:p.embed_query('question')
    assert len(calls)==1 and p.last_calls[0]['http_status']==status
    assert p.last_calls[0]['usage'] is None and 'private-test-token' not in str(error.value)


def test_transport_failure_and_unknown_usage_are_preserved():
    def fail(request):raise httpx.ReadTimeout('private-test-token')
    p=provider(fail)
    with pytest.raises(ProviderError):p.embed_query('question')
    assert p.last_calls[0]['status']=='request_failed' and p.last_usage is None
    def no_usage(request):
        body=response(request);del body['usage'];return httpx.Response(200,json=body)
    p=provider(no_usage);p.embed_query('question')
    assert p.last_usage is None


def test_native_configuration_snapshot_is_explicit_without_changing_other_modes(tmp_path):
    with pytest.raises(ValueError):Settings(_env_file=None,embedding_provider='dashscope',embedding_model='BAAI/bge-m3',embedding_dimensions=1024)
    with pytest.raises(ValueError):Settings(_env_file=None,embedding_provider='dashscope',embedding_model=MODEL,embedding_dimensions=2560,
        embedding_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')
    path=tmp_path/'settings.env'
    path.write_text('RAG_EMBEDDING_PROVIDER=dashscope\nRAG_EMBEDDING_MODEL=qwen3-vl-embedding\n'
        'RAG_EMBEDDING_DIMENSIONS=2560\nRAG_EMBEDDING_API_KEY=private-test-token\n',encoding='utf-8')
    cfg=configuration_snapshot(path)
    assert cfg['embedding_runtime']['api']=='dashscope_native_multimodal'
    assert cfg['embedding_runtime']['qa_input_modality']=='text'
    assert not cfg['embedding_runtime']['image_generation_input_enabled']
    assert 'adapters/providers/dashscope.py' in cfg['pipeline_source_files'] and 'private-test-token' not in json.dumps(cfg)
