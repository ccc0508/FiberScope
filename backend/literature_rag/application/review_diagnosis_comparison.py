"""Source mappings for comparative claims; only verified citation additions are automatic."""
import json
import re
from typing import Literal
from pydantic import Field, PrivateAttr, ValidationError
from . import review_diagnosis_relation_compact as prior
from . import review_diagnosis_relation as relation
from .review_diagnosis_v2 import Requirement
from .evidence_review import StrictModel, NonBlank, Ref, Issue, Claim, Basis, normalized_quote

VERSION='bounded-corrective-review-v2.6-comparison'
prioritize_supplement=True
is_relation=prior.is_relation
critical_claim_indexes=prior.critical_claim_indexes
validate_edit_target=prior.validate_edit_target


def comparison_claim_indexes(draft):
    return [i for i,c in enumerate(draft.claims) if re.search(
        r'不一致|冲突|矛盾|相比|相较|高于|低于|不同|而摘要|而正文|inconsisten|conflict|contradict|whereas|compared|higher than|lower than',c.text,re.I)]


class Fact(StrictModel):
    fact: NonBlank
    source_ref: Ref
    source_quote: str = Field(min_length=8,max_length=800)


class Comparison(StrictModel):
    claim_index: int = Field(ge=0)
    original_text: str = Field(min_length=1,max_length=20000)
    comparability: Literal['same_scope','different_scope','unclear','not_comparison']
    statement_supported: bool
    reason: NonBlank
    facts: list[Fact] = Field(max_length=8)


class DiagnosticPayload(prior.DiagnosticPayload):
    comparison_checks: list[Comparison] = Field(max_length=32)
    _citation_repairs: set[int] = PrivateAttr(default_factory=set)
    _comparison_errors: list[dict] = PrivateAttr(default_factory=list)


DIAGNOSTIC_PROMPT=prior.DIAGNOSTIC_PROMPT+'''
Also return comparison_checks. Check every comparison_claim_indexes entry and other cross-source
comparisons you identify. A comparison sentence must cite all sources contributing its factual parts;
a citation on a previous sentence does not transfer. Return each factual part and its actual source.
Confirm material, measured variables, conditions, statistic and scope are comparable before selecting
same_scope. Different numbers alone do NOT establish conflict. Use different_scope or unclear if needed.
Shape: {"claim_index":0,"original_text":"exact input claim text","comparability":"same_scope","statement_supported":true,
"reason":"brief explanation of scope equivalence or mismatch",
"facts":[{"fact":"one factual part","source_ref":"[1]","source_quote":"short verbatim source span"},
{"fact":"other factual part","source_ref":"[2]","source_quote":"short verbatim source span"}]}
statement_supported means ALL mapped facts and the comparison conclusion are supported, not merely comparable.
Allowed comparability: same_scope, different_scope, unclear, not_comparison. For not_comparison use facts:[].
For a correct same_scope statement whose ONLY defect is missing citations, do not propose an issues edit:
the program will add the mapped references after validating the exact original text and all quotations.
Keep semantic defects in issues with original_text and existing required checks. Do not label a false
comparison same_scope just to get citations attached. At most 32 comparison checks; [] if none.
'''


def parse_response(content):
    raw=json.loads(content)
    checks=raw.pop('comparison_checks',None)
    old=prior.parse_response(json.dumps(raw,ensure_ascii=False))
    errors=list(old._parse_errors);valid=[]
    if not isinstance(checks,list) or len(checks)>32:
        errors.append(dict(component='comparison_checks',reason_code='invalid_comparison_list'))
    else:
        for i,c in enumerate(checks):
            try:valid.append(Comparison.model_validate(c))
            except ValidationError as error:
                from .review_diagnostics import validation_details
                errors.append(dict(component='comparison_checks',index=i,reason_code='invalid_comparison_item',fields=validation_details(error)))
    result=DiagnosticPayload.model_construct(issues=old.issues,requirements=old.requirements,
        claim_checks=old.claim_checks,relation_checks=old.relation_checks,comparison_checks=valid)
    result._parse_errors=errors
    return result


