"""Select and verify exact evidence fragments for result-driven delegation."""
from copy import deepcopy
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pydantic.json_schema import SkipJsonSchema

from .agent_context import EvidenceProjection
from .citation_policy import citation_records
from .sql_deliverables import signatures


Role = Literal['sql', 'literature']
MAX_SPECIALIST_CALLS = 3


class SuggestedBudget(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    collection_rounds: int | None = Field(default=None, ge=1, le=18)
    model_calls: SkipJsonSchema[int | None] = Field(default=None, ge=1, le=20)
    tool_calls: int | None = Field(default=None, ge=1, le=20)

    @property
    def total_calls(self):
        return (self.collection_rounds + 2 if self.collection_rounds is not None else max(3,self.model_calls or 7))


class InputSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    input_id: str | None = Field(default=None, pattern=r'^input_[1-9][0-9]*$')
    need: str = Field(default='', max_length=240)

    source_child_id: str = Field(min_length=1, max_length=250)
    ref: str = Field(pattern=r'^\[[1-9][0-9]*\]$')
    quote: str | None = Field(default=None, min_length=1, max_length=2400)
    columns: list[str] = Field(default_factory=list, max_length=12)
    row_indices: list[int] | None = Field(default=None, max_length=20)


class DelegateStep(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    requirement_ids: list[str] = Field(min_length=1, max_length=20)
    waits_for_batch_result: bool = False
    fresh_query_ids: list[str] = Field(default_factory=list, max_length=20)
    task: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=800)
    inputs: list[InputSelection] = Field(default_factory=list, max_length=8)
    missing_inputs: list[str] = Field(default_factory=list, max_length=8)
    budget: SuggestedBudget = Field(default_factory=SuggestedBudget)


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False))


def source_entries(children):
    """Return only sources actually seen by the producing specialist."""
    entries = {}
    for child in children:
        for event in child.get('trace', {}).get('tool_calls', []):
            if event.get('model_delivery', {}).get('status') != 'delivered':
                continue
            result, tool = event['result'], event['request']['tool']
            for record in citation_records(tool, result):
                entries[(child['id'], record['ref'])] = (event, record)
    return entries


def select_evidence(event, ref, choice=None):
    """Preserve the original reference and deliver only its selected source."""
    tool = event['request']['tool']
    original = event['result']
    result = original['result']
    text_key = {'search_literature': 'evidence', 'read_section': 'sources', 'read_table': 'table'}.get(tool)
    if text_key:
        if choice and (choice.columns or choice.row_indices is not None):
            raise ValueError('SQL row and column selectors require a SQL result')
        candidates = [result[text_key]] if text_key == 'table' else result[text_key]
        source = deepcopy(next(entry for entry in candidates if entry['ref'] == ref))
        if choice and choice.quote is not None:
            original_text = source['text']
            if choice.quote not in original_text:
                raise ValueError('Use a contiguous exact quote from the selected source')
            offset = original_text.index(choice.quote)
            start = source.get('start_char', 0) + offset
            source.pop('text_sha256', None)
            source.update(text=choice.quote, start_char=start, end_char=start + len(choice.quote))
        payload = {text_key: source if text_key == 'table' else [source]}
    elif tool == 'query_experiment_data':
        if choice and choice.quote is not None:
            raise ValueError('SQL handoff selects columns and row indices')
        cols, rows = result.get('columns', []), result.get('rows', [])
        payload = {k: deepcopy(result[k]) for k in (
            'ref', 'view', 'views', 'query_scope', 'row_count', 'truncated', 'result_state',
            'columns', 'rows', 'column_metadata',
        ) if k in result}
        if choice is None and 'sql' in result:
            payload['sql'] = result['sql']
        if choice:
            if choice.columns and any(cols.count(name) != 1 for name in choice.columns):
                raise ValueError('Selected columns must uniquely exist in the referenced SQL result')
            indices = [cols.index(name) for name in choice.columns] if choice.columns else list(range(len(cols)))
            picked = list(range(len(rows))) if choice.row_indices is None else choice.row_indices
            if any(type(i) is not int or not 0 <= i < len(rows) for i in picked):
                raise ValueError('Selected row indices must exist in the referenced SQL result')
            if cols:
                payload.update(columns=[cols[i] for i in indices], rows=[[rows[j][i] for i in indices] for j in picked])
            else:
                payload['rows'] = [rows[j] for j in picked]
            if 'column_metadata' in payload:
                payload['column_metadata'] = [m for m in payload['column_metadata'] if m.get('name') in payload.get('columns', [])]
            payload['selected_row_indices'] = picked
            proof = signatures(result.get('sql',''),cols)
            payload['metric_signatures'] = {name:proof[name] for name in payload['columns'] if name in proof} if cols else {}
            payload['row_count'] = result.get('row_count',len(rows))
    else:
        if choice and (choice.quote is not None or choice.columns or choice.row_indices is not None or tool == 'view_image'):
            raise ValueError('This source does not support the requested selector; for figures select textual evidence')
        payload = deepcopy(result)
    if choice:
        payload['selected_for'] = choice.need
        payload['selection_notice'] = 'Selected exact subset of the original evidence. Only the supplied content was forwarded.'
    return {'request': {'tool': tool}, 'status': 'completed', 'model_delivery': {'status': 'delivered'},
            'result': {'status': 'completed', 'result': payload}}


