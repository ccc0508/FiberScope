import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.adapters.providers.jev_evidence import JevEvidenceJudge, MODEL
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
    script.append(decision("61 [1]"))
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
    assert state["evidence_check_status"] == "supported"
    assert state["tool_attempts"] == (2 if supplements else 1)
    assert len(requests) == (2 if supplements else 1)
    assert state.get("evidence_supplement_requested", False) == supplements
    if supplements:
        prompt = adapter.requests[2][0][-1]["content"]
        assert '"need_2"' in prompt and '"need_1"' not in prompt


def test_jev_timeout_keeps_answer_review_available():
    lookup = ToolCall("lookup", "describe_experiment_data", {
        "views": ["fiber.v_sample_overview"], "reason": "schema",
        "requirements": [{"role": "sql", "source_quote": "sample fields"}],
    })
    draft = decision(json.dumps({"answer": "Here are the fields.", "coverage": []}))
    adapter = Fake([decision(calls=[lookup]), draft, decision("Here are the fields.")])

    def timeout(*_):
        raise TimeoutError()

    state = AgentLoop(
        adapter, lambda *_: {"status": "completed", "call_id": "directory", "result": {"views": {}}},
        lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=timeout),
    ).run("Report the sample fields.", "test")
    assert state["status"] == "completed"
    assert state["evidence_check_status"] == "unavailable"
    assert [call["stage"] for call in state["model_calls"]] == [
        "decide", "decide", "evidence_check", "review",
    ]
