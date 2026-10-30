"""Replay frozen retrieval with supplied vectors. No gold, credentials or generation."""
from dataclasses import asdict
import json
from pathlib import Path
import sys


def run(payload):
    sys.path.insert(0,payload['backend'])
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.application.context import ContextOptions
    from literature_rag.application.retrieve import RetrievalService
    config=payload['configuration'];root=Path(payload['library'])
    metadata=SqliteMetadataStore(root/'metadata.sqlite3')
    vector_store=ChromaVectorStore(root/'chroma',config['embedding_provider'],config['embedding_model'],config['embedding_dimensions'])

    class Trace:
        matches=[]
        def search(self,query,limit):
            self.matches=vector_store.search(query,limit)
            return self.matches

    class Fixed:
        def embed_query(self,text):
            if text!=self.question.strip():
                raise ValueError('Replay question mismatch')
            return self.vector

    trace=Trace();fixed=Fixed();options=config['context_expansion']
    service=RetrievalService(metadata,trace,fixed,ContextOptions(
        options['context_expansion_enabled'],options['context_neighbor_radius'],
        options['context_max_evidence_chars'],options['context_max_total_chars']))
    results=[]
    for query in payload['queries']:
        fixed.question=query['question'];fixed.vector=query['vector']
        final=service.retrieve(query['question'],config['top_k'],config['min_score'])
        by_id={c.id:c for c in metadata.get_chunks([m.chunk_id for m in trace.matches])}
        candidates=[]
        for rank,match in enumerate(trace.matches,1):
            c=by_id.get(match.chunk_id)
            candidates.append(dict(rank=rank,chunk_id=match.chunk_id,score=match.score,
                passes_threshold=match.score>=config['min_score'],metadata_present=c is not None,
                page_start=c.page_start if c else None,page_end=c.page_end if c else None,
                kind=c.kind if c else None,text=c.text if c else None))
        results.append(dict(task_id=query['task_id'],question=query['question'],candidates=candidates,
            seeds=[asdict(e) for e in service.last_seed_evidences],final=[asdict(e) for e in final],
            context=service.last_context_diagnostics))
    return dict(records=results,generation_calls=0,judge_calls=0,embedding_provider_calls=0)


if __name__=='__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as error:
        print('Retrieval replay failed: '+type(error).__name__,file=sys.stderr)
        sys.exit(1)
