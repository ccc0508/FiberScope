"""Automatic subfigure grouping and original-PDF crops retain verified source identity."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

import fitz
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from index_literature_images import image_groups,build,plan
from reembed_literature import save,digest
from freeze_qa_baseline import library_fingerprint
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.visual_evidence import VisualCatalog
from literature_rag.config import Settings
from literature_rag.domain.models import Chunk,Document,DocumentStatus
from tests.test_body_context import body_catalog


def fixture(tmp_path):
    root=tmp_path/'source';(root/'papers').mkdir(parents=True)
    pdf=root/'papers/paper.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=1000,height=1000)
        for box in [(100,100,400,300),(420,100,800,300),(100,500,800,800)]:page.draw_rect(fitz.Rect(box),color=(0,0,1))
        doc.save(pdf)
    rows=[dict(type='image',page_idx=0,bbox=[10,10,40,40]),dict(type='text',text='Title',page_idx=0),
        dict(type='chart',page_idx=0,bbox=[100,100,400,300]),
        dict(type='chart',page_idx=0,bbox=[420,100,800,300],chart_caption=['Figure 1. Two panels.']),
        dict(type='text',text='Body',page_idx=0),
        dict(type='image',page_idx=0,bbox=[100,500,800,800],image_caption=['Figure 2. A schematic.'])]
    native=tmp_path/'native.json';save(native,rows)
    chunks=[Chunk('c1','doc','paper.pdf',1,1,0,'Figure 1. Two panels.',5,'qwen3-vl-embedding',kind='figure_caption'),
            Chunk('c2','doc','paper.pdf',1,1,1,'Figure 2. A schematic.',5,'qwen3-vl-embedding',kind='figure_caption')]
    store=SqliteMetadataStore(root/'metadata.sqlite3');store.initialize()
    store.upsert_document(Document('doc','paper.pdf',Path('papers/paper.pdf'),digest(pdf),pdf.stat().st_size,DocumentStatus.PENDING))
    store.complete_document('doc',1,chunks)
    catalog=body_catalog(chunks,['figure_caption','figure_caption'])
    for c,i in zip(chunks,[3,5],strict=True):
        catalog.mapping[c.id].update(source_spans=[dict(source_id=f'mineru_block_{i:04}',page=1,bbox=rows[i]['bbox'])],
            text_sha256=sha256(c.text.encode()).hexdigest())
    save(root/'structure.json',dict(status='ready',chunks=2,mapping=catalog.mapping,sections=list(catalog.sections.values()),
        native_content_sha256=digest(native),embedding_provider='dashscope',embedding_model='qwen3-vl-embedding',embedding_dimensions=256))
    (root/'chroma').mkdir()
    with sqlite3.connect(root/'chroma/chroma.sqlite3') as conn:conn.execute('CREATE TABLE fixture (id INTEGER)')
    settings=Settings(_env_file=None,embedding_provider='dashscope',embedding_model='qwen3-vl-embedding',embedding_dimensions=256)
    return root,native,settings


class Embedder:
    def __init__(self):self.paths=[];self.last_usage=None;self.last_calls=[]
    def embed_images(self,paths):
        self.paths.extend(paths);self.last_usage=dict(input_tokens=0,image_tokens=10,total_tokens=10)
        return [[1.]*256 for _ in paths]


def test_groups_include_all_subpanels_and_exclude_uncaptioned_logos(tmp_path):
    source,native,settings=fixture(tmp_path)
    groups=image_groups(json.loads(native.read_text(encoding='utf-8')))
    assert [g['label'] for g in groups]==['Figure 1','Figure 2']
    assert [i for i,_ in groups[0]['regions']]==[2,3]
    plans,_=plan(source,native)
    assert plans[0]['bbox'][0]<100 and plans[0]['bbox'][2]>800
    assert plans[0]['parent_chunk_id']=='c1'
    before=library_fingerprint(source);output=tmp_path/'new';embedder=Embedder()
    record=build(source,output,native,settings,embedder=embedder)
    assert record['status']=='ready' and len(embedder.paths)==2 and library_fingerprint(source)==before
    cat=VisualCatalog.load(output,SqliteMetadataStore(output/'metadata.sqlite3'),'dashscope','qwen3-vl-embedding',256)
    assert len(cat.assets)==2 and cat.assets[0].width>1000
    assert cat.manifest['source_regions'][cat.assets[0].id]==['mineru_block_0002','mineru_block_0003']
    again=Embedder();build(source,output,native,settings,embedder=again,resume=True)
    assert again.paths==[]


def test_wrong_native_or_embedding_fails_before_paid_image_calls(tmp_path):
    source,native,settings=fixture(tmp_path);embedder=Embedder()
    bad=tmp_path/'bad.json';bad.write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError):build(source,tmp_path/'new',bad,settings,embedder=embedder)
    wrong=Settings(_env_file=None,embedding_provider='dashscope',embedding_model='qwen3-vl-embedding',embedding_dimensions=512)
    with pytest.raises(ValueError,match='exact model'):build(source,tmp_path/'new',native,wrong,embedder=embedder)
    assert embedder.paths==[]
