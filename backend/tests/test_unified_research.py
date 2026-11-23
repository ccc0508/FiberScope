import json

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.application.agent_loop import AgentLoop
from tests.test_agent_loop import Fake, decision


def test_unified_agent_direct_answer_preserves_user_output_format():
    answer = '[{"sample":"A","value":null}]'
    adapter = Fake([decision(answer)])
    state = AgentLoop(
        adapter, lambda *_: None, lambda _: None, paper_directory=[], unified_research=True
    ).run("Convert to JSON.", "direct")
    assert state["answer"] == answer
    assert state["review_status"] == "not_required"
    assert state["budget_usage"] == {"model": 1, "tools": 0, "search": 0}
    assert len(adapter.requests[0][1]) == 9
    assert all("independent_in_turn" not in schema["properties"] for schema in adapter.requests[0][1].values())
    system = adapter.requests[0][0][0]["content"]
    assert "fiber.v_sample_overview" in system and "fiber.v_recycled_cycle_detail" in system
    assert '"columns":' not in system and '"enum":' not in system


@pytest.mark.parametrize("issue,repair_succeeds", [
    (None, None), ("invalid", True), ("missing", True), ("both", True), ("missing", False),
])
def test_unified_agent_repairs_inline_citations_once(issue, repair_succeeds):
    requirements = [
        {"role": "sql", "source_quote": "local count"},
        {"role": "literature", "source_quote": "paper result", "paper_quote": "Published results from paper A"},
    ]
    calls = [
        ToolCall("sql", "query_experiment_data", {
            "sql": "SELECT COUNT(*) FROM fiber.v_sample_overview",
            "reason": "count local records", "requirements": requirements[:1],
            "target_requirements": ["need_1"],
        }),
        ToolCall("paper", "search_literature", {
            "query": "paper result", "document_id": "doc_a", "reason": "check the paper",
            "target_requirements": ["need_2"], "requirements": requirements[1:],
        }),
    ]
    answer = "The local count is 61 [1]. The paper reports ten observations [2]."
    coverage = [
        {"requirement_id": "need_1", "status": "verified", "refs": ["[1]"], "finding": "61"},
        {"requirement_id": "need_2", "status": "verified", "refs": ["[2]"],
         "document_id": "doc_a", "finding": "ten observations"},
    ]
    draft_answer = answer
    if issue in ("invalid", "both"):
        draft_answer = draft_answer.replace("[1]", "[9]")
    if issue in ("missing", "both"):
        draft_answer = draft_answer.replace(" [2]", "")
    draft = json.dumps({"answer": draft_answer, "coverage": coverage})
    decisions = [decision(calls=calls), decision(draft)]
    if issue:
        decisions.append(decision(answer if repair_succeeds else draft))
    adapter = Fake(decisions)
    sent = []

    def execute(request, *_):
        assert not {"independent_in_turn", "requirements", "target_requirements"} & request.keys()
        sent.append(request["tool"])
        if request["tool"] == "query_experiment_data":
            return {"status": "completed", "result": {"ref": "[1]", "rows": [[61]], "columns": ["count"]}}
        return {"status": "completed", "result": {"evidence": [
            {"ref": "[2]", "document_id": "doc_a", "text": "Ten observations."}
        ]}}

    state = AgentLoop(adapter, execute, lambda _: None, unified_research=True).run(
        "Give the local count and paper result for paper A.", "mixed"
    )
    assert sent == ["query_experiment_data", "search_literature"]
    assert state["review_status"] == "disabled"
    if repair_succeeds is False:
        assert state["answer"] == "" and state["status"] == "failed"
        assert state["stop_reason"] == "missing_literature_citations"
    else:
        assert state["answer"] == answer and state["status"] == "completed"
    assert state["coverage_report"]["complete"]
    assert state["task_contract"]["requirements"][1]["paper_quote"] == requirements[1]["paper_quote"]
    assert state["task_contract"]["rejected"] == []
    assert state["task_contract"]["locked"]
    search_schema = adapter.requests[1][1]["search_literature"]
    assert "requirements" not in search_schema["properties"]
    assert "target_requirements" in search_schema["required"]
    stages = ["decide", "decide"]
    validation = state["citation_validation"]
    if issue:
        stages.append("citation_repair")
        assert not adapter.requests[-1][1]
        errors = json.loads(adapter.requests[-1][0][-1]["content"])["errors"]
        assert (errors.get("invalid_refs") == ["[9]"]) == (issue in ("invalid", "both"))
        assert errors.get("missing_literature_citations", False) == (issue in ("missing", "both"))
        assert validation["status"] == ("repaired" if repair_succeeds else "failed")
        if not repair_succeeds:
            assert validation["attempts"][-1]["answer"] == draft_answer
            assert validation["errors"] == {"missing_literature_citations": True}
    else:
        assert validation["status"] == "passed"
    assert [call["stage"] for call in state["model_calls"]] == stages
