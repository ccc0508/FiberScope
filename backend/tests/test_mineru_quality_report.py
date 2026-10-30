"""Jev-only matched subsets and escaped four-system report rendering, without model calls."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_mineru_quality_20261030 as report


def metric(point=1, concern=False):
    return dict(point_mean=point,required_point_sum=point,required_point_count=1,
        support_counts={'supported':1},factual_claims=1,factual_citations=1,supported_citations=1,
        complete_groups=1,boundary=2,reference_concern=concern,all_five_pass=point==1)


def test_pairing_excludes_missing_and_reference_concerns_without_zero_filling():
    values={('quality','A'):metric(.5),('sections','A'):metric(0),
            ('quality','B'):metric(1),('quality','C'):metric(1,True),('sections','C'):metric(1)}
    result=report.paired(values,['A','B','C'],'sections')
    assert result['task_ids']==['A'] and result['tasks']==1
    assert result['scores']['quality']['point_macro_average']==.5
    assert result['point_delta']==.5 and result['point_wins']==['A']
    assert result['exclusions']==[dict(task_id='B',unavailable=['sections']),dict(task_id='C',unavailable=['quality'])]


def test_each_comparison_uses_its_own_maximum_common_set():
    values={('quality',t):metric(1) for t in ['A','B','C']}
    values.update({('sections','A'):metric(.5),('sections','B'):metric(1),('pymupdf','A'):metric(1),('pymupdf','C'):metric(0)})
    assert report.paired(values,['A','B','C'],'sections')['task_ids']==['A','B']
    assert report.paired(values,['A','B','C'],'pymupdf')['task_ids']==['A','C']


def test_html_does_not_invent_jev_reasons_or_render_candidate_markup(tmp_path):
    values={('quality','A'):metric(1),('sections','A'):metric(.5)}
    result=dict(new_answer_runtime={'outcomes':{'answered':1}},new_valid_grades=1,
                comparisons={'sections':report.paired(values,['A'],'sections')})
    row=dict(task_id='A',question='<script>question()</script>',reference_answer='reference',key_points=[],
        systems={'quality':dict(candidate={'answer':'<img src=x onerror=alert(1)>'},metrics=metric(),review={'key_point_scores':{'P1':1}})},
        point_change_from_sections=.5,point_change_from_pymupdf=None)
    path=tmp_path/'report.html'
    report.html_report(path,result,[row])
    text=path.read_text(encoding='utf-8')
    assert '<img src=x' not in text and '&lt;img src=x' in text
    assert '<script>question()' not in text and '&lt;script&gt;question()' in text
    assert '不生成自由文字理由' in text and '新Luna调用0' in text
    assert 'data-search=' in text and '引用组完整' in text


def test_publication_refresh_is_idempotent_and_never_hashes_itself(tmp_path):
    output=tmp_path/'report';output.mkdir()
    document=tmp_path/'method.md';document.write_text('A preserved document.',encoding='utf-8')
    exporter=tmp_path/'exporter.py';exporter.write_text('print(1)',encoding='utf-8')
    (output/'comparison.json').write_text('{"unchanged":true}',encoding='utf-8')
    report.seal_publication(output,document,exporter)
    before=(output/'publication.json').read_bytes()
    value=report.seal_publication(output,document,exporter)
    assert 'publication.json' not in value['files'] and set(value['files'])=={'comparison.json'}
    assert (output/'publication.json').read_bytes()==before
