import json

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


def test_unified_agent_tracks_two_sources_in_the_same_context():
    requirements = [
        {"role": "sql", "source_quote": "local count"},
        {"role": "literature", "source_quote": "paper result", "paper_quote": "paper A"},
    ]
    calls = [
        ToolCall("sql", "query_experiment_data", {
            "sql": "SELECT COUNT(*) FROM fiber.v_sample_overview",
            "reason": "count local records", "requirements": requirements[:1],
            "target_requirements": ["need_1"],
        }),
        ToolCall("paper", "search_literature", {
            "query": "paper result", "document_ids": ["doc_a"], "reason": "check the paper",
            "target_requirements": ["need_2"], "requirements": requirements[1:],
        }),
    ]
    answer = "The local count is 61 [1]. The paper reports ten observations [2]."
    coverage = [
        {"requirement_id": "need_1", "status": "verified", "refs": ["[1]"], "finding": "61"},
        {"requirement_id": "need_2", "status": "verified", "refs": ["[2]"],
         "document_id": "doc_a", "finding": "ten observations"},
    ]
    draft = json.dumps({"answer": answer, "coverage": coverage})
    adapter = Fake([decision(calls=calls), decision(draft), decision(answer)])
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
    assert state["answer"] == answer and state["review_status"] == "completed"
    assert state["coverage_report"]["complete"]
    assert state["citation_validation"]["status"] == "passed"
    assert state["task_contract"]["locked"]
    assert all("requirements" not in schema["properties"] for schema in adapter.requests[1][1].values())
    assert len(adapter.requests) == 3
