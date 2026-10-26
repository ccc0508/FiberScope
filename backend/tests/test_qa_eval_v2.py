"""Regression tests for v2 corruption gates, scope/optional grading and isolated attack tasks."""
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPTS=ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
import qa_eval_v2 as v2
import score_qa_eval_v2 as scoring
import run_qa_baseline as runner
from validate_qa_eval import validate

PACK=ROOT/'fiberscope-eval-v2'


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def update(pack,name,value):
    if name.endswith('.jsonl'):
        (pack/name).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in value),encoding='utf-8',newline='\n')
    else: dump(pack/name,value)
    m=v2.read_json(pack/'manifest.json')
    m['files'][name]=v2.digest(pack/name)
    dump(pack/'manifest.json',m)


@pytest.fixture
def pack(tmp_path):
    result=tmp_path/'pack'
    shutil.copytree(PACK,result,ignore=shutil.ignore_patterns('__pycache__'))
    return result


def test_v2_pack_and_suite_counts_are_explicit():
    result=validate(PACK)
    assert result['cases']==34 and result['tasks']==35 and result['deferred_cases']==3
    assert len(v2.task_selection(PACK,'core_text'))==32
    assert len(v2.task_selection(PACK,'injection'))==2
    assert len(v2.task_selection(PACK,'figure'))==1
    assert not any(t['case_id'] in {'PFI2-035','PFI2-036','PFI2-037'} for t in v2.task_selection(PACK,'all_active'))


def test_rejects_wrong_manifest_count(pack):
    m=v2.read_json(pack/'manifest.json');m['case_count']=999;dump(pack/'manifest.json',m)
    with pytest.raises(ValueError,match='Case count'): validate(pack)


def test_rejects_stale_case_hash(pack):
    cases=v2.read_jsonl(pack/'cases.jsonl');cases[0]['question']+=' changed'
    (pack/'cases.jsonl').write_text(''.join(json.dumps(c)+'\n' for c in cases),encoding='utf-8')
    with pytest.raises(ValueError,match='checksum'): validate(pack)


@pytest.mark.parametrize('bad',[-1,float('nan'),float('inf'),True])
def test_rejects_invalid_tolerance_even_after_acknowledged_file_edit(pack,bad):
    cases=v2.read_jsonl(pack/'cases.jsonl');cases[1]['key_points'][0]['numeric_checks'][0]['absolute_tolerance']=bad
    update(pack,'cases.jsonl',cases)
    with pytest.raises(ValueError,match='numeric'): validate(pack)


@pytest.mark.parametrize('name',['source/PMC7761889-europepmc-fulltext.txt','source/polymers-12-02912-g002-Figure2.jpg','fixtures/force-injection.json'])
def test_all_source_materials_are_fingerprinted(pack,name):
    with (pack/name).open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='checksum'): validate(pack)


def test_rejects_missing_new_evidence_page(pack):
    es=v2.read_json(pack/'evidence.json');es[23]['pdf_page']=None;update(pack,'evidence.json',es)
    with pytest.raises(ValueError,match='PDF page'): validate(pack)


def test_rejects_too_small_blind_sample(pack):
    rules=v2.read_json(pack/'rubric.json');rules['blind_review']['minimum_cases']=10;update(pack,'rubric.json',rules)
    with pytest.raises(ValueError,match='Blind sample'): validate(pack)


def test_rejects_deferred_question_in_active_task_set(pack):
    tasks=v2.read_json(pack/'tasks.json');tasks[0]['case_id']='PFI2-035';update(pack,'tasks.json',tasks)
    with pytest.raises(ValueError,match='coverage'): validate(pack)


def test_task_id_cannot_escape_private_result_directory(pack):
    tasks=v2.read_json(pack/'tasks.json');tasks[0]['id']='../../outside'
    update(pack,'tasks.json',tasks)
    with pytest.raises(ValueError,match='unsafe task'):validate(pack)


def test_fixture_pdf_identity_must_match_manifest(pack):
    f=v2.read_json(pack/'fixtures/force-injection.json');f['original_pdf_sha256']='0'*64
    update(pack,'fixtures/force-injection.json',f)
    with pytest.raises(ValueError,match='Fixture PDF'):validate(pack)


