"""Question-derived coverage diagnosis. Evaluation answers never enter this contract."""
from typing import Annotated, Literal
import re

from pydantic import Field, StringConstraints, model_validator

from literature_rag.application.evidence_review import (
    NonBlank, Ref, ReviewPayload, ReviewRejected, StrictModel, SYSTEM_PROMPT, normalized_quote,
)

VERSION = 'bounded-corrective-review-v2'
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


def critical_claim_indexes(draft):
    pattern=r'断裂|破坏|裂解|解聚|cleavage|break|scission|degrad|because|由于|归因|源于|导致|caus|机制|机理'
    return [i for i,c in enumerate(draft.claims) if re.search(pattern,c.text,re.I)][:8]


class ClaimCheck(StrictModel):
    claim_index: int = Field(ge=0)
    source_ref: Ref
    source_quote: Annotated[str, StringConstraints(min_length=8,max_length=800)]
    source_object: NonBlank
    answer_object: NonBlank
    source_change: NonBlank
    answer_change: NonBlank
    source_certainty: NonBlank
    answer_certainty: NonBlank
    verdict: Literal['supported','overstated','unclear']
    issue_indexes: list[Annotated[int,Field(ge=0)]] = Field(max_length=8)


class DiagnosticPayload(ReviewPayload):
    requirements: list[Requirement] = Field(min_length=1, max_length=32)
    claim_checks: list[ClaimCheck] = Field(max_length=12)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError('Duplicate requirement ID')
        return self


DIAGNOSTIC_PROMPT = SYSTEM_PROMPT.replace(
    'If no material defect is established, return exactly {"issues": []}; do not improve style for its own sake.',
    'Do not improve style for its own sake. Always return the coverage requirements described below.',
) + '''
In addition to issues, return requirements (1-24 items) in the SAME JSON object.
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

Also return claim_checks (up to 12): concise source/answer comparisons, NOT hidden reasoning.
The input lists critical_claim_indexes. Check EVERY listed original claim, and any other important
mechanism/causal assertion that appears unsafe. For each, quote an actual supplied source and compare
its OBJECT/STRUCTURAL LEVEL, CHANGE and CERTAINTY against the draft separately.
Intermolecular/interchain connections are not intramolecular/backbone bonds. Prepositions such as
between/among do not establish cleavage within a molecule. Adding 'possibly' does NOT fix a wrong
object or a stronger structural change. Unless the supplied source explicitly establishes that
stronger change, narrow the wording to what it supports, or explicitly leave it undetermined.
An ambiguous source is not permission for a more specific translation. Mark such a draft overstated
or unclear and supply a minimal edit rather than declaring it supported just because words overlap.
Every overstated/unclear check must link to an issue (and a requirement). Supported checks have no edits.
Required shape, empty only when there are no critical assertions to inspect:
"claim_checks":[{"claim_index":0,"source_ref":"[1]","source_quote":"short verbatim quote",
"source_object":"object/level in source","answer_object":"object/level in draft",
"source_change":"change actually described","answer_change":"change claimed",
"source_certainty":"observed/proposed/uncertain","answer_certainty":"certainty claimed",
"verdict":"supported|overstated|unclear","issue_indexes":[]}]
If a prior ledger includes a program-requested abstract/results cross-check, compare each relevant
number with its material, variable pair, conditions and statistic. Distinct contexts are not conflicts.
For a true disagreement cite each source and both values separately; do not choose, average or silently
reconcile them. If one region lacks the number, say the check did not establish a contradiction.
'''


def validate_diagnosis(payload, draft, evidences, context=None):
    if not context and len(payload.requirements)>24:
        raise ReviewRejected('too_many_initial_requirements')
    refs = {e.ref for e in evidences}
    by_ref={e.ref:e for e in evidences}
    checked=set()
    for c in payload.claim_checks:
        if c.claim_index>=len(draft.claims) or c.claim_index in checked or c.source_ref not in refs:
            raise ReviewRejected('invalid_claim_check_location')
        checked.add(c.claim_index)
        quote=normalized_quote(c.source_quote)
        if len(quote)<8 or quote not in normalized_quote(by_ref[c.source_ref].text):
            raise ReviewRejected('claim_check_quote_not_in_evidence')
        if any(i>=len(payload.issues) for i in c.issue_indexes):
            raise ReviewRejected('invalid_claim_check_edit')
        if any(payload.issues[i].claim_index not in (None,c.claim_index) for i in c.issue_indexes):
            raise ReviewRejected('claim_check_edit_targets_different_claim')
        if (c.verdict=='supported') != (not c.issue_indexes):
            raise ReviewRejected('claim_check_needs_matching_action')
    if not set(critical_claim_indexes(draft))<=checked:
        raise ReviewRejected('critical_claim_check_missing')
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
