"""Experimental minimal revision checks; same-call self-checks are not a semantic guarantee."""
import json
from typing import Literal

from pydantic import Field, ValidationError

from . import review_diagnosis_v2 as prior
from .evidence_review import NonBlank, ReviewRejected, StrictModel

VERSION = 'bounded-corrective-review-v3-minimal'
critical_claim_indexes = prior.critical_claim_indexes


class RevisionCheck(StrictModel):
    issue_index: int = Field(ge=0)
    verdict: Literal['supported', 'overstated', 'unclear']
    reason: NonBlank


class DiagnosticPayload(prior.DiagnosticPayload):
    revision_checks: list[RevisionCheck] = Field(max_length=8)


DIAGNOSTIC_PROMPT = prior.DIAGNOSTIC_PROMPT + '''
Minimal-revision policy (applies to both review rounds):
Measurement boundaries: when the question asks what a measured quantity means, or draws a conclusion
about amount/structure/performance, explicitly check whether the answer separates the actual measured
variable (absolute quantity, normalized fraction, or indirect proxy) from the inferred variable.
Merely naming a ratio does not explain a necessary limit on interpreting it. If this distinction is
material and supported by the supplied method, express it in the answer; otherwise request the narrow
missing method or leave it undetermined. Do not attach generic limitations to unrelated questions.
Comparisons: 'most', 'main', 'strongest', 'more direct' and equivalent Chinese wording require evidence
actually comparing those factors under matching conditions. A correlation or explanatory discussion
does not establish that ranking. Remove an unnecessary unsupported ranking, or explicitly state that
the requested ranking is not established by the supplied excerpts.
Minimal changes: preserve every unaffected proposition, condition and citation within an edited claim.
Do not add a new mechanistic explanation to repair a wording/coverage defect. Add only the missing
qualification or directly supported requested content. Deleting an unsupported extra is acceptable.
Before submitting issues, compare EACH proposed replacement against both the ORIGINAL draft and its
source basis. Check every newly added/changed proposition: subject/object, direction, certainty,
measurement interpretation and comparison scope. Preserve parallel explanatory factors as parallel;
do not turn them into a sequence where one causes the others. A source quote containing the same nouns
is not evidence for a newly asserted causal link. If a proposal strengthens the source, revise it to
a smaller supported edit before submission; otherwise mark it overstated/unclear to block that edit.
Return revision_checks alongside issues, requirements and claim_checks:
"revision_checks":[{"issue_index":0,"verdict":"supported|overstated|unclear",
"reason":"brief Chinese source-based comparison of the original and proposed propositions"}]
Exactly one check per issue (including deletions/appends); [] when issues is empty. Checks address the
PROPOSED replacement; claim_checks still address the ORIGINAL draft. These are fallible self-checks,
not proof or an independent second judge. Never output an evaluation score or a model answer rubric.
'''


def parse_response(content):
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise ValueError('invalid_review_envelope')
    values = raw.pop('revision_checks', None)
    old = prior.parse_response(json.dumps(raw, ensure_ascii=False))
    errors = list(old._parse_errors)
    checks = []
    if not isinstance(values, list) or len(values) > 8:
        errors.append(dict(component='revision_checks', reason_code='invalid_revision_checks'))
    else:
        for index, value in enumerate(values):
            try:
                checks.append(RevisionCheck.model_validate(value))
            except ValidationError:
                errors.append(dict(component='revision_checks', index=index, reason_code='invalid_revision_check'))
    result = DiagnosticPayload.model_construct(issues=old.issues, requirements=old.requirements,
        claim_checks=old.claim_checks, revision_checks=checks)
    result._parse_errors = errors
    return result


def validate_revision(payload, index):
    checks = [c for c in payload.revision_checks if c.issue_index == index]
    if len(checks) != 1:
        raise ReviewRejected('missing_or_duplicate_revision_check')
    if checks[0].verdict != 'supported':
        raise ReviewRejected('revision_not_supported')


def inspect_diagnosis(payload, draft, evidences, context=None):
    audit = prior.inspect_diagnosis(payload, draft, evidences, context)
    for i in range(len(payload.issues)):
        try:
            validate_revision(payload, i)
        except ReviewRejected as error:
            audit['errors'].append(dict(component='revision_checks', issue_index=i, reason_code=error.code))
    if any(c.issue_index >= len(payload.issues) for c in payload.revision_checks):
        audit['errors'].append(dict(component='revision_checks', reason_code='unknown_revision_issue'))
    audit['valid'] = not audit['errors']
    return audit


def validate_diagnosis(payload, draft, evidences, context=None):
    audit = inspect_diagnosis(payload, draft, evidences, context)
    if audit['errors']:
        raise ReviewRejected(audit['errors'][0]['reason_code'])
