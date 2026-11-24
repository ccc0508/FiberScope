import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.adapters.providers.jev_evidence import JevEvidenceJudge, MODEL
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from tests.test_agent_loop import Fake, decision


def decisions(payload, supports, *, optional=(), actionable=True):
    output = {}
    for item in payload["requirements"]:
        key = item.get("check_id", item["requirement_id"])
        supported = supports[key]
        probability = 0. if key in optional else 1.
        output[key] = {"supported": supported, "partially_supported": 1 - supported, "insufficient": 0.}
        output[f"scope_{key}"] = {"required": probability, "nonessential": 1 - probability}
        if item.get("next_lookup"):
            output[f"lookup_{key}"] = {"actionable": float(actionable), "not_actionable": float(not actionable)}
    return output, {}


@pytest.mark.parametrize("lookup_only", [False, True])
def test_jev_uses_typed_choices_without_a_draft(lookup_only):
    payload = {"question": "Count groups.", "requirements": [{"requirement_id": "need_1", "check_id": "need_1_check_1",
               "criterion": "The number of groups.", "direct_sources": [{"ref": "[1]"}],
               "gap": "Count unique groups.", "next_lookup": {"tool": "query_experiment_data"}}],
               "evidence": [{"ref": "[1]", "rows": [[47]]}]}
    if lookup_only:
        payload["lookup_review_only"] = True

    def post(url, *, json, **kwargs):
        assert url.endswith("/alpha/decisions")
        assert json["state"] == payload
        if lookup_only:
            assert set(json["questions"]) == {"lookup_need_1_check_1"}
        else:
            assert json["questions"]["need_1_check_1"]["type"] == "choice"
            assert "only its criterion" in json["questions"]["need_1_check_1"]["instructions"]
            assert "direct_sources" in json["questions"]["need_1_check_1"]["instructions"]
            assert "Ignore evidence" in json["questions"]["scope_need_1_check_1"]["instructions"]
        assert "lookup_history" in json["questions"]["lookup_need_1_check_1"]["instructions"]
        assert json["provider"] == {"allow_fallbacks": False}
        answer = {"choice": "supported", "confidence": .92, "probabilities": {
            "supported": .89, "partially_supported": .09, "insufficient": .02,
        }}
        scope = {"choice": "required", "confidence": .98, "probabilities": {"required": .98, "nonessential": .02}}
        lookup = {"choice": "not_actionable", "confidence": .92,
                  "probabilities": {"actionable": .08, "not_actionable": .92}}
        answers = {"lookup_need_1_check_1": lookup}
        if not lookup_only:
            answers.update(need_1_check_1=answer, scope_need_1_check_1=scope)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"model": MODEL, "provider": "TypeSafe", "answers": answers,
                          "usage": {"input_tokens": 100, "total_tokens": 100}},
        )

    scores, usage = JevEvidenceJudge("test", post=post).check(payload, 10)
    if not lookup_only:
        assert scores["need_1_check_1"]["supported"] == .89
        assert scores["scope_need_1_check_1"]["required"] == .98
    assert scores["lookup_need_1_check_1"]["not_actionable"] == .92
    assert usage == {"prompt_tokens": 100, "total_tokens": 100}


