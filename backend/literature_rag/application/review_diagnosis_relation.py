"""Bounded relation audit: program checks coverage/provenance, model judges meaning."""
import json
import re
from typing import Literal
from pydantic import Field, ValidationError
from . import review_diagnosis_bound as bound
from . import review_diagnosis_v2 as prior
from .evidence_review import StrictModel, NonBlank, Ref, ReviewRejected, normalized_quote

VERSION = 'bounded-corrective-review-v2.4-relation'
prioritize_supplement = True


def is_relation(text):
    return bool(re.search(r'因为|由于|归因|源于|导致|使得|使.{0,40}(?:提高|降低|增加|减少|变化|增强)|'
        r'因.{1,80}而|有助于|有利于|促进|抑制|决定|相关|关系|解释|机制|机理|'
        r'\b(?:caus\w*|because|due to|lead\w* to|result\w* (?:in|from)|correlat\w*|'
        r'associat\w*|explain\w*|contribut\w*|promot\w*|inhibit\w*|mechanism\w*)\b',text,re.I))


critical_claim_indexes = prior.critical_claim_indexes


class RelationCheck(StrictModel):
    claim_index: int | None = Field(ge=0)
    issue_index: int | None = Field(ge=0)
    replacement_index: int | None = Field(ge=0)
    source_ref: Ref
    source_quote: str = Field(min_length=8,max_length=800)
    source_cause: NonBlank
    source_effect: NonBlank
    answer_cause: NonBlank
    answer_effect: NonBlank
    source_relation: Literal['causal','association','proposed_explanation','parallel_factors','no_relation','unclear']
    answer_relation: Literal['causal','association','proposed_explanation','parallel_factors','no_relation','unclear']
    conditions_and_certainty: NonBlank
    verdict: Literal['supported','overstated','unclear']
    reason: NonBlank
    repair_issue_indexes: list[int] = Field(max_length=8)


class DiagnosticPayload(prior.DiagnosticPayload):
    relation_checks: list[RelationCheck] = Field(max_length=64)


DIAGNOSTIC_PROMPT = bound.DIAGNOSTIC_PROMPT + '''
Relation audit: the input lists relation_claim_indexes as a coverage aid, not a verdict.
Check EVERY listed original claim and other implicit relations you identify. Also check EVERY proposed
replacement/append expressing a relation. Negated causation and cautiously worded explanations also
need checking, but do not weaken a directly supported relation or edit a correct sentence merely for style.
For each compare actual cause, effect, direction, relation type, conditions and certainty against a short
verbatim source span. Noun overlap is insufficient. Parallel explanatory factors are not a causal chain;
correlation is not causation; an author's explanation is not automatically an experimental demonstration.
Retain supported causal claims and necessary explanations. Repair only the specific unsupported relation.
Do not invent causes when the source describes association; use 'not stated' where appropriate.
Return relation_checks alongside issues, requirements and claim_checks. Shape:
{"claim_index":0,"issue_index":null,"replacement_index":null,"source_ref":"[1]",
"source_quote":"verbatim span","source_cause":"source factor(s)","source_effect":"source outcome",
"answer_cause":"answer factor(s)","answer_effect":"answer outcome",
"source_relation":"causal|association|proposed_explanation|parallel_factors|no_relation|unclear",
"answer_relation":"causal|association|proposed_explanation|parallel_factors|no_relation|unclear",
"conditions_and_certainty":"brief Chinese comparison","verdict":"supported|overstated|unclear",
"reason":"brief Chinese source-grounded judgment","repair_issue_indexes":[]}
Original checks use claim_index and null issue_index/replacement_index. If overstated/unclear, link
repair_issue_indexes to an issue targeting THAT original claim, including its original_text.
Replacement checks use claim_index:null and the proposed issue_index/replacement_index; repair_issue_indexes
must be empty. A replacement must be supported or that edit cannot be applied. No rewriting unrelated claims.
At most 64 checks. If limits prevent complete checking, do not claim completion. This is fallible model
judgment; there is no external rubric or reference answer. Do not add unrelated measurement exposition.
'''