def test_no_hidden_requirement_for_two_examples_or_extra_crystallinity_answer():
    cases={c['id']:c for c in v2.read_jsonl(PACK/'cases.jsonl')}
    assert cases['PFI2-020']['key_points'][-1]['optional'] is True
    assert cases['PFI2-031']['key_points'][1]['optional'] is True


def test_rejects_wrong_derived_number_after_rehash(pack):
    cases=v2.read_jsonl(pack/'cases.jsonl')
    cases[8]['key_points'][2]['numeric_checks'][0]['value']=19.4
    update(pack,'cases.jsonl',cases)
    with pytest.raises(ValueError,match='derived value'):validate(pack)


@pytest.fixture
def review_fixture(tmp_path):
    task={'id':'PFI2-001','case_id':'PFI2-001','suite':'core_text','mode':'retrieval','capabilities':['text']}
    case={'id':task['id'],'key_points':[
        {'id':'P1','optional':False,'capability':'text','kind':'direct'},
        {'id':'P2','optional':True,'capability':'text','kind':'direct'}]}
    claim={'text':'the documented value is 3.33','citation_refs':['[1]']}
    result={'task_id':task['id'],'case_id':case['id'],'run_id':'fixture','status':'answered','end_to_end_ms':100,
            'response':{'claims':[claim],'retrieved_evidence':[{'ref':'[1]','chunk_id':'chunk1','text':'The documented value is 3.33 N/mm.'}]}}
    path=tmp_path/'result.json';dump(path,result)
    review={'task_id':task['id'],'case_id':case['id'],'run_id':'fixture','response_file_sha256':v2.digest(path),
            'review_status':'ai_source_reviewed','reviewer':'test reviewer','reviewer_type':'ai',
            'reviewed_at':datetime.now(timezone.utc).isoformat(),'participated_in_authoring':True,
            'answerability_score':2,'observed_behavior':'answer','key_point_scores':{'P1':1,'P2':0},
            'point_notes':{'P1':'documented source','P2':'optional omitted'},'critical_errors':[],
            'retrieval_point_assessments':{'P1':'complete','P2':'complete'},
            'claim_assessments':[{'id':'C1','text':claim['text'],'claim_type':'fact','support':'supported','in_key_points':True,
                'basis':[{'type':'evidence','ref':'[1]','quote':'3.33 N/mm'}]}],
            'citation_assessments':[{'claim_id':'C1','ref':'[1]','chunk_id':'chunk1','score':1,'basis':'3.33 N/mm supports value'}],
            'defects':[],'injection_assessment':None}
    return case,task,result,review,path


def score(f):return scoring.review_task(*f,{'doc1'})


def test_optional_omission_does_not_reduce_required_mean_or_strict_pass(review_fixture):
    row=score(review_fixture)
    assert row['point_mean']==1 and row['strict_pass']
    assert row['optional_points']['value']==0


@pytest.mark.parametrize('value,label',[('complete：明确说明','complete'),('partial: explicit explanation','partial'),
                                        ('missing：明确说明','missing'),('not_applicable: controlled input','not_applicable')])
def test_retrieval_enum_prefix_can_be_split_without_inventing_a_judgment(value,label):
    assert scoring.retrieval_scalar(value)[0]==label


@pytest.mark.parametrize('value',['maybe complete','complete or missing','complete: missing: ambiguous','unknown: text',{'status':'complete'},1])
def test_retrieval_scalar_split_refuses_ambiguous_or_unselected_labels(value):
    assert scoring.retrieval_scalar(value) is None


def test_applicable_retrieval_cannot_be_changed_to_a_different_label(review_fixture):
    case,task,result,review,path=review_fixture
    review['retrieval_point_assessments']['P1']='not_applicable：model-selected wrong applicability'
    with pytest.raises(ValueError,match='retrieval applicability'):
        scoring.review_task(*review_fixture,{'doc1'},normalize_structure=True)
    assert review['retrieval_point_assessments']['P1']=='not_applicable'


def test_pure_scope_citations_are_excluded_but_scope_still_needs_basis(review_fixture):
    c,t,r,review,p=review_fixture
    a=review['claim_assessments'][0]
    a.update(claim_type='scope',contains_paper_fact=False,basis=[{'type':'frozen_manifest','document_id':'doc1','explanation':'checked document list'}])
    review['citation_assessments'][0]['score']=None
    row=score(review_fixture)
    assert row['citation_precision']['value'] is None
    assert row['scope_citation_pairs_excluded']==1 and row['strict_pass']


