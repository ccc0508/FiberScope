"""Actionable, model-facing recovery guidance for rejected tool requests."""

from pydantic import ValidationError

from literature_rag.diagnostics import worker_exception_details
from .tool_retry import TRANSIENT
from .tools import INPUT


BINDING_ERRORS = {
    "lookup_outside_ready_task_scope", "missing_initial_task_binding", "invalid_evidence_task_binding",
}
BINDING_ISSUES = {
    "missing_sql_binding": "No unambiguous SQL requirement was bound to this call.",
    "invalid_initial_targets": "initial_targets must contain 1-based integer positions of accepted SQL entries in this call's requirements.",
    "unavailable_target_requirements": "target_requirements contains a value that was not published as a SQL need in an earlier tool result.",
    "conflicting_sql_bindings": "target_requirements and the SQL requirements in this call refer to different tasks.",
    "multiple_sql_binding_selectors": "Choose one binding field. Using initial_targets and target_requirements together is ambiguous.",
}


def invalid_parameters(request):
    try:
        INPUT.validate_python(request)
    except ValidationError as error:
        return [
            {"field": ".".join(map(str, issue["loc"])), "problem": issue["msg"]}
            for issue in error.errors(include_input=False, include_context=False, include_url=False)[:8]
        ]
    return []


def executor_failure(error):
    code = type(error).__name__
    if code not in TRANSIENT:
        code = "tool_execution_failed"
    return dict(status="failed", error_code=code, worker_diagnostic=dict(
        kind="executor_exception", exceptions=worker_exception_details(error),
    ))


def add_recovery_guidance(request, result, schedule=None, ready_sql_scopes=()):
    """Preserve error codes and explain the smallest correction the model can make."""
    if result["status"] == "completed":
        return result
    code = result.get("error_code")
    tool = request["tool"]
    feedback = None
    if code in BINDING_ERRORS and tool in {"describe_experiment_data", "query_experiment_data"}:
        binding = (schedule or {}).get("binding_details", {})
        ids = binding.get("available_requirement_ids", [])
        positions = binding.get("valid_initial_positions", [])
        reason = BINDING_ISSUES.get(binding.get("issue"), "This lookup did not bind to a ready SQL requirement.")
        if code == "lookup_outside_ready_task_scope" and not ready_sql_scopes:
            feedback = "No SQL task is ready in this plan. Wait for the missing choice or finish the other ready tasks."
        else:
            if binding.get("phase") == "locked":
                feedback = reason + " Use an existing SQL need ID in target_requirements. Keep the original task scope and referenced fields."
            else:
                feedback = reason + (
                    f" To retry {tool}, include the relevant SQL requirement with a verbatim source_quote and use "
                    "initial_targets to point to its 1-based position. Send initial_targets: [1] for one requirement. "
                    "Keep the intended population and filter. A directory result gives columns and units, then run SELECT for the requested values."
                )
            if positions:
                feedback += f" Accepted positions in the rejected request: {positions}."
            if ids:
                feedback += f" Published SQL IDs that may be reused in target_requirements: {', '.join(ids)}."
            if ready_sql_scopes:
                feedback += " Ready user scope: " + " | ".join(scope[:240] for scope in ready_sql_scopes[:3])
            result = dict(result, binding_recovery=dict(available_requirement_ids=ids,
                                                        valid_initial_positions=positions,
                                                        issue=binding.get("issue")))
    elif code in {"invalid_arguments", "invalid_query", "ValueError"}:
        fields = result.get("invalid_parameters") or invalid_parameters(request)
        if fields:
            result = dict(result, invalid_parameters=fields)
            feedback = "Correct these fields before retrying: " + "; ".join(
                f"{item['field']}: {item['problem']}" for item in fields
            )
            if tool == "read_table":
                feedback += (
                    " Use a known printed table_number or a verified chunk_id. If you have neither, "
                    "use search_literature to locate the table first."
                )
        if feedback is None and tool == "query_experiment_data":
            feedback = (
                "The query returned no validated result. Correct sql using the validation message. "
                "Use the actual columns and an allowed fiber view returned by describe_experiment_data. "
                "If you already have that directory result, reuse it. Keep the task binding and exact user filters."
            )
    elif code in {"unsupported_sql", "query_plan_rejected"}:
        feedback = (
            "Revise sql using the diagnostic. Keep the result grain and filters, remove the unsupported construct "
            "or narrow the expensive operation, and submit one read-only SELECT over the confirmed views."
        )
    elif code == "database_query_failed":
        sqlstate = result.get("sqlstate") or ""
        if sqlstate in {"42703", "42P01", "42883", "42804", "22P02"}:
            feedback = "Check the diagnostic for the invalid column, relation or type and update sql using the confirmed schema before retrying."
        elif sqlstate.startswith("08") or sqlstate in {"40001", "40P01", "57014", "57P03"}:
            feedback = "For the first temporary database failure, you may retry this operation once unchanged within budget. Otherwise report the missing result."
        else:
            feedback = "Use the SQL diagnostic and confirmed schema to correct the operation, or report the missing result."
    elif code in TRANSIENT:
        feedback = "For the first temporary failure, you may retry once unchanged within budget. Otherwise use another permitted path or report the gap."
    elif code == "parameters_not_corrected":
        feedback = "This operation still has the previous parameter error. Correct the named field from that result; editing the reason will not change the operation."
    elif code == "duplicate_call":
        feedback = "This operation was already run or scheduled. Reuse its result. For a remaining gap, request different fields, a narrower target, or another relevant source."
    elif code in {"context_budget", "tool_budget"}:
        feedback = "Collection budget is exhausted. Use the evidence already delivered and state which requested facts remain unresolved."
    elif code == "query_execution_failed":
        feedback = "The experiment data service could not execute this request. Use previously returned rows or report the missing result. Do not infer values from the view definition."
    elif code in {"tool_execution_failed", "tool_result_unavailable", "worker_failed"}:
        feedback = ("This lookup returned no usable result. Continue independent tasks, try another offered lookup "
                    "for the same requirement, or state the gap. Do not infer evidence from the failed call.")
    elif code == "batch_lookup_failed":
        feedback = "Use the diagnostic for each batch entry, correct the listed identifiers or offsets, and retry only the entries still needed."
    elif code in {"unknown_section", "offset_outside_section", "exclusions_outside_section"}:
        feedback = "Use the document and section handles from the section directory. Check the returned offsets in the recovery result before retrying."
    elif code in {"unknown_document", "unknown_asset"}:
        feedback = "Use the exact paper or asset identifier from the paper directory or successful locator result before retrying."
    if feedback is None and not result.get("notice"):
        feedback = "This attempt provided no evidence. Use any diagnostic returned to correct the request. If no correction is available, try a different permitted lookup or report the gap."
    return dict(result, recovery_guidance=feedback) if feedback else result
