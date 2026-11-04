from dataclasses import replace
import json
from types import SimpleNamespace as NS
import pytest
from literature_rag.application import review_diagnosis_ranking as r
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from tests.test_evidence_review import DRAFT,SOURCES
from tests.test_corrective_review import requirement,controller

@pytest.mark.parametrize('text,expected',[
 ('WRV与结合强度有关',False),('针叶木的数值高于阔叶木',False),
 ('最大的长度为3 mm',False),('WRV对强度的贡献最大',True),
 ('这些因素哪个贡献最大？',True),('WRV和强度的联系最直接',True),
 ('无法确定哪个因素最重要',True),('A has the strongest correlation',True)])
def test_explicit_routing(text,expected):
 assert r.ranking_signal(text)==expected

def payload():
 return r.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[])))

def test_question_triggers_without_ranked_answer_and_budget_is_bounded():
 assert r.ranking_context('哪个因素最重要？',DRAFT,SOURCES)['triggered']
 d=replace(DRAFT,claims=tuple(replace(DRAFT.claims[0],text='A贡献最大') for _ in range(5)))
 ctx=r.ranking_context('说明结果',d,SOURCES)
 assert ctx['ranking_claim_indexes']==[0,1,2] and ctx['unchecked_claim_indexes']==[3,4]
 assert any(e['reason_code']=='ranking_budget_unchecked' for e in r.ranking_errors(payload(),'Q',d,SOURCES))

def test_missing_record_blocks_completion_without_extra_call():
 service,provider,_=controller([payload()]);provider.diagnosis_version='v2_ranking'
 service.review('哪个因素贡献最大？',SOURCES,DRAFT)
 t=service.last_trace
 assert t['status']=='incomplete' and t['api_calls']==1
 assert t['rounds'][0]['ranking_context']['triggered']
 assert any(e['reason_code']=='ranking_requirement_missing_or_changed' for e in t['rounds'][0]['diagnosis_errors'])

@pytest.mark.parametrize('question,active',[('哪个因素贡献最大？',True),('针叶木数值是否高于阔叶木？',False)])
def test_prompt_is_conditional_same_call_and_budget(question,active):
 calls=[]
 def create(**kw):
  calls.append(kw)
  return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[]))))])
 p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v2_ranking')
 p.review(question,SOURCES,DRAFT)
 assert len(calls)==1 and calls[0]['max_tokens']==32768
 assert ('Factor-ranking audit is active' in calls[0]['messages'][0]['content'])==active
