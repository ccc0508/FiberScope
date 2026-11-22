from pathlib import Path
from types import SimpleNamespace
import sys

import fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from index_table_evidence import build_table_links
from mineru_table_reference_recovery import recover_table_references


def sources(text):
    body=SimpleNamespace(id='body',document_id='paper',kind='paragraph',chunk_index=1,text=text)
    table=SimpleNamespace(id='table',document_id='paper',kind='table',chunk_index=2,text='表2 数据')
    mapping={body.id:dict(content_role='body',role_status='identified',body_text=text,
        source_spans=[dict(source_id='native_body',page=1,bbox=[40,40,925,420],text=text)]),
        table.id:dict(content_role='table',role_status='identified',body_text=table.text)}
    return [body,table],mapping


def test_restore_unique_pdf_number_and_build_link_without_rewriting_evidence():
    text='各类样品的实验结果如表 所示。低温时有所变化。'
    chunks,mapping=sources(text)
    with fitz.open() as pdf:
        p=pdf.new_page(width=300,height=300)
        p.insert_text((23,42),text.replace('表 ','表2'),fontname='china-s',fontsize=11)
        p.insert_text((23,250),text.replace('表 ','表9'),fontname='china-s',fontsize=11)
        recovered,ledger=recover_table_references(pdf,chunks,mapping,ocr=None)
    assert recovered=={'body':{2}}
    assert len(ledger)==1 and ledger[0]['method']=='pdf_text_layer'
    assert {(l['source_chunk_id'],l['target_chunk_id']) for l in build_table_links(chunks,mapping,recovered)}=={
        ('body','table'),('table','body')}
    assert chunks[0].text==text and mapping['body']['body_text']==text


def test_abstain_when_pdf_region_contains_two_matching_references():
    text='各类样品的实验结果如表 所示。低温时有所变化。'
    chunks,mapping=sources(text)
    with fitz.open() as pdf:
        p=pdf.new_page(width=320,height=300)
        for y,num in [(35,2),(64,3)]:
            p.insert_text((23,y),text.replace('表 ',f'表{num}'),fontname='china-s',fontsize=10)
        recovered,ledger=recover_table_references(pdf,chunks,mapping,ocr=None)
    assert not recovered and ledger[0]['reason']=='ambiguous_pdf_alignment'


def test_ocr_only_receives_the_local_crop_and_confirms_unique_row():
    text='各类样品的实验结果如表 所示。低温时有所变化。'
    chunks,mapping=sources(text)
    images=[]
    def recognize(png):
        images.append(png)
        return text.replace('表 ','表 2 ')
    with fitz.open() as pdf:
        p=pdf.new_page(width=320,height=300)
        p.insert_text((23,35),text,fontname='china-s',fontsize=10)
        recovered,ledger=recover_table_references(pdf,chunks,mapping,ocr=recognize)
    assert recovered=={'body':{2}} and len(images)==1
    assert ledger[0]['method']=='local_ocr' and ledger[0]['ocr_rect_points'][3]<100
    assert images[0].startswith(b'\x89PNG')
