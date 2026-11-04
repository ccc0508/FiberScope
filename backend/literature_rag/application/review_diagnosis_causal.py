"""Bounded multi-outcome/chain audit using complete sentences already in evidence."""
import re
from typing import Literal
from pydantic import Field, PrivateAttr
from . import review_diagnosis_comparison as comparison
from . import review_diagnosis_relation_compact as compact
from . import review_diagnosis_relation as relation
from .evidence_review import StrictModel, NonBlank, ReviewRejected

VERSION='bounded-corrective-review-v2.7-causal'
prioritize_supplement=True
is_relation=compact.is_relation
critical_claim_indexes=compact.critical_claim_indexes
comparison_claim_indexes=comparison.comparison_claim_indexes
validate_edit_target=comparison.validate_edit_target
LIMIT=3


def risk(text):
    causal=re.search(r'导致|引起|使得|使[^。！？;；\n]{0,30}(?:提高|降低)|因(?!此)[^。！？;；\n]{0,80}而|有助于|归因|源于|\b(?:causes?|because|leads? to|due to|results? in)\b',text,re.I)
    if not causal:return False
    tail=text[causal.start():]
    return bool(re.search(r'、|以及|和|及|\band\b|,',tail,re.I) or
                re.search(r'进而|从而|进一步|因此|\b(?:thereby|then|in turn)\b',tail,re.I))


def targets(draft):
    all_ids=[i for i,c in enumerate(draft.claims) if risk(c.text)]
    return dict(selected=all_ids[:LIMIT],unchecked=all_ids[LIMIT:])


def sentence_spans(text):
    # Never split decimal points; only punctuation-ended spans are candidates, not dangling tails.
    start=0
    for m in re.finditer(r'[。！？!?]|(?<!\d)\.(?=\s|$)|(?<=\d)\.(?=\s|$)',text):
        a=start;b=m.end();start=b
        while a<b and text[a].isspace():a+=1
        if b-a<=1800 and b>a:yield a,b


class Outcome(StrictModel):
    effect: NonBlank
    supported: bool


class RelationCheck(compact.RelationCheck):
    sentence_start: int | None = Field(default=None,ge=0)
    sentence_end: int | None = Field(default=None,ge=0)
    outcomes: list[Outcome] = Field(default_factory=list,max_length=6)


class BasePayload(compact.DiagnosticPayload):
    relation_checks: list[RelationCheck] = Field(max_length=64)


class DiagnosticPayload(comparison.DiagnosticPayload):
    relation_checks: list[RelationCheck] = Field(max_length=64)
    _relation_target_repairs: list[dict] = PrivateAttr(default_factory=list)


DIAGNOSTIC_PROMPT=comparison.DIAGNOSTIC_PROMPT+'''
Bounded detailed causal audit: only multi-outcome causes and multi-step causal chains need extra fields.
The input causal_detail_targets selects at most 3 original claims; unchecked are NOT certified.
For each selected original and up to 3 risky proposed replacement claims, use a COMPLETE punctuation-ended
source sentence, not a supporting fragment. Source text is already provided: do not repeat it in full.
Set sentence_start/sentence_end to its zero-based character offsets in that source evidence text;
use supplied causal_sentence_locations where available. Keep source_quote as a short span INSIDE it.
Return outcomes:[{"effect":"one result asserted by the answer","supported":true}] for EVERY asserted
result (max 6). Check whether the full sentence supports each arrow, its direction, conditions and certainty.
Parallel explanatory factors must not become separate caused outcomes. If any arrow is unsupported,
verdict cannot be supported; link a minimal edit preserving valid results and the author's explanation.
Do not weaken a source that directly supports multiple results. An unchanged correct causal sentence needs
no edit. If the complete source sentence is unavailable or more results exceed the limit, leave the check
incomplete rather than fabricate context. All existing original-text, citation and comparison rules apply.
For non-selected ordinary relation checks omit these extra fields. No extra retrieval or model call.
Relation target IDs are mutually exclusive. All indexes are zero-based.
Original claim 6 repaired by issue 2: claim_index=6, issue_index=null, replacement_index=null,
repair_issue_indexes=[2]. NEVER copy 2 into issue_index in this original check.
Checking the first replacement in issue 2: claim_index=null, issue_index=2, replacement_index=0,
repair_issue_indexes=[]. These are TWO separate records, even when they quote the same source.
Before returning, verify every original check has null issue_index AND null replacement_index;
every replacement check has null claim_index AND empty repair_issue_indexes.
'''


