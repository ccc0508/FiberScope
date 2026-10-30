"""Fixed-context replay uses original evidence, normal validation and no retrieval/embedding."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import answer_guidance_worker as worker
import run_answer_guidance_20261031 as run
from literature_rag.domain.models import Evidence,EvidenceSource,GeneratedAnswer,GeneratedClaim


def fixture(tmp_path):
    e=Evidence('[1]','chunk','doc','paper.pdf',2,2,'An observed source fact.',.7,
        source_chunks=(EvidenceSource('chunk',0,2,2,'An observed source fact.','paragraph'),),seed_chunk_ids=('chunk',))
    raw=json.loads(json.dumps([asdict(e)]))
    d=dict(version='answer-guidance-fixed-evidence-v1',task_id='A',question='Question',evidences=raw,
        documents=[dict(document_id='doc',filename='paper.pdf',file_hash='sealed-pdf')],
        source_result_sha256='original-sealed-result',evidence_sha256=run.canonical_sha(raw))
    path=tmp_path/'fixture.json';path.write_text(json.dumps(d),encoding='utf-8')
    return path,d


def test_replay_passes_exact_source_and_question_without_gold_or_new_search(tmp_path,monkeypatch):
    import literature_rag.config as config
    import literature_rag.diagnostics as diagnostics
    import literature_rag.adapters.providers.deepseek as provider
    path,d=fixture(tmp_path);calls=[]
    settings=NS(llm_provider='deepseek',rerank_enabled=False,llm_model='fixed-model',
        llm_api_key=NS(get_secret_value=lambda:'secret-canary'),llm_base_url='https://test.invalid',
        llm_thinking_enabled=True,llm_reasoning_effort='high',answer_guidance_enabled=True,top_k=8,min_score=.35)
    monkeypatch.setattr(config,'Settings',lambda **kw:settings)
    monkeypatch.setattr(diagnostics,'configuration_snapshot',lambda _:dict(llm_model='fixed-model'))
    class Generator:
        model_name='fixed-model';last_usage={'total_tokens':10};last_model_info={'returned_model':'reported'}
        def __init__(self,*args,**kwargs):calls.append(('init',kwargs))
        def generate(self,q,e,feedback=None):
            calls.append(('generate',q,json.loads(json.dumps([asdict(s) for s in e])),feedback))
            return GeneratedAnswer('An observed source fact. [1]',(GeneratedClaim('An observed source fact.',('[1]',)),))
    monkeypatch.setattr(provider,'DeepSeekGenerator',Generator)
    result=worker.evaluate(dict(backend_dir=str(ROOT/'backend'),fixture_file=str(path),question='Question'))
    assert result['status']=='answered' and len(result['generation_calls'])==1
    assert calls[1]==('generate','Question',d['evidences'],None)
    assert calls[0][1]==dict(thinking_enabled=True,reasoning_effort='high',answer_guidance_enabled=True)
    assert result['embedding_usage'] is None and result['rerank_calls']==[]
    assert result['fixed_evidence_diagnostics']['evidence_sha256']==d['evidence_sha256']
    assert result['fixed_evidence_diagnostics']['generation_input_evidence_sha256']==d['evidence_sha256']
    assert 'secret-canary' not in json.dumps(result)


@pytest.mark.parametrize('change',['extra_gold','evidence','question'])
def test_replay_rejects_unsealed_or_extra_input_before_provider_call(tmp_path,change):
    path,d=fixture(tmp_path)
    if change=='extra_gold':d['reference_answer']='forbidden'
    elif change=='evidence':d['evidences'][0]['text']='Changed scientific text'
    else:d['question']='Different question'
    path.write_text(json.dumps(d),encoding='utf-8')
    with pytest.raises(ValueError):worker.evaluate(dict(backend_dir=str(ROOT/'backend'),fixture_file=str(path),question='Question'))


def test_resume_keeps_completed_failure_without_paid_replay(tmp_path):
    directory=tmp_path/'run';(directory/'results').mkdir(parents=True);(directory/'attempts').mkdir()
    run_path=directory/'run.json';run_path.write_text(json.dumps(dict(tasks=[dict(id='A',case_id='A')])) ,encoding='utf-8')
    (tmp_path/'fixtures').mkdir();(tmp_path/'fixtures/A.json').write_text(json.dumps({'question':'Q'}),encoding='utf-8')
    result=directory/'results/A.json';result.write_text(json.dumps({'status':'failed'}),encoding='utf-8')
    (directory/'attempts/A.json').write_text(json.dumps({'result_sha256':run.judge.digest(result)}),encoding='utf-8')
    original=run.OUTPUT
    try:
        run.OUTPUT=tmp_path
        assert run.one('control','A',{'arms':{'control':{'run_dir':str(directory)}}})=='failed'
    finally:run.OUTPUT=original