def prepare_payload(payload,draft,evidences):
    """No fuzzy target matching, quote repair, text rewrite, or automatic semantic inference."""
    refs={e.ref:e for e in evidences};seen=set();covered=set()
    errors=[]
    counts={c.claim_index:sum(x.claim_index==c.claim_index for x in payload.comparison_checks) for c in payload.comparison_checks}
    for c in payload.comparison_checks:
        index=c.claim_index;code=None
        if counts[index]!=1:code='duplicate_comparison_target'
        elif index>=len(draft.claims) or c.original_text!=draft.claims[index].text:code='comparison_original_mismatch'
        elif c.comparability=='not_comparison':
            if c.facts:code='noncomparison_has_facts'
        elif len(c.facts)<2:code='comparison_sides_missing'
        elif any(f.source_ref not in refs or normalized_quote(f.source_quote) not in normalized_quote(refs[f.source_ref].text)
                 or len(normalized_quote(f.source_quote))<8 for f in c.facts):code='comparison_quote_not_in_source'
        elif c.comparability!='same_scope':code='comparison_scope_unresolved'
        elif not c.statement_supported:code='comparison_statement_unsupported'
        if code:
            errors.append(dict(component='comparison_checks',claim_index=index,reason_code=code));continue
        covered.add(index)
        if c.comparability=='not_comparison':continue
        original=draft.claims[index]
        needed=list(dict.fromkeys(f.source_ref for f in c.facts))
        missing=[r for r in needed if r not in original.citation_refs]
        if not missing:continue
        if any(i.claim_index==index for i in payload.issues):
            errors.append(dict(component='comparison_checks',claim_index=index,reason_code='comparison_has_semantic_edit'));continue
        if len(payload.issues)>=8 or len(payload.requirements)>=(32 if payload.requirements and any(r.id=='R90' for r in payload.requirements) else 24) or len(needed)>6 or len(set(original.citation_refs)|set(needed))>8 or len(original.text)>1200:
            errors.append(dict(component='comparison_checks',claim_index=index,reason_code='comparison_repair_budget'));continue
        # One basis per source; retain every original citation and original text verbatim.
        basis=[]
        for f in c.facts:
            if f.source_ref not in seen:
                basis.append(Basis(kind='text',ref=f.source_ref,quote=f.source_quote));seen.add(f.source_ref)
        seen.clear()
        n=len(payload.issues)
        payload.issues.append(Issue(claim_index=index,original_text=original.text,category='citation',
            problem='比较句缺少已核对事实来源的引用。',basis=basis,
            replacement_claims=[Claim(text=original.text,citation_refs=list(original.citation_refs)+missing)]))
        payload._citation_repairs.add(n)
        rid=89
        while f'R{rid}' in {r.id for r in payload.requirements}:rid-=1
        payload.requirements.append(Requirement(id=f'R{rid}',requirement='补齐比较句各事实的来源引用：'+original.text[:400],
            status='edit',evidence_refs=needed,claim_indexes=[index],issue_indexes=[n],reason=c.reason))
    for i in set(comparison_claim_indexes(draft))-covered:
        errors.append(dict(component='comparison_checks',claim_index=i,reason_code='comparison_check_missing'))
    payload._comparison_errors=errors


def validate_edit_semantics(payload,index,draft,evidences):
    # Only program-created, quote-validated citation additions take this path. Text is unchanged.
    if index in payload._citation_repairs:return
    prior.validate_edit_semantics(payload,index,draft,evidences)


def inspect_diagnosis(payload,draft,evidences,context=None):
    audit=relation.inspect_diagnosis(payload,draft,evidences,context,edit_validator=validate_edit_semantics)
    audit['errors'].extend(payload._comparison_errors)
    audit['valid']=not audit['errors']
    return audit
