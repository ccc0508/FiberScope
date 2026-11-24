"""Validate per-item evidence submissions and bind supplements to approved lookups."""
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .tool_retry import signature
from .tools import INPUT


SECTION_TOOLS = frozenset({"list_sections", "read_section"})


EVIDENCE_LOOKUP_TOOLS = {
    "literature": frozenset({
        "search_literature", "find_documents", "list_sections", "read_section",
        "read_table", "find_figure", "view_image",
    }),
    "sql": frozenset({"describe_experiment_data", "query_experiment_data"}),
}

# Successful locators may authorize a read of a handle they returned in this supplement.
LOCATOR_READS = {
    "read_table": ("read_table", "tables", "chunk_id"),
    "view_image": ("find_figure", "assets", "asset_id"),
    "read_section": ("list_sections", "sections", "section_id"),
}


class EvidenceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    check_id: str = Field(min_length=1, max_length=48)
    gap: str = Field(default="", max_length=400)
    next_lookup: dict | None = None


def lookup_signature(request):
    """Compare real tool parameters, including implicit defaults, without the rationale."""
    operation = INPUT.validate_python(request).model_dump(exclude_none=True)
    if operation["tool"] in {"search_literature", "find_documents"}:
        operation["query"] = " ".join(re.findall(r"[^\W_]+", operation["query"].casefold()))
    if "table_number" in operation:
        operation["table_number"] = operation["table_number"].casefold()
    return signature(operation)


def attempted_lookups(events):
    """Return executable operations that actually ran, including failed operations."""
    history, keys = [], set()
    for event in events:
        if event.get("status") not in {"completed", "failed"}:
            continue
        request = event.get("request", {})
        try:
            key = lookup_signature(request)
        except ValidationError:
            continue
        keys.add(key)
        history.append({
            "operation": {k: v for k, v in request.items() if k != "reason"},
            "status": event["status"],
        })
    return history, keys


def attach_submissions(payload, raw_rows, events, available_tools):
    """Validate optional gap proposals independently of how tool evidence was bound."""
    items = {item["requirement_id"]: item for item in payload["requirements"]}
    _, tried = attempted_lookups(events)
    errors, submitted = [], set()
    for row in raw_rows:
        if isinstance(row, dict) and "sources" in row:
            # Older drafts can be replayed without trusting their hand-picked excerpts.
            row = {key: value for key, value in row.items() if key != "sources"}
        try:
            submission = EvidenceSubmission.model_validate(row)
        except ValidationError as error:
            errors.append({"code": "invalid_evidence_submission",
                           "errors": error.errors(include_input=False, include_url=False, include_context=False)})
            continue
        key = submission.check_id
        item = items.get(key)
        if item is None or key in submitted:
            errors.append({"check_id": key, "code": "unknown_or_duplicate_check_id"})
            continue
        submitted.add(key)
        if submission.gap:
            item["gap"] = submission.gap
        if submission.next_lookup is None:
            continue
        try:
            request = INPUT.validate_python(submission.next_lookup).model_dump(exclude_none=True)
            key_signature = lookup_signature(request)
        except ValidationError:
            errors.append({"check_id": key, "code": "invalid_lookup_arguments"})
            continue
        if not submission.gap:
            errors.append({"check_id": key, "code": "missing_specific_gap"})
        elif request["tool"] not in available_tools & EVIDENCE_LOOKUP_TOOLS[item["role"]]:
            errors.append({"check_id": key, "code": "lookup_tool_unavailable"})
        elif key_signature in tried:
            errors.append({"check_id": key, "code": "lookup_already_attempted"})
        else:
            item["next_lookup"] = request
            item["lookup_history"], _ = attempted_lookups([
                event for event in events
                if key in (event.get("coverage_schedule") or {}).get("target_requirements", [])
            ])
    return errors