@pytest.mark.parametrize("initial_support, supplements", [(.79, True), (.80, False)])
def test_supplement_targets_only_items_below_threshold(initial_support, supplements):
    question = "Report the local count and the paper result."
    requirements = [
        {"role": "sql", "source_quote": "local count"},
        {"role": "literature", "source_quote": "paper result",
         "optional_details": ["Report the instrument model."]},
    ]
    sql = ToolCall("sql", "query_experiment_data", {
        "sql": "SELECT COUNT(*) FROM fiber.v_sample_overview", "reason": "count",
        "requirements": requirements,
    })
    extra = {**requirements[1], "deliverable": "An extra paper detail"}
    lookup = {"query": "paper result", "reason": "missing evidence"}
    draft = decision(json.dumps({"answer": "61 [1]", "coverage": [], "evidence_checks": [
        {"check_id": "need_1", "sources": [{"ref": "[1]"}]},
        {"check_id": "need_2", "gap": "Paper A's reported result is missing.",
         "next_lookup": {"tool": "search_literature", **lookup}},
    ]}))
    script = [decision(calls=[sql]), draft]
    if supplements:
        script += [
            decision(calls=[
                ToolCall("missing", "search_literature", {**lookup, "requirements": [extra]}),
                ToolCall("wrong", "search_literature", {**lookup, "target_requirements": ["need_1"]}),
                ToolCall("new", "search_literature", {**lookup, "target_requirements": ["need_3"]}),
                ToolCall("optional", "search_literature", {**lookup, "target_requirements": ["need_2_optional_1"]}),
                ToolCall("mixed", "search_literature", {
                    **lookup, "target_requirements": ["need_2", "need_2_optional_1"],
                }),
                ToolCall("changed", "search_literature", {
                    **lookup, "query": "some other paper", "target_requirements": ["need_2"],
                }),
                ToolCall("paper", "search_literature", {**lookup, "target_requirements": ["need_2"]}),
            ]),
            decision(json.dumps({"answer": "61 [1]", "coverage": [], "requirements": [extra]})),
        ]
    adapter = Fake(script)
    requests = []

    def judge(payload, _timeout):
        requests.append(payload)
        assert [item["requirement_id"] for item in payload["requirements"]] == ["need_1", "need_2"]
        assert all(item["required"] for item in payload["requirements"])
        score = initial_support if len(requests) == 1 else .99
        if len(requests) == 1:
            assert payload["requirements"][0]["direct_sources"] == [{"ref": "[1]"}]
            assert payload["lookup_history"][0]["operation"]["tool"] == "query_experiment_data"
        return decisions(payload, {"need_1": .98, "need_2": score})

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
    assert not state["evidence_check"]["pending"]
    assert state["evidence_check"]["threshold"] == .80
    assert all("optional_details" not in item for item in state["task_contract"]["requirements"])
    if supplements:
        prompt = adapter.requests[2][0][-1]["content"]
        assert '"need_2"' in prompt and '"need_1"' not in prompt
        assert "below 0.80" in prompt
        assert "need_2_optional_1" not in prompt and "instrument model" not in prompt
        rejected = [t["result"] for t in state["tool_calls"] if t["status"] == "blocked"]
        assert len(rejected) == 6
        assert all(t["error_code"] == "invalid_followup_search_targets"
                   and t["allowed_requirement_ids"] == ["need_2"] for t in rejected[:-1])
        assert rejected[-1]["error_code"] == "unapproved_evidence_lookup"
        assert state["task_contract"]["ignored_additions"] == 2
        assert state["budget_usage"]["search"] == 1
        assert len(requests[-1]["requirements"]) == 2


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


