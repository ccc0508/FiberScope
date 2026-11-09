"""Ground task checklists in user text; track evidence coverage, not scientific truth."""
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Requirement(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    role: Literal['sql', 'literature']
    source_quote: str = Field(min_length=1, max_length=1500)
    paper_quote: str = Field(default='', max_length=200)


class EvidenceCheck(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    aspect: Literal['study_object', 'data_origin', 'validation', 'sample_scope', 'author_explanation', 'measurement_limits', 'confounders', 'numeric_range', 'consistency']
    status: Literal['verified', 'partial', 'missing']
    refs: list[str] = Field(default_factory=list)
    finding: str = Field(default='', max_length=800)
    gap: str = Field(default='', max_length=800)


class CoverageItem(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    requirement_id: str
    status: Literal['verified', 'partial', 'missing', 'not_attempted', 'needs_clarification']
    document_id: str = ''
    refs: list[str] = Field(default_factory=list)
    finding: str = Field(default='', max_length=800)
    gap: str = Field(default='', max_length=800)
    checks: list[EvidenceCheck] = Field(default_factory=list, max_length=12)


def ground_requirements(requirements, question):
    accepted, rejected = [], []
    for r in requirements:
        item = r.model_dump()
        if r.source_quote not in question or (r.paper_quote and r.paper_quote not in question):
            rejected.append(dict(item, reason='not_verbatim_user_text'))
            continue
        if any(all(a[k] == item[k] for k in item) for a in accepted):
            continue
        accepted.append(dict(item, requirement_id=f'need_{len(accepted)+1}'))
    return accepted, rejected


def coverage_report(requirements, coverage, trace):
    """Only delivered successful results qualify; schema-only SQL tasks may use directory data.

    A valid ref proves availability, NOT semantic entailment or correct paper identification.
    Those remain explicit model-review responsibilities.
    """
    from .citation_policy import citation_records
    available, documents = set(), {}
    described = False
    def walk(value, document=''):
        if isinstance(value, dict):
            document = value.get('document_id') or (value.get('asset') or {}).get('document_id') or document
            if value.get('ref') and document:
                documents.setdefault(value['ref'], set()).add(document)
            for child in value.values(): walk(child, document)
        elif isinstance(value, list):
            for child in value: walk(child, document)
    for event in trace.get('tool_calls', []):
        if event.get('model_delivery', {}).get('status') != 'delivered': continue
        result = event.get('result', {})
        if result.get('status') != 'completed': continue
        tool = event['request']['tool']
        described |= tool == 'describe_experiment_data'
        available.update(r['ref'] for r in citation_records(tool, result))
        walk(result)
    rows = []
    for need in requirements:
        matches = [c for c in coverage if c.requirement_id == need['requirement_id']]
        errors = []
        item = matches[0].model_dump() if len(matches) == 1 else dict(status='not_attempted', refs=[])
        if len(matches) != 1: errors.append('missing_or_duplicate_coverage_item')
        if item['status'] in ('verified', 'partial'):
            if not item.get('finding'): errors.append('missing_finding')
            if item['status'] == 'partial' and not item.get('gap'): errors.append('missing_gap')
            if any(ref not in available for ref in item['refs']): errors.append('unavailable_ref')
            if need['role'] == 'literature':
                if not item['refs']: errors.append('missing_source_refs')
                if need.get('paper_quote') and not item.get('document_id'): errors.append('missing_document_id')
                elif item.get('document_id') and not any(item['document_id'] in documents.get(ref, set()) for ref in item['refs']):
                    errors.append('document_not_supported_by_refs')
            elif not item['refs'] and not described: errors.append('no_query_or_directory_evidence')
        check_errors = []
        checks = item.get('checks', [])
        for index, check in enumerate(checks):
            if check['status'] in ('verified', 'partial'):
                if not check.get('finding') or not check.get('refs'):
                    check_errors.append(f'check_{index}_missing_evidence')
                if any(ref not in available for ref in check['refs']):
                    check_errors.append(f'check_{index}_unavailable_ref')
            if check['status'] != 'verified' and not check.get('gap'):
                check_errors.append(f'check_{index}_missing_gap')
        effective = 'missing' if errors else item['status']
        if effective == 'verified' and (check_errors or any(c['status'] != 'verified' for c in checks)):
            effective = 'partial'
        rows.append(dict(requirement=need, reported=item, status=effective,
                         errors=errors + check_errors))
    complete=bool(rows) and all(r['status']=='verified' for r in rows)
    adequacy='sufficient' if complete else ('partial' if any(r['status'] in ('verified','partial') for r in rows) else 'insufficient')
    return dict(items=rows, complete=complete, evidence_adequacy=adequacy,
                unknown_ids=[c.requirement_id for c in coverage if c.requirement_id not in {r['requirement_id'] for r in requirements}],
                scope='Availability/coverage checks only; correctness and paper identity require evidence review.')


def completion_feedback(requirements):
    def check(raw, trace):
        from .specialist_agent import SpecialistResult, unwrap_json
        try: parsed = SpecialistResult.model_validate_json(unwrap_json(raw))
        except ValueError: return None  # existing bounded format repair owns malformed JSON
        report = coverage_report(requirements, parsed.coverage, trace)
        trace.setdefault('coverage_checks', []).append(report)
        if parsed.status == 'needs_clarification' or report['complete']: return None
        return ('Coverage is incomplete. Within the REMAINING budget, prioritize unattempted papers and '
                'requested facts over further detail on covered items. Use targeted document/table/figure '
                'lookup. If no useful path remains, report missing honestly; never invent a verified item. '
                'Return the full result with one coverage entry per requirement.\n'+json.dumps(report, ensure_ascii=False))
    return check
