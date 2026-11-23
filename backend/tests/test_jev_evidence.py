import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.adapters.providers.jev_evidence import ANSWER_CHECKS, JevEvidenceJudge, MODEL
from literature_rag.application.agent_loop import AgentLoop
from tests.test_agent_loop import Fake, decision


def test_jev_uses_typed_choices_without_a_draft():
    payload = {"question": "Count groups.", "requirements": [{"requirement_id": "need_1"}],
               "evidence": [{"ref": "[1]", "rows": [[47]]}]}

    def post(url, *, json, **kwargs):
        assert url.endswith("/alpha/decisions")
        assert json["state"] == payload
        assert json["questions"]["need_1"]["type"] == "choice"
        assert json["provider"] == {"allow_fallbacks": False}
        answer = {"choice": "supported", "confidence": .92, "probabilities": {
            "supported": .89, "partially_supported": .09, "insufficient": .02,
        }}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"model": MODEL, "provider": "TypeSafe", "answers": {"need_1": answer},
                          "usage": {"input_tokens": 100, "total_tokens": 100}},
        )

    scores, usage = JevEvidenceJudge("test", post=post).check(payload, 10)
    assert scores["need_1"]["supported"] == .89
    assert usage == {"prompt_tokens": 100, "total_tokens": 100}


def test_final_answer_check_uses_separate_typed_decisions():
    payload = {"question": "Compare two papers.", "answer": "Both randomized.",
               "evidence": [{"ref": "[1]", "text": "A randomized; B reports only the split."}]}

    def post(url, *, json, **kwargs):
        assert json["state"] == payload
        assert set(json["questions"]) == set(ANSWER_CHECKS)
        answers = {}
        for key, question in json["questions"].items():
            assert question["type"] == "choice"
            assert set(question["criteria"]) == {"supported", "incorrect", "inconclusive"}
            answers[key] = {"probabilities": {"supported": 0, "incorrect": .95, "inconclusive": .05}}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"model": MODEL, "provider": "TypeSafe", "answers": answers},
        )

    scores, _ = JevEvidenceJudge("test", post=post).check_answer(payload, 10)
    assert scores["source_attribution"]["incorrect"] == .95


@pytest.mark.parametrize("outcome", ["passed", "inconclusive", "revised", "repair_failed"])
def test_jev_checks_final_synthesis_after_evidence_and_never_reopens_tools(outcome):
    question = "Report the split in each paper."
    original = "Both splits were random [1][2]."
    fixed = "A randomized [1]. B reports a split, without specifying randomization [2]."
    initial_lookup = ToolCall("initial", "search_literature", {
        "query": "training and test split", "reason": "locate the split",
        "requirements": [{"role": "literature", "source_quote": "split in each paper"}],
    })
    decisions = [decision(calls=[initial_lookup]), decision(json.dumps({"answer": original, "coverage": []}))]
    if outcome == "revised":
        decisions.append(decision(fixed))
    elif outcome == "repair_failed":
        decisions.append(decision(calls=[ToolCall("late", "search_literature", {"query": "details"})]))
    adapter = Fake(decisions)
    order = []

    def execute(request, *_):
        order.append(request["tool"])
        return {"status": "completed", "result": {"evidence": [
            {"ref": "[1]", "document_id": "a", "text": "Randomly divided 70/30."},
            {"ref": "[2]", "document_id": "b", "text": "Selected 17 for training and 4 for testing."},
        ]}}

    def check(payload, _timeout):
        order.append("evidence_check")
        assert "answer" not in payload
        return {"need_1": {"supported": .99, "partially_supported": .01, "insufficient": 0}}, {}

    def check_answer(payload, _timeout):
        order.append("answer_check")
        assert payload["answer"] == original
        assert {item["ref"] for item in payload["evidence"]} == {"[1]", "[2]"}
        key = {"passed": "supported", "inconclusive": "inconclusive"}.get(outcome, "incorrect")
        return {"source_attribution": {label: float(label == key)
                for label in ("supported", "incorrect", "inconclusive")}}, {}

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=check, check_answer=check_answer),
    ).run(question, "final-check")
    assert order == ["search_literature", "evidence_check", "answer_check"]
    assert state["answer_check"]["status"] == outcome
    assert state["answer"] == (fixed if outcome == "revised" else original)
    assert state["draft"] == original and state["tool_attempts"] == 1
    assert state["status"] == "completed" and state["citation_validation"]["status"] == "passed"
    stages = ["decide", "decide", "evidence_check", "answer_check"]
    if outcome in ("revised", "repair_failed"):
        stages.append("answer_repair")
        assert adapter.requests[-1][1] == {}
        assert "source_attribution" in adapter.requests[-1][0][-1]["content"]
    assert [call["stage"] for call in state["model_calls"]] == stages


