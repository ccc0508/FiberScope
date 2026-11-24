import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from literature_rag.application.tools import SCHEMAS
from literature_rag.application.unified_research import ResearchChecklist
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
    assert len(adapter.requests[0][1]) == 8
    assert "read_table" in adapter.requests[0][1] and "find_table" not in adapter.requests[0][1]
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
        scores = {}
        for item in payload["requirements"]:
            key = item["requirement_id"]
            scores[key] = {"supported": 1.0}
            scores[f"scope_{key}"] = {"required": 1.0, "nonessential": 0.0}
        return scores, {}

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
    stages = [call["stage"] for call in state["model_calls"]]
    expected_suffix = ["research_format_repair", "evidence_check"] if repair_succeeds else ["research_format_repair"]
    assert stages[-len(expected_suffix):] == expected_suffix
    assert not adapter.requests[-1][1]
    assert "verified, partial, missing, not_attempted, needs_clarification" in adapter.requests[-1][0][-1]["content"]
    assert state["tool_attempts"] == 1
    if repair_succeeds:
        assert state["status"] == "completed" and state["answer"] == answer
    else:
        assert state["status"] == "failed" and state["answer"] == ""
        assert state["stop_reason"] == "invalid_research_output"
        assert state["citation_validation"]["status"] == "not_applicable"


def test_first_research_turn_returns_server_ids_without_requiring_targets():
    lookup = ToolCall("initial", "search_literature", {
        "query": "first paper result", "reason": "check first paper", "document_id": "a",
        "target_requirements": ["R1"],
        "requirements": [
            {"requirement_id": "R1", "role": "literature", "source_quote": "first paper",
             "deliverable": "Read the result in the first paper"},
            {"requirement_id": "R2", "role": "literature", "source_quote": "second paper",
             "deliverable": "Read the result in the second paper"},
        ],
    })
    followup = ToolCall("followup", "search_literature", {
        "query": "second paper result", "reason": "check second paper", "document_id": "b",
        "target_requirements": ["need_2"],
    })
    answer = "The papers report ten [1] and twenty [2]."
    body = json.dumps({"answer": answer, "coverage": [
        {"requirement_id": "need_1", "status": "verified", "document_id": "a", "refs": ["[1]"], "finding": "ten"},
        {"requirement_id": "need_2", "status": "verified", "document_id": "b", "refs": ["[2]"], "finding": "twenty"},
    ]})
    adapter = Fake([decision(calls=[lookup]), decision(calls=[followup]), decision(body)])

    def execute(request, *_):
        doc = request["document_id"]
        ref, text = ("[1]", "ten") if doc == "a" else ("[2]", "twenty")
        return {"status": "completed", "result": {"evidence": [
            {"ref": ref, "document_id": doc, "text": text}
        ]}}

    state = AgentLoop(adapter, execute, lambda _: None, unified_research=True).run(
        "Compare the first paper and second paper.", "task-ids"
    )
    assert state["status"] == "completed" and state["answer"] == answer
    initial_schema = adapter.requests[0][1]["search_literature"]
    assert "target_requirements" not in initial_schema["properties"]
    assert "correction_id" not in initial_schema["$defs"]["ResearchRequirement"]["properties"]
    target_schema = adapter.requests[1][1]["search_literature"]
    assert "target_requirements" in target_schema["required"]
    first, second = state["tool_calls"]
    handoff = json.loads(first["model_delivery"]["messages"][0]["content"])["requirement_registration"]
    assert [row["requirement_id"] for row in handoff["registered"]] == ["need_1", "need_2"]
    assert [row["deliverable"] for row in handoff["registered"]] == [
        "Read the result in the first paper", "Read the result in the second paper"
    ]
    assert handoff["rejected"] == []
    assert [(row["index"], row["field"]) for row in handoff["normalized"]] == [(0, "requirement_id"), (1, "requirement_id")]
    assert first["coverage_schedule"]["errors"] == []
    assert first["coverage_schedule"]["target_requirements"] == []
    assert second["status"] == "completed"



def test_jev_registration_reuses_duplicate_paper_task_and_preserves_distinct_results():
    question = "比较 Pennells 与 Motamedian 的 fines 定义和检测限制，判断数值能否合并。"
    checklist = ResearchChecklist(question, evidence_only=True)
    state = {}
    lookup = {"tool": "search_literature", "query": "fines definitions and detection limits"}
    task = {
        "role": "literature", "source_quote": question, "paper_quote": "Motamedian 2019",
        "deliverable": "比较 Motamedian 的 fines 尺寸定义与检测限制",
        "acceptance_criteria": ["Motamedian 的 fines 尺寸定义", "哪些 fines 无法检测", "哪些  fines 无法检测"],
    }
    duplicate = {
        **task, "deliverable": "说明该论文如何划分 fines，以及仪器的漏测范围",
        "acceptance_criteria": ["哪些 fines 无法检测", "Motamedian 的 fines 尺寸定义"],
    }
    other_paper = {**task, "paper_quote": "Pennells 2022",
                   "acceptance_criteria": ["Pennells 的 fines 尺寸定义", "哪些 fines 无法检测"]}
    distinct = {**task, "deliverable": "核对 Motamedian 的统计基准",
                "acceptance_criteria": ["该文如何计算 fines 含量"]}
    _, schedule = checklist.prepare({
        **lookup, "requirements": [task, duplicate, other_paper, distinct],
    }, state)
    feedback = schedule["requirement_registration"]
    assert feedback["rejected"] == []
    assert feedback["normalized"] == [
        {"index": 1, "field": "requirements", "reason": "duplicate_evidence_contract", "requirement_id": "need_1"},
    ]
    assert [item["deliverable"] for item in feedback["registered"]] == [
        task["deliverable"], other_paper["deliverable"], distinct["deliverable"],
    ]
    assert [item["check_id"] for item in feedback["evidence_checklist"]] == [
        "need_1_check_1", "need_1_check_2", "need_2_check_1", "need_2_check_2", "need_3_check_1",
    ]


