"""Re-embedding preserves scientific sources and resumes without repaying valid batches."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from reembed_literature import build, digest, save
from freeze_qa_baseline import library_fingerprint
from index_table_evidence import plan as table_plan
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.body_context import BodySectionCatalog
from literature_rag.application.table_evidence import TableRelations
from literature_rag.config import Settings
from literature_rag.domain.errors import ProviderError
from tests.test_body_table_context import source_library


def fixture(tmp_path):
    source,chunks=source_library(tmp_path)
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    for c in chunks:structure['mapping'][c.id]['text_sha256']=sha256(c.text.encode()).hexdigest()
    save(source/'structure.json',structure)
    table=table_plan(source)
    table['embedding']=dict(provider='openai',model='fake',dimensions=3)
    save(source/'table-row-vectors.json',dict(rows=[dict(id=r['id'],vector=[1.,0.,0.]) for r in table['rows']]))
    table['row_vectors_sha256']=digest(source/'table-row-vectors.json')
    save(source/'table-retrieval.json',table)
    structure['table_evidence']=dict(manifest_sha256=digest(source/'table-retrieval.json'),vectors_sha256=table['row_vectors_sha256'])
    save(source/'structure.json',structure)
    (source/'chroma').mkdir()
    with sqlite3.connect(source/'chroma/chroma.sqlite3') as conn:conn.execute('CREATE TABLE marker (id INTEGER)')
    settings=Settings(_env_file=None,embedding_provider='dashscope',embedding_model='qwen3-vl-embedding',
        embedding_dimensions=256,embedding_batch_size=2)
    return source,chunks,settings


class Embedder:
    def __init__(self,fail_at=None):self.texts=[];self.last_usage=None;self.fail_at=fail_at;self.last_calls=[]
    def embed_documents(self,texts):
        self.texts.append(list(texts))
        if len(self.texts)==self.fail_at:
            self.last_usage=None
            raise ProviderError('simulated unavailable')
        self.last_usage=dict(input_tokens=10,image_tokens=0,total_tokens=10)
        self.last_calls=[dict(status='completed',api_calls=1,usage=self.last_usage)]
        return [[1.]*256 for _ in texts]


def test_new_index_preserves_ids_text_sections_links_and_uses_one_new_model_everywhere(tmp_path):
    source,chunks,settings=fixture(tmp_path);before=library_fingerprint(source)
    output=tmp_path/'new';embedder=Embedder()
    result=build(source,output,settings,embedder=embedder)
    assert result['status']=='ready' and len(embedder.texts)==3 and library_fingerprint(source)==before
    old=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    new=json.loads((output/'structure.json').read_text(encoding='utf-8'))
    assert new['mapping']==old['mapping'] and new['sections']==old['sections']
    metadata=SqliteMetadataStore(output/'metadata.sqlite3')
    got=metadata.get_chunks([c.id for c in chunks])
    assert [(c.id,c.text,c.chunk_index,c.kind) for c in got]==[(c.id,c.text,c.chunk_index,c.kind) for c in chunks]
    assert {c.embedding_model for c in got}=={'qwen3-vl-embedding'}
    rel=TableRelations.load(output,metadata,'dashscope','qwen3-vl-embedding',256)
    rel.validate_body_catalog(BodySectionCatalog.load(output,metadata))
    with pytest.raises(Exception):TableRelations.load(output,metadata,'openai','fake',3)
    assert build(source,output,settings,resume=True,embedder=Embedder())['status']=='ready'
    with pytest.raises(ValueError):build(source,source,settings,embedder=Embedder())
    with pytest.raises(ValueError):build(source,output,settings,embedder=Embedder())


def test_retry_uses_completed_cache_and_refuses_unknown_inflight_paid_request(tmp_path):
    source,chunks,settings=fixture(tmp_path);output=tmp_path/'new'
    failed=Embedder(fail_at=2)
    with pytest.raises(ProviderError):build(source,output,settings,embedder=failed)
    ledger=json.loads((output/'embedding-reindex.json').read_text(encoding='utf-8'))
    assert ledger['status']=='failed' and [c['status'] for c in ledger['calls']]==['completed','failed']
    resumed=Embedder();result=build(source,output,settings,resume=True,embedder=resumed)
    assert result['status']=='ready' and len(resumed.texts)==2
    assert failed.texts[0] not in resumed.texts
    ledger=json.loads((output/'embedding-reindex.json').read_text(encoding='utf-8'))
    ledger['status']='failed';ledger['calls'][-1]['status']='started';save(output/'embedding-reindex.json',ledger)
    blocked=Embedder()
    with pytest.raises(ValueError,match='Interrupted paid request'):build(source,output,settings,resume=True,embedder=blocked)
    assert blocked.texts==[]
