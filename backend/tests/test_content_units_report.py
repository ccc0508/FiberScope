"""Reject hidden experiment changes and preserve missing grades in paired reporting."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_content_units_20261030 as report


def metric(value=1,concern=False):
    return dict(point_mean=value,required_point_sum=value,required_point_count=1,
        support_counts={'supported':1},factual_claims=1,factual_citations=1,supported_citations=1,
        complete_groups=1,boundary=2,reference_concern=concern,all_five_pass=value==1)


def fixture(tmp_path):
    paths=[tmp_path/'new',tmp_path/'old']
    for p in paths:
        source=p/'backend/literature_rag/application/prompts.py'
        source.parent.mkdir(parents=True);source.write_bytes(b'identical prompt\n')
        (p/'run.json').write_text(json.dumps(dict(tasks=['same'],dataset_manifest_sha256='same',
            configuration_probe=dict(top_k=8,min_score=.35,prompt_pipeline_sha256='same'),
            source_files={'literature_rag/application/prompts.py':sha256(source.read_bytes()).hexdigest()})),encoding='utf-8')
    return paths


@pytest.mark.parametrize('change',['prompt','settings','questions','dataset'])
def test_controls_reject_changes_even_when_new_source_hash_is_updated(tmp_path,change):
    new,old=fixture(tmp_path)
    assert report.source_controls(new,old)['only_corpus_organization_changed']
    data=json.loads((new/'run.json').read_text('utf-8'))
    if change=='prompt':
        path=new/'backend/literature_rag/application/prompts.py';path.write_bytes(b'changed prompt\n')
        data['source_files']['literature_rag/application/prompts.py']=sha256(path.read_bytes()).hexdigest()
    elif change=='settings':data['configuration_probe']['top_k']=12
    elif change=='questions':data['tasks']=['different']
    else:data['dataset_manifest_sha256']='different'
    (new/'run.json').write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError):report.source_controls(new,old)


def test_pairing_excludes_missing_and_flagged_grades_without_zero_filling():
    m={('content','A'):metric(),('tables','A'):metric(.5),('content','B'):metric(),
       ('content','C'):metric(concern=True),('tables','C'):metric()}
    result=report.paired(m,['A','B','C'],'tables')
    assert result['task_ids']==['A'] and result['tasks']==1
    assert result['point_wins']==['A'] and result['scores']['content']['point_macro_average']==1
    assert len(result['exclusions'])==2


def test_html_escapes_untrusted_answers_and_keeps_missing_grade_label(tmp_path):
    values={('content','A'):metric(),('tables','A'):metric()}
    result=dict(comparisons={'tables':report.paired(values,['A'],'tables')})
    row=dict(task_id='A',question='Question',reference_answer='Reference',reference_case={'question':'Question'},
        systems={'content':dict(candidate={'answer':'<script>alert(1)</script>'},metrics=metric(),review={}),
                 'tables':dict(candidate={'answer':'Old'},metrics=None,review=None)},diagnostics={})
    path=tmp_path/'report.html';report.html_report(path,result,[row]);text=path.read_text('utf-8')
    assert '<script>alert(1)' not in text and '&lt;script&gt;alert(1)' in text
    assert '有效评分缺失' in text and '不生成自由文字理由' in text
