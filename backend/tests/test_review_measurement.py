from dataclasses import replace
import json
from types import SimpleNamespace as NS
import pytest
from literature_rag.application import review_diagnosis_measurement as m
from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
from tests.test_evidence_review import DRAFT,SOURCES
from tests.test_corrective_review import requirement

@pytest.mark.parametrize('question,trigger',[
 ('如何从FT-IR得到相对含量？说明拟合和含量口径。',True),
 ('能不能用CI-XI直接算出氢键含量？',True),
 ('表2的相对含量是多少？',False),
 ('用什么仪器测量纤维形态？',False),
 ('绝对浓度如何标定？',True),
])
def test_routing(question,trigger):
 assert m.measurement_context(question,DRAFT,SOURCES)['triggered']==trigger

def test_absolute_claim_against_relative_source_routes():
 es=[replace(SOURCES[0],text='Relative peak area decreased.')]
 d=replace(DRAFT,claims=(replace(DRAFT.claims[0],text='氢键总量减少。'),))
 assert m.measurement_context('结果是什么？',d,es)['claim_indexes']==[0]

def test_requirement_missing_is_not_complete():
 raw=dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[])
 p=m.parse_response(json.dumps(raw))
 assert m.measurement_errors(p,'如何解释相对含量？',DRAFT,SOURCES)
 assert not m.measurement_errors(p,'仪器名称？',DRAFT,SOURCES)
 raw['requirements'][0].update(id='R80',requirement=m.REQUIREMENT)
 p=m.parse_response(json.dumps(raw))
 assert not m.measurement_errors(p,'如何解释相对含量？',DRAFT,SOURCES)

def test_service_missing_boundary_record_blocks_completion_and_logs_trigger():
 from tests.test_corrective_review import controller
 p=m.parse_response(json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[])))
 service,provider,_=controller([p]);provider.diagnosis_version='v2_measurement'
 service.review('如何解释含量口径？',SOURCES,DRAFT)
 trace=service.last_trace
 assert trace['status']=='incomplete'
 assert trace['rounds'][0]['measurement_context']['triggered']
 assert any(x['reason_code']=='measurement_requirement_missing_or_changed' for x in trace['rounds'][0]['diagnosis_errors'])

def test_snapshot_includes_measurement_and_inherited_sources(tmp_path):
 from literature_rag.config import Settings
 from literature_rag.diagnostics import configuration_snapshot
 assert Settings.model_fields['corrective_review_version'].default=='v1'
 p=tmp_path/'settings.env'
 p.write_text('RAG_EVIDENCE_REVIEW_ENABLED=true\nRAG_CORRECTIVE_REVIEW_ENABLED=true\n'
  'RAG_CORRECTIVE_REVIEW_VERSION=v2_measurement\nRAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=PRIVATE_TEST\n'
  'RAG_RERANK_BASE_URL=https://example.invalid/v1\nRAG_LLM_PROVIDER=deepseek\n'
  'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=PRIVATE_TEST\n',encoding='utf-8')
 result=configuration_snapshot(p)
 assert result['evidence_review']['version']==m.VERSION
 assert 'application/review_diagnosis_measurement.py' in result['pipeline_source_files']
 assert 'application/review_diagnosis_causal.py' in result['pipeline_source_files']

@pytest.mark.parametrize('question,active',[('解释含量口径',True),('仪器名称？',False)])
def test_conditional_prompt_same_call(question,active):
 calls=[]
 def create(**kw):
  calls.append(kw)
  return NS(model='deepseek-flash',usage=None,choices=[NS(finish_reason='stop',message=NS(content=json.dumps(dict(issues=[],requirements=[requirement()],claim_checks=[],relation_checks=[],comparison_checks=[]))))])
 p=DeepSeekEvidenceReviewer('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),diagnostic=True,diagnosis_version='v2_measurement')
 p.review(question,SOURCES,DRAFT)
 assert len(calls)==1 and calls[0]['max_tokens']==32768
 assert ('Measurement-boundary audit is active' in calls[0]['messages'][0]['content'])==active
 assert 'calibrated absolute quantities remain absolute' in m.MEASUREMENT_PROMPT
