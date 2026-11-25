"""Fixed public-search inputs and execution checks for the intent development set."""

import json
import re
from pathlib import Path

from literature_rag.application.evidence_acceptance import EVIDENCE_LOOKUP_TOOLS
from literature_rag.application.question_intent import PLAN_TOOL

PACK = Path(__file__).resolve().parents[2] / "data/agent-intent-evaluation"
FILES = (PACK / "questions.jsonl", PACK / "gold.jsonl")
REFERENCE_SQL = {
    "INTENT04": (
        "SELECT sw_proportion_pct, hw_proportion_pct FROM fiber.v_sample_overview "
        "WHERE canonical_code = 'BLEND_SW050_HW050'",
    ),
    "INTENT08": (
        "SELECT fiber_length_weighted_mm FROM fiber.v_fiber_paper_analysis "
        "WHERE canonical_code = 'BLEND_SW050_HW050'",
    ),
}


def intent_cases():
    questions, references = (
        {row["id"]: row for row in map(json.loads, path.read_text(encoding="utf-8-sig").splitlines())}
        for path in FILES
    )
    if len(questions) != 10 or questions.keys() != references.keys():
        raise ValueError("Invalid intent development catalog")
    for key, item in questions.items():
        reference = references[key]
        if key in REFERENCE_SQL:
            reference["reference_sql"] = list(REFERENCE_SQL[key])
        yield dict(id=key, group="intent", category=reference["title"],
                   question=item["question"], prompt=item["question"], reference=reference)


class IntentSearchFixture:
    def __init__(self, case_id, question):
        case = next((case for case in intent_cases() if case["id"] == case_id), None)
        if case is None or case["question"] != question:
            raise ValueError("Intent fixture requires its registered question")
        self.fixture = case["reference"].get("fixture", {})
        self.queries = []

    def __call__(self, query, timeout):
        self.queries.append(query)
        return self.fixture.get("sources", []) if query == self.fixture.get("expected_query") else []


def replay_intent_boundary(case_id, question):
    """Run the two control cases through the policy with fixed model decisions."""
    if case_id not in {"INTENT03", "INTENT10"}:
        return None
    from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter, Decision, ToolCall
    from literature_rag.application.agent_loop import AgentLoop

    def declaration(*tasks):
        return ToolCall("plan", PLAN_TOOL, {"tasks": list(tasks)}, native=False)

    def decision(text="", calls=()):
        return Decision(text, list(calls), {"role": "assistant", "content": text}, None, "stop")

    fixture = IntentSearchFixture(case_id, question)
    if case_id == "INTENT03":
        steps = [decision(calls=[declaration(dict(id="public", kind="web", source_quote=question))])]
    else:
        local, _, public = question.partition("；")
        public = public.split("。", 1)[0]
        plan = declaration(dict(id="paper", kind="literature", source_quote=local),
                           dict(id="public", kind="web", source_quote=public))
        lookup = ToolCall("paper", "read_table", dict(
            document_id="replay", table_number="1", reason="Exercise a local lookup",
            requirements=[dict(role="literature", source_quote=local)], initial_targets=[1],
        ), native=False)
        change = declaration(dict(id="paper", kind="web", source_quote=local))
        steps = [
            decision(calls=[plan, lookup]),
            decision(calls=[change]),
            decision('{"answer":"纤维宽度的单位为 μm [1]。","coverage":[]}'),
            decision("模拟公开结果没有提供具体运营时间。"),
        ]

    class ReplayAdapter:
        tool_messages = staticmethod(ChatAgentAdapter.tool_messages)

        def decide(self, *_):
            return next(decisions)

    decisions = iter(steps)
    local_calls = []

    def execute(request, *_):
        local_calls.append(request["tool"])
        return dict(status="completed", result=dict(table=dict(ref="[1]", text="Width (μm)")))

    result = AgentLoop(
        ReplayAdapter(), execute, lambda _: None, unified_research=True, first_turn_intent=True,
        evidence_supplement_enabled=False, public_search=None if case_id == "INTENT03" else fixture,
    ).run(question, "fixture-replay")
    rejected = any("intent_locked_after_first_decision" in json.dumps(call["input_messages"])
                   for call in result["model_calls"])
    statuses = [item["status"] for item in result["public_web_searches"]]
    passed = result["status"] == "completed" and (
        (statuses == ["unconfigured"] and not local_calls and not fixture.queries)
        if case_id == "INTENT03" else
        (rejected and local_calls == ["read_table"] and fixture.queries == [fixture.fixture["expected_query"]])
    )
    return dict(passed=passed, transport_queries=fixture.queries, local_calls=local_calls,
                web_statuses=statuses, late_change_rejected=rejected, answer=result["answer"])


