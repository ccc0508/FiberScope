"""Generate once from a sealed context fixture using the unchanged historical pipeline."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

os.environ['ANONYMIZED_TELEMETRY']='False'


def canonical(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def evaluate(body):
    backend=Path(body['backend_dir']).resolve();sys.path.insert(0,str(backend))
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    from literature_rag.domain.models import Evidence,EvidenceSource
    from literature_rag.domain.errors import InfrastructureError,ProviderError
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import CitationValidator
    from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
    fixture=json.loads(Path(body['fixture_file']).read_text('utf-8'))
    if fixture['version']!='context-expansion-fixed-seeds-v1' or fixture['question']!=body['question']:
        raise ValueError('Unexpected fixed-seed fixture')
    for key in ('seeds','evidences'):
        if canonical(fixture[key])!=fixture[key+'_sha256']:
            raise ValueError('Fixture evidence changed')
    evidences=[]
    for raw in fixture['evidences']:
        d=dict(raw);d['source_chunks']=tuple(EvidenceSource(**s) for s in d['source_chunks'])
        d['seed_chunk_ids']=tuple(d['seed_chunk_ids']);evidences.append(Evidence(**d))
    if canonical([asdict(e) for e in evidences])!=fixture['evidences_sha256']:
        raise ValueError('Generation evidence reconstruction differs')
    settings=Settings(_env_file=backend/'.env.literature')
    if settings.llm_provider!='deepseek' or getattr(settings,'rerank_enabled',False) or getattr(settings,'answer_guidance_enabled',False):
        raise ValueError('Unexpected extra generation feature')
    generator=DeepSeekGenerator(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
        thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort)
    config=configuration_snapshot(backend/'.env.literature');config['documents']=fixture['documents']
    calls=[];generated=[]
    class FixedRetriever:
        def retrieve(self,question,*args):
            if question!=fixture['question']:raise ValueError('No question rewriting')
            return evidences
    class CapturedGenerator:
        model_name=generator.model_name
        def generate(self,*args):
            call=dict(attempt=len(calls)+1,outcome='failed',usage=None,model_info=None);calls.append(call)
            try:
                answer=generator.generate(*args);generated.append(answer);call['outcome']='generated';return answer
            finally:
                call.update(usage=getattr(generator,'last_usage',None),model_info=getattr(generator,'last_model_info',None))
    shared=dict(configuration=config,generation_calls=calls,embedding_usage=None,rerank_calls=[],
        retrieval_seed_evidence=fixture['seeds'],retrieved_evidence=fixture['evidences'],context_assembly=fixture['assembly'],
        fixed_seed_diagnostics=dict(version=fixture['version'],strategy=fixture['strategy'],retrieval_bypassed=True,
            embedding_calls=0,rerank_calls=0,seeds_sha256=fixture['seeds_sha256'],
            generation_input_evidence_sha256=canonical([asdict(e) for e in evidences]),
            fixture_sha256=sha256(Path(body['fixture_file']).read_bytes()).hexdigest()))
    try:
        answer=AnswerService(FixedRetriever(),CapturedGenerator(),CitationValidator()).answer(body['question'],settings.top_k,settings.min_score)
    except (InfrastructureError,ProviderError):
        return dict(**shared,status='failed',answer='',claims=[],citations=[],reason_code='context_replay_provider_error',latency_ms=0)
    by_id={e.chunk_id:e for e in evidences}
    return dict(**shared,status=answer.status.value,answer=answer.answer,
        claims=[asdict(c) for c in generated[-1].claims] if answer.status.value=='answered' else [],
        citations=[{**asdict(c),'document_id':by_id[c.chunk_id].document_id,'excerpt':by_id[c.chunk_id].text} for c in answer.citations],
        reason_code=answer.reason_code,latency_ms=answer.latency_ms)


if __name__=='__main__':
    try:print(json.dumps(evaluate(json.loads(sys.stdin.read())),ensure_ascii=False))
    except Exception as error:
        print(type(error).__name__,file=sys.stderr);sys.exit(1)
