"""Create a sealed role-aware chunk preview and SQLite library, without embedding calls."""
from collections import Counter
from dataclasses import asdict,replace
from hashlib import sha256
from html import escape
from pathlib import Path
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.domain.models import Chunk,Document,DocumentStatus
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from index_mineru_experiment import native_units
from mineru_roles import organize_roles,VERSION
from section_context_20261031 import save

SOURCE=ROOT/'.rag-data/evaluations/pfi-mineru-sections-v2-20261030-r1/library'
OUTPUT=ROOT/'.rag-data/index-versions/content-roles-v1-20261031'
PUBLIC=ROOT/'data/literature/parsing-comparisons/content-roles-v1-20261031'


def build():
    if OUTPUT.exists() or PUBLIC.exists():raise ValueError('Never overwrite a sealed preview')
    old=json.loads((SOURCE/'structure.json').read_text('utf-8'))
    pages=json.loads((SOURCE/'source-pages.json').read_text('utf-8'))
    blocks=[{k:v for k,v in b.items() if k!='source_id'} for p in pages for b in p['native_blocks']]
    units,excluded=native_units(blocks,len(pages),max_chars=1000000)
    result=organize_roles(units,old['source_documents'][0]['id'],blocks)
    with sqlite3.connect((SOURCE/'metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rawdoc=dict(db.execute('select * from documents').fetchone())
        oldchunks=[dict(r) for r in db.execute('select * from chunks order by chunk_index')]
    # Source page snapshots preserve native order; do not reconstruct a new order from bboxes.
    old_by_index={m['preview_index']:cid for cid,m in old['mapping'].items()}
    mapping={};chunks=[];projection={cid:[] for cid in old['mapping']}
    for i,c in enumerate(result['chunks']):
        cid='chk_'+sha256(f'{VERSION}|{rawdoc["id"]}|{i}|{c["text"]}'.encode()).hexdigest()[:20]
        chunks.append(Chunk(cid,rawdoc['id'],rawdoc['filename'],c['page_start'],c['page_end'],i,c['text'],
            (len(c['text'])+3)//4,old['embedding_model'],kind=c['kind']))
        mapping[cid]={k:v for k,v in c.items() if k!='text'}
        mapping[cid]['text_sha256']=sha256(c['text'].encode()).hexdigest()
        parent=old_by_index[c['parent_chunk_index']];mapping[cid]['parent_chunk_id']=parent;projection[parent].append(cid)
    for cid,children in projection.items():
        expected=old['mapping'][cid]['source_spans'];actual=[s for child in children for s in mapping[child]['source_spans']]
        if expected!=actual:raise ValueError('Primary projection changes original text or span order')
    OUTPUT.mkdir(parents=True);PUBLIC.mkdir(parents=True)
    store=SqliteMetadataStore(OUTPUT/'metadata.sqlite3');store.initialize()
    doc=SqliteMetadataStore._to_document(rawdoc);store.upsert_document(replace(doc,status=DocumentStatus.PENDING,chunk_count=0))
    store.complete_document(doc.id,doc.page_count,chunks)
    manifest={**old,'version':VERSION,'chunks':len(chunks),'mapping':mapping,'sections':result['sections'],
        'native_roles':result['native_roles'],'chunk_kinds':result['chunk_kinds'],'content_role_counts':result['content_role_counts'],
        'source_coverage':result['source_coverage'],'projection':projection,'unit_policy':result['policy'],
        'embedding_calls':[],'vector_index_built':False,'parent_structure_sha256':sha256((SOURCE/'structure.json').read_bytes()).hexdigest(),
        'role_rules_sha256':sha256((ROOT/'scripts/mineru_roles.py').read_bytes()).hexdigest()}
    save(OUTPUT/'structure.json',manifest)
    save(PUBLIC/'roles-and-chunks.json',manifest)
    save(PUBLIC/'summary.json',dict(version=VERSION,old_chunks=len(oldchunks),new_chunks=len(chunks),
        content_roles=result['content_role_counts'],native_roles=dict(Counter(r['role'] for r in result['native_roles'].values())),
        source_coverage=result['source_coverage'],primary_projection_exact=True,model_calls=0,embedding_calls=0,vector_index_built=False,
        classification_accuracy=None,classification_note='Role labels are rule evidence; no independent multi-paper gold set accuracy is claimed.'))
    e=lambda x:escape(str(x),quote=True)
    h=['<!doctype html><meta charset="utf-8"><title>MinerU内容分类与组块</title><style>body{font:15px/1.7 system-ui;margin:30px auto;max-width:1250px;padding:20px;background:#f3f6fa;color:#203247}details{background:white;padding:14px;margin:12px 0;border:1px solid #dce5ef}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style>',
       '<h1>MinerU内容分类与组块</h1><p>原文与源位置保留；分类为规则推断，不是已验证的正确概率。未知/混合内容保持独立；没有重新解析PDF或建立向量索引。</p>']
    for c in chunks:
        m=mapping[c.id]
        h+=['<details><summary>'+e(f'{c.chunk_index} · {m["content_role"]} · {m["role_status"]} · 第{c.page_start}–{c.page_end}页')+'</summary>',
            '<p>'+e(', '.join(m['role_signals']))+'</p><pre>'+e(c.text)+'</pre><pre>'+e(json.dumps(m['source_spans'],ensure_ascii=False,indent=2))+'</pre></details>']
    (PUBLIC/'comparison.html').write_text('\n'.join(h),encoding='utf-8',newline='\n')
    save(PUBLIC/'publication.json',dict(files={p.name:sha256(p.read_bytes()).hexdigest() for p in PUBLIC.iterdir() if p.is_file()},
        model_calls=0,classification_accuracy=None))
    return json.loads((PUBLIC/'summary.json').read_text('utf-8'))


if __name__=='__main__':
    try:print(json.dumps(build(),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Preserve previous snapshots; inspect offline classification.')));raise SystemExit(1)
