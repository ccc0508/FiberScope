"""Bounded, conditional audit of factor rankings; no additional model call."""
import re
from . import review_diagnosis_measurement as prior

VERSION='bounded-corrective-review-v2.9-ranking'
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
measurement_context=prior.measurement_context
measurement_errors=prior.measurement_errors
MEASUREMENT_PROMPT=prior.MEASUREMENT_PROMPT

LIMIT=3
REQUIREMENT='核对因素强弱或贡献排名的证据、比较口径及回答边界'
RANKING_PROMPT='''
Factor-ranking audit is active. In the SAME requirements ledger include R81 with
requirement="核对因素强弱或贡献排名的证据、比较口径及回答边界"; preserve it in later rounds.
Check only selected ranking_claim_indexes (at most 3) and the question's ranking request.
In a brief reason distinguish association, predictive importance, causal contribution, or an author's
qualitative explanation. Strongest correlation does not imply greatest causal contribution. A mechanism
explaining an outcome does not establish it as the most direct, most important, or dominant factor.
For each selected ranking, check comparison group, outcome, metric and conditions against actual evidence.
Preserve a supported ranking with its scope; retain an author's qualitative opinion only as an attributed
opinion. Do not weaken all rankings or invent a missing quantitative comparison.
If evidence cannot establish the requested ranking, the FINAL ANSWER must say it cannot determine the
largest contribution from the supplied evidence. Remove only unsupported ranking words, keep supported
relationships, and answer the ranking request. Merely adding "possibly" does not supply ranking evidence.
For covered, point to the actual draft claim giving the supported ranking or explicit limit; a statement
in this review's reason is not a substitute. Otherwise propose a minimal bound edit with existing sources.
Reuse requirements/issues and existing binding/citation checks. No new output schema or extra model call.
Do not expand unrelated methods, mechanisms or measurement caveats. Unchecked extra rankings are not certified.
'''


def ranking_signal(text):
    return bool(re.search(r'最重要|最关键|最直接|主导因素|主要由|贡献排名|因素排名|'
        r'(?:贡献|作用|影响|相关性).{0,12}(?:最大|最强|更大|更强|最主要)|'
        r'哪个.{0,15}(?:重要|关键)|'
        r'\b(?:most important|most direct|dominant factor|greatest contribution|strongest correlation)\b',text,re.I))


def ranking_context(question,draft,evidences):
    ids=[i for i,c in enumerate(draft.claims) if ranking_signal(c.text)]
    return dict(triggered=ranking_signal(question) or bool(ids),question_requests_ranking=ranking_signal(question),
        ranking_claim_indexes=ids[:LIMIT],unchecked_claim_indexes=ids[LIMIT:],
        policy='explicit-ranking-signals; heuristic-routing-not-semantic-verification')


def ranking_errors(payload,question,draft,evidences):
    ctx=ranking_context(question,draft,evidences)
    if not ctx['triggered']:return []
    errors=[]
    rows=[r for r in payload.requirements if r.id=='R81']
    if len(rows)!=1 or rows[0].requirement!=REQUIREMENT:
        errors.append(dict(component='factor_ranking',reason_code='ranking_requirement_missing_or_changed'))
    if ctx['unchecked_claim_indexes']:
        errors.append(dict(component='factor_ranking',reason_code='ranking_budget_unchecked',claim_indexes=ctx['unchecked_claim_indexes']))
    return errors
