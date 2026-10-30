"""Opt-in prompt changes preserve control requests, scientific sources and output schemas."""
import json
from types import SimpleNamespace as NS

import pytest

from literature_rag.application.prompts import SYSTEM_PROMPT,ANSWER_GUIDANCE,evidence_prompt,system_prompt
from literature_rag.adapters.providers.deepseek import DeepSeekGenerator,_JSON_OUTPUT_INSTRUCTION
from literature_rag.adapters.providers.openai import OpenAIGenerator
from literature_rag.config import Settings
from literature_rag.domain.models import Evidence
from literature_rag.diagnostics import configuration_snapshot


def source():
    return Evidence('[1]','c','d','paper.pdf',2,2,'Unmodified original data and conditions.',.8)


def test_control_text_is_identical_and_evidence_rendering_does_not_change():
    assert system_prompt(False)==SYSTEM_PROMPT and system_prompt(True)==SYSTEM_PROMPT+'\n\n'+ANSWER_GUIDANCE
    e=source()
    assert evidence_prompt('Question',[e])=='Question:\nQuestion\n\nEvidence:\n[1] file=paper.pdf pages=2-2 chunk=c\nUnmodified original data and conditions.'
    with pytest.raises(ValueError):system_prompt('true')
    assert Settings(_env_file=None).answer_guidance_enabled is False


def test_deepseek_ab_changes_only_system_instruction_and_makes_one_call():
    calls=[]
    payload=dict(answer='Source fact [1]',claims=[dict(text='Source fact',citation_refs=['[1]'])])
    def create(**kwargs):
        calls.append(kwargs)
        return NS(choices=[NS(message=NS(content=json.dumps(payload)))],usage=None,model='same')
    client=NS(chat=NS(completions=NS(create=create)))
    answers=[]
    for flag in [False,True]:
        g=DeepSeekGenerator('same-model','unused',client=client,thinking_enabled=True,reasoning_effort='high',answer_guidance_enabled=flag)
        answers.append(g.generate('Question',[source()]))
    assert len(calls)==2 and answers[0]==answers[1]
    old,new=calls
    assert old['messages'][0]['content']==SYSTEM_PROMPT+'\n\n'+_JSON_OUTPUT_INSTRUCTION
    assert new['messages'][0]['content']==system_prompt(True)+'\n\n'+_JSON_OUTPUT_INSTRUCTION
    assert old['messages'][1:]==new['messages'][1:]
    assert {k:v for k,v in old.items() if k!='messages'}=={k:v for k,v in new.items() if k!='messages'}


def test_openai_ab_preserves_schema_store_policy_and_source_payload():
    calls=[]
    def parse(**kwargs):
        calls.append(kwargs)
        return NS(output_parsed=dict(answer='Source fact [1]',claims=[dict(text='Source fact',citation_refs=['[1]'])]),usage=None)
    for flag in [False,True]:
        g=OpenAIGenerator('same','unused',client=NS(responses=NS(parse=parse)),answer_guidance_enabled=flag)
        g.generate('Question',[source()])
    assert len(calls)==2 and calls[0]['input'][1:]==calls[1]['input'][1:]
    assert calls[0]['text_format'] is calls[1]['text_format']
    assert calls[0]['store'] is calls[1]['store'] is False


def test_guidance_is_identified_without_exposing_private_configuration(tmp_path):
    p=tmp_path/'test.env';p.write_text('RAG_ANSWER_GUIDANCE_ENABLED=true\nRAG_LLM_API_KEY=secret-canary\n',encoding='utf-8')
    c=configuration_snapshot(p)
    assert c['answer_guidance']['enabled'] and c['answer_guidance']['version']=='answer-completeness-v1'
    assert 'secret-canary' not in json.dumps(c)