def parse_response(content):
    return parse_checks(content, RelationCheck, DiagnosticPayload)


def parse_checks(content, check_type, payload_type):
    raw=json.loads(content)
    if not isinstance(raw,dict):raise ValueError('invalid_review_envelope')
    checks=raw.pop('relation_checks',None)
    old=prior.parse_response(json.dumps(raw,ensure_ascii=False));errors=list(old._parse_errors);valid=[]
    if not isinstance(checks,list) or len(checks)>64:
        errors.append(dict(component='relation_checks',reason_code='invalid_relation_list'))
    else:
        for i,c in enumerate(checks):
            try:valid.append(check_type.model_validate(c))
            except ValidationError:errors.append(dict(component='relation_checks',index=i,reason_code='invalid_relation_item'))
    result=payload_type.model_construct(issues=old.issues,requirements=old.requirements,
        claim_checks=old.claim_checks,relation_checks=valid)
    result._parse_errors=errors
    return result


def _valid(c,payload,draft,evidences):
    refs={e.ref:e for e in evidences}
    if c.source_ref not in refs or normalized_quote(c.source_quote) not in normalized_quote(refs[c.source_ref].text):return False
    if len(normalized_quote(c.source_quote))<8:return False
    if c.claim_index is not None:
        if c.issue_index is not None or c.replacement_index is not None or c.claim_index>=len(draft.claims):return False
        if c.verdict=='supported':return not c.repair_issue_indexes
        return bool(c.repair_issue_indexes) and all(0<=i<len(payload.issues) and payload.issues[i].claim_index==c.claim_index for i in c.repair_issue_indexes)
    if c.issue_index is None or c.replacement_index is None or c.repair_issue_indexes:return False
    if c.issue_index>=len(payload.issues):return False
    replacements=payload.issues[c.issue_index].replacement_claims
    return c.replacement_index<len(replacements) and c.source_ref in replacements[c.replacement_index].citation_refs


def validate_edit_target(payload,index,draft):
    bound.validate_edit_target(payload,index,draft)


def validate_edit_semantics(payload,index,draft,evidences):
    for j,claim in enumerate(payload.issues[index].replacement_claims):
        checks=[c for c in payload.relation_checks if c.issue_index==index and c.replacement_index==j]
        if not is_relation(claim.text) and not checks:continue
        if not checks or any(c.verdict!='supported' or not _valid(c,payload,draft,evidences) for c in checks):
            raise ReviewRejected('replacement_relation_not_verified')


def inspect_diagnosis(payload,draft,evidences,context=None,*,edit_validator=None):
    audit=bound.inspect_diagnosis(payload,draft,evidences,context)
    checked=set()
    for i,c in enumerate(payload.relation_checks):
        if not _valid(c,payload,draft,evidences):
            audit['errors'].append(dict(component='relation_checks',index=i,reason_code='invalid_relation_source_or_target'))
        elif c.claim_index is not None:checked.add(c.claim_index)
    missing=[i for i,c in enumerate(draft.claims) if is_relation(c.text) and i not in checked]
    if missing:audit['errors'].append(dict(component='relation_checks',reason_code='original_relation_check_missing',claim_indexes=missing))
    for i in range(len(payload.issues)):
        try:(edit_validator or validate_edit_semantics)(payload,i,draft,evidences)
        except ReviewRejected as e:audit['errors'].append(dict(component='relation_checks',issue_index=i,reason_code=e.code))
    audit['valid']=not audit['errors']
    return audit


def validate_diagnosis(payload,draft,evidences,context=None):
    audit=inspect_diagnosis(payload,draft,evidences,context)
    if audit['errors']:raise ReviewRejected(audit['errors'][0]['reason_code'])
