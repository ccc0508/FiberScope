from pathlib import Path
from types import SimpleNamespace

from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.retrieve import RetrievalService
from literature_rag.domain.models import Chunk, Document, DocumentStatus, VectorMatch
from literature_rag.stage_trace import StageTrace
from tests.literature_fakes import SpyEmbedder


def test_hybrid_retrieval_keeps_two_top_50_lists_and_sends_rrf_top_50_to_reranker(tmp_path):
    metadata = SqliteMetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    for doc in ("requested", "other"):
        filename = f"{doc}.pdf"
        metadata.upsert_document(Document(doc, filename, Path(filename), doc, 1, DocumentStatus.PENDING))
        chunks = [
            Chunk(f"{doc}-{num:03d}", doc, filename, 1, 1, num,
                  f"<td>孔隙率 NRMSE {num}</td>" if num < 55 else f"Semantic evidence {num}",
                  1, "test")
            for num in range(101)
        ]
        metadata.complete_document(doc, 1, chunks)

    def vector_search(embedding, limit, *, document_ids):
        assert limit == 50 and document_ids == ["requested"]
        return [VectorMatch(f"requested-{num:03d}", .9 if num != 95 else .2) for num in range(46, 96)]

    ranked = []

    def rerank(query, texts):
        assert query == "孔隙率 NRMSE"
        assert len(texts) == 50
        ranked.extend(texts)
        return [.9] * len(texts)

    service = RetrievalService(metadata, SimpleNamespace(search=vector_search), SpyEmbedder(),
                               reranker=SimpleNamespace(rerank=rerank), keyword_corpus=metadata.iter_searchable_text)
    with StageTrace() as trace:
        results = service.retrieve("孔隙率 NRMSE", 3, .35, document_ids=["requested"], max_seeds_per_document=3)

    stages = {record["name"]: record for record in trace.records}
    assert len(stages["retrieval.vector_search"]["output"]["candidates"]) == 50
    keyword_hits = stages["retrieval.bm25_search"]["output"]["candidates"]
    assert len(keyword_hits) == 50 and all(hit["chunk_id"].startswith("requested-") for hit in keyword_hits)
    fusion = stages["retrieval.rrf"]["output"]
    pool = fusion["selected_ids"]
    assert len(pool) == len(set(pool)) == 50
    assert pool == stages["retrieval.rerank"]["input"]["candidate_ids"]
    ranks = {row["chunk_id"]: row["branch_ranks"] for row in fusion["candidates"]}
    assert any(ranks[cid].keys() == {"bm25"} for cid in pool)
    assert any(ranks[cid].keys() == {"vector"} for cid in pool)
    assert ranks[pool[0]].keys() == {"vector", "bm25"}
    assert "requested-095" not in ranks
    assert any("<td>" in text for text in ranked)
    assert len(results) == 3 and all(row.document_id == "requested" for row in results)