def fill_inputs(step, entries, offered, max_chars):
    events, manifest = [], []
    for choice in step.inputs:
        key = (choice.source_child_id, choice.ref)
        if key not in offered:
            raise ValueError('Select a source by the exact child and reference shown under available_inputs')
        event = select_evidence(entries[key][0], choice.ref, choice)
        if json_size(event) > min(6000, max_chars):
            raise ValueError('Select a shorter exact quote or fewer SQL columns and rows')
        events.append(event)
        manifest.append(dict(choice.model_dump(exclude_none=True), delivered_chars=json_size(event)))
    if json_size(events) > max_chars:
        raise ValueError('Selected inputs exceed the handoff budget; keep the essential excerpts only')
    return events, manifest


def clean_references(value, allowed):
    """Remove unavailable citation labels from planning and synthesis data."""
    if isinstance(value, str):
        return re.sub(r'\[[1-9][0-9]*\]', lambda m: m[0] if m[0] in allowed else '（证据未转交）', value)
    if isinstance(value, list):
        return [clean_references(x, allowed) for x in value]
    if isinstance(value, dict):
        return {key: [ref for ref in val if ref in allowed] if key in ('refs', 'source_refs') and isinstance(val, list)
                else clean_references(val, allowed) for key, val in value.items()}
    return value


def pack_evidence(children, entries, max_chars):
    """Pack individual citable records before optional metadata."""
    preferred = set()
    for child in children:
        for item in child.get('coverage_report', {}).get('items', []):
            reported = item.get('reported', {})
            preferred.update(reported.get('refs', []))
            for check in reported.get('checks', []):
                preferred.update(check.get('refs', []))
    context, refs, offered = [], {}, {}
    projection = EvidenceProjection()
    ordering = sorted(entries, key=lambda key: key[1] not in preferred)
    for key in ordering:
        child_id, ref = key
        event, record = entries[key]
        if ref not in refs:
            trial = deepcopy(projection)
            compact = trial.project(select_evidence(event, ref)['result'])
            compact['source_child_id'] = child_id
            if json_size(context + [compact]) > max_chars:
                continue
            context.append(compact)
            projection = trial
            refs[ref] = record
        if record['kind'] != 'source_image':
            offered[key] = record
    # Preserve schema-only answers and tool failures after citable material.
    for child in children:
        for event in child.get('trace', {}).get('tool_calls', []):
            delivery = event.get('model_delivery', {}).get('status')
            if delivery != 'delivered':
                continue
            raw, tool = event['result'], event['request']['tool']
            if citation_records(tool, raw) or tool not in ('describe_experiment_data', 'query_experiment_data'):
                continue
            item = dict(tool=tool, source_child_id=child['id'], result=projection.project(raw))
            if json_size(context + [item]) <= max_chars:
                context.append(item)
    return context, refs, offered