def section_continuation_allowed(request, related_events):
    """Follow directory handles or exact cursors that were delivered for this check."""
    documents, listed, handles, directory_cursors = set(), set(), set(), set()
    read_starts, read_cursors = set(), set()
    for event in related_events:
        previous = event["request"]
        output = event["result"]["result"]
        if previous["tool"] == "search_literature" and previous.get("document_id"):
            documents.add(previous["document_id"])
        if previous["tool"] == "list_sections":
            for page in output.get("documents") or [output]:
                if page.get("status", "completed") != "completed":
                    continue
                document = page.get("document_id")
                if not document:
                    continue
                listed.add(document)
                handles.update((document, row["section_id"]) for row in page.get("sections", []))
                if page.get("next_offset") is not None:
                    directory_cursors.add((document, page["next_offset"]))
        elif previous["tool"] == "read_section":
            targets = previous.get("targets") or [previous]
            sections = output.get("sections") or [output]
            for target, page in zip(targets, sections):
                if page.get("status", "completed") != "completed":
                    continue
                handle = (target["document_id"], target["section_id"])
                exclusions = tuple(target.get("exclude_chunk_ids", []))
                read_starts.add((*handle, target.get("offset", 0)))
                if page.get("next_offset") is not None:
                    read_cursors.add((*handle, page["next_offset"], exclusions))

        for source in output.get("evidence", []) + output.get("sources", []) + [output.get("table", {})]:
            document = source.get("document_id")
            if document:
                documents.add(document)
                section = source.get("section_id") or (source.get("locator") or {}).get("section_id")
                if section:
                    handles.add((document, section))

    if request["tool"] == "list_sections":
        offset = request.get("offset", 0)
        if offset:
            return (request["document_id"], offset) in directory_cursors
        requested = set(request.get("document_ids") or [request["document_id"]])
        return requested <= documents - listed

    for target in request.get("targets") or [request]:
        handle = (target["document_id"], target["section_id"])
        offset = target.get("offset", 0)
        if (*handle, offset) in read_starts:
            return False
        if offset:
            if (*handle, offset, tuple(target.get("exclude_chunk_ids", []))) not in read_cursors:
                return False
        elif handle not in handles:
            return False
    return True


def supplement_lookup_allowed(request, target_ids, approved, events):
    """Authorize exactly the proposed operation or a read grounded in its locator."""
    try:
        operation = lookup_signature(request)
    except ValidationError:
        return False
    _, tried = attempted_lookups(events)
    if operation in tried:
        return False
    locator = LOCATOR_READS.get(request["tool"])
    for key in target_ids:
        planned = approved[key]["next_lookup"]
        if operation == lookup_signature(planned):
            continue
        related_events = [
            event for event in events
            if key in (event.get("coverage_schedule") or {}).get("target_checks", [])
            and event.get("status") == "completed"
            and event.get("model_delivery", {}).get("status") == "delivered"
        ]
        if request["tool"] in SECTION_TOOLS:
            if not section_continuation_allowed(request, related_events):
                return False
            continue
        if not locator or planned["tool"] != locator[0]:
            return False
        table_resolution = request["tool"] == "read_table"
        if table_resolution and (not planned.get("table_number") or not request.get("chunk_id")):
            return False
        locator_tool, result_key, handle_key = locator
        matching_outputs = (
            event["result"]["result"] for event in related_events
            if event["request"]["tool"] == locator_tool
            and (not table_resolution or lookup_signature(event["request"]) == lookup_signature(planned))
        )
        handles = {
            handle for output in matching_outputs for handle in locator_handles(output, result_key, handle_key)
        }
        targets = request.get("targets") or [request]
        if any((target["document_id"], target[handle_key]) not in handles or target.get("offset")
               for target in targets):
            return False
    return bool(target_ids)


def locator_handles(output, result_key, handle_key):
    for row in output.get(result_key) or []:
        document_id = row.get("document_id") or output.get("document_id")
        if isinstance(row.get(handle_key), str):
            yield document_id, row[handle_key]
    for document in output.get("documents") or []:
        yield from locator_handles(document, result_key, handle_key)
