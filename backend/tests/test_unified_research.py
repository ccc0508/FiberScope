import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
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
        decisions.append(decision(json.dumps({"answer": answer}) if repair_succeeds else draft))
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

def run_submission(outputs, *, close_on_tool_limit=False):
    lookup = ToolCall("paper", "search_literature", {
        "query": "paper A results", "document_id": "doc_a", "reason": "find results",
        "requirements": [
            {"role": "literature", "source_quote": "first result", "paper_quote": "paper A"},
            {"role": "literature", "source_quote": "second result", "paper_quote": "paper A"},
        ],
    })
    adapter = Fake([decision(calls=[lookup]), *(decision(output) for output in outputs)])

    def judge(payload, _timeout):
        return {
            item["requirement_id"]: {"supported": 1.0} for item in payload["requirements"]
        }, {}

    state = AgentLoop(
        adapter, lambda *_: {"status": "completed", "result": {"evidence": [
            {"ref": "[1]", "document_id": "doc_a", "text": "The first result is ten."},
            {"ref": "[2]", "document_id": "doc_a", "text": "The second result is twenty."},
        ]}}, lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model="jev", check=judge),
        budget=AgentBudget(max_tool_calls=1 if close_on_tool_limit else 8),
    ).run("Give the first result and second result in paper A.", "format")
    return state, adapter


@pytest.mark.parametrize("mixed_footer", [False, True])
def test_research_submission_keeps_public_answer_when_one_coverage_item_is_invalid(mixed_footer):
    public_answer = "The paper reports ten [1] and twenty [2]."
    internal = [
        {"requirement_id": "need_1", "status": "verified", "document_id": "doc_a",
         "refs": ["[1]"], "finding": "ten"},
        {"requirement_id": "need_2", "status": "verified", "document_id": "doc_a",
         "refs": ["[2]"], "finding": "twenty"},
    ]
    raw_envelope = {"answer": public_answer, "coverage": internal}
    if mixed_footer:
        raw_envelope["answer"] = "Duplicate summary must not replace the visible body."
        internal[1]["status"] = "supported"
        output = public_answer + "\n\n```json\n" + json.dumps(raw_envelope) + "\n```"
        field, code = "status", "literal_error"
    else:
        internal[1]["paper_quote"] = "paper A"
        output = json.dumps(raw_envelope)
        field, code = "paper_quote", "extra_forbidden"

    state, _ = run_submission([output], close_on_tool_limit=mixed_footer)
    assert state["answer"] == public_answer
    assert state["status"] == "completed"
    coverage = state["coverage_report"]["items"]
    assert [row["status"] for row in coverage] == ["verified", "missing"]
    assert coverage[1]["errors"] == ["invalid_coverage_item"]
    assert state["citation_validation"]["status"] == "passed"
    attempt, = state["research_output_attempts"]
    assert attempt["stage"] == ("finalize" if mixed_footer else "decide")
    assert attempt["status"] == "recovered"
    if mixed_footer:
        assert attempt["recovery"] == "trailing_coverage_block"
    issue, = attempt["issues"]
    assert issue["requirement_id"] == "need_2"
    error, = issue["errors"]
    assert error["type"] == code and error["loc"] == (field,)
    assert not any(call["stage"] == "research_format_repair" for call in state["model_calls"])
    assert any(call.get("text") == output for call in state["model_calls"])


@pytest.mark.parametrize("close_on_tool_limit", [False, True])
@pytest.mark.parametrize("repair_succeeds", [False, True])
def test_research_format_failure_gets_one_tool_free_repair(close_on_tool_limit, repair_succeeds):
    malformed = 'Preamble that is not a reliable answer.\n{"answer": "Incomplete", "coverage": ['
    answer = "Available evidence [1]."
    repaired = json.dumps({"answer": answer, "coverage": []}) if repair_succeeds else malformed
    state, adapter = run_submission([malformed, repaired], close_on_tool_limit=close_on_tool_limit)

    assert [attempt["stage"] for attempt in state["research_output_attempts"]] == [
        "finalize" if close_on_tool_limit else "decide", "research_format_repair",
    ]
    assert state["research_output_attempts"][0]["status"] == "invalid"
    assert state["model_calls"][-1]["stage"] == "research_format_repair"
    assert not adapter.requests[-1][1]
    assert "verified, partial, missing, not_attempted, needs_clarification" in adapter.requests[-1][0][-1]["content"]
    assert state["tool_attempts"] == 1
    if repair_succeeds:
        assert state["status"] == "completed" and state["answer"] == answer
    else:
        assert state["status"] == "failed" and state["answer"] == ""
        assert state["stop_reason"] == "invalid_research_output"
        assert state["citation_validation"]["status"] == "not_applicable"
