"""Recognize tool-shaped JSON in a research continuation's text output."""

import json


SQL_TOOL = "query_experiment_data"
BARE_SQL_FIELDS = {"sql", "reason", "target_requirements"}


def _unique_keys(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


def followup_tool_output(text, schemas, pending_sql_targets):
    """Return an explicit lookup or an issue for one bounded correction."""
    try:
        payload = json.loads(text, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError):
        return None, None
    if not isinstance(payload, dict) or payload.keys() & {"answer", "coverage", "plan"}:
        return None, None

    if "name" in payload and (set(payload) == {"name"} or "arguments" in payload):
        name = payload.get("name")
        if not isinstance(name, str) or name not in schemas:
            return None, "The named tool is unavailable for this local task. Use one of the tools listed below."
        if set(payload) != {"name", "arguments"} or not isinstance(payload["arguments"], dict):
            return None, f"Send {name} through Function Calling with a single arguments object."
        arguments = payload["arguments"]
    elif SQL_TOOL in schemas and "sql" in payload and payload.keys() <= BARE_SQL_FIELDS:
        name, arguments = SQL_TOOL, payload
        targets = arguments.get("target_requirements")
        if (payload.keys() != BARE_SQL_FIELDS or not isinstance(targets, list) or not targets
                or any(not isinstance(target, str) or target not in pending_sql_targets for target in targets)
                or not isinstance(arguments["sql"], str) or not arguments["sql"].strip()
                or not isinstance(arguments["reason"], str) or not arguments["reason"].strip()):
            return None, ("A SQL request was written in the response body without an unambiguous pending task. "
                          "Call query_experiment_data with sql, reason and the published SQL task IDs in target_requirements.")
    else:
        return None, None

    schema = schemas[name]
    unknown = sorted(arguments.keys() - (schema["properties"].keys() - {"tool"}))
    missing = sorted(set(schema.get("required", ())) - arguments.keys() - {"tool"})
    if unknown or missing:
        return None, (f"Incorrect arguments for {name}. Remove unrecognized fields {unknown} "
                      f"and include missing required fields {missing}.")
    return (name, arguments), None
