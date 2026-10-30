"""Allowed-source controls, maximum paired subsets and hostile text escaping for table evaluation."""
from pathlib import Path
import json
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_table_evidence_20261030 as report


def metric(value=1,concern=False):
    return dict(point_mean=value,required_point_sum=value,required_point_count=1,
        support_counts={'supported':1},factual_claims=1,factual_citations=1,supported_citations=1,
        complete_groups=1,boundary=2,reference_concern=concern,all_five_pass=value==1)


def test_pairing_tracks_strict_pass_regressions_separately_from_point_improvement():
    m={('tables','A'):metric(1),('quality','A'):metric(.5),('tables','B'):metric(1),('quality','B'):metric(1),
       ('tables','C'):metric(1),('quality','D'):metric(1)}
    m[('tables','B')]['all_five_pass']=False
    result=report.paired(m,['A','B','C','D'],'quality')
    assert result['task_ids']==['A','B'] and result['point_wins']==['A']
    assert result['all_five_wins']==['A'] and result['all_five_losses']==['B']
    assert result['scores']['tables']['point_macro_average']==1
    assert len(result['exclusions'])==2


def controls_fixture(tmp_path):
    from hashlib import sha256
    dirs=[tmp_path/'new',tmp_path/'old']
    names=['literature_rag/application/prompts.py','literature_rag/application/citations.py',
        'literature_rag/application/answer_question.py','literature_rag/adapters/providers/deepseek.py',
        'literature_rag/application/context.py','literature_rag/application/retrieve.py']
    for index,directory in enumerate(dirs):
        sources={}
        for name in names:
            path=directory/'backend'/name;path.parent.mkdir(parents=True,exist_ok=True)
            content=b'same source\n' if name!='literature_rag/application/retrieve.py' else f'retrieval {index}\n'.encode()
            path.write_bytes(content);sources[name]=sha256(content).hexdigest()
        config=dict(llm_model='same',top_k=8,min_score=.35,context_expansion={'max_chars':24000},
                    prompt_pipeline_sha256=str(index),pipeline_version=str(index))
        if index==0:config['table_retrieval']=dict(enabled=True,version='table-evidence-v1')
        (directory/'run.json').write_text(json.dumps(dict(tasks=[dict(id='same')],source_files=sources,configuration_probe=config)),encoding='utf-8')
    return dirs


def test_controls_allow_only_declared_retrieval_changes_and_keep_prompts_equal(tmp_path):
    new,old=controls_fixture(tmp_path)
    proof=report.source_controls(new,old)
    assert proof['changed_source_files']==['literature_rag/application/retrieve.py']
    assert proof['same_answer_prompt_generator_and_citation_validator']


def test_controls_reject_undeclared_prompt_changes_even_with_updated_source_hash(tmp_path):
    from hashlib import sha256
    new,old=controls_fixture(tmp_path)
    path=new/'backend/literature_rag/application/prompts.py';path.write_bytes(b'new hidden prompt')
    contract=json.loads((new/'run.json').read_text(encoding='utf-8'))
    contract['source_files']['literature_rag/application/prompts.py']=sha256(path.read_bytes()).hexdigest()
    (new/'run.json').write_text(json.dumps(contract),encoding='utf-8')
    with pytest.raises(ValueError,match='Unapproved'):report.source_controls(new,old)


def test_report_escapes_candidate_and_displays_missing_grades(tmp_path):
    values={('tables','A'):metric(),('quality','A'):metric()}
    result=dict(valid_grades=1,comparisons={'quality':report.paired(values,['A'],'quality')})
    row=dict(task_id='A',question='Question',reference_answer='Reference',key_points=[],
        systems={'tables':dict(candidate={'answer':'<script>alert(1)</script>'},metrics=metric(),review={}),
                 'quality':dict(candidate={'answer':'Older answer'},metrics=None,review=None)},table_diagnostics={})
    path=tmp_path/'report.html';report.html_report(path,result,[row]);text=path.read_text(encoding='utf-8')
    assert '<script>alert(1)' not in text and '&lt;script&gt;alert(1)' in text
    assert '有效评分缺失' in text and '不生成自由文字理由' in text and '五项全部达标' in text
