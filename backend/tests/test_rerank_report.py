"""Pairing, declared experimental changes, and unsafe candidate rendering."""
from hashlib import sha256
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_qa_rerank_20261030 as report


def metric(value=1,concern=False):
    return dict(point_mean=value,required_point_sum=value,required_point_count=1,
        support_counts={'supported':1},factual_claims=1,factual_citations=1,supported_citations=1,
        complete_groups=1,boundary=2,reference_concern=concern,all_five_pass=value==1)


def fixture(tmp_path):
    paths=[tmp_path/'new',tmp_path/'old']
    names=['literature_rag/application/prompts.py','literature_rag/application/answer_question.py',
        'literature_rag/application/citations.py','literature_rag/application/context.py',
        'literature_rag/application/table_evidence.py','literature_rag/adapters/providers/deepseek.py',
        'literature_rag/adapters/providers/openai.py','literature_rag/application/retrieve.py']
    for i,d in enumerate(paths):
        sources={}
        for n in names:
            p=d/'backend'/n;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(b'unchanged source\n' if not n.endswith('retrieve.py') else f'retrieval {i}\n'.encode())
            sources[n]=sha256(p.read_bytes()).hexdigest()
        config=dict(top_k=8,min_score=.35,context={'budget':24000},pipeline_version=str(i),prompt_pipeline_sha256=str(i))
        if i==0:config['rerank']=dict(enabled=True,version='candidate-rerank-v1')
        (d/'run.json').write_text(json.dumps(dict(tasks=['same'],dataset_manifest_sha256='same',configuration_probe=config,source_files=sources)),encoding='utf-8')
    return paths


def test_source_controls_accept_only_explicit_ranking_changes(tmp_path):
    new,old=fixture(tmp_path)
    result=report.source_controls(new,old)
    assert result['changed_runtime_files']==['literature_rag/application/retrieve.py']


@pytest.mark.parametrize('change',['prompt','settings','questions'])
def test_source_controls_reject_hidden_answer_or_budget_changes(tmp_path,change):
    new,old=fixture(tmp_path);c=json.loads((new/'run.json').read_text('utf-8'))
    if change=='prompt':
        p=new/'backend/literature_rag/application/prompts.py';p.write_bytes(b'changed prompt')
        c['source_files']['literature_rag/application/prompts.py']=sha256(p.read_bytes()).hexdigest()
    elif change=='settings':c['configuration_probe']['min_score']=.1
    else:c['tasks']=['different']
    (new/'run.json').write_text(json.dumps(c),encoding='utf-8')
    with pytest.raises(ValueError):report.source_controls(new,old)


def test_maximum_pairing_uses_each_controls_available_subset_and_tracks_regressions():
    m={('rerank','A'):metric(),('content','A'):metric(.5),('tables','A'):metric(),
       ('rerank','B'):metric(),('tables','B'):metric(),('content','C'):metric()}
    m[('rerank','B')]['all_five_pass']=False
    p=report.paired(m,['A','B','C'],'content')
    assert p['task_ids']==['A'] and p['scores']['rerank']['tasks']==1
    assert p['exclusions'][0]['missing_or_flagged']==['content']
    p=report.paired(m,['A','B','C'],'tables')
    assert p['task_ids']==['A','B'] and p['all_five_losses']==['B']


def test_html_escapes_model_text_and_keeps_missing_grades(tmp_path):
    values={('rerank','A'):metric(),('content','A'):metric()}
    result=dict(comparisons={'content':report.paired(values,['A'],'content')})
    row=dict(task_id='A',question='Question',reference_case={},
        systems={'rerank':dict(candidate={'answer':'<script>alert(1)</script>'},metrics=metric(),review={}),
                 'content':dict(candidate={'answer':'Old'},metrics=None,review=None)},retrieval_diagnostics={})
    p=tmp_path/'report.html';report.html_report(p,result,[row]);text=p.read_text('utf-8')
    assert '<script>alert(1)' not in text and '&lt;script&gt;alert(1)' in text
    assert '有效评分缺失' in text and '不生成自由文字理由' in text


def audit_fixture():
    contract=dict(requested_judges={'jev':'same'},jobs=[dict(name='jev-rag-A',request_sha256='same')])
    direct=({},['same scientific job'],contract,{('jev','rag','A'):{'grade':'original'}},
        {'jev':[{'status':'completed'},{'status':'api_failed'}]},Counter({('jev','rag','completed'):1}),[{'name':'jev-rag-A'}])
    recovery=({},['same scientific job'],deepcopy(contract),{('jev','rag','B'):{'grade':'recovered'}},
        {'jev':[{'status':'completed'}]},Counter({('jev','rag','completed'):1}),[{'name':'jev-rag-B'}])
    return direct,recovery


def test_transport_recovery_preserves_original_grades_and_counts_all_failed_calls():
    direct,recovery=audit_fixture();merged=report.combine_grade_audits(direct,recovery)
    assert len(merged[3])==2 and merged[3][('jev','rag','A')]=={'grade':'original'}
    assert len(merged[4]['jev'])==3
    assert [p['execution_phase'] for p in merged[6]]==['direct','proxy_recovery']


@pytest.mark.parametrize('change',['duplicate_valid','request','judge'])
def test_transport_recovery_rejects_rescoring_or_changed_scientific_inputs(change):
    direct,recovery=audit_fixture()
    if change=='duplicate_valid':recovery[3][('jev','rag','A')]={}
    elif change=='request':recovery[2]['jobs'][0]['request_sha256']='changed'
    else:recovery[2]['requested_judges']={'jev':'changed'}
    with pytest.raises(ValueError):report.combine_grade_audits(direct,recovery)
