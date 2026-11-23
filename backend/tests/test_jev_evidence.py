import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.adapters.providers.jev_evidence import JevEvidenceJudge, MODEL
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from tests.test_agent_loop import Fake, decision


def test_jev_uses_typed_choices_without_a_draft():
    payload = {"question": "Count groups.", "requirements": [{"requirement_id": "need_1", "check_id": "need_1_check_1", "criterion": "The number of groups."}],
               "evidence": [{"ref": "[1]", "rows": [[47]]}]}

    def post(url, *, json, **kwargs):
        assert url.endswith("/alpha/decisions")
        assert json["state"] == payload
        assert json["questions"]["need_1_check_1"]["type"] == "choice"
        assert "only its criterion" in json["questions"]["need_1_check_1"]["instructions"]
        assert json["provider"] == {"allow_fallbacks": False}
        answer = {"choice": "supported", "confidence": .92, "probabilities": {
            "supported": .89, "partially_supported": .09, "insufficient": .02,
        }}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"model": MODEL, "provider": "TypeSafe", "answers": {"need_1_check_1": answer},
                          "usage": {"input_tokens": 100, "total_tokens": 100}},
        )

    scores, usage = JevEvidenceJudge("test", post=post).check(payload, 10)
    assert scores["need_1_check_1"]["supported"] == .89
    assert usage == {"prompt_tokens": 100, "total_tokens": 100}


@pytest.mark.parametrize("initial_support, supplements", [(.89, True), (.90, False)])
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
    draft = decision(json.dumps({"answer": "61 [1]", "coverage": []}))
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
                ToolCall("paper", "search_literature", {**lookup, "target_requirements": ["need_2"]}),
            ]),
            decision(json.dumps({"answer": "61 [1]", "coverage": [], "requirements": [extra]})),
        ]
    adapter = Fake(script)
    requests = []

    def judge(payload, _timeout):
        requests.append(payload)
        assert set(payload) == {"question", "requirements", "evidence"}
        assert [item["required"] for item in payload["requirements"]] == [True, True, False]
        score = initial_support if len(requests) == 1 else .99
        return {
            "need_1": {"supported": .98, "partially_supported": .01, "insufficient": .01},
            "need_2": {"supported": score, "partially_supported": 1 - score, "insufficient": 0},
            "need_2_optional_1": {"supported": 0, "partially_supported": 0, "insufficient": 1},
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
    assert not state["evidence_check"]["pending"]
    assert [item["check_id"] for item in state["evidence_check"]["optional_gaps"]] == ["need_2_optional_1"]
    if supplements:
        prompt = adapter.requests[2][0][-1]["content"]
        assert '"need_2"' in prompt and '"need_1"' not in prompt
        assert "need_2_optional_1" not in prompt and "instrument model" not in prompt
        rejected = [t["result"] for t in state["tool_calls"] if t["status"] == "blocked"]
        assert len(rejected) == 5
        assert all(t["error_code"] == "invalid_followup_search_targets"
                   and t["allowed_requirement_ids"] == ["need_2"] for t in rejected)
        assert state["task_contract"]["ignored_additions"] == 2
        assert state["budget_usage"]["search"] == 1
        assert len(requests[-1]["requirements"]) == 3


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
        "optional_details": [criteria[0]],
    }
    initial = ToolCall("initial", "search_literature", {
        "document_id": "doc_a", "query": "Paper A material and methods", "reason": "get evidence",
        "requirements": [task],
    })
    queries = [initial.arguments["query"]]
    draft = decision(json.dumps({"answer": "The material is pulp [1].", "coverage": []}))
    outputs = [decision(calls=[initial]), draft]
    if search_budget > 1:
        supplement = {"document_id": "doc_a", "query": "data origin and validation",
                      "reason": "complete data provenance"}
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
        return {
            item["check_id"]: {"supported": score, "partially_supported": 1-score, "insufficient": 0.}
            for item, score in zip(payload["requirements"], scores, strict=True)
        }, {}

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
    assert {"acceptance_criteria", "optional_details"} <= fields.keys()
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
