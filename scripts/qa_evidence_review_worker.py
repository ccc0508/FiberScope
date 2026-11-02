"""One isolated review of a sealed draft; no retrieval, gold labels or previous grades."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys


def main():
    backend=Path(__file__).resolve().parent;sys.path.insert(0,str(backend))
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
    from literature_rag.application.citations import CitationValidator
    from literature_rag.application.evidence_review import EvidenceReviewService
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    from qa_answer_replay_worker import evidence
    body=json.loads(sys.stdin.read());run=json.loads((backend.parent/'run.json').read_text(encoding='utf-8'))
    control=run['evidence_review_control'];raw=(backend/'evidence-review-cache.json').read_bytes()
    if sha256(raw).hexdigest()!=control['cache_sha256'] or sha256(Path(__file__).read_bytes()).hexdigest()!=control['worker_sha256']:
        raise ValueError('Sealed review input changed')
    row=json.loads(raw)['questions'][sha256(body['question'].strip().encode()).hexdigest()]
    if row['question']!=body['question'].strip():raise ValueError('Question changed')
    es=[evidence(e) for e in row['evidences']]
    draft=GeneratedAnswer(row['draft']['answer'],tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in row['draft']['claims']))
    validator=CitationValidator();original=validator.validate(draft,es)
    if original.answer!=row['draft']['answer']:raise ValueError('Original displayed draft changed')
    s=Settings(_env_file=backend/'.env.literature')
    if not s.evidence_review_enabled:raise ValueError('Review is disabled')
    root=Path(body['data_dir']).resolve()
    p=DeepSeekEvidenceReviewer(s.llm_model,s.llm_api_key.get_secret_value(),s.llm_base_url,
        thinking_enabled=s.llm_thinking_enabled,reasoning_effort=s.llm_reasoning_effort,
        timeout_seconds=s.evidence_review_timeout_seconds,visual_root=root if s.visual_retrieval_enabled else None)
    reviewer=EvidenceReviewService(p,visual_root=root if s.visual_retrieval_enabled else None)
    final=reviewer.review(body['question'],es,draft);validated=validator.validate(final,es)
    by_ref={e.ref:e for e in es};citations=[]
    for c in validated.citations:
        source=by_ref[c.ref];citations.append({**asdict(c),'document_id':source.document_id,'excerpt':source.text})
    config=configuration_snapshot(backend/'.env.literature');config['documents']=row['documents']
    if (root/'structure.json').is_file():config['library_structure_sha256']=sha256((root/'structure.json').read_bytes()).hexdigest()
    result=dict(status='answered',answer=validated.answer,claims=[asdict(c) for c in final.claims],citations=citations,
        reason_code=None,latency_ms=reviewer.last_trace.get('latency_ms'),configuration=config,
        retrieved_evidence=row['evidences'],retrieval_seed_evidence=row['seed_evidence'],
        context_assembly=dict(replayed=True,retrieval_api_calls=0,source_result_sha256=row['source_result_sha256']),
        embedding_usage=None,query_embedding_calls=[],query_rewrite_calls=[],rerank_calls=[],generation_calls=[],
        citation_validation=dict(version='citation-validation-trace-v1',scope='structural_validation_only',attempts=[]),
        evidence_review=reviewer.last_trace,draft_replay=dict(source_run_id=control['source_run_id'],
            source_result_sha256=row['source_result_sha256'],source_answer_sha256=row['source_answer_sha256'],
            new_primary_generation_calls=0,original_citation_validation=row['original_citation_validation']))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
