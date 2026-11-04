"""Opt-in question-driven measurement-boundary audit, within the existing call."""
import re
from . import review_diagnosis_causal as prior

VERSION='bounded-corrective-review-v2.8.1-measurement'
prioritize_supplement=prior.prioritize_supplement
is_relation=prior.is_relation
critical_claim_indexes=prior.critical_claim_indexes
comparison_claim_indexes=prior.comparison_claim_indexes
validate_edit_target=prior.validate_edit_target
validate_edit_semantics=prior.validate_edit_semantics
DiagnosticPayload=prior.DiagnosticPayload
parse_response=prior.parse_response
prepare_payload=prior.prepare_payload
inspect_diagnosis=prior.inspect_diagnosis
request_context=prior.request_context
DIAGNOSTIC_PROMPT=prior.DIAGNOSTIC_PROMPT

REQUIREMENT='核对实际测量量、回答推断量及回答该问题所必需的解释边界'
MEASUREMENT_PROMPT='''
Measurement-boundary audit is active for this request. In the SAME requirements ledger include R80,
requirement="核对实际测量量、回答推断量及回答该问题所必需的解释边界". Preserve it in later rounds.
In its brief reason distinguish (1) what was actually measured/calculated and its normalization or units,
(2) what the question/answer infers, (3) what the supplied method does or does not establish.
A correct method description may still omit a necessary inference limit. A normalized peak-area fraction
is not an absolute bond count or concentration; its decrease alone does not prove fewer bonds absolutely.
If the user asks for measurement/content scope, interpretation, or quantitative conversion, and the
reported quantity is a normalized fraction, the FINAL ANSWER must explicitly distinguish the relative
measurement from absolute quantity. Merely using the word "relative" is insufficient for that request.
Mentioning the limitation ONLY in this review's reason does not answer the user. Do not mark R80 covered
because the draft "does not claim an absolute number". For covered, quote the actual draft sentence that
states the relevant inference limit in R80.reason. If it is absent, propose a minimal measurement edit
to the existing measurement/interpretation sentence and mark R80 edit, using the existing source basis.
Do not require this explicit caveat for a plain numeric lookup or a genuinely calibrated absolute value.
Do NOT assume every measurement is relative: calibrated absolute quantities remain absolute if supported.
For a numeric lookup or instrument list do not append generic caveats. If the interpretation is already
bounded, preserve it. If a boundary is necessary but missing, minimally edit the existing relevant claim,
cite the actual methodological basis, and identify your methodological inference rather than attributing
an unstated conclusion to the authors. Never invent a quote containing the caveat.
Use existing supplied evidence when sufficient; do not add unrelated methods, mechanisms or citations.
If the method is genuinely unknown, mark unresolved or use the existing bounded lookup policy.
Do not replace coefficient/conflict evidence with a long methods explanation. Existing budgets apply.
Use normal covered/edit/lookup/unresolved actions and existing issue/claim bindings. No extra schema.
'''


def measurement_context(question,draft,evidences):
    # Conservative lexical routing, not a claim that semantics have been checked.
    measurement=r'含量|数量|浓度|比例|峰面积|分峰|归一化|测量|口径|FT.?IR|百分比|count|concentration|fraction|peak.area|normaliz|measurement'
    interpretation=r'口径|含义|意味|代表|说明|解释|为什么|如何|是否|是不是|能否|能不能|算出|换算|推断|绝对|意味着|mean|interpret|infer|absolute|convert|calculate'
    relative=r'相对|占比|百分比|比例|峰面积|归一化|relative|fraction|percent|peak.area|normaliz'
    absolute=r'绝对|总量|浓度|分子数|数量|absolute|total number|concentration|bond count'
    question_trigger=bool(re.search(measurement,question,re.I) and re.search(interpretation,question,re.I))
    ids=[i for i,c in enumerate(draft.claims) if re.search(relative,c.text,re.I) and re.search(absolute,c.text,re.I)]
    # Catch an absolute assertion against a relative source, without scanning unrelated evidence.
    refs={e.ref:e.text for e in evidences}
    ids+= [i for i,c in enumerate(draft.claims) if re.search(absolute,c.text,re.I)
           and any(re.search(relative,refs.get(r,''),re.I) for r in c.citation_refs)]
    return dict(triggered=question_trigger or bool(ids),question_interpretation=question_trigger,
                claim_indexes=sorted(set(ids)),policy='heuristic-routing-not-semantic-verification')


def measurement_errors(payload,question,draft,evidences):
    if not measurement_context(question,draft,evidences)['triggered']:return []
    rows=[r for r in payload.requirements if r.id=='R80']
    if len(rows)!=1 or rows[0].requirement!=REQUIREMENT:
        return [dict(component='measurement_boundary',reason_code='measurement_requirement_missing_or_changed')]
    return []
