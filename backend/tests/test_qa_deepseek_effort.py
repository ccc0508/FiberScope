"""Verify actual High request parameters and credential-free model provenance offline."""
import json
from types import SimpleNamespace as NS
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
from literature_rag.diagnostics import configuration_snapshot


def generate(**options):
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model='DeepSeek-V4.1-Flash-1017',system_fingerprint='fixture-fingerprint',
                  usage=NS(prompt_tokens=10,completion_tokens=20,total_tokens=30,
                           completion_tokens_details=NS(reasoning_tokens=12)),
                  choices=[NS(message=NS(content=json.dumps({'answer':'Synthetic fact [1]',
                           'claims':[{'text':'Synthetic fact','citation_refs':['[1]']}]}),
                           reasoning_content='HIDDEN_REASONING_MUST_NOT_BE_PERSISTED'))])
    g=DeepSeekGenerator('deepseek-flash','TEST_SECRET',client=NS(chat=NS(completions=NS(create=create))),**options)
    answer=g.generate('synthetic question',[])
    return g,calls,answer


def test_high_is_explicit_on_wire_and_returned_model_is_recorded():
    g,calls,answer=generate(thinking_enabled=True,reasoning_effort='high')
    assert calls[0]['model']=='deepseek-flash'
    assert calls[0]['extra_body']=={'thinking':{'type':'enabled'}}
    assert calls[0]['reasoning_effort']=='high'
    assert calls[0]['response_format']=={'type':'json_object'}
    assert g.last_model_info['returned_model']=='DeepSeek-V4.1-Flash-1017'
    assert g.last_usage['reasoning_tokens']==12
    assert 'HIDDEN_REASONING' not in repr((g.last_usage,g.last_model_info,answer))
    assert 'TEST_SECRET' not in repr((g.last_usage,g.last_model_info))


def test_unconfigured_legacy_requests_keep_provider_defaults():
    g,calls,_=generate()
    assert 'reasoning_effort' not in calls[0] and 'extra_body' not in calls[0]


@pytest.mark.parametrize('options',[{'thinking_enabled':False,'reasoning_effort':'high'},
                                    {'reasoning_effort':'invented'},{'thinking_enabled':'yes'}])
def test_invalid_effort_configuration_is_rejected_before_call(options):
    with pytest.raises(ValueError):generate(**options)


def test_reasoning_settings_are_in_snapshot_but_secrets_are_excluded(tmp_path,monkeypatch):
    for key in ('RAG_LLM_REASONING_EFFORT','RAG_LLM_THINKING_ENABLED'):monkeypatch.delenv(key,raising=False)
    path=tmp_path/'private.env';path.write_text('RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_REASONING_EFFORT=high\nRAG_LLM_THINKING_ENABLED=true\nRAG_LLM_API_KEY=TEST_SECRET\n')
    snapshot=configuration_snapshot(path)
    assert snapshot['llm_reasoning_effort']=='high' and snapshot['llm_thinking_enabled'] is True
    assert 'TEST_SECRET' not in repr(snapshot)