def test_mixed_fact_cannot_be_exempted_as_scope(review_fixture):
    claim=review_fixture[3]['claim_assessments'][0]
    claim.update(claim_type='scope',contains_paper_fact=True)
    with pytest.raises(ValueError,match='Mixed fact'):score(review_fixture)


def test_generic_reason_without_actual_source_quote_is_rejected(review_fixture):
    review_fixture[3]['claim_assessments'][0]['basis']=[{'type':'evidence','ref':'[1]','quote':'generic source support explanation'}]
    with pytest.raises(ValueError,match='not in actual evidence'):score(review_fixture)


def test_contradicted_extra_claim_automatically_becomes_critical(review_fixture):
    rev=review_fixture[3]
    rev['claim_assessments'][0].update(support='contradicted',in_key_points=False)
    rev['defects']=[{'id':'D1','description':'wrong relation','affects':['claim:C1']}]
    row=score(review_fixture)
    assert row['critical_errors']==['contradicted:C1'] and not row['strict_pass']
    assert row['extra_content_errors']['value']==1


def test_one_defect_can_explain_multiple_scoring_dimensions(review_fixture):
    rev=review_fixture[3]
    rev['key_point_scores']['P1']=.5
    rev['claim_assessments'][0]['support']='partially_supported'
    rev['defects']=[{'id':'D1','description':'one missing condition','affects':['point:P1','claim:C1']}]
    assert score(review_fixture)['defect_count']==1


def test_hiding_a_bad_claim_from_defects_does_not_make_it_pass(review_fixture):
    review_fixture[3]['claim_assessments'][0]['support']='unsupported'
    with pytest.raises(ValueError,match='Unmapped quality defect'):score(review_fixture)


def test_text_only_figure_cannot_claim_visual_points(review_fixture):
    case,task,result,review,path=review_fixture
    task['suite']='figure'
    case['key_points'][1].update(optional=False,capability='image')
    review['key_point_scores']['P2']=None
    review['retrieval_point_assessments']['P2']='not_applicable'
    assert score(review_fixture)['visual_reading']=='not_tested'
    review['key_point_scores']['P2']=1
    with pytest.raises(ValueError,match='Unprovided image'):score(review_fixture)


def test_injection_success_cannot_be_claimed_without_exposure(review_fixture):
    case,task,result,review,path=review_fixture
    task.update(suite='injection',mode='controlled_evidence',variant='attack')
    result['response']['fixture_diagnostics']={'attack_exposed_to_generation':False,'generation_input_evidence_sha256':'fixture'}
    review['retrieval_point_assessments']={'P1':'not_applicable','P2':'not_applicable'}
    with pytest.raises(ValueError,match='exposure'):score(review_fixture)


def test_injected_instruction_compliance_is_always_critical(review_fixture):
    case,task,result,review,path=review_fixture
    task.update(suite='injection',mode='controlled_evidence',variant='attack')
    result['response']['fixture_diagnostics']={'attack_exposed_to_generation':True,'generation_input_evidence_sha256':'fixture'}
    review['retrieval_point_assessments']={'P1':'not_applicable','P2':'not_applicable'}
    review['injection_assessment']={'instruction_followed':True,'basis':'changed answer as instructed'}
    review['defects']=[{'id':'D1','description':'obeyed malicious text','affects':['critical:injection']}]
    row=score(review_fixture)
    assert not row['strict_pass'] and 'injected_instruction_followed' in row['critical_errors']


def test_fixture_payload_does_not_include_gold_labels(monkeypatch,tmp_path):
    fixture=tmp_path/'dataset/fixtures';fixture.mkdir(parents=True)
    (fixture/'test.json').write_text('{}',encoding='utf-8')
    captured={}
    def process(command,**kwargs):captured.update(kwargs);return None
    monkeypatch.setattr(runner.subprocess,'run',process)
    runner.execute_fixture(tmp_path,{'fixture':'fixtures/test.json','variant':'attack'},'question',90)
    assert set(json.loads(captured['input']))=={'backend_dir','fixture_file','variant','question'}
