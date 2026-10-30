"""Cross-format section rules, exact scientific-text coverage, and safe fallbacks."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from index_mineru_experiment import native_units
from mineru_sections import organize


def b(text,level=None,page=0,kind='text',**fields):
    result=dict(type=kind,text=text,page_idx=page,bbox=[10,20,500,80],**fields)
    if level is not None:
        result['text_level']=level
    return result


def run(raw,target=1200):
    units,_=native_units(raw,max(x['page_idx'] for x in raw)+1,max_chars=100000)
    result=organize(units,'test_document',raw,target_chars=target)
    assert result['source_coverage']['exact_once']
    return result


def test_numbered_levels_override_flat_parser_levels_and_keep_cross_page_membership():
    raw=[b('2. Methods',2),b('2.1. Laboratory procedure',2),b('A complete method.',page=0),
         b('The same method continues here.',page=1),b('2.2. Characterization',2,page=1),b('A distinct measurement.',page=1)]
    result=run(raw)
    assert result['sections'][1]['parent_id']==result['sections'][0]['id']
    assert result['sections'][1]['path']==['2. Methods','2.1. Laboratory procedure']
    assert result['chunks'][0]['section_id']==result['chunks'][1]['section_id']
    assert result['chunks'][-1]['section_id']!=result['chunks'][0]['section_id']
    assert all(c['kind']!='heading' for c in result['chunks'])


def test_repeated_titles_mixed_caption_prefix_and_numeric_annotation_do_not_rewrite_sources():
    raw=[b('3. Results',2),b('3.1. Morphology3.1. Morphology',2),
         b('caption tail3.2. Crystal structure',2),b('The index is 70.42%. It later reaches 72.54%.'),b('4.1 nm',2)]
    before=deepcopy(raw);result=run(raw)
    assert raw==before
    assert [s['number'] for s in result['sections']]==['3','3.1','3.2']
    assert result['sections'][1]['title']=='3.1. Morphology'
    assert any('caption tail' in c['body_text'] for c in result['chunks'])
    assert any('70.42%' in c['body_text'] and '72.54%' in c['body_text'] for c in result['chunks'])
    assert any('4.1 nm' in c['body_text'] for c in result['chunks'])
    assert {a['code'] for a in result['anomalies']} >= {'measurement_annotation','mixed_heading_prefix_preserved','repeated_title_label_collapsed_raw_preserved'}


def test_unnumbered_paper_uses_layout_levels_without_assuming_this_papers_titles():
    raw=[b('Introduction',2),b('Background for a different experiment.'),b('Experimental setup',2),
         b('Chemical pretreatment',3),b('Conditions for a new kind of pulp.'),b('Results',2),b('Independent result.')]
    result=run(raw)
    assert result['sections'][2]['parent_id']==result['sections'][1]['id']
    assert result['chunks'][1]['section_path']==['Experimental setup','Chemical pretreatment']
    assert result['chunks'][-1]['section_path']==['Results']


def test_unknown_section_falls_back_without_inventing_a_parent_or_losing_text():
    result=run([b('3.2. Standalone section',2),b('Content with an unavailable parent.'),
                b('A wrongly tagged entire sentence.',2),b('Following text has uncertain section ownership.')])
    assert result['sections'][0]['parent_id'] is None
    assert result['chunks'][0]['section_status']=='parent_unresolved'
    assert result['chunks'][-1]['section_status']=='unassigned'
    assert result['chunks'][-1]['section_path']==[]


def test_short_paragraphs_merge_only_within_section_and_tables_stay_atomic():
    table='<table><tr><td>70.42</td><td>%</td></tr></table>'
    result=run([b('1. Experiments',2),b('First short paragraph.'),b('Second short paragraph.'),
                b('',kind='table',table_caption=['Table 1.'],table_body=table,table_footnote=['Measured at 4000 r.']),
                b('2. Results',2),b('A separate result.')])
    assert len(result['chunks'])==3
    assert result['chunks'][0]['body_text']=='First short paragraph.\n\nSecond short paragraph.'
    assert result['chunks'][1]['kind']=='table' and table in result['chunks'][1]['body_text']
    assert result['chunks'][2]['section_path']==['2. Results']


def test_sentence_splits_preserve_exact_offsets_and_reading_order():
    text=' '.join(f'Experiment {i} measures the same source value of 70.42 percent.' for i in range(90))
    result=run([b('1. Results',2),b(text)],target=200)
    spans=[s for c in result['chunks'] for s in c['source_spans']]
    assert ''.join(s['text'] for s in spans)==text
    assert all(s['text']==text[s['start']:s['end']] for s in spans)
    assert len(result['chunks'])>5


def test_oversized_atomic_table_fails_instead_of_truncating_rows():
    with pytest.raises(ValueError,match='Atomic source'):
        run([b('1. Results',2),b('',kind='table',table_body='<table>'+('row '*2200)+'</table>')])


def test_references_keep_their_type_and_remain_searchable_in_this_ablation():
    result=run([b('5. References',2),b('1. A paper with original metadata.',kind='ref_text')])
    assert result['sections'][0]['role']=='references'
    assert result['chunks'][0]['kind']=='reference'
    assert 'original metadata' in result['chunks'][0]['body_text']


def test_paper_title_after_front_matter_is_document_metadata_not_a_section():
    result=run([b('Article'),b('A New Study of Fibers and Paper',1),b('Authors and affiliations.'),
                b('1. Introduction',2),b('The scientific introduction.')])
    assert len(result['document_titles'])==1
    assert [s['title'] for s in result['sections']]==['1. Introduction']


def test_software_version_in_a_continued_sentence_is_not_a_section():
    result=run([b('3. Results',2),b('3.2. Crystals',2),
                b('5.2.1 software). The measured value is consistent with another study.')])
    assert [s['number'] for s in result['sections']]==['3','3.2']
    assert result['chunks'][0]['section_path']==['3. Results','3.2. Crystals']


def test_html_duplicate_title_changes_only_the_metadata_label():
    raw='<sub>3. Results</sub><sup>3.</sup> <sup>Results</sup>'
    result=run([b(raw,2),b('Original scientific text.')])
    assert result['sections'][0]['title']=='3. Results'
    assert result['sections'][0]['source_spans'][0]['text']==raw


def test_confirmed_sentence_continuation_can_cross_a_page_and_keeps_both_locators():
    result=run([b('1. Methods',2),b('The first part continues'),
                b('Journal running header',page=0,kind='header'),b('on the next page.',page=1)])
    assert len(result['chunks'])==1
    assert (result['chunks'][0]['page_start'],result['chunks'][0]['page_end'])==(1,2)
    assert [s['page'] for s in result['chunks'][0]['source_spans']]==[1,2]


def test_picture_without_caption_is_still_a_merge_barrier():
    result=run([b('1. Results',2),b('First sentence.'),
                b('',kind='chart',chart_caption=[]),b('Second sentence.')])
    assert len(result['chunks'])==2
