"""Separate a workflow tool request from an explicit final submission."""

import json


def _unique_keys(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("JSON fields must be unique.")
    return result


def workflow_tool_output(text, schemas, *, native=False):
    try:
        payload = json.loads(text, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError):
        if native and not text.strip():
            return [], None
        return [], "Use native Function Calling or one JSON object with top-level actions, or submit answer and coverage."
    if not isinstance(payload, dict):
        return [], "The decision must be a JSON object."
    if payload.get("plan") is not None:
        return [], "The plan is already locked. Submit actions for its ready tasks or finalize the answer."
    if "actions" not in payload:
        if not native and isinstance(payload.get("answer"), str) and payload["answer"].strip():
            return [], None
        if "sql" in payload:
            return [], ("Missing tool name. Put the SQL and reason in query_experiment_data.arguments "
                        "and include the ready task_id.")
        return [], "Use native Function Calling, top-level actions, or answer for a final submission."
    if native or payload.get("answer"):
        return [], "Submit either tool requests or an answer, using one tool-call channel."
    actions = payload["actions"]
    if (payload.keys() - {"plan", "actions", "answer"} or not isinstance(actions, list)
            or not 1 <= len(actions) <= 16 or payload.get("answer", "") != ""):
        return [], "Use a non-empty actions array of {name, arguments} objects with no additional fields."
    for i, action in enumerate(actions, 1):
        if not isinstance(action, dict) or action.keys() != {"name", "arguments"}:
            return [], f"Action {i} must contain only name and arguments."
        if not isinstance(action["name"], str) or action["name"] not in schemas:
            return [], f"Action {i} must name one of the offered tools."
        if not isinstance(action["arguments"], dict):
            return [], f"Action {i}.arguments must be a JSON object."
    return actions, None
