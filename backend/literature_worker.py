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
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import CitationValidator

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
    generator = generator_type(settings.llm_model, settings.llm_api_key.get_secret_value(), settings.llm_base_url)
    evidence_by_chunk = {}

    class CapturedRetriever(RetrievalService):
        def retrieve(self, *args):
            evidences = super().retrieve(*args)
            evidence_by_chunk.update({e.chunk_id: e for e in evidences})
            return evidences

    answer = AnswerService(CapturedRetriever(metadata, vectors, embedder), generator, CitationValidator()).answer(
        body['question'], settings.top_k, settings.min_score)
    citations = []
    for citation in answer.citations:
        evidence = evidence_by_chunk[citation.chunk_id]
        citations.append({**asdict(citation), 'document_id': evidence.document_id, 'excerpt': evidence.text})
    print(json.dumps({'status': answer.status.value, 'answer': answer.answer, 'citations': citations,
                      'latency_ms': answer.latency_ms}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Intentionally no traceback, question text, key or provider response in HTTP output.
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)
