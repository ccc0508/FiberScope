"""Paid smoke/replay checks on saved drafts; no gold labels, judge or primary generation.

Writes an immutable attempt directory. This is not a complete comparative evaluation.
"""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from qa_answer_replay_worker import evidence


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--results-dir', type=Path, required=True)
    parser.add_argument('--case-ids', nargs='+', required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', choices=['v1','v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact'], default='v1')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Attempt directory already exists; never automatically repeat a paid attempt')
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
    from literature_rag.adapters.providers.rerank import SiliconFlowReranker
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    from literature_rag.application.evidence_review import EvidenceReviewService, checksum
    from literature_rag.application.review_diagnosis import diagnosis_contract
    VERSION=diagnosis_contract(args.version).VERSION
    from literature_rag.application.corrective_review import CorrectiveReviewService, TargetedEvidenceReader
    from literature_rag.application.retrieve import RetrievalService
    from literature_rag.application.context import ContextOptions
    from literature_rag.application.body_context import BodySectionCatalog
    from literature_rag.application.table_evidence import TableRelations, TableVectorSearch
    from literature_rag.application.visual_evidence import VisualCatalog, VisualVectorSearch
    from literature_rag.application.citations import CitationValidator
    from literature_rag.domain.models import Evidence, GeneratedAnswer, GeneratedClaim

    settings = Settings(_env_file=ROOT/'backend/.env.literature',corrective_review_version=args.version)
    if settings.embedding_provider != 'dashscope' or not settings.rerank_enabled:
        raise ValueError('This replay checks the existing Qwen + reranker pipeline')

    class ReadOnlyMetadata(SqliteMetadataStore):
        def _connect(self):
            conn = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            return conn

    metadata = ReadOnlyMetadata(args.library/'metadata.sqlite3')
    catalog = BodySectionCatalog.load(args.library, metadata)
    vectors = ChromaVectorStore(args.library/'chroma', settings.embedding_provider,
        settings.embedding_model, settings.embedding_dimensions)
    if settings.table_retrieval_enabled:
        tables = TableRelations.load(args.library, metadata, settings.embedding_provider,
            settings.embedding_model, settings.embedding_dimensions)
        vectors = TableVectorSearch(vectors, tables)
    visual = None
    if settings.visual_retrieval_enabled:
        visual = VisualCatalog.load(args.library, metadata, settings.embedding_provider,
            settings.embedding_model, settings.embedding_dimensions)
        vectors = VisualVectorSearch(vectors, visual)
    docs = {d.id:d.file_hash for d in metadata.list_documents()}
    inputs = []
    for case_id in args.case_ids:
        if Path(case_id).name != case_id:
            raise ValueError('Use a case ID, not a path')
        path = args.results_dir/(case_id+'.json')
        raw = path.read_bytes(); row = json.loads(raw); response = row['response']
        if response['status'] != 'answered':raise ValueError('Replay needs a validated saved answer')
        if any(docs.get(d['document_id']) != d['file_hash'] for d in response['configuration']['documents']):
            raise ValueError('Library differs from saved source documents')
        inputs.append(dict(case_id=case_id, question=row['question'], source_sha256=sha256(raw).hexdigest(),
            draft=dict(answer=response['answer'], claims=response['claims']), evidences=response['retrieved_evidence'],
            candidate_ids=[c['chunk_id'] for c in response['context_assembly'].get('rerank', {}).get('candidates', [])]))
    args.output.mkdir(parents=True)
    write(args.output/'inputs.json', inputs)
    import os
    prior_version=os.environ.get('RAG_CORRECTIVE_REVIEW_VERSION')
    os.environ['RAG_CORRECTIVE_REVIEW_VERSION']=args.version
    try:configuration = configuration_snapshot(ROOT/'backend/.env.literature')
    finally:
        if prior_version is None:os.environ.pop('RAG_CORRECTIVE_REVIEW_VERSION',None)
        else:os.environ['RAG_CORRECTIVE_REVIEW_VERSION']=prior_version
    write(args.output/'manifest.json', dict(status='started', mode=VERSION,
        initial_drafts_frozen=True, initial_retrieval_calls=0, primary_generation_calls=0, judge_calls=0,
        gold_loaded=False, paid_calls_authorized_by='implementation verification',
        configuration=configuration, input_sha256=checksum(inputs),
        source_files={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'backend/literature_rag').rglob('*.py')}, monetary_cost=None))

    def run(item):
        started = perf_counter()
        es = [evidence(e) for e in item['evidences']]
        draft = GeneratedAnswer(item['draft']['answer'], tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in item['draft']['claims']))
        CitationValidator().validate(draft, es)
        for e in es:
            for source in e.source_chunks:
                if source.chunk_id not in catalog.chunks or catalog.chunks[source.chunk_id].text != source.text:
                    raise ValueError('Saved source text differs from current library')
        embedder = DashScopeEmbedder(settings.embedding_model, settings.embedding_dimensions,
            settings.embedding_api_key.get_secret_value(), settings.embedding_base_url)
        reranker = SiliconFlowReranker(settings.rerank_model, settings.rerank_api_key.get_secret_value(),
            settings.rerank_base_url, settings.rerank_timeout_seconds)
        retriever = RetrievalService(metadata, vectors, embedder,
            ContextOptions(True, settings.context_neighbor_radius, settings.context_max_evidence_chars,
                settings.context_max_total_chars), reranker=reranker, body_context_catalog=catalog,
            visual_catalog=visual, visual_max_images=settings.visual_max_images,
            visual_max_total_bytes=settings.visual_max_total_bytes)
        chunks = {c.id:c for c in metadata.get_chunks(item['candidate_ids'])}
        retriever.last_candidate_evidences = [Evidence('', c.id, c.document_id, c.filename,
            c.page_start, c.page_end, c.text, 0.) for cid in item['candidate_ids'] if (c:=chunks.get(cid))]
        p = DeepSeekEvidenceReviewer(settings.llm_model, settings.llm_api_key.get_secret_value(),
            settings.llm_base_url, thinking_enabled=settings.llm_thinking_enabled,
            reasoning_effort=settings.llm_reasoning_effort, timeout_seconds=settings.evidence_review_timeout_seconds,
            max_output_tokens=settings.evidence_review_max_output_tokens, visual_root=args.library, diagnostic=True,diagnosis_version=args.version)
        deadline = started+295
        service = CorrectiveReviewService(EvidenceReviewService(p, visual_root=args.library, deadline=deadline),
            TargetedEvidenceReader(retriever), deadline=deadline)
        final = service.review(item['question'], es, draft)
        validated = CitationValidator().validate(final, service.last_evidences, allow_sparse_refs=True)
        result = dict(case_id=item['case_id'], question=item['question'], answer=validated.answer,
            claims=[asdict(c) for c in final.claims], citations=[asdict(c) for c in validated.citations],
            review_summary=service.last_summary, evidence_review=service.last_trace)
        write(args.output/(item['case_id']+'.json'), result)
        return dict(case_id=item['case_id'], status=service.last_summary['status'],
            review_calls=service.last_trace['api_calls'], supplement_rounds=service.last_trace['supplement_rounds'])

    summaries = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run, item):item['case_id'] for item in inputs}
        for future in as_completed(futures):
            try:summary = future.result()
            except Exception as error:
                summary = dict(case_id=futures[future], status='harness_failed', error_type=type(error).__name__)
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
    write(args.output/'summary.json', summaries)


if __name__ == '__main__':
    main()