@pytest.mark.parametrize("case, reason", [
    ("nonessential", None),
    ("covered", "lookup_rejected"),
    ("paraphrase", "lookup_rejected"),
    ("tried", "no_new_lookup"),
    ("no_gap", "no_new_lookup"),
])
def test_low_evidence_score_does_not_authorize_unnecessary_lookup(case, reason):
    initial = {
        "document_id": "doc_a", "query": "Paper A results", "reason": "get evidence",
    }
    lookup = {**initial, "query": "paper A; RESULTS " if case == "tried" else "A paper measurements"}
    submission = {
        "check_id": "need_1_check_1", "gap": "" if case == "no_gap" else "Exact value of the result",
        "sources": [{"ref": "[1]", "quote": "The result is  42."},
                    {"ref": "[1]", "quote": "Invented text."},
                    {"ref": "[3]", "quote": "Unavailable source."}],
        "next_lookup": {"tool": "search_literature", **lookup},
    }
    draft = {"answer": "The result is 42 [1].", "coverage": [], "evidence_checks": [submission]}
    adapter = Fake([decision(calls=[ToolCall("start", "search_literature", {
        **initial, "requirements": [{
            "role": "literature", "paper_quote": "Paper A", "source_quote": "Report Paper A's result.",
            "deliverable": "Identify the result", "acceptance_criteria": ["Identify the result."],
        }],
    })]), decision(json.dumps(draft))])

    def judge(payload, _timeout):
        item, = payload["requirements"]
        assert item["direct_sources"] == [{"ref": "[1]", "quote": "The result is  42."}]
        assert ("next_lookup" in item) == (case not in {"tried", "no_gap"})
        return decisions(payload, {"need_1_check_1": .63},
                         optional=("need_1_check_1",) if case == "nonessential" else (),
                         actionable=case not in {"covered", "paraphrase"})

    state = AgentLoop(
        adapter, lambda *_: {"status": "completed", "result": {"evidence": [
            {"ref": "[1]", "document_id": "doc_a", "text": "The result is 42."},
        ]}}, lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run("Report Paper A's result.", "unnecessary")
    assert state["answer"] == draft["answer"]
    assert not state.get("evidence_supplement_requested")
    checks = state["evidence_check"]
    assert not checks["pending"]
    assert [item["reason"] for item in checks["unresolved"]] == ([reason] if reason else [])
    assert bool(checks["scope_excluded"]) == (case == "nonessential")
    errors = [e["code"] for e in state["model_calls"][-1]["submission_errors"]]
    assert "source_quote_not_found" in errors and "unavailable_evidence_ref" in errors


def test_table_locator_only_authorizes_the_returned_handle():
    planned = {"document_id": "doc_a", "table_number": "2", "reason": "Table 2 gives the unit."}
    task = {"role": "literature", "paper_quote": "Paper A", "source_quote": "exact unit",
            "deliverable": "Give the exact unit", "acceptance_criteria": ["Give the unit."]}
    target = {"target_requirements": ["need_1_check_1"]}
    adapter = Fake([
        decision(calls=[ToolCall("initial", "search_literature", {
            "query": "Paper A overview", "reason": "first evidence", "requirements": [task],
        })]),
        decision(json.dumps({"answer": "The exact unit is unclear [1].", "coverage": [], "evidence_checks": [
            {"check_id": "need_1_check_1", "gap": "The actual tensile unit is missing.",
             "next_lookup": {"tool": "find_table", **planned}},
        ]})),
        decision(calls=[ToolCall("locator", "find_table", {**planned, **target})]),
        decision(calls=[
            ToolCall("bad", "read_table", {**target, "document_id": "doc_a", "chunk_id": "wrong", "reason": "unit"}),
            ToolCall("table", "read_table", {**target, "document_id": "doc_a", "chunk_id": "table-2", "reason": "unit"}),
        ]),
        decision(json.dumps({"answer": "The unit is N·m/g [2].", "coverage": []})),
    ])
    executed = []

    def execute(request, *_):
        tool = request["tool"]
        executed.append(tool)
        outputs = {
            "search_literature": {"evidence": [{"ref": "[1]", "document_id": "doc_a", "text": "Tensile index"}]},
            "find_table": {"tables": [{"document_id": "doc_a", "chunk_id": "table-2"}]},
            "read_table": {"table": {"ref": "[2]", "document_id": "doc_a", "text": "Tensile index (N·m/g)"}},
        }
        return {"status": "completed", "result": outputs[tool]}

    def judge(payload, _timeout):
        return decisions(payload, {"need_1_check_1": 0.3 if len(payload["evidence"]) == 1 else 1.})

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        allowed_tools={"search_literature", "find_table", "read_table"},
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run("What is the exact unit in Paper A?", "table-supplement")
    assert executed == ["search_literature", "find_table", "read_table"]
    assert state["tool_calls"][2]["result"]["error_code"] == "unapproved_evidence_lookup"
    assert state["answer"] == "The unit is N·m/g [2]."


@pytest.mark.parametrize("scenario", ["approved", "repair", "repeat", "rejected", "no_plan", "budget"])
def test_jev_can_prompt_one_plan_after_finding_an_unplanned_gap(scenario):
    check_id = "need_1_check_1"
    first = {"tool": "search_literature", "reason": "methods", "query": "Paper A methods", "document_id": "doc_a"}
    new = {**first, "reason": "compare validation errors", "query": "independent validation NRMSE"}
    initial_answer = "Paper A describes its methods [1], but the validation error is unclear."
    initial = ToolCall("initial", first["tool"], {k: v for k, v in first.items() if k != "tool"} | {
        "requirements": [{
            "role": "literature", "paper_quote": "Paper A", "source_quote": "validation error",
            "deliverable": "Report the validation error", "acceptance_criteria": ["Give the validation error."],
        }],
    })
    draft = json.dumps({"answer": initial_answer, "coverage": []})
    turns = [decision(calls=[initial]), decision(initial_answer if scenario == "repair" else draft)]
    if scenario == "repair":
        turns.append(decision(draft))
    if scenario != "budget":
        plan = [{"check_id": check_id, "gap": "The actual validation error is missing.",
                 "next_lookup": first if scenario == "repeat" else new}]
        turns.append(decision(json.dumps([] if scenario == "no_plan" else plan)))
    if scenario in {"approved", "repair"}:
        turns.append(decision(json.dumps({"answer": "The validation error was 0.2 [2].", "coverage": []})))
    adapter = Fake(turns)
    executed = []

    def execute(request, *_):
        executed.append(request)
        ref, text = ("[1]", "The experiment used a validation set.") if len(executed) == 1 else (
            "[2]", "The validation NRMSE was 0.2.",
        )
        return {"status": "completed", "result": {"evidence": [
            {"ref": ref, "document_id": "doc_a", "text": text},
        ]}}

    def judge(payload, _timeout):
        if payload.get("lookup_review_only"):
            assert len(payload["requirements"]) == 1
            assert payload["requirements"][0]["next_lookup"] == new
            assert len(payload["lookup_history"]) == 1
            yes = float(scenario != "rejected")
            return {f"lookup_{check_id}": {"actionable": yes, "not_actionable": 1 - yes}}, {}
        return decisions(payload, {check_id: .99 if len(executed) == 2 else .1})

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        allowed_tools={"search_literature"},
        budget=AgentBudget(max_model_calls=6 if scenario == "budget" else 10),
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run("What was the validation error in Paper A?", "unplanned-gap")
    assert state["status"] == "completed"
    if scenario == "budget":
        assert "evidence_supplement_planning" not in state
        assert len(executed) == 1
        return
    assert sum(c["stage"] == "evidence_supplement_plan" for c in state["model_calls"]) == 1
    planning = state["evidence_supplement_planning"]
    if scenario in {"approved", "repair"}:
        assert planning["status"] == "approved"
        assert state["evidence_supplement_requested"]
        assert len(executed) == 2
        assert state["tool_calls"][-1]["dispatch"] == "approved_evidence_plan"
        assert state["tool_calls"][-1]["coverage_schedule"]["target_checks"] == [check_id]
        assert state["answer"] == "The validation error was 0.2 [2]."
    else:
        assert planning["status"] == {
            "repeat": "no_eligible_lookup", "rejected": "lookup_rejected", "no_plan": "no_useful_lookup",
        }[scenario]
        assert not state.get("evidence_supplement_requested")
        assert len(executed) == 1
        assert state["answer"] == initial_answer


def test_source_quote_repairs_keep_catalog_titles_after_retrieval():
    anchor = "参考Morais与Curto（2022）与Uddin等（2024）的划分方式"
    items = [
        {"role": "literature", "source_quote": f"{paper}的划分方式（样本量）",
         "paper_quote": f"Published methods by {paper}", "deliverable": f"说明{paper}所报告的训练和测试划分"}
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
        decision(json.dumps({**draft, "requirements": [
            {**repaired[0], "deliverable": "An unrelated result"}, *repaired,
        ]}, ensure_ascii=False)),
    ])
    requests = []

    def judge(payload, _timeout):
        requests.append(payload)
        return decisions(payload, {"need_1": 1., "need_2": 1.})

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
    assert state["task_contract"]["ignored_additions"] == 1
    assert len(requests) == 1
    assert [item["deliverable"] for item in requests[0]["requirements"]] == [
        item["deliverable"] for item in items
    ]
    assert [item["source_quote"] for item in requests[0]["requirements"]] == [anchor, anchor]
    assert [item["paper_quote"] for item in requests[0]["requirements"]] == [
        item["paper_quote"] for item in items
    ]
    assert {entry["ref"] for entry in requests[0]["evidence"]} == {"[1]", "[2]"}