def intent_trace_checks(case, result):
    key = case["id"]
    trace = result.get("intent_evaluation")
    if not isinstance(trace, dict) or trace.get("case_id") != key:
        raise ValueError("Missing intent evaluation fixture trace")
    expected = case["reference"].get("fixture", {}).get("expected_query")
    queries = trace["transport_queries"]
    first, *later = result.get("model_calls") or [{}]
    first_ids = {call["id"] for call in first.get("calls", [])}
    tools = result.get("tool_calls", [])
    executed = [tool for tool in tools if tool["status"] in {"failed", "completed"}]
    first_tools = {tool["request"]["tool"] for tool in executed
                   if {tool.get("provider_call_id"), tool.get("parent_provider_call_id")} & first_ids}
    executed_names = {tool["request"]["tool"] for tool in executed}
    first_literature = bool(first_tools & EVIDENCE_LOOKUP_TOOLS["literature"])
    cited = set(re.findall(r"\[\d+\]", result.get("answer", "")))
    local_refs = {e["ref"] for e in result.get("evidence", []) if e["kind"] in {"source_text", "source_image"}}
    delivered = {item["ref"] for item in result.get("citation_validation", {}).get("available_records", [])}
    replay = trace.get("replay", {})
    checks = {
        "INTENT01": lambda: (first.get("text") == result.get("answer"), not later and not executed and not queries),
        "INTENT02": lambda: (first_literature, bool(cited & local_refs & delivered) and not queries),
        "INTENT03": lambda: (queries == [expected], not executed and replay.get("passed") is True),
        "INTENT04": lambda: (
            bool(first_tools & EVIDENCE_LOOKUP_TOOLS["sql"]) and queries == [expected],
            _isolated_web_context(result),
        ),
        "INTENT05": lambda: (bool(executed_names & EVIDENCE_LOOKUP_TOOLS["literature"]), not queries),
        "INTENT06": lambda: (first_literature, not queries),
        "INTENT07": lambda: (
            any(task["status"] == "ask" for task in result.get("question_intent", {}).get("tasks", [])),
            first_literature and "query_experiment_data" not in executed_names and not queries,
        ),
        "INTENT08": lambda: ("query_experiment_data" in executed_names, not queries),
        "INTENT09": lambda: (
            queries == [expected] and _isolated_web_context(result),
            bool(cited & local_refs & delivered)
            and all(e["kind"] != "public_web" for e in result.get("evidence", [])),
        ),
        "INTENT10": lambda: (queries == [expected], replay.get("passed") is True),
    }[key]()
    critical = []
    if queries and (expected is None or queries != [expected]):
        critical.append("外部查询违反首轮锁定范围。")
    if key == "INTENT07" and "query_experiment_data" in executed_names:
        critical.append("未澄清门槛即执行数据库查询。")
    if key in {"INTENT04", "INTENT09"} and queries and not _isolated_web_context(result):
        # Missing web synthesis is a completion defect. An actual leak has
        # independently observable evidence in a local model context.
        if _web_seen_in_local_context(result):
            critical.append("网页摘要进入本地科研上下文。")
    if key == "INTENT10" and replay.get("transport_queries", []) not in ([], [expected]):
        critical.append("重放触发了额外外部查询。")
    return checks, critical


def _web_seen_in_local_context(result):
    snippets = [source["snippet"] for job in result.get("public_web_searches", []) for source in job["sources"]]
    return any(
        snippet in json.dumps(call.get("input_messages", []), ensure_ascii=False)
        for call in result.get("model_calls", []) if call["stage"] != "public_web_answer"
        for snippet in snippets
    )


def _isolated_web_context(result):
    responses = [call for call in result.get("model_calls", []) if call["stage"] == "public_web_answer"]
    if len(responses) != 1 or responses[0].get("available_tools") or _web_seen_in_local_context(result):
        return False
    messages = responses[0].get("input_messages", [])
    if [entry["role"] for entry in messages] != ["system", "user"]:
        return False
    try:
        payload = json.loads(messages[1]["content"])
    except (ValueError, TypeError):
        return False
    completed = [job for job in result.get("public_web_searches", []) if job["status"] == "completed"]
    return any(payload == {"query": job["query"], "sources": job["sources"]} for job in completed)
