import json
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.adapters.providers.jev_evidence import JevEvidenceJudge, MODEL
from literature_rag.application.agent_loop import AgentLoop
from tests.test_agent_loop import Fake, decision


@pytest.mark.parametrize("named_paper", [False, True])
def test_jev_uses_typed_choices_without_a_draft(named_paper):
    item = {"requirement_id": "need_1"}
    if named_paper:
        item.update(role="literature", paper_quote="paper A")
    payload = {"question": "Count groups.", "requirements": [item],
               "evidence": [{"ref": "[1]", "rows": [[47]]}]}

    def post(url, *, json, **kwargs):
        assert url.endswith("/alpha/decisions")
        assert json["state"] == payload
        assert json["questions"]["need_1"]["type"] == "choice"
        assert ("source_unspecified" in json["questions"]["need_1"]["criteria"]) == named_paper
        assert json["provider"] == {"allow_fallbacks": False}
        answer = {"choice": "supported", "confidence": .92, "probabilities": {
            "supported": .89, "partially_supported": .09, "insufficient": .02,
        }}
        if named_paper:
            answer["probabilities"]["source_unspecified"] = 0
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
        decision(draft["answer"]),
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


@pytest.mark.parametrize("source_found", [False, True])
def test_fixed_checklist_with_unreported_detail_or_unresolved_search(source_found):
    question = "How did paper A divide its data?"
    requirement = {
        "role": "literature", "source_quote": "How did paper A divide its data",
        "paper_quote": "paper A", "deliverable": "Report the split and whether it was grouped.",
    }
    extra = {**requirement, "deliverable": "Additionally determine the number of replicate sheets."}
    initial = ToolCall("initial", "search_literature", {
        "query": "training and test split", "reason": "find reported procedure", "requirements": [requirement],
    })
    followup = ToolCall("supplement", "search_literature", {
        "query": "grouped assignment", "reason": "check for a grouping rule",
        "target_requirements": ["need_1"], "requirements": [extra],
    })
    answer = (
        "The methods report a 70/30 split [1]. The consulted passage does not specify grouping."
        if source_found else "Could not verify the split from the consulted evidence."
    )
    draft = decision(json.dumps({"answer": answer, "coverage": []}))
    script = [decision(calls=[initial]), draft]
    if not source_found:
        script += [
            decision(calls=[followup]),
            decision(json.dumps({"answer": answer, "coverage": [], "requirements": [extra]})),
        ]
    adapter = Fake([*script, decision(answer)])
    judged = []

    def judge(payload, _timeout):
        judged.append(payload)
        return {
            "need_1": {"supported": .02, "partially_supported": .02,
                       "source_unspecified": .94 if source_found else 0,
                       "insufficient": .02 if source_found else .96},
        }, {}

    def execute(request, *_):
        evidence = []
        if source_found:
            evidence.append({"ref": "[1]", "document_id": "doc_a", "text": "A 70/30 split was used."})
        return {"status": "completed", "result": {"evidence": evidence}}

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True,
        evidence_judge=SimpleNamespace(model=MODEL, check=judge),
    ).run(question, "fixed")
    assert state["status"] == "completed" and state["answer"] == answer
    assert len(judged) == 1
    assert [item["deliverable"] for item in state["task_contract"]["requirements"]] == [requirement["deliverable"]]
    assert state["task_contract"]["ignored_additions"] == (0 if source_found else 2)
    assert state["tool_attempts"] == (1 if source_found else 2)
    assert state.get("evidence_supplement_requested", False) is (not source_found)
    assert state["evidence_check_status"] == ("supported_with_source_limits" if source_found else "needs_evidence")
    assert bool(state["evidence_check"]["source_unspecified"]) is source_found
