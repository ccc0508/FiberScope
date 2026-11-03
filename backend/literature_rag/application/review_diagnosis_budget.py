"""Bound edits with supplement-first commitment; same prompt as the binding baseline."""
from .review_diagnosis_bound import (
    DiagnosticPayload, DIAGNOSTIC_PROMPT, parse_response, critical_claim_indexes,
    validate_edit_target, inspect_diagnosis, validate_diagnosis,
)

VERSION = 'bounded-corrective-review-v2.3-budget'
prioritize_supplement = True
