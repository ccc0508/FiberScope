"""Same relation checks and gates, shorter emitted records; opt-in experiment."""
from typing import Annotated, Literal
from pydantic import Field, StringConstraints
from . import review_diagnosis_relation as prior
from .evidence_review import StrictModel, Ref

VERSION = 'bounded-corrective-review-v2.5-relation-compact'
prioritize_supplement = prior.prioritize_supplement
is_relation = prior.is_relation
critical_claim_indexes = prior.critical_claim_indexes
validate_edit_target = prior.validate_edit_target
validate_edit_semantics = prior.validate_edit_semantics
inspect_diagnosis = prior.inspect_diagnosis
validate_diagnosis = prior.validate_diagnosis


class RelationCheck(StrictModel):
    claim_index: int | None = Field(ge=0)
    issue_index: int | None = Field(ge=0)
    replacement_index: int | None = Field(ge=0)
    source_ref: Ref
    source_quote: str = Field(min_length=8, max_length=800)
    verdict: Literal['supported', 'overstated', 'unclear']
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    repair_issue_indexes: list[int] = Field(max_length=8)


class DiagnosticPayload(prior.prior.DiagnosticPayload):
    relation_checks: list[RelationCheck] = Field(max_length=64)


_START = 'Return relation_checks alongside issues, requirements and claim_checks. Shape:\n'
_END = 'Original checks use claim_index and null issue_index/replacement_index.'
_before, _shape = prior.DIAGNOSTIC_PROMPT.split(_START)
_, _after = _shape.split(_END)
DIAGNOSTIC_PROMPT = _before + _START + '''
{"claim_index":0,"issue_index":null,"replacement_index":null,"source_ref":"[1]",
"source_quote":"verbatim short span","verdict":"supported|overstated|unclear",
"reason":"one brief source-grounded comparison, at most 200 characters","repair_issue_indexes":[]}
Keep the SAME cause/effect, direction, relation type, conditions and certainty checks required above,
but do not emit separate source_cause/source_effect/answer_cause/answer_effect, relation-type or
conditions_and_certainty fields. Summarize only the decisive agreement or mismatch in reason; avoid
repeating the draft and source. For supported relations, a brief agreement is enough. Do not omit any
required original or replacement check. Keep issues, original_text, requirements and claim_checks unchanged.
''' + _END + _after


def parse_response(content):
    return prior.parse_checks(content, RelationCheck, DiagnosticPayload)