def prepare_payload(payload,draft,evidences):
    # Remove only a redundant, independently bound pointer. Never guess the target or verdict.
    for n,check in enumerate(payload.relation_checks):
        ci,ii=check.claim_index,check.issue_index
        if (ci is None or ii is None or check.replacement_index is not None
            or ci>=len(draft.claims) or ii>=len(payload.issues)
            or check.verdict=='supported' or check.repair_issue_indexes!=[ii]):
            continue
        issue=payload.issues[ii]
        if issue.claim_index!=ci or issue.original_text!=draft.claims[ci].text:
            continue
        candidate=check.model_copy(update={'issue_index':None})
        if not relation._valid(candidate,payload,draft,evidences):
            continue
        payload._relation_target_repairs.append(dict(index=n,
            reason_code='redundant_original_issue_index',before=check.model_dump(),after=candidate.model_dump()))
        payload.relation_checks[n]=candidate
    comparison.prepare_payload(payload,draft,evidences)


def request_context(draft,evidences):
    selected=targets(draft);refs={r for i in selected['selected'] for r in draft.claims[i].citation_refs}
    locations=[]
    for e in evidences:
        if e.ref not in refs:continue
        for a,b in sentence_spans(e.text):
            if is_relation(e.text[a:b]):locations.append(dict(ref=e.ref,start=a,end=b))
    return dict(causal_detail_targets=selected,causal_sentence_locations=locations[:48])


def parse_response(content):
    return comparison.parse_with(content,lambda s:relation.parse_checks(s,RelationCheck,BasePayload),DiagnosticPayload)


def detail_valid(c,evidences):
    e=next((e for e in evidences if e.ref==c.source_ref),None)
    return bool(e and (c.sentence_start,c.sentence_end) in set(sentence_spans(e.text)) and c.outcomes
        and c.source_quote in e.text[c.sentence_start:c.sentence_end]
        and (c.verdict!='supported' or all(o.supported for o in c.outcomes)))


def validate_edit_semantics(payload,index,draft,evidences):
    comparison.validate_edit_semantics(payload,index,draft,evidences)
    if index in payload._citation_repairs:return
    risky=[(i,j) for i,issue in enumerate(payload.issues) for j,c in enumerate(issue.replacement_claims) if risk(c.text)]
    for j,c in enumerate(payload.issues[index].replacement_claims):
        if not risk(c.text):continue
        checks=[x for x in payload.relation_checks if x.issue_index==index and x.replacement_index==j]
        if (index,j) not in risky[:LIMIT] or not checks or any(not detail_valid(x,evidences) for x in checks):
            raise ReviewRejected('causal_replacement_detail_incomplete')


def inspect_diagnosis(payload,draft,evidences,context=None):
    audit=relation.inspect_diagnosis(payload,draft,evidences,context,edit_validator=validate_edit_semantics)
    audit['errors'].extend(payload._comparison_errors)
    selection=targets(draft)
    for i in selection['selected']:
        checks=[c for c in payload.relation_checks if c.claim_index==i]
        if not checks or any(not detail_valid(c,evidences) for c in checks):
            audit['errors'].append(dict(component='causal_detail',claim_index=i,reason_code='complete_sentence_or_outcomes_missing'))
    if selection['unchecked']:
        audit['errors'].append(dict(component='causal_detail',claim_indexes=selection['unchecked'],reason_code='detail_budget_unchecked'))
    audit['valid']=not audit['errors']
    return audit
