"""Workflow development cases and readback of historical intent traces."""

import json
import re
from pathlib import Path

from literature_rag.application.citation_policy import citation_records
from literature_rag.application.evidence_acceptance import EVIDENCE_LOOKUP_TOOLS

PACK = Path(__file__).resolve().parents[2] / "data/agent-intent-evaluation"
FILES = (PACK / "workflow-v1.json",)
def intent_cases():
    definitions = json.loads(FILES[0].read_text(encoding="utf8"))
    for case in definitions:
        reference = {key: value for key, value in case.items() if key not in {"question", "id", "title"}}
        yield dict(id=case["id"], group="intent", category=case["title"], question=case["question"],
                   prompt=case["question"], reference=reference)


def workflow_trace_checks(case, result):
    reference = case["reference"]
    calls = result.get("tool_calls", [])
    executed = [call for call in calls if call["status"] in {"failed", "completed"}]
    completed = [call for call in calls if call["status"] == "completed"]
    tasks = {task["id"]: task for task in result.get("question_intent", {}).get("tasks", [])}
    evidence_tools = {"query_experiment_data", "read_table", "search_literature", "read_section", "view_image"}

    def names(call_list):
        return {call["request"]["tool"] for call in call_list}

    checks = reference["workflow_checks"]
    first, *later = result.get("model_calls") or [{}]
    trace_type = checks["type"]
    if trace_type == "direct":
        passed = (not later and first.get("text") == result.get("answer"), not executed)
    elif trace_type == "clarify":
        user_tasks = [task for task in tasks.values() if task["kind"] == "clarify" and task["status"] == "ask"]
        passed = (bool(user_tasks) and not (names(executed) & EVIDENCE_LOOKUP_TOOLS["sql"]),
                  bool(names(completed) & EVIDENCE_LOOKUP_TOOLS["literature"])
                  if checks.get("paper") else not executed)
    elif trace_type == "independent":
        roles = {tasks.get(call.get("workflow_task_id"), {}).get("kind") for call in completed
                 if call["request"]["tool"] in evidence_tools}
        passed = (set(checks["roles"]) <= roles,
                  any(task["kind"] == "direct" for task in tasks.values()) if checks.get("daily")
                  else bool(tasks) and all(not task["depends_on"] for task in tasks.values()))
    else:
        edges = [(task, dep) for task in tasks.values() if task["kind"] == checks["downstream"]
                 for dep in task.get("depends_on", [])
                 if tasks.get(dep["task_id"], {}).get("kind") == checks["upstream"]]
        valid_order = False
        for downstream, dependency in edges:
            upstream = tasks[dependency["task_id"]]
            source_refs = {upstream["outputs"][key]["ref"] for key in dependency["outputs"]
                           if key in upstream.get("outputs", {})}
            for index, call in enumerate(calls):
                if (call["status"] != "completed" or call.get("workflow_task_id") != downstream["id"]
                        or call["request"]["tool"] not in evidence_tools):
                    continue
                transferred = call.get("workflow_inputs", {}).get(upstream["id"], {})
                earlier = {record["ref"] for event in calls[:index]
                           if event.get("workflow_task_id") == upstream["id"]
                           and event.get("model_delivery", {}).get("status") == "delivered"
                           for record in citation_records(event["request"]["tool"], event.get("result", {}))}
                if (set(dependency["outputs"]) <= transferred.keys() and source_refs
                        and all(item["ref"] in earlier for item in transferred.values())):
                    valid_order = True
        passed = (bool(edges), valid_order)
    critical = []
    if result.get("public_web_searches") or any(
        call["request"]["tool"] in {"web_search", "web", "public_search"} for call in executed
    ):
        critical.append("当前工作流不允许公开搜索。")
    for call in executed:
        task = tasks.get(call.get("workflow_task_id"), {})
        if any(not set(item["outputs"]) <= call.get("workflow_inputs", {}).get(item["task_id"], {}).keys()
               for item in task.get("depends_on", [])):
            critical.append("前置证据未交付时执行了依赖任务。")
    return passed, critical


def intent_trace_checks(case, result):
    if "workflow_checks" in case["reference"]:
        return workflow_trace_checks(case, result)
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
