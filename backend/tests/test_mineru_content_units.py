"""Exact source conservation, metadata/annotation roles, formula context and page-boundary guards."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from index_mineru_experiment import native_units
from mineru_content_units import process


def block(text='',kind='text',page=0,bbox=None,level=None,**fields):
    result=dict(type=kind,text=text,page_idx=page,bbox=bbox or [100,200,850,300],**fields)
    if level is not None:result['text_level']=level
    return result


def run(blocks):
    units,_=native_units(blocks,max(b['page_idx'] for b in blocks)+1,max_chars=100000)
    return process(units,'test',blocks)


def test_article_and_keywords_saved_as_metadata_without_losing_chars_or_body():
    raw=[block('Article',bbox=[100,110,200,130]),block('Keywords: fibers; refining'),
         block('1. Methods',level=2),block('Actual conditions: 10% pulp consistency.')]
    before=deepcopy(raw);result=run(raw)
    assert raw==before
    assert {c['role'] for c in result['document_metadata']}=={'publication_type','keywords'}
    assert all(c['kind']!='document_metadata' for c in result['chunks'])
    assert result['source_coverage']['characters']==sum(len(b['text']) for b in raw)
    assert '10%' in result['chunks'][0]['text']


def test_measurement_near_figure_attaches_to_caption_and_never_merges_into_prose():
    raw=[block('3. Results',level=2),block('Software continuation ends here.'),
         block('2.7 nm',bbox=[400,150,500,170]),
         block(kind='image',bbox=[200,185,800,500],image_caption=['Figure 1. A fiber structure.']),
         block('The following scientific result.')]
    result=run(raw)
    figure=next(c for c in result['chunks'] if c['kind']=='figure_caption')
    assert '2.7 nm' in figure['body_text'] and 'A fiber structure' in figure['body_text']
    assert all('2.7 nm' not in c['body_text'] for c in result['chunks'] if c['kind']=='paragraph')
    assert figure['organization']['visual_source_id']=='mineru_block_0003'


def test_plain_measurement_without_visual_layout_is_not_assumed_to_be_image_annotation():
    result=run([block('1. Results',level=2),block('2.7 nm'),block('A complete separate measurement explanation.')])
    assert not any(e['kind']=='figure_annotation_classified' for e in result['events'])
    assert '2.7 nm' in ''.join(c['body_text'] for c in result['chunks'])


def test_formula_has_its_name_condition_variables_and_units_in_one_bundle():
    raw=[block('2. Methods',level=2),block('The WRV was measured with 0.5 g samples.'),
         block('$$ WRV=(m_1-m_2)/m_2 $$',kind='equation'),
         block('where m_1 is the centrifuged mass and m_2 is the dry mass, both in g.'),
         block('This next paragraph concerns another experiment.')]
    result=run(raw)
    bundle=next(c for c in result['chunks'] if c['kind']=='equation_bundle')
    assert all(t in bundle['body_text'] for t in ['0.5 g','WRV=','m_1 is','both in g'])
    assert 'another experiment' not in bundle['body_text']
    assert len(bundle['source_spans'])==3
    assert result['source_coverage']['exact_once']


def test_formula_does_not_take_neighbor_from_different_section():
    raw=[block('2. Methods',level=2),block('2.1. Sample preparation',level=2),block('A previous procedure.'),
         block('2.2. Calculation',level=2),block('$$ y=x $$',kind='equation'),block('where x is the input.')]
    result=run(raw)
    bundle=next(c for c in result['chunks'] if c['kind']=='equation_bundle')
    assert 'previous procedure' not in bundle['body_text']


def test_shared_formula_neighbor_is_not_duplicated_between_bundles():
    result=run([block('1. Methods',level=2),block('$$ x=a $$',kind='equation'),
        block('where a is a known constant. Equation (2) follows.'),block('$$ y=b $$',kind='equation'),block('where b is another constant.')])
    assert len([c for c in result['chunks'] if c['kind']=='equation_bundle'])==2
    assert sum(c['body_text'].count('where a is') for c in result['chunks'])==1
    assert result['source_coverage']['exact_once']


def test_cross_page_software_version_continuation_preserves_both_source_positions():
    result=run([block('3. Results',level=2),block('Drawn using the plotting software',bbox=[100,800,850,900]),
                block('Journal header',kind='header'),block('5.2.1 software). This is consistent with the reported result.',page=1,bbox=[100,100,850,145])])
    joined=next(c for c in result['chunks'] if c.get('organization',{}).get('kind')=='page_boundary_sentence_continuation')
    assert (joined['page_start'],joined['page_end'])==(1,2)
    assert [s['page'] for s in joined['source_spans']]==[1,2]
    assert any(e['kind']=='page_continuation_joined' for e in result['events'])


@pytest.mark.parametrize('ending,beginning,position',[('A finished sentence.','3.5 software).',100),('An unfinished sentence','A new sentence.',100),('An unfinished sentence','4.2 software).',400)])
def test_cross_page_guard_rejects_complete_sentences_new_sentences_and_middle_page_text(ending,beginning,position):
    result=run([block('1. Methods',level=2),block(ending,bbox=[100,800,850,900]),
                block(beginning,page=1,bbox=[100,position,850,position+40])])
    assert not any(e['kind']=='page_continuation_joined' for e in result['events'])


def test_actual_paper_has_five_bundles_two_metadata_fields_and_one_safe_continuation():
    from index_mineru_content import prepare
    source=ROOT/'.rag-data/index-versions/table-evidence-v1-20261030'
    if not source.exists():pytest.skip('Private sealed integration corpus is not distributed')
    _,_,organized,chunks,_,reused,info=prepare(source)
    assert info['chunks']==85 and info['chunk_kinds']['equation_bundle']==5
    assert info['document_metadata']==2 and info['source_coverage']['exact_once']
    assert len(reused)==76 and info['new_vectors']==9
    assert len([e for e in info['events'] if e['kind']=='page_continuation_joined'])==1
    assert all('4.1 nm' not in c['body_text'] for c in organized['chunks'] if c['kind']=='paragraph')
    assert len([c for c in chunks if c.kind=='table'])==2
