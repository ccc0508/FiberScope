"""Role boundaries, abstention, metadata lookalikes, and exact span preservation."""
from pathlib import Path
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from index_mineru_experiment import native_units
from mineru_roles import classify,organize_roles


def run(texts):
    raw=[dict(type=kind,text=text,page_idx=page,bbox=[10,20,900,90],**({'text_level':level} if level else {}))
        for text,kind,level,page in texts]
    units,_=native_units(raw,max(b['page_idx'] for b in raw)+1,max_chars=100000)
    return organize_roles(units,'document',raw),units


def b(text,kind='text',level=None,page=0):return text,kind,level,page


def test_front_matter_roles_remain_distinct_and_source_characters_unchanged():
    result,units=run([b('Jane Smith, John Doe and Alice Green'),b('Department of Chemistry, Example University; a@example.edu'),
        b('Received: 1 January; Accepted: 2 March'),b('Abstract: Fibers increase the measured strength.'),b('Keywords: fibers; paper'),
        b('1. Introduction',level=2),b('First body paragraph.'),b('Second body paragraph.')])
    assert [c['content_role'] for c in result['chunks']]==['authors','affiliation','dates','abstract','keywords','body']
    assert result['chunks'][-1]['body_text']=='First body paragraph.\n\nSecond body paragraph.'
    assert result['source_coverage']['exact_once']
    assert Counter(s['source_id'] for c in result['chunks'] for s in c['source_spans'])['mineru_block_0000']==1


def test_chinese_labels_and_multi_paragraph_abstract_do_not_absorb_keywords():
    result,_=run([b('作者：张三、李四'),b('工作单位：某某大学'),b('摘要',level=2),b('第一段摘要。'),b('第二段摘要。'),
        b('关键词：纤维；纸张'),b('1. 引言',level=2),b('正文。')])
    assert [c['content_role'] for c in result['chunks']]==['authors','affiliation','abstract','keywords','body']
    assert '第二段摘要' in result['chunks'][2]['body_text'] and '关键词' not in result['chunks'][2]['body_text']


def test_structured_abstract_uses_heading_depth_and_stops_at_introduction():
    result,_=run([b('Abstract',level=2),b('Background',level=3),b('The background.'),b('Methods',level=3),b('The abstract method.'),
        b('Introduction',level=2),b('The scientific body discusses an abstract concept and author identity.')])
    roles=result['native_roles'];assert roles['mineru_block_0004']['role']=='abstract'
    assert roles['mineru_block_0006']['role']=='body'


def test_native_reference_type_does_not_override_copyright_or_publisher_notice():
    result,_=run([b('References',level=2),b('1. Smith, J. A study. Journal 2020, 1, 1–9.',kind='ref_text'),
        b('Publisher’s Note: The publisher remains neutral.',kind='ref_text'),
        b('© 2020 by the authors. This article is open access.',kind='ref_text')])
    assert [c['content_role'] for c in result['chunks']]==['reference','publisher_note','copyright']
    assert all(len(c['source_spans'])==1 for c in result['chunks'])


def test_unknown_and_mixed_blocks_stay_independent_and_are_not_invented_as_authors():
    result,_=run([b('Unknown front text'),b('Another unknown front text'),
        b('Abstract: Results are mixed. Keywords: fibers; paper'),b('1. Introduction',level=2),
        b('The university measured an abstract concept.')])
    assert [c['content_role'] for c in result['chunks'][:3]]==['unknown','unknown','mixed']
    assert result['chunks'][-1]['content_role']=='body'


def test_different_reference_entries_do_not_merge_and_inline_citations_are_body():
    result,_=run([b('1. Introduction',level=2),b('Previous work [1] reports the result in 2020.'),b('References',level=2),
        b('1. Smith, J. Study A. Journal 2020.',kind='ref_text'),b('2. Doe, J. Study B. Journal 2021.',kind='ref_text')])
    assert [c['content_role'] for c in result['chunks']]==['body','reference','reference']


def test_separate_funding_heading_contains_its_paragraph_and_stops_at_references():
    result,_=run([b('1. Results',level=2),b('Some results.'),b('Funding',level=2),
        b('This work was supported by a university grant.'),b('References',level=2),
        b('1. Smith. A study. Journal 2020.',kind='ref_text')])
    assert result['native_roles']['mineru_block_0003']['role']=='funding'
    assert result['native_roles']['mineru_block_0005']['role']=='reference'


def test_embedded_keyword_label_without_punctuation_is_mixed_not_a_pure_abstract():
    result,_=run([b('Abstract: Some extracted results Keywords: fibers'),b('1. Introduction',level=2),b('Body.')])
    assert result['chunks'][0]['content_role']=='mixed' and result['chunks'][0]['role_status']=='uncertain'


def test_long_abstract_can_split_but_all_parts_share_abstract_identity():
    text='Abstract: '+' '.join('Fibers exhibit a measured increase in strength.' for _ in range(90))
    result,_=run([b(text),b('Keywords: fibers'),b('Introduction',level=2),b('Body.')])
    abstracts=[c for c in result['chunks'] if c['content_role']=='abstract']
    assert len(abstracts)>1 and len({c['role_group'] for c in abstracts})==1
    assert ''.join(s['text'] for c in abstracts for s in c['source_spans'])==text