@pytest.mark.parametrize("initial_support, supplements", [(.89, True), (.90, False)])
def test_supplement_targets_only_items_below_threshold(initial_support, supplements):
    question = "Report the local count and the paper result."
    requirements = [
        {"role": "sql", "source_quote": "local count"},
        {"role": "literature", "source_quote": "paper result"},
    ]
    sql = ToolCall("sql", "query_experiment_data", {
        "sql": "SELECT COUNT(*) FROM fiber.v_sample_overview", "reason": "count",
        "requirements": requirements,
    })
    lookup = ToolCall("paper", "search_literature", {"query": "paper result", "reason": "missing evidence"})
    draft = decision(json.dumps({"answer": "61 [1]", "coverage": []}))
    script = [decision(calls=[sql]), draft]
    if supplements:
        script += [decision(calls=[lookup]), draft]
    adapter = Fake(script)
    requests = []

    def judge(payload, _timeout):
        requests.append(payload)
        assert set(payload) == {"question", "requirements", "evidence"}
        score = initial_support if len(requests) == 1 else .99
        return {
            "need_1": {"supported": .98, "partially_supported": .01, "insufficient": .01},
            "need_2": {"supported": score, "partially_supported": 1 - score, "insufficient": 0},
        }, {}

    def execute(request, *_):
        if request["tool"] == sql.name:
            return {"status": "completed", "result": {
                "ref": "[1]", "sql": request["sql"], "rows": [[61]], "columns": ["count"],
            }}
        return {"status": "completed", "result": {"evidence": [
            {"ref": "[2]", "document_id": "doc", "text": "Paper result."},
        ]}}

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run(question, "test")
    assert state["status"] == "completed"
    assert state["review_status"] == "disabled"
    assert state["evidence_check_status"] == "supported"
    assert state["tool_attempts"] == (2 if supplements else 1)
    assert len(requests) == (2 if supplements else 1)
    assert state.get("evidence_supplement_requested", False) == supplements
    if supplements:
        prompt = adapter.requests[2][0][-1]["content"]
        assert '"need_2"' in prompt and '"need_1"' not in prompt


def test_jev_timeout_still_returns_the_answer():
    lookup = ToolCall("lookup", "describe_experiment_data", {
        "views": ["fiber.v_sample_overview"], "reason": "schema",
        "requirements": [{"role": "sql", "source_quote": "sample fields"}],
    })
    draft = decision(json.dumps({"answer": "Here are the fields.", "coverage": []}))
    adapter = Fake([decision(calls=[lookup]), draft])

    def timeout(*_):
        raise TimeoutError()

    state = AgentLoop(
        adapter, lambda *_: {"status": "completed", "call_id": "directory", "result": {"views": {}}},
        lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=timeout),
    ).run("Report the sample fields.", "test")
    assert state["status"] == "completed"
    assert state["answer"] == "Here are the fields."
    assert state["evidence_check_status"] == "unavailable"
    assert [call["stage"] for call in state["model_calls"]] == [
        "decide", "decide", "evidence_check",
    ]


def test_rejected_paper_quotes_can_be_registered_after_retrieval():
    anchor = "参考Morais与Curto（2022）与Uddin等（2024）的划分方式"
    items = [
        {"role": "literature", "source_quote": f"{paper}的划分方式（样本量）",
         "paper_quote": paper, "deliverable": f"说明{paper}所报告的训练和测试划分"}
        for paper in ("Morais与Curto（2022）", "Uddin等（2024）")
    ]
    repaired = [
        {**item, "source_quote": anchor, "correction_id": f"quote_{i}"}
        for i, item in enumerate(items, 1)
    ]
    draft = {"answer": "Two splits [1][2].", "coverage": []}
    lookup = ToolCall("paper", "read_section", {
        "targets": [{"document_id": "a", "section_id": "sec-a"},
                    {"document_id": "b", "section_id": "sec-b"}],
        "reason": "read splits", "requirements": items,
    })
    adapter = Fake([
        decision(calls=[lookup]), decision(json.dumps(draft, ensure_ascii=False)),
        decision(json.dumps({**draft, "requirements": repaired}, ensure_ascii=False)),
    ])
    requests = []

    def judge(payload, _timeout):
        requests.append(payload)
        return {f"need_{i}": {"supported": 1, "partially_supported": 0, "insufficient": 0}
                for i in (1, 2)}, {}

    state = AgentLoop(
        adapter,
        lambda *_: {"status": "completed", "result": {"sources": [
            {"ref": "[1]", "document_id": "a", "text": "70/30"},
            {"ref": "[2]", "document_id": "b", "text": "17/4"},
        ]}},
        lambda _: None, unified_research=True, evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run(anchor, "test")

    assert state["status"] == "completed" and state["tool_attempts"] == 1
    assert state["requirement_registration_retry_requested"]
    notice = json.loads(adapter.requests[1][0][-1]["content"])["requirement_registration"]
    assert [item["invalid_fields"] for item in notice["rejected"]] == [["source_quote"]] * 2
    assert [item["resolved_by"] for item in state["task_contract"]["rejected"]] == ["need_1", "need_2"]
    assert len(requests) == 1
    assert [item["deliverable"] for item in requests[0]["requirements"]] == [
        item["deliverable"] for item in items
    ]
    assert [item["source_quote"] for item in requests[0]["requirements"]] == [anchor, anchor]
    assert {entry["ref"] for entry in requests[0]["evidence"]} == {"[1]", "[2]"}
