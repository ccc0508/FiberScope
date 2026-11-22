from decimal import Decimal

import pytest
from diagnostic_metrics import (
    digest,
    mixed_case,
    mixed_packet,
    projected,
    retrieval,
    same_rows,
    sql_case,
)


def test_unified_packet_uses_only_tool_results_present_in_final_input():
    def event(provider_id):
        return {
            "provider_call_id": provider_id,
            "request": {"tool": "query_experiment_data"},
            "status": "completed",
            "result": {"status": "completed", "call_id": provider_id, "result": {"rows": [[61]]}},
            "model_delivery": {"status": "delivered", "messages": []},
        }

    state = {
        "pipeline_version": "unified-research-v1", "run_id": "r", "answer": "done",
        "tool_calls": [event("in"), event("out")],
        "model_calls": [{"status": "completed", "stage": "review", "text": "done",
                         "input_messages": [{"role": "tool", "tool_call_id": "in"}]}],
    }
    packet = mixed_packet({"id": "MIX01"}, state, ["required count"])
    assert [x["call_id"] for x in packet["calls"]] == ["in", "out"]
    assert [x["call_id"] for x in packet["evidence"].values()] == ["in"]


def search(call_id, candidates, seeds):
    return {
        "call_id": call_id,
        "status": "completed",
        "input": {"tool": "search_literature"},
        "internal_steps": [
            {
                "name": "retrieval.vector_search",
                "status": "completed",
                "input": {"limit": 50},
                "output": {"candidates": [{"chunk_id": i} for i in candidates]},
            },
            {"name": "retrieval.rerank", "status": "completed"},
            {
                "name": "retrieval.select_seeds",
                "status": "completed",
                "input": {"top_k": 2},
                "output": {"selected_ids": seeds},
            },
        ],
    }


def test_retrieval_uses_paired_stages_and_deduplicates_per_question():
    state = {
        "tool_trace": [
            search("a", ["x", "u", "y"], ["x", "y"]),
            search("b", ["x", "v"], ["x", "v"]),
        ],
        "evidence": [{"chunk_id": "z"}],
    }
    score = retrieval(state, {"x", "y", "z"})
    assert score["vector"]["precision"]["percent"] == 50
    assert score["vector_at_seed_limit"]["recall"]["percent"] == 33.33
    assert score["reranked"]["recall"]["percent"] == 66.67
    assert score["reranked"]["missed"] == ["z"]


def test_missing_empty_and_absent_search_are_distinct():
    assert retrieval({"tool_trace": []}, {"r"})["status"] == "no_successful_search"
    trace = search("a", [], [])
    scored = retrieval({"tool_trace": [trace]}, {"r"})
    assert scored["vector"]["precision"]["percent"] is None
    assert scored["vector"]["recall"]["percent"] == 0
    trace["internal_steps"].pop()
    assert (
        retrieval({"tool_trace": [trace]}, {"r"})["status"] == "missing_paired_stages"
    )


def test_result_set_preserves_order_multiplicity_null_and_precision():
    tol = Decimal("0.01")
    assert same_rows([[2], [1]], [[1], [2]], False, tol)
    assert not same_rows([[2], [1]], [[1], [2]], True, tol)
    assert not same_rows([[1], [2]], [[1], [1]], False, tol)
    assert not same_rows([[0]], [[None]], False, tol)
    assert not same_rows([], [[None]], False, tol)
    assert same_rows([[2.49]], [["2.4935"]], False, tol)
    assert not same_rows([["01"]], [["1"]], False, tol)


def test_split_query_requires_matching_source():
    results = {
        "q1": {"columns": ["k", "v"], "rows": [[1, 5]]},
        "q2": {"columns": ["id", "w"], "rows": [[2, 4]]},
    }
    parts = [
        {"sql": "q1", "join_key": "k", "columns": ["v"]},
        {"sql": "q2", "join_key": "id", "columns": ["w"]},
    ]
    assert projected(results, parts) is None
    results["q2"]["rows"][0][0] = 1
    assert projected(results, parts) == [[5, 4]]


def test_unknown_query_requires_run_bound_judgment():
    case = {"id": "SQL01", "reference_sql": ["ref"]}
    refs = [{"sql": "ref", "rows": []}]
    event = {
        "request": {"tool": "query_experiment_data", "sql": "other"},
        "status": "completed",
        "result": {"result": {"columns": ["id"], "rows": []}},
    }
    state = {"tool_calls": [event]}
    assert sql_case(case, state, refs, None)["status"] == "review_required"
    verdict = {
        "correct": False,
        "reason": "筛选了错误的样本",
        "fingerprint": digest([[event], refs]),
    }
    assert sql_case(case, state, refs, None, verdict)["correct"] is False
    event["request"]["sql"] = "updated"
    with pytest.raises(ValueError):
        sql_case(case, state, refs, None, verdict)


def test_mixed_tools_and_evidence_are_independent_and_trace_bound():
    packet = {
        "calls": [{}],
        "needs": ["取数", "文献"],
        "evidence": {"e1": {"status": "completed"}, "e2": {"status": "failed"}},
        "run_id": "r",
    }
    review = {
        "calls": [{"correct": True, "reason": "正确的补查"}],
        "needs": [
            {"sources": ["e1"], "reason": "已取得 SQL 结果"},
            {"sources": [], "reason": "未取得所需论文"},
        ],
        "fingerprint": digest(packet),
    }
    scores = mixed_case(packet, review)
    assert scores["tools"]["percent"] == 100
    assert scores["evidence"]["percent"] == 50
    for source in ("e2", "e3"):
        review["needs"][1]["sources"] = [source]
        with pytest.raises(ValueError):
            mixed_case(packet, review)
    review["fingerprint"] = "old"
    with pytest.raises(ValueError):
        mixed_case(packet, review)
