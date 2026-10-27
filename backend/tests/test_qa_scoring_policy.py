"""Shared-policy and joint-evidence regression gates; synthetic labels, no paid judging."""
from copy import deepcopy
from pathlib import Path
import sys

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
import judge_qa_jev as jev
import qa_jev_prompt
import qa_scoring_policy as policy
import score_qa_eval_v2 as scoring
import compare_qa_jev as comparison
from .test_qa_judge import run_dir
from .test_qa_jev import config, response
from .test_qa_eval_v2 import review_fixture


def test_both_judges_receive_identical_policy_and_no_frozen_rubric_mutation(run_dir):
    source,manifest,cases,sources=judge.verify_run(run_dir)
    task=source['tasks'][0];case=cases[task['case_id']]
    _,result=judge.read_result(run_dir,source,case,task)
    rubric=judge.read_json(run_dir/'dataset/rubric.json');before=deepcopy(rubric)
    gpt=judge.packet(case,task,result,manifest,sources,rubric)
    native,targets=qa_jev_prompt.build_request(config(),case,task,result,manifest,sources,rubric)
    assert gpt['scoring_policy']==native['state']['scoring_policy']==policy.POLICY
    assert gpt['scoring_policy_sha256']==native['state']['scoring_policy_sha256']==policy.SHA256
    assert gpt['rubric']==native['state']['rubric'] and rubric==before
    assert gpt['reference_case']['key_points']==case['key_points']
    assert native['questions']['group_C1']['criteria']==qa_jev_prompt.GROUP_LABELS
    assert targets['group_C1']=={'kind':'citation_group','claim_id':'C1'}
    assert 'all factual content' not in native['questions']['citation_C1_1']['criteria']['supported']


def test_reference_fulltext_is_never_silently_added_to_actual_retrieval(run_dir):
    source,manifest,cases,sources=judge.verify_run(run_dir);task=source['tasks'][0]
    _,result=judge.read_result(run_dir,source,cases[task['case_id']],task)
    sources=deepcopy(sources)
    sources['paper_texts'][0]['text']+='\nFULLTEXT_ONLY_MISSING_ENDPOINT'
    packet=judge.packet(cases[task['case_id']],task,result,manifest,sources,judge.read_json(run_dir/'dataset/rubric.json'))
    assert 'FULLTEXT_ONLY_MISSING_ENDPOINT' in packet['paper_texts'][0]['text']
    assert packet['candidate']['retrieved_evidence']==result['response']['retrieved_evidence']
    assert 'FULLTEXT_ONLY_MISSING_ENDPOINT' not in judge.encode(packet['candidate'])


@pytest.fixture
def joint_review(review_fixture):
    case,task,result,review,path=review_fixture
    result['response']['claims'][0].update(text='Synthetic A and B',citation_refs=['[1]','[2]'])
    result['response']['retrieved_evidence'].append(dict(ref='[2]',chunk_id='chunk2',text='Synthetic support for B.'))
    judge.write(path,result);review['response_file_sha256']=judge.digest(path)
    review['claim_assessments'][0]['text']='Synthetic A and B'
    review['citation_assessments'].append(dict(claim_id='C1',ref='[2]',chunk_id='chunk2',score=1,basis='Synthetic support for B'))
    review.update(scoring_policy_version=policy.VERSION,scoring_policy_sha256=policy.SHA256,
                  citation_group_assessments=[dict(claim_id='C1',refs=['[1]','[2]'],coverage='complete',basis='Both synthetic components covered')])
    return case,task,result,review,path


def test_two_complementary_citations_can_jointly_cover_a_claim(joint_review):
    row=scoring.review_task(*joint_review,{'doc1'})
    assert row['strict_pass'] and row['citation_precision']['value']==1
    assert row['citation_coverage']['value']==1


def test_relevant_citations_do_not_hide_an_incomplete_cited_group(joint_review):
    case,task,result,review,path=joint_review
    review['citation_group_assessments'][0].update(coverage='partial',basis='Synthetic missing component despite useful references')
    review['defects']=[dict(id='D1',description='Synthetic joint support gap',affects=['coverage:C1'])]
    row=scoring.review_task(*joint_review,{'doc1'})
    assert row['citation_precision']['value']==1 and row['citation_coverage']['value']==0
    assert not row['strict_pass']
    native=deepcopy(review);native['claim_assessments'][0]['evidence_location_status']='verified_verbatim_passage'
    assert not jev.metrics(case,task,native)['shared_dimensions_pass']


def test_irrelevant_extra_citation_fails_precision_even_when_group_is_complete(joint_review):
    review=joint_review[3];review['citation_assessments'][1].update(score=0,basis='Synthetic irrelevant extra reference')
    review['defects']=[dict(id='D1',description='Synthetic irrelevant citation',affects=['citation:C1:[2]'])]
    row=scoring.review_task(*joint_review,{'doc1'})
    assert row['citation_coverage']['value']==1 and row['citation_precision']['value']==.5
    assert not row['strict_pass']