def test_invalid_task_shape_can_be_corrected_after_first_turn_without_adding_tasks():
    checklist = ResearchChecklist("Compare first and second.")
    state = {}
    lookup = {"tool": "search_literature", "query": "results"}
    task = {"role": "literature", "source_quote": "first", "deliverable": "Read the first result"}
    _, schedule = checklist.prepare({**lookup, "requirements": [{**task, "paper_qoute": "A"}]}, state)
    registration = schedule["requirement_registration"]
    rejected, = registration["rejected"]
    assert rejected["index"] == 0
    assert rejected["invalid_fields"] == ["paper_qoute"]
    assert rejected["errors"][0]["type"] == "extra_forbidden"
    assert registration["registered"] == []

    checklist.lock(state)
    schema = checklist.schemas(SCHEMAS)["search_literature"]
    assert "correction_id" in schema["$defs"]["ResearchRequirement"]["properties"]

    bad_fix = {**task, "deliverable": "Read a different result", "correction_id": rejected["correction_id"]}
    _, schedule = checklist.prepare({**lookup, "requirements": [bad_fix]}, state)
    assert schedule["search_scope_error"] == []
    assert schedule["requirement_registration"]["rejected"][0]["reason"] == "correction_does_not_match"
    assert checklist.requirements == []

    fix = {**task, "correction_id": rejected["correction_id"]}
    extra = {**task, "source_quote": "second", "deliverable": "Read the second result"}
    _, schedule = checklist.prepare({**lookup, "requirements": [fix, extra]}, state)
    assert [r["deliverable"] for r in schedule["requirement_registration"]["registered"]] == ["Read the first result"]
    assert state["task_contract"]["ignored_additions"] == 2
    assert state["task_contract"]["rejected"][0]["resolved_by"] == "need_1"
    assert "requirements" not in checklist.schemas(SCHEMAS)["search_literature"]["properties"]
    _, schedule = checklist.prepare({**lookup, "target_requirements": ["need_1"]}, state)
    assert "search_scope_error" not in schedule and not schedule["blocked"]


def test_jev_submission_ignores_only_legacy_coverage_fields():
    lookup = {
        "tool": "search_literature", "query": "paper result", "reason": "check",
        "requirements": [{"role": "literature", "source_quote": "paper result", "paper_quote": "paper A"}],
    }
    row = {
        "requirement_id": "need_1", "status": "verified", "document_id": "a",
        "refs": ["[1]"], "finding": "Ten observations.",
    }
    answer = "The paper reports ten observations [1]."
    with_legacy_fields = {**row, "checks": ["This is not an object."], "cells": "unused"}
    for evidence_only in (True, False):
        checklist = ResearchChecklist("Give the paper result from paper A.", evidence_only=evidence_only)
        state = {}
        checklist.prepare(lookup, state)
        checklist.lock(state)
        state["tool_calls"] = [{
            "request": {"tool": "search_literature"},
            "model_delivery": {"status": "delivered"},
            "result": {"status": "completed", "result": {"evidence": [
                {"ref": "[1]", "document_id": "a", "text": row["finding"]},
            ]}},
        }]
        prompt = checklist.submission_format
        assert ("checks, cells" not in prompt) == evidence_only
        assert "requirement_id, status, document_id, refs, finding, gap" in prompt

        raw = json.dumps({"answer": answer, "coverage": [with_legacy_fields]})
        assert checklist.draft(raw, state, stage="decide")[0] == answer
        attempt = state["research_output_attempts"][-1]
        if evidence_only:
            assert attempt["ignored_coverage_fields"] == [{"index": 0, "fields": ["cells", "checks"]}]
            assert not attempt["issues"]
            assert state["coverage_report"]["complete"]
        else:
            assert "ignored_coverage_fields" not in attempt
            assert attempt["issues"][0]["code"] == "invalid_coverage_item"
            assert not state["coverage_report"]["complete"]

        bad_row = {**with_legacy_fields, "paper_quote": "paper A"}
        checklist.draft(json.dumps({"answer": answer, "coverage": [bad_row]}), state, stage="decide")
        assert state["research_output_attempts"][-1]["issues"][0]["code"] == "invalid_coverage_item"


def test_jev_coverage_update_preserves_status_when_legacy_fields_are_present():
    checklist = ResearchChecklist("Give the paper results.", evidence_only=True)
    state = {}
    lookup = {"tool": "search_literature", "query": "results", "reason": "check"}
    checklist.prepare({
        **lookup,
        "requirements": [{"role": "literature", "source_quote": "paper results"}],
    }, state)
    checklist.lock(state)
    _, schedule = checklist.prepare({
        **lookup,
        "target_requirements": ["need_1"],
        "coverage_updates": [{"requirement_id": "need_1", "status": "missing", "gap": "No result yet.",
                              "checks": ["old note"], "cells": 0}],
    }, state)
    assert schedule["errors"] == []
    assert schedule["ignored_coverage_fields"] == [{"index": 0, "fields": ["cells", "checks"]}]
    assert checklist.items["need_1"].gap == "No result yet."
