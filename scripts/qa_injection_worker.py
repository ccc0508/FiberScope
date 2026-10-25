"""Controlled evidence fixture using an unmodified frozen AnswerService and generator."""
import hashlib
import json
import os
from pathlib import Path
import sys
from dataclasses import asdict

os.environ['ANONYMIZED_TELEMETRY']='False'


def fixture_evidence(fixture, variant):
    from literature_rag.domain.models import Evidence
    if variant not in {'clean','attack'}:
        raise ValueError('Unknown controlled-evidence variant')
    text=fixture['clean_text']
    if variant=='attack':
        text+='\n\n'+fixture['injected_text']
    return Evidence(ref='[1]',chunk_id=fixture['source_chunk_id'],document_id=fixture['original_document_id'],
                    filename='Li-2020-PFI-refining-aggregation-structure-cellulose.pdf',page_start=fixture['source_pdf_page'],
                    page_end=fixture['source_pdf_page'],text=text,score=1.0)


def evaluate(body):
    backend=Path(body['backend_dir']).resolve()
    sys.path.insert(0,str(backend))
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import CitationValidator
    from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
    from literature_rag.adapters.providers.openai import OpenAIGenerator
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    from literature_rag.domain.errors import InfrastructureError,ProviderError
    fixture=json.loads(Path(body['fixture_file']).read_text(encoding='utf-8'))
    evidence=fixture_evidence(fixture,body['variant'])
    settings=Settings(_env_file=backend/'.env.literature')
    configuration=configuration_snapshot(backend/'.env.literature')
    configuration['documents']=[{'document_id':fixture['original_document_id'],'filename':evidence.filename,
                                'file_hash':fixture['original_pdf_sha256']}]
    generator_type=DeepSeekGenerator if settings.llm_provider=='deepseek' else OpenAIGenerator
    generator=generator_type(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url)
    calls,generated=[],[]
    diagnostic={'mode':'controlled_retrieved_evidence','variant':body['variant'],'retrieval_bypassed':True,
                'attack_exposed_to_generation':False,'generation_input_evidence_sha256':None,
                'embedding_called':False,'fixture_sha256':hashlib.sha256(Path(body['fixture_file']).read_bytes()).hexdigest()}

    class FixedEvidence:
        def retrieve(self,*args):
            return [evidence]

    class CapturedGenerator:
        model_name=generator.model_name
        def generate(self,question,evidences,feedback=None):
            forwarded='\n'.join(e.text for e in evidences)
            diagnostic['generation_input_evidence_sha256']=hashlib.sha256(forwarded.encode()).hexdigest()
            diagnostic['attack_exposed_to_generation']=fixture['injected_text'] in forwarded
            call={'attempt':len(calls)+1,'outcome':'failed','usage':None}
            calls.append(call)
            try:
                answer=generator.generate(question,evidences,feedback)
                generated.append(answer)
                call['outcome']='generated'
                return answer
            finally:
                call['usage']=getattr(generator,'last_usage',None)
    try:
        answer=AnswerService(FixedEvidence(),CapturedGenerator(),CitationValidator()).answer(body['question'],settings.top_k,settings.min_score)
        citations=[{**asdict(c),'document_id':evidence.document_id,'excerpt':evidence.text} for c in answer.citations]
        return dict(status=answer.status.value,answer=answer.answer,citations=citations,
                    claims=[asdict(c) for c in generated[-1].claims] if answer.status.value=='answered' else [],
                    reason_code=answer.reason_code,latency_ms=answer.latency_ms,configuration=configuration,
                    generation_calls=calls,embedding_usage=None,retrieved_evidence=[asdict(evidence)],fixture_diagnostics=diagnostic)
    except (InfrastructureError,ProviderError):
        return dict(status='failed',answer='',citations=[],claims=[],reason_code='fixture_provider_error',
                    configuration=configuration,generation_calls=calls,embedding_usage=None,
                    retrieved_evidence=[asdict(evidence)],fixture_diagnostics=diagnostic)


if __name__=='__main__':
    try:
        print(json.dumps(evaluate(json.loads(sys.stdin.read())),ensure_ascii=False))
    except Exception as error:
        print(type(error).__name__,file=sys.stderr)
        sys.exit(1)
