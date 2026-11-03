"""Question-derived coverage diagnosis. Evaluation answers never enter this contract."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from literature_rag.application.evidence_review import (
    NonBlank, Ref, ReviewPayload, ReviewRejected, StrictModel, SYSTEM_PROMPT,
)

VERSION = 'bounded-corrective-review-v1'
Identifier = Annotated[str, StringConstraints(pattern=r'^R[1-9][0-9]?$')]


class Lookup(StrictModel):
    query: NonBlank
    document_ref: Ref
    target: Literal['candidates', 'abstract', 'methods', 'results', 'table', 'figure', 'section']
    # Optional literal heading/table label, never a guessed chunk ID.
    locator: Annotated[str, StringConstraints(max_length=160)] = ''


class Requirement(StrictModel):
    id: Identifier
    requirement: NonBlank
    status: Literal['covered', 'edit', 'lookup', 'unresolved']
    evidence_refs: list[Ref] = Field(max_length=8)
    claim_indexes: list[Annotated[int, Field(ge=0)]] = Field(max_length=16)
    issue_indexes: list[Annotated[int, Field(ge=0)]] = Field(max_length=8)
    reason: NonBlank
    lookup: Lookup | None = None

    @model_validator(mode='after')
    def coherent_action(self):
        if (self.status == 'lookup') != (self.lookup is not None):
            raise ValueError('Only a lookup diagnosis requires a lookup action')
        if self.status == 'covered' and (not self.evidence_refs or not self.claim_indexes):
            raise ValueError('Covered requires evidence and answer locations')
        if self.status == 'edit' and not self.issue_indexes:
            raise ValueError('An edit diagnosis must identify proposed edits')
        if self.status in {'covered', 'unresolved'} and self.issue_indexes:
            raise ValueError('Covered/unresolved cannot report an unapplied edit')
        return self


class DiagnosticPayload(ReviewPayload):
    requirements: list[Requirement] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError('Duplicate requirement ID')
        return self


DIAGNOSTIC_PROMPT = SYSTEM_PROMPT.replace(
    'If no material defect is established, return exactly {"issues": []}; do not improve style for its own sake.',
    'Do not improve style for its own sake. Always return the coverage requirements described below.',
) + '''
In addition to issues, return requirements (1-16 items) in the SAME JSON object.
Derive requirements ONLY from the user's question and interpretation limits necessary to answer it.
Do not assume a hidden rubric. Check each requested comparison, explanation, number and limitation,
and material extra assertions in the draft. A correct measurement description can still omit what the
measurement does NOT establish. Distinguish interactions BETWEEN molecules from breakage WITHIN a
molecule; do not silently strengthen a statement about one structural level into another.
For each requirement map actual evidence refs and original zero-based claim indexes, then choose:
covered: supplied evidence supports the answer including necessary limits; no material edit.
edit: evidence already suffices, but the answer misuses it or omits a necessary qualification; provide
minimal anchored issues and their zero-based issue_indexes. Do not retrieve to fix a writing defect.
lookup: specific information is absent or ambiguous in CURRENT EXCERPTS; explain exactly why it is
needed and propose one narrow query and a source target in a paper already supplied.
unresolved: no justified actionable lookup, conflicting/unreadable evidence, or exhausted actions.
Missing excerpts never prove absence in an entire paper. Do not invent a missing number to search for.
A requirement may need both an immediate safe edit and lookup: use lookup plus issue_indexes.
When checking a reported numerical relationship, consider whether the abstract and results need to
be compared, but only request a missing region if necessary for the user's question, not routinely.
Each lookup uses document_ref of an existing evidence item to scope ONE paper. target is candidates
(gap-specific search), abstract, methods, results, table, figure, or section. locator is a literal
heading/label already known, or empty; never guess an ID. No web search, new paper, or recursive plan.
At most TWO requirements may request lookup. Mark further gaps unresolved with an explicit reason.
The second review receives a prior coverage ledger. Preserve all prior requirement IDs and requested
meanings; reevaluate using the augmented excerpts. No more lookup is allowed: remaining gaps must be
unresolved. New evidence being retrieved does NOT mean it resolves a gap; check material, conditions,
measurement and contradictions. If still unsupported, bound the answer to the provided excerpts.
Required additional shape:
"requirements":[{"id":"R1","requirement":"part of the user question",
"status":"covered|edit|lookup|unresolved","evidence_refs":["[1]"],"claim_indexes":[0],
"issue_indexes":[],"reason":"short evidence/answer coverage diagnosis in Chinese",
"lookup":null}]
For lookup replace null with {"query":"specific missing information, no invented answer",
"document_ref":"[1]","target":"methods","locator":""}.
Return issues plus requirements even when issues is empty. No scores or hidden reasoning.
'''


def validate_diagnosis(payload, draft, evidences, context=None):
    refs = {e.ref for e in evidences}
    for r in payload.requirements:
        if (not set(r.evidence_refs) <= refs or any(i >= len(draft.claims) for i in r.claim_indexes)
                or any(i >= len(payload.issues) for i in r.issue_indexes)
                or (r.lookup and r.lookup.document_ref not in refs)):
            raise ReviewRejected('invalid_diagnosis_locations')
    if sum(r.status == 'lookup' for r in payload.requirements) > 2:
        raise ReviewRejected('too_many_lookup_requests')
    linked = {i for r in payload.requirements for i in r.issue_indexes}
    if linked != set(range(len(payload.issues))):
        raise ReviewRejected('unmapped_diagnostic_edits')
    if context:
        expected = {r['id']: r['requirement'] for r in context['requirements']}
        actual = {r.id: r.requirement for r in payload.requirements}
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ReviewRejected('lost_prior_requirement')
        if any(r.status == 'lookup' for r in payload.requirements):
            raise ReviewRejected('second_review_cannot_request_lookup')


def diagnosis_contract(version='v1'):
    """Keep the previously shipped protocol as default; v2 is an opt-in experiment."""
    if version=='v1':
        import sys
        return sys.modules[__name__]
    if version=='v2':
        from . import review_diagnosis_v2
        return review_diagnosis_v2
    if version=='v3':
        from . import review_diagnosis_v3
        return review_diagnosis_v3
    if version=='v2_bound':
        from . import review_diagnosis_bound
        return review_diagnosis_bound
    if version=='v2_budget':
        from . import review_diagnosis_budget
        return review_diagnosis_budget
    if version=='v2_relation_compact':
        from . import review_diagnosis_relation_compact
        return review_diagnosis_relation_compact
    if version=='v2_relation':
        from . import review_diagnosis_relation
        return review_diagnosis_relation
    raise ValueError('Unknown corrective review version')
