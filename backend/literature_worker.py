"""One bounded inference process; no database credentials or raw provider errors in output."""
import json
import os
import sys
from pathlib import Path

# Executed with -I; import only the checked-in core, never the old project.
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['ANONYMIZED_TELEMETRY'] = 'False'


def main():
    import sqlite3
    from dataclasses import asdict
    from literature_rag.config import Settings
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.providers.openai import OpenAIEmbedder, OpenAIGenerator
    from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
    from literature_rag.application.retrieve import RetrievalService
    from literature_rag.application.context import ContextOptions
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import CitationValidator
    from literature_rag.diagnostics import configuration_snapshot
    from literature_rag.domain.errors import ProviderError, InfrastructureError

    body = json.loads(sys.stdin.read())
    root = Path(body['data_dir']).resolve()
    if not (root / 'chroma/chroma.sqlite3').is_file():
        raise FileNotFoundError('missing vector index')
    settings = Settings(_env_file=Path(__file__).resolve().parent / '.env.literature')
    if settings.embedding_provider != 'openai' or settings.llm_provider not in ('openai', 'deepseek'):
        raise ValueError('unsupported provider')
    if not all((settings.embedding_api_key, settings.embedding_model, settings.embedding_dimensions, settings.llm_api_key, settings.llm_model)):
        raise ValueError('missing configuration')

    class ReadOnlyMetadata(SqliteMetadataStore):
        def _connect(self):
            conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            return conn

    metadata = ReadOnlyMetadata(root / 'metadata.sqlite3')
    embedder = OpenAIEmbedder(settings.embedding_model, settings.embedding_dimensions,
                             settings.embedding_api_key.get_secret_value(), settings.embedding_base_url)
    vectors = ChromaVectorStore(root / 'chroma', settings.embedding_provider,
                                settings.embedding_model, settings.embedding_dimensions)
    generator_type = DeepSeekGenerator if settings.llm_provider == 'deepseek' else OpenAIGenerator
    generation_options = ({'thinking_enabled': settings.llm_thinking_enabled,
                           'reasoning_effort': settings.llm_reasoning_effort}
                          if settings.llm_provider == 'deepseek' else {})
    generator = generator_type(settings.llm_model, settings.llm_api_key.get_secret_value(), settings.llm_base_url,
                               **generation_options)
    evidence_by_chunk = {}
    generation_calls = []
    generated_answers = []
    configuration = configuration_snapshot(Path(__file__).resolve().parent / '.env.literature')
    configuration['documents'] = [
        {'document_id': doc.id, 'filename': doc.filename, 'file_hash': doc.file_hash}
        for doc in metadata.list_documents() if doc.status.value == 'completed'
    ]
    if (root/'structure.json').is_file():
        from hashlib import sha256
        configuration['library_structure_sha256']=sha256((root/'structure.json').read_bytes()).hexdigest()
    seed_evidence=[]
    context_diagnostics={}

    class CapturedGenerator:
        model_name = generator.model_name

        def generate(self, *args):
            call = {'attempt': len(generation_calls) + 1, 'usage': None, 'outcome': 'failed'}
            generation_calls.append(call)
            try:
                result = generator.generate(*args)
                generated_answers.append(result)
                call['outcome'] = 'generated'
                return result
            finally:
                call['usage'] = getattr(generator, 'last_usage', None)
                call['model_info'] = getattr(generator, 'last_model_info', None)

    class CapturedRetriever(RetrievalService):
        def retrieve(self, *args):
            evidences = super().retrieve(*args)
            seed_evidence.extend(asdict(e) for e in self.last_seed_evidences)
            context_diagnostics.update(self.last_context_diagnostics)
            evidence_by_chunk.update({e.chunk_id: e for e in evidences})
            return evidences

    try:
        context_options=ContextOptions(settings.context_expansion_enabled,settings.context_neighbor_radius,
                                      settings.context_max_evidence_chars,settings.context_max_total_chars)
        answer = AnswerService(CapturedRetriever(metadata, vectors, embedder,context_options), CapturedGenerator(), CitationValidator()).answer(
            body['question'], settings.top_k, settings.min_score)
    except (ProviderError, InfrastructureError) as error:
        print(json.dumps({'status': 'failed', 'answer': '', 'citations': [],
                          'reason_code': 'provider_error' if isinstance(error, ProviderError) else 'retrieval_error',
                          'error_status': 503, 'configuration': configuration,
                          'retrieved_evidence': [asdict(e) for e in evidence_by_chunk.values()],
                          'retrieval_seed_evidence': seed_evidence, 'context_assembly': context_diagnostics,
                          'embedding_usage': getattr(embedder, 'last_usage', None),
                          'generation_calls': generation_calls, 'claims': [], 'latency_ms': 0}, ensure_ascii=False))
        return
    citations = []
    for citation in answer.citations:
        evidence = evidence_by_chunk[citation.chunk_id]
        citations.append({**asdict(citation), 'document_id': evidence.document_id, 'excerpt': evidence.text})
    print(json.dumps({'status': answer.status.value, 'answer': answer.answer, 'citations': citations,
                      'latency_ms': answer.latency_ms, 'reason_code': answer.reason_code,
                      'configuration': configuration, 'generation_calls': generation_calls,
                      'embedding_usage': getattr(embedder, 'last_usage', None),
                      'claims': [asdict(claim) for claim in generated_answers[-1].claims] if answer.status.value == 'answered' else [],
                      'retrieval_seed_evidence': seed_evidence, 'context_assembly': context_diagnostics,
                      'retrieved_evidence': [asdict(e) for e in evidence_by_chunk.values()]}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Intentionally no traceback, question text, key or provider response in HTTP output.
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)
