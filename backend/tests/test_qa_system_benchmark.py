"""Offline import, blinding, matched-rule and billing-preserving resume checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import import_qa_system_answers as importer
import qa_system_judge as grading
import judge_qa_eval as judge
import judge_qa_jev as jev
import report_qa_system_benchmark as reporting


def answer():
    return dict(task_id='PFI2-001',answer='测试事实。[1]',claims=[dict(text='测试事实。',citation_refs=[1])],
                citations=[dict(ref='1',page_start=2,page_end=2,quote='Test source 10%.')])


def test_mixed_json_preserves_content_and_detects_duplicate_fields():
    row=answer();text='```json\n'+json.dumps(row,ensure_ascii=False)+'\n```\nseparate file note'
    parsed,outside=importer.parse_mixed(text)
    assert [p['value'] for p in parsed]==[row]
    assert 'separate file note' in ''.join(outside)
    with pytest.raises(ValueError,match='Duplicate'):
        importer.parse_mixed('{"task_id":"a","task_id":"b"}')


def test_reference_normalization_does_not_rewrite_scientific_content():
    raw=answer();before=deepcopy(raw);result=importer.normalize_external(raw)
    assert result['answer']==raw['answer'] and result['claims'][0]['text']==raw['claims'][0]['text']
    assert result['claims'][0]['citation_refs']==['[1]'] and result['citations'][0]['ref']=='[1]'
    assert raw==before


@pytest.mark.parametrize('mutate',[
    lambda r:r['claims'][0].update(text='Different text'),
    lambda r:r['claims'][0].update(citation_refs=[2]),
    lambda r:r['citations'][0].update(page_start=0),
    lambda r:r['citations'][0].update(page_end=1),
    lambda r:r['citations'].append(deepcopy(r['citations'][0])),
    lambda r:r.update(api_key='SHOULD_NOT_BE_ACCEPTED'),
])
def test_bad_external_identity_or_content_is_not_silently_fixed(mutate):
    raw=answer();mutate(raw)
    with pytest.raises(ValueError):importer.normalize_external(raw)


def test_quote_check_tolerates_only_documented_typography_not_missing_percent():
    citation=dict(text='10 °SR, 7.72%',page_start=1,page_end=1)
    variants=dict(synthetic=['10 ◦ SR, 7.72%'])
    assert importer.verify_quote(citation,variants)['status']=='typography_only'
    citation['text']='10 °SR, 7.72'
    # Remove an internal percentage, not a genuine short excerpt ending before a punctuation mark.
    citation['text']='10 °SR, 7.72 units'
    assert importer.verify_quote(citation,dict(synthetic=['10 ◦SR, 7.72% units']))['status']=='needs_source_review'


def fixture():
    candidate=importer.normalize_external(answer());candidate.pop('task_id')
    candidate['citations'][0]['verification']=dict(status='normalized_exact')
    candidate['available_context']=dict(kind='supplied_excerpts',texts=['Test source 10%.'])
    case=dict(question='Test question?',category='factual',expected_behavior='answer',reference_answer='Test fact',
              key_points=[dict(id='P1',text='Test fact',capability='text',optional=False)],critical_errors=[])
    job=dict(system='SECRET_PLATFORM',blind_id='SECRET_BLIND_ID',reference_case=case,task=dict(capabilities=['text']),candidate=candidate)
    meta=dict(source_documents=[dict(id='DOC',filename='paper.pdf')])
    sources=dict(reference_evidence=[dict(id='E01',quote='Test source 10%.')],paper_texts=[dict(document_id='DOC',text='Test source 10%.')])
    return grading.packet(job,meta,sources,dict(pdfplumber=['Test source 10%.']*14))


def choices(questions):
    defaults=dict(boundary='appropriate',reference_check='sound',point_P1='complete',kind_C1='fact',
                  support_C1='supported',basis_C1='E01',group_C1='complete',citation_C1_1='supported')
    assert set(defaults)==set(questions)
    return defaults


def luna_response(questions):
    result=dict(answers={k:dict(choice=v,reason='合成测试理由') for k,v in choices(questions).items()})
    return dict(model='openai/gpt-6-luna',choices=[dict(finish_reason='stop',message=dict(content=judge.encode(result)))],
                usage=dict(prompt_tokens=100,completion_tokens=20,total_tokens=120,cost=.001))


def jev_response(request):
    picked=choices(request['questions'])
    return dict(model='typesafe/jev-1.14',provider='TypeSafe',
                answers={k:dict(type='choice',choice=v,confidence=1,probabilities={label:float(label==v) for label in request['questions'][k]['criteria']})
                         for k,v in picked.items()},usage=dict(input_tokens=100,output_tokens=20,cost=.001))


def test_five_rules_and_scientific_packet_are_shared_without_identity_or_sixth_metric():
    state,questions,targets=fixture();serialized=judge.encode(state)
    assert 'SECRET_PLATFORM' not in serialized and 'SECRET_BLIND_ID' not in serialized
    assert not any(k.startswith('retrieval_') for k in questions)
    assert set(grading.POLICY['dimensions'])=={'key_points','claim_support','citation_support','citation_group_coverage','answerability'}
    a=judge.Config('https://openrouter.ai/api/v1','openai/gpt-6-luna','SYNTHETIC')
    b=jev.Config('https://openrouter.ai/api','typesafe/jev-1.14','SYNTHETIC')
    left=grading.request_for('luna',a,state,questions);right=grading.request_for('jev',b,state,questions)
    content=json.loads(left['messages'][1]['content'])
    assert content['state']==right['state'] and content['questions']==right['questions']
    l=grading.decode('luna',luna_response(questions),left,questions,targets,state)
    r=grading.decode('jev',jev_response(right),right,questions,targets,state)
    assert {k:v for k,v in l.items() if k!='reasons'}=={k:v for k,v in r.items() if k!='reasons'}


def test_no_valid_score_is_replaced_and_resume_causes_no_extra_charge(tmp_path):
    state,questions,targets=fixture();config=judge.Config('https://openrouter.ai/api/v1','openai/gpt-6-luna','SYNTHETIC')
    request=grading.request_for('luna',config,state,questions)
    (tmp_path/'inputs').mkdir();(tmp_path/'records').mkdir()
    path=tmp_path/'inputs/test.json';judge.write(path,dict(request=request,state=state,questions=questions,targets=targets))
    entry=dict(name='test',judge='luna',input_sha256=judge.digest(path));calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json=luna_response(questions))
    factory=lambda:httpx.Client(transport=httpx.MockTransport(handler))
    assert grading.evaluate_one(tmp_path,entry,config,threading.Event(),factory,3)=='completed'
    first=(tmp_path/'records/test/1.json').read_bytes()
    assert grading.evaluate_one(tmp_path,entry,config,threading.Event(),factory,3)=='completed'
    assert len(calls)==1 and (tmp_path/'records/test/1.json').read_bytes()==first
    assert not (tmp_path/'records/test/2.json').exists()


def test_quote_and_score_repair_is_never_performed_by_the_importer():
    raw=answer();raw['citations'][0]['quote']='invented source quote'
    result=importer.normalize_external(raw)
    assert result['citations'][0]['text']=='invented source quote'
    assert importer.verify_quote(result['citations'][0],dict(synthetic=['Test source 10%.']*14))['status']=='needs_source_review'


def test_summary_denominators_exclude_scope_and_keep_boundary_separate():
    state,questions,targets=fixture();config=judge.Config('https://openrouter.ai/api/v1','openai/gpt-6-luna','SYNTHETIC')
    request=grading.request_for('luna',config,state,questions)
    review=grading.decode('luna',luna_response(questions),request,questions,targets,state)
    review['claim_assessments'].append(dict(id='C2',claim_type='scope',support='supported'))
    review['citation_group_assessments'].append(dict(claim_id='C2',coverage=None))
    review['citation_assessments'].append(dict(claim_id='C2',score=None))
    review['answerability_score']=1
    row=reporting.metrics(review,state['reference_case'],state['capabilities'])
    summary=reporting.summarize([row])
    assert summary['point_macro_average']==1 and summary['all_five_pass']==0
    assert summary['citation_coverage']==dict(numerator=1,denominator=1,value=1)
    assert summary['support_counts']==dict(supported=1) and summary['boundary_mean']==1


def test_failed_request_cost_is_unknown_and_not_assumed_free():
    rows=[dict(api_calls=1,duration_ms=10,status='api_failed'),
          dict(api_calls=1,duration_ms=20,status='completed',usage=dict(input_tokens=100,output_tokens=20,total_tokens=120),
               raw_response=dict(usage=dict(cost=.001)))]
    result=reporting.accounting(rows,'luna')
    assert result['calls']==2 and result['usage_unknown_calls']==result['cost_unknown_calls']==1
    assert result['reported_cost_usd']=='0.001' and result['invoice_cost_usd'] is None


def test_public_json_bytes_and_hostile_answer_rendering_are_safe(tmp_path):
    reporting.save(tmp_path/'public.json',dict(value='科研数据'))
    assert b'\r\n' not in (tmp_path/'public.json').read_bytes()
    state,questions,targets=fixture();config=judge.Config('https://openrouter.ai/api/v1','openai/gpt-6-luna','SYNTHETIC')
    review=grading.decode('luna',luna_response(questions),grading.request_for('luna',config,state,questions),questions,targets,state)
    row=reporting.metrics(review,state['reference_case'],state['capabilities']);summary=reporting.summarize([row])
    result=dict(valid_grades=4,matched_tasks=1,scores={k:{s:summary for s in ['rag','dsh']} for k in ['luna','jev']})
    candidate=deepcopy(state['candidate']);candidate['answer']='<script>alert(1)</script>'
    sample=dict(task_id='PFI2-001',question='Test',reference_answer='Reference',key_points=state['reference_case']['key_points'],
                systems={s:dict(candidate=candidate,judges={k:dict(metrics=row,review=review) for k in ['luna','jev']}) for s in ['rag','dsh']})
    path=tmp_path/'report.html';reporting.render_html(path,result,[sample]);text=path.read_text(encoding='utf-8')
    assert '<script>' not in text and '&lt;script&gt;' in text and '事实完全支持' in text


def test_platform_token_charge_is_separate_from_model_usage(tmp_path):
    old=dict(total_tokens=65281766)
    clarified=dict(total_tokens=None,reported_platform_charge=dict(amount=65281766,unit='Token'))
    reporting.save(tmp_path/'runtime-confirmation.json',old)
    reporting.save(tmp_path/'runtime-billing-clarification.json',clarified)
    path,metadata=reporting.runtime_metadata(tmp_path,{})
    text=''.join(reporting.runtime_cost_lines(metadata))
    assert path.name=='runtime-billing-clarification.json' and metadata['total_tokens'] is None
    assert '平台总费用：65,281,766 Token' in text and '平台费用' in text
    assert '模型Token用量：65,281,766' not in text
    assert judge.read_json(tmp_path/'runtime-confirmation.json')==old


def test_jev_only_configuration_never_loads_luna_credentials(monkeypatch):
    calls=[]
    config=jev.Config('https://openrouter.ai/api','typesafe/jev-1.14','SYNTHETIC')
    monkeypatch.setattr(jev,'load_config',lambda path:(calls.append(path.name) or config))
    monkeypatch.setattr(grading.luna,'load_config',lambda path:pytest.fail('Luna config must not be read'))
    assert grading.configs(['jev'])=={'jev':config}
    assert calls==['.env.jev']


def test_single_judge_system_filter_preserves_the_scientific_packet(tmp_path,monkeypatch):
    state,questions,targets=fixture()
    candidate=deepcopy(state['candidate'])
    case=state['reference_case']
    jobs=[dict(system=s,blind_id=s+'-blind',task_id='PFI2-001',task=dict(capabilities=['text']),
               reference_case=case,candidate=candidate) for s in ['rag','dsh']]
    sources={k:state[k] for k in ['reference_evidence','paper_texts']}
    meta=dict(source_documents=state['source_documents'])
    source=tmp_path/'import';source.mkdir();(source/'import.json').write_text('{}')
    monkeypatch.setattr(grading,'load_import',lambda directory:(meta,jobs,sources,dict(pdfplumber=['Test source 10%.']*14)))
    config=jev.Config('https://openrouter.ai/api','typesafe/jev-1.14','SYNTHETIC')
    output=tmp_path/'study'
    before=grading.packet(jobs[0],meta,sources,dict(pdfplumber=['Test source 10%.']*14))
    result=grading.prepare(source,output,{'jev':config},['rag'])
    frozen=judge.read_json(output/'study.json')
    assert result['prepared']==1 and result['model_calls']==0
    assert set(frozen['requested_judges'])=={'jev'} and frozen['selected_systems']==['rag']
    assert frozen['policy_sha256']==grading.POLICY_SHA
    assert {e['system'] for e in frozen['jobs']}=={'rag'}
    saved=judge.read_json(next((output/'inputs').iterdir()))
    assert (saved['state'],saved['questions'],saved['targets'])==before