@pytest.mark.parametrize('change',['missing_group','wrong_refs','inconsistent_coverage','wrong_policy_hash'])
def test_v3_rejects_incomplete_or_inconsistent_group_protocol(joint_review,change):
    review=joint_review[3]
    if change=='missing_group':review.pop('citation_group_assessments')
    elif change=='wrong_refs':review['citation_group_assessments'][0]['refs']=['[1]']
    elif change=='inconsistent_coverage':review['citation_group_assessments'][0]['coverage']='missing'
    else:review['scoring_policy_sha256']='tampered'
    with pytest.raises(ValueError,match='citation group|Citation group|policy fingerprint'):
        scoring.review_task(*joint_review,{'doc1'})


def test_actual_retrieval_scope_has_its_own_locator_and_preserves_raw_group_label(run_dir,tmp_path):
    def handler(request):
        body=response(request)
        for key,choice in [('kind_C1','scope'),('basis_C1','ACTUAL_RETRIEVAL_SCOPE')]:
            entry=body['answers'][key];entry.update(choice=choice,probabilities={k:float(k==choice) for k in entry['probabilities']})
        return httpx.Response(200,json=body)
    out=tmp_path/'scope-v3'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=jev.run(run_dir,out,config(),client=client)
    assert result['valid_reviews']==1
    review=judge.read_json(out/'tasks/PFI2-033-clean.json')['review']
    group=review['citation_group_assessments'][0]
    assert group['raw_coverage']=='complete' and group['coverage'] is None
    assert review['claim_assessments'][0]['evidence_location_status']=='actual_retrieval_scope_selected'


def test_retrieval_scope_basis_must_cover_exact_actual_evidence_set():
    result={'response':{'retrieved_evidence':[dict(ref='[1]',text='A'),dict(ref='[2]',text='B')]}}
    good=dict(type='retrieval_scope_review',refs=['[1]','[2]'],explanation='Synthetic current-evidence scope')
    scoring.source_basis([good],result,'scope',{'doc1'})
    with pytest.raises(ValueError,match='all actual evidence'):
        scoring.source_basis([dict(good,refs=['[1]'])],result,'scope',{'doc1'})
    with pytest.raises(ValueError,match='Scope basis'):
        scoring.source_basis([good],result,'fact',{'doc1'})


def test_old_and_new_policy_reviews_cannot_be_pooled_or_compared():
    with pytest.raises(ValueError,match='Mixed scoring policy'):
        policy.require_same_policy([{},dict(scoring_policy_version=policy.VERSION)])
    with pytest.raises(ValueError,match='Mixed scoring policy'):
        comparison.compare_labels({'T':{}},{'T':dict(scoring_policy_version=policy.VERSION)},[],{})


def test_mixed_fact_can_supplement_verified_quote_with_retrieval_scope_proof():
    result={'response':{'retrieved_evidence':[dict(ref='[1]',text='The documented fact is A.')]}}
    quote=dict(type='evidence',ref='[1]',quote='The documented fact is A.')
    scope=dict(type='retrieval_scope_review',refs=['[1]'],explanation='Only supplied evidence was inspected for missing B.')
    scoring.source_basis([quote,scope],result,'fact',{'doc1'})
    with pytest.raises(ValueError,match='Scope basis'):
        scoring.source_basis([scope],result,'fact',{'doc1'})
    with pytest.raises(ValueError,match='not in actual evidence'):
        scoring.source_basis([dict(quote,quote='Invented factual quotation'),scope],result,'fact',{'doc1'})
    with pytest.raises(ValueError,match='Scope basis'):
        scoring.source_basis([quote,dict(type='full_pdf_review',document_id='doc1',explanation='Not factual proof')],
                             result,'fact',{'doc1'})


def test_legacy_request_reconstruction_does_not_inject_new_policy(run_dir):
    source,manifest,cases,sources=judge.verify_run(run_dir);task=source['tasks'][0]
    _,result=judge.read_result(run_dir,source,cases[task['case_id']],task)
    rubric=judge.read_json(run_dir/'dataset/rubric.json')
    gpt=judge.packet(cases[task['case_id']],task,result,manifest,sources,rubric,prompt_version='qa-independent-judge-v2')
    request,targets=qa_jev_prompt.build_request(config(),cases[task['case_id']],task,result,manifest,sources,rubric,
                                                prompt_version='qa-jev-openrouter-v1')
    assert 'scoring_policy' not in gpt and 'scoring_policy' not in request['state']
    assert 'citation_group_assessments' not in gpt['output_shape']
    assert not any(k.startswith('group_') for k in request['questions'])
    assert gpt['contract_version']=='qa-independent-judge-v2'