@pytest.mark.parametrize("search_budget", [1, 2])
def test_jev_checks_facts_separately_and_groups_unmet_ones_in_one_query(search_budget):
    question = "For Paper A, report its material, dataset origin and validation source."
    criteria = ["Identify the material.", "Identify the dataset origin.", "Identify the validation source."]
    task = {
        "role": "literature", "source_quote": "material, dataset origin and validation source",
        "paper_quote": "Paper A", "deliverable": "Summarize the paper's data.",
        "acceptance_criteria": criteria,
    }
    initial = ToolCall("initial", "search_literature", {
        "document_id": "doc_a", "query": "Paper A material and methods", "reason": "get evidence",
        "requirements": [task],
    })
    queries = [initial.arguments["query"]]
    supplement = {"document_id": "doc_a", "query": "data origin and validation",
                  "reason": "complete data provenance"}
    draft = decision(json.dumps({"answer": "The material is pulp [1].", "coverage": [], "evidence_checks": [
        {"check_id": "need_1_check_1", "sources": [{"ref": "[1]", "quote": "Paper evidence [1]"}]},
        *({"check_id": f"need_1_check_{n}", "gap": criteria[n - 1],
           "next_lookup": {"tool": "search_literature", **supplement}} for n in (2, 3)),
    ]}))
    outputs = [decision(calls=[initial]), draft]
    if search_budget > 1:
        outputs += [
            decision(calls=[
                ToolCall("covered", "search_literature", {**supplement, "target_requirements": ["need_1_check_1"]}),
                ToolCall("parent", "search_literature", {**supplement, "target_requirements": ["need_1"]}),
                ToolCall("both", "search_literature", {
                    **supplement, "target_requirements": ["need_1_check_2", "need_1_check_3"],
                }),
            ]),
            decision(json.dumps({"answer": "Pulp [1], with experimental and validation data [2].", "coverage": []})),
        ]
        queries.append(supplement["query"])
    adapter = Fake(outputs)
    judge_calls = []
    tool_queries = []

    def judge(payload, _timeout):
        judge_calls.append(payload)
        assert [r["criterion"] for r in payload["requirements"]] == criteria
        assert all(r["requirement_id"] == "need_1" and r["required"] and "deliverable" not in r
                   for r in payload["requirements"])
        assert len(payload["evidence"]) == len(judge_calls)
        scores = (1., .15, .20) if len(judge_calls) == 1 else (1., .95, .99)
        return decisions(payload, dict(zip((item["check_id"] for item in payload["requirements"]), scores, strict=True)))

    def execute(request, *_):
        assert "target_requirements" not in request
        tool_queries.append(request["query"])
        ref = f"[{len(tool_queries)}]"
        return {"status": "completed", "result": {"evidence": [
            {"ref": ref, "document_id": "doc_a", "text": "Paper evidence " + ref},
        ]}}

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        allowed_tools={"search_literature"},
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
        budget=AgentBudget(max_search_calls=search_budget),
    ).run(question, "fact-check")
    assert state["status"] == "completed"
    assert tool_queries == queries
    assert state["search_rounds"] == search_budget
    assert len(judge_calls) == search_budget
    fields = adapter.requests[0][1]["search_literature"]["$defs"]["ResearchRequirement"]["properties"]
    assert "acceptance_criteria" in fields
    assert "optional_details" not in fields
    if search_budget == 2:
        feedback = adapter.requests[2][0][-1]["content"]
        assert "need_1_check_2" in feedback and "need_1_check_3" in feedback
        assert "need_1_check_1" not in feedback and criteria[0] not in feedback
        assert state["evidence_check_status"] == "supported"
        assert state["tool_calls"][-1]["coverage_schedule"]["target_requirements"] == ["need_1"]
        assert state["tool_calls"][-1]["coverage_schedule"]["target_checks"] == ["need_1_check_2", "need_1_check_3"]
        for event in state["tool_calls"][1:3]:
            assert event["result"]["error_code"] == "invalid_followup_search_targets"
    else:
        assert state["evidence_check_status"] == "needs_evidence"
        assert not state.get("evidence_supplement_requested")
        assert len(adapter.requests) == 2
