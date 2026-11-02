"""Replay only sealed scientific inputs, never another model's answers or grades."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys


def evidence(row):
    from literature_rag.domain.models import Evidence, EvidenceSource, VisualAsset
    return Evidence(**{**row,
        'source_chunks': tuple(EvidenceSource(**s) for s in row.get('source_chunks', [])),
        'seed_chunk_ids': tuple(row.get('seed_chunk_ids', [])),
        'visual_assets': tuple(VisualAsset(**{**a, 'bbox': tuple(a['bbox'])})
                               for a in row.get('visual_assets', []))})


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    control = json.loads((root.parent/'run.json').read_text(encoding='utf-8'))['answer_replay_control']
    raw = (root/'answer-evidence-cache.json').read_bytes()
    if sha256(raw).hexdigest() != control['cache_sha256']:
        raise ValueError('Scientific input cache changed')
    if sha256(Path(__file__).read_bytes()).hexdigest() != control['wrapper_sha256']:
        raise ValueError('Replay wrapper changed')
    cache = json.loads(raw)
    from literature_rag.application.retrieve import RetrievalService
    def retrieve(self, question, top_k, min_score):
        row = cache['questions'].get(sha256(question.strip().encode()).hexdigest())
        if row is None or row['question'] != question.strip():
            raise ValueError('Question differs from sealed scientific input')
        if row['top_k'] != top_k or row['min_score'] != min_score:
            raise ValueError('Retrieval policy differs')
        if any(k in row for k in ('answer', 'claims', 'scores', 'key_points')):
            raise ValueError('Replay contains non-source data')
        self.last_seed_evidences = [evidence(e) for e in row['seed_evidence']]
        self.last_context_diagnostics = dict(replayed=True, source_result_sha256=row['source_result_sha256'],
            input_sha256=row['input_sha256'], retrieval_api_calls=0)
        self.last_query_diagnostics = dict(status='replayed_final_evidence', api_calls=0)
        self.last_query_embedding_calls = []
        self.last_rerank_diagnostics = dict(status='replayed_final_evidence', api_calls=0)
        result = [evidence(e) for e in row['evidences']]
        if sha256(json.dumps([asdict(e) for e in result], ensure_ascii=False,
                sort_keys=True).encode()).hexdigest() != row['input_sha256']:
            raise ValueError('Restored source input changed')
        return result
    RetrievalService.retrieve = retrieve
    import literature_worker
    literature_worker.main()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
