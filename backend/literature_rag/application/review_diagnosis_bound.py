"""v2.1 plus exact original-claim binding; no v3 semantic policy or extra calls."""
from . import review_diagnosis_v2 as prior
from .evidence_review import ReviewRejected

VERSION = 'bounded-corrective-review-v2.2-bound'
DiagnosticPayload = prior.DiagnosticPayload
parse_response = prior.parse_response
critical_claim_indexes = prior.critical_claim_indexes

# Update the primary example itself, rather than contradicting it with an addendum.
_OLD_ISSUE_START = '{"issues": [{"claim_index": 0, "category":'
_BOUND_ISSUE_START = ('{"issues": [{"claim_index": 0, '
    '"original_text": "exact complete text of input draft claim 0", "category":')
if prior.DIAGNOSTIC_PROMPT.count(_OLD_ISSUE_START) != 1:
    raise RuntimeError('Review issue example changed; update the bound output contract')

DIAGNOSTIC_PROMPT = prior.DIAGNOSTIC_PROMPT.replace(
    _OLD_ISSUE_START, _BOUND_ISSUE_START,
).replace(
    'For issues return ONLY this JSON structure (max 8 issues):',
    'The issues field uses this JSON structure (max 8 issues); also include the diagnostic fields below:',
) + '''
Edit target binding is mandatory for EVERY issue:
For replacement, splitting or deletion, include "original_text": the EXACT complete text field of the
claim at claim_index in THIS request's draft (zero-based). Copy it verbatim, including punctuation,
spaces, numbers and spelling; do not add citation tokens from citation_refs. Never paraphrase it.
For a genuinely missing part appended with claim_index:null, include "original_text":null.
All indexes refer to the input draft, never to intermediate replacements or a previous review round.
When a claim_check links an issue, it must point to that same original claim, unless the issue appends
a genuinely missing part. Conflicting indexes or a missing/mismatched original_text reject that edit.
Example target fields: "claim_index":0,"original_text":"exact text of the first input claim".
For deletion, keep both target fields and set replacement_claims to []. For splitting, keep both
target fields and put all replacement sentences in that issue's replacement_claims.
For append, the target fields are exactly "claim_index":null,"original_text":null.
Before returning JSON, check EVERY issues item contains original_text (including explicit null for
append), and every non-null original_text exactly matches the indexed input claim. Do not output this
format checklist or invent an issue when none is needed. Never omit the field to save tokens.
An unchanged claim needs no issue. Keep all existing source-basis and citation requirements.
'''


def validate_edit_target(payload, issue_index, draft):
    issue = payload.issues[issue_index]
    if 'original_text' not in issue.model_fields_set:
        raise ReviewRejected('original_text_missing')
    if issue.claim_index is None:
        if issue.original_text is not None:
            raise ReviewRejected('append_original_text_must_be_null')
        return
    if issue.claim_index >= len(draft.claims):
        raise ReviewRejected('invalid_bound_claim_index')
    if issue.original_text != draft.claims[issue.claim_index].text:
        raise ReviewRejected('original_text_mismatch')
    # A diagnostic contradiction is a reason to block this edit even if its quote
    # has an unrelated validation error. Never use it to retarget the edit.
    if any(issue_index in c.issue_indexes and c.claim_index != issue.claim_index
           for c in payload.claim_checks):
        raise ReviewRejected('claim_check_edit_target_conflict')


def inspect_diagnosis(payload, draft, evidences, context=None):
    audit = prior.inspect_diagnosis(payload, draft, evidences, context)
    for index in range(len(payload.issues)):
        try:
            validate_edit_target(payload, index, draft)
        except ReviewRejected as error:
            audit['errors'].append(dict(component='edit_binding',issue_index=index,reason_code=error.code))
    audit['valid'] = not audit['errors']
    return audit


def validate_diagnosis(payload, draft, evidences, context=None):
    audit = inspect_diagnosis(payload, draft, evidences, context)
    if audit['errors']:
        raise ReviewRejected(audit['errors'][0]['reason_code'])
