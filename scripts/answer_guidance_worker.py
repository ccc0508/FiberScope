"""Replay fixed, sealed evidence through the normal generator and citation validator."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

os.environ['ANONYMIZED_TELEMETRY']='False'


def evaluate(body):
    backend=Path(body['backend_dir']).resolve();sys.path.insert(0,str(backend))
    from literature_rag.config import Settings
    from literature_rag.domain.models import Evidence,EvidenceSource
    from literature_rag.domain.errors import InfrastructureError,ProviderError
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import CitationValidator
    from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
    from literature_rag.diagnostics import configuration_snapshot
    fixture=json.loads(Path(body['fixture_file']).read_text('utf-8'))
    if set(fixture)!={'version','task_id','question','evidences','documents','source_result_sha256','evidence_sha256'}:
        raise ValueError('Unexpected evidence fixture fields')
    if fixture['version']!='answer-guidance-fixed-evidence-v1' or fixture['question']!=body['question']:
        raise ValueError('Fixed source question mismatch')
    canonical=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if sha256(canonical(fixture['evidences'])).hexdigest()!=fixture['evidence_sha256']:
        raise ValueError('Fixed evidence fingerprint mismatch')
    evidences=[]
    for raw in fixture['evidences']:
        e=dict(raw);e['source_chunks']=tuple(EvidenceSource(**s) for s in raw.get('source_chunks',[]))
        e['seed_chunk_ids']=tuple(raw.get('seed_chunk_ids',[]));evidences.append(Evidence(**e))
    if [asdict(e) for e in evidences]!=fixture['evidences']:
        # Dataclass tuples are JSON arrays; compare their canonical wire projection.
        if canonical([asdict(e) for e in evidences])!=canonical(fixture['evidences']):raise ValueError('Evidence reconstruction changed')
    settings=Settings(_env_file=backend/'.env.literature')
    if settings.llm_provider!='deepseek' or settings.rerank_enabled:raise ValueError('Controlled experiment requires original DeepSeek and no rerank')
    generator=DeepSeekGenerator(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
        thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
        answer_guidance_enabled=settings.answer_guidance_enabled)
    configuration=configuration_snapshot(backend/'.env.literature');configuration['documents']=fixture['documents']
    calls=[];generated=[]
    diagnostic=dict(mode='fixed_retrieved_evidence',retrieval_bypassed=True,embedding_calls=0,rerank_calls=0,
        source_result_sha256=fixture['source_result_sha256'],evidence_sha256=fixture['evidence_sha256'],
        generation_input_evidence_sha256=sha256(canonical([asdict(e) for e in evidences])).hexdigest(),
        fixture_sha256=sha256(Path(body['fixture_file']).read_bytes()).hexdigest())
    class FixedRetriever:
        def retrieve(self,question,*args):
            if question!=fixture['question']:raise ValueError('Question rewrite is not allowed')
            return evidences
    class CapturedGenerator:
        model_name=generator.model_name
        def generate(self,*args):
            call=dict(attempt=len(calls)+1,outcome='failed',usage=None,model_info=None);calls.append(call)
            try:
                answer=generator.generate(*args);generated.append(answer);call['outcome']='generated';return answer
            finally:
                call.update(usage=getattr(generator,'last_usage',None),model_info=getattr(generator,'last_model_info',None))
    shared=dict(configuration=configuration,generation_calls=calls,embedding_usage=None,rerank_calls=[],
        retrieved_evidence=[asdict(e) for e in evidences],retrieval_seed_evidence=[],
        context_assembly=dict(enabled=False,context_chars=sum(len(e.text) for e in evidences),budget_limited=False,
            mode='fixed_evidence_replay_no_new_assembly'),fixed_evidence_diagnostics=diagnostic)
    try:
        answer=AnswerService(FixedRetriever(),CapturedGenerator(),CitationValidator()).answer(body['question'],settings.top_k,settings.min_score)
    except (InfrastructureError,ProviderError):
        return dict(**shared,status='failed',answer='',claims=[],citations=[],reason_code='fixed_evidence_provider_error',latency_ms=0)
    by_id={e.chunk_id:e for e in evidences}
    return dict(**shared,status=answer.status.value,answer=answer.answer,
        claims=[asdict(c) for c in generated[-1].claims] if answer.status.value=='answered' else [],
        citations=[{**asdict(c),'document_id':by_id[c.chunk_id].document_id,'excerpt':by_id[c.chunk_id].text} for c in answer.citations],
        reason_code=answer.reason_code,latency_ms=answer.latency_ms)


if __name__=='__main__':
    try:print(json.dumps(evaluate(json.loads(sys.stdin.read())),ensure_ascii=False))
    except Exception as error:
        print(type(error).__name__,file=sys.stderr);sys.exit(1)
