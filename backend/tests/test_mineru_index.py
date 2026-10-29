"""Preserve raw parser output, table integrity, and original-page citation checks."""
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import index_mineru_experiment as indexing
import import_qa_system_answers as importer


def block(kind,text='',page=0,**fields):
    return dict(type=kind,text=text,page_idx=page,bbox=[10,20,300,400],**fields)


def test_native_boundaries_errors_and_caption_scope_are_preserved():
    raw=[block('header','Journal'),block('text','duplicate duplicate',text_level=2),
         block('chart',img_path='images/a.png',chart_caption=[]),
         block('chart',img_path='images/b.png',chart_caption=['Figure 1. Measured result.']),
         block('ref_text','Original reference.')]
    units,excluded=indexing.native_units(raw,1)
    assert [u['text'] for u in units]==['duplicate duplicate','Figure 1. Measured result.','Original reference.']
    assert units[0]['kind']=='heading' and units[0]['native_text_level']==2
    assert units[1]['kind']=='figure_caption' and units[1]['image_path']=='images/b.png'
    assert {x['reason'] for x in excluded}=={'page_auxiliary','no_textual_content'}
    assert raw[1]['text']=='duplicate duplicate'


def test_table_remains_one_unit_and_oversized_table_fails_without_truncation():
    raw=[block('table',table_caption=['Table 1'],table_body='<table><tr><td>3.14</td></tr></table>',table_footnote=['units'])]
    units,_=indexing.native_units(raw,1)
    assert len(units)==1 and units[0]['kind']=='table' and '3.14' in units[0]['text'] and units[0]['text'].endswith('units')
    with pytest.raises(ValueError,match='budget'):indexing.native_units(raw,1,max_chars=10)


@pytest.mark.parametrize('change',[dict(page_idx=-1),dict(page_idx=1),dict(bbox=[1,2,1001,4]),dict(bbox=[100,20,10,30])])
def test_bad_original_page_locator_is_rejected(change):
    bad=block('text','source');bad.update(change)
    with pytest.raises(ValueError):indexing.native_units([bad],1)


def test_parser_quote_mismatch_requires_original_page_review_without_repair():
    evidence=dict(ref='[1]',page_start=1,page_end=1,text='The value is 20%.')
    variants={'original':['The value is 10%.']}
    citation=importer.rag_citation(evidence,variants)
    assert citation['verification']['status']=='needs_source_review'
    assert citation['text']=='The value is 20%.'
    assert importer.rag_citation(evidence)['verification']['status']=='frozen_chunk_metadata_verified'
