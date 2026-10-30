"""Build an isolated content-organized index, reusing all unchanged parent and table-row vectors."""
from argparse import ArgumentParser
from collections import Counter,defaultdict
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.domain.models import Chunk,VectorRecord
from mineru_content_units import VERSION,process
from index_table_evidence import plan as table_plan


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def key(chunk):
    return (chunk.kind,chunk.page_start,chunk.page_end,chunk.text)


def prepare(source):
    source=Path(source).resolve()
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    if structure.get('status')!='ready':raise ValueError('Source index is not ready')
    for name,field in [('native-source.json','native_source_sha256'),('quality-ledger.json','quality_ledger_sha256')]:
        if digest(source/name)!=structure[field]:raise ValueError('Original parsing or correction ledger changed')
    native=json.loads((source/'native-source.json').read_text(encoding='utf-8'))
    ledger=json.loads((source/'quality-ledger.json').read_text(encoding='utf-8'))
    corrections={r['source_id']:r for r in ledger}
    units=deepcopy(native['units'])
    for unit in units:
        entry=corrections.get(unit['source_id'])
        if entry:
            if entry['status']=='pending' or unit['text']!=entry['original_text']:raise ValueError('Incomplete or changed correction source')
            unit.update(text=entry['corrected_text'],kind=entry['corrected_kind'],native_text_level=entry['corrected_text_level'])
    organized=process(units,native['document_id'],native['blocks'])
    store=SqliteMetadataStore(source/'metadata.sqlite3')
    docs=store.list_documents()
    if len(docs)!=1 or docs[0].id!=native['document_id']:raise ValueError('Expected the sealed single-document corpus')
    document=docs[0]
    with sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        ids=[r[0] for r in conn.execute('SELECT id FROM chunks ORDER BY chunk_index')]
    old_chunks=store.get_chunks(ids)
    lookup=defaultdict(list)
    for c in old_chunks:lookup[key(c)].append(c)
    chunks=[];mapping={};reused=[]
    for i,unit in enumerate(organized['chunks']):
        old=lookup.get((unit['kind'],unit['page_start'],unit['page_end'],unit['text']),[])
        provenance=[]
        for span in unit['source_spans']:
            entry=corrections.get(span['source_id'])
            regions=entry.get('verified_regions',[]) if entry else []
            provenance.append(dict(source_id=span['source_id'],page=span['page'],bbox=span['bbox'],
                view_start=span['start'],view_end=span['end'],
                offset_space='corrected_unit' if entry and entry['status']=='accepted_correction' else 'native_unit',
                correction_id=entry['id'] if entry else None,
                status=entry['status'] if entry else 'not_flagged_not_reviewed',verified_regions=regions))
        pages=[r['page'] for p in provenance for r in p['verified_regions']]
        if pages:
            unit['page_start']=min(unit['page_start'],*pages);unit['page_end']=max(unit['page_end'],*pages)
            old=lookup.get((unit['kind'],unit['page_start'],unit['page_end'],unit['text']),[])
        if len(old)==1:
            chunk=replace(old[0],chunk_index=i)
            reused.append(chunk.id)
        else:
            signature=json.dumps([VERSION,document.id,unit['kind'],unit['source_spans'],unit['text']],ensure_ascii=False,sort_keys=True)
            cid='chk_'+sha256(signature.encode()).hexdigest()[:20]
            chunk=Chunk(cid,document.id,document.filename,unit['page_start'],unit['page_end'],i,unit['text'],
                        (len(unit['text'])+3)//4,structure['embedding_model'],kind=unit['kind'])
        unit['quality_provenance']=provenance
        unit['chunk_id']=chunk.id
        chunks.append(chunk);mapping[chunk.id]={k:v for k,v in unit.items() if k not in {'text','chunk_id'}}
    if len({c.id for c in chunks})!=len(chunks):raise ValueError('Content chunk identity collision')
    info=dict(version=VERSION,source_structure_sha256=digest(source/'structure.json'),previous_chunks=len(old_chunks),
        chunks=len(chunks),chunk_kinds=organized['chunk_kinds'],reused_vectors=len(reused),new_vectors=len(chunks)-len(reused),
        removed_primary_ids=sorted(set(ids)-{c.id for c in chunks}),document_metadata=len(organized['document_metadata']),
        events=organized['events'],source_coverage=organized['source_coverage'],
        paragraph_target_chars=1200,max_evidence_chars=8000,policy=organized['policy'])
    return document,structure,organized,chunks,mapping,reused,info


def preview(source,output):
    output=Path(output)
    if output.exists():raise ValueError('Use a new preview directory')
    _,_,organized,chunks,_,_,info=prepare(source)
    output.mkdir(parents=True)
    save(output/'summary.json',info)
    save(output/'document-metadata.json',organized['document_metadata'])
    save(output/'events.json',organized['events'])
    (output/'chunks.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in organized['chunks']),encoding='utf-8',newline='\n')
    e=lambda v:escape(str(v),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>内容组织预览</title><style>body{font:15px/1.7 system-ui;background:#f3f6fa;color:#203247;margin:30px}main{max-width:1250px;margin:auto}article{background:white;padding:18px;margin:15px 0;border:1px solid #dce5ef;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><main><h1>元数据、公式解释与跨页正文组织</h1>',
        '<p>原始字符与修正记录保留，元数据另存；公式和解释绑定，图内标注回归图注，有依据的跨页句子衔接。无新增解析或视觉模型调用。</p>',
        '<article><pre>'+e(json.dumps(info,ensure_ascii=False,indent=2))+'</pre></article>',
        '<article><h2>独立文献元数据</h2><pre>'+e(json.dumps(organized['document_metadata'],ensure_ascii=False,indent=2))+'</pre></article>']
    for i,c in enumerate(organized['chunks']):
        html+=['<article><h2>'+str(i)+' · '+e(c['kind'])+' · 第'+str(c['page_start'])+'—'+str(c['page_end'])+'页</h2><p>'+e(' > '.join(c['section_path']))+'</p><pre>'+e(c['body_text'])+'</pre>',
            '<details><summary>组织依据、原始片段与位置</summary><pre>'+e(json.dumps({k:v for k,v in c.items() if k not in {'text','body_text'}},ensure_ascii=False,indent=2))+'</pre></details></article>']
    html.append('</main></html>')
    (output/'comparison.html').write_text(''.join(html),encoding='utf-8',newline='\n')
    save(output/'publication.json',dict(version=VERSION,builder_sha256=digest(Path(__file__)),rules_sha256=digest(Path(__file__).with_name('mineru_content_units.py')),
        files={p.name:digest(p) for p in output.iterdir() if p.is_file()}))
    return info


def build(source,output,env_file):
    from literature_rag.config import Settings
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists() or output.is_relative_to(source):raise ValueError('Use a new independent output directory')
    document,structure,organized,chunks,mapping,reused,info=prepare(source)
    settings=Settings(_env_file=env_file)
    if structure['embedding_model']!=settings.embedding_model or structure['embedding_dimensions']!=settings.embedding_dimensions:
        raise ValueError('Embedding configuration differs')
    shutil.copytree(source,output)
    structure['status']='building'
    save(output/'structure.json',structure)
    vectors=ChromaVectorStore(output/'chroma',settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    if info['removed_primary_ids']:vectors.collection.delete(ids=info['removed_primary_ids'])
    updated=[c for c in chunks if c.id not in set(reused)]
    store=SqliteMetadataStore(output/'metadata.sqlite3')
    store.complete_document(document.id,document.page_count,chunks)
    organization=dict(**info,document_metadata_records=organized['document_metadata'],source_mapping=mapping)
    save(output/'chunk-organization.json',organization)
    structure.update(version=VERSION,status='building',chunks=len(chunks),chunk_kinds=organized['chunk_kinds'],mapping=mapping,
        content_organization=info,organization_sha256=digest(output/'chunk-organization.json'),
        embedding_calls=[],metadata_sha256=digest(output/'metadata.sqlite3'),
        activation='Independent content-organized index; default configuration unchanged.')
    save(output/'structure.json',structure)
    embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    try:
        for start in range(0,len(updated),settings.embedding_batch_size):
            batch=updated[start:start+settings.embedding_batch_size]
            call=dict(status='started',chunk_count=len(batch),usage=None)
            structure['embedding_calls'].append(call);save(output/'structure.json',structure)
            try:
                values=embedder.embed_documents([c.text for c in batch])
                call.update(status='completed',usage=embedder.last_usage)
                vectors.upsert([VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename) for c in batch],values)
            finally:save(output/'structure.json',structure)
        structure['status']='ready';save(output/'structure.json',structure)
        # All table texts and their parent IDs must be unchanged: reuse their actual row embeddings.
        old=json.loads((source/'table-retrieval.json').read_text(encoding='utf-8'))
        new=table_plan(output)
        if old['rows']!=new['rows'] or old['parent_text_sha256']!=new['parent_text_sha256']:
            raise ValueError('Table row identity changed; prior row vectors cannot be reused')
        new.update(embedding=old['embedding'],embedding_calls=[],row_vectors_sha256=old['row_vectors_sha256'],
                   reused_row_vectors_from_manifest_sha256=digest(source/'table-retrieval.json'),reused_row_count=len(old['rows']))
        save(output/'table-retrieval.json',new)
        structure['table_evidence']=dict(version=new['version'],rows=len(new['rows']),links=len(new['links']),
            manifest_sha256=digest(output/'table-retrieval.json'),vectors_sha256=new['row_vectors_sha256'],
            row_embeddings_reused=True)
        structure['metadata_sha256']=digest(output/'metadata.sqlite3')
        save(output/'structure.json',structure)
    except Exception:
        structure['status']='failed';save(output/'structure.json',structure);raise
    return dict(status=structure['status'],**info,embedding_calls=structure['embedding_calls'],table_rows_reused=len(new['rows']))


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preview','build']);parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    args=parser.parse_args();sys.stdout.reconfigure(encoding='utf-8')
    result=preview(args.source_dir,args.output) if args.action=='preview' else build(args.source_dir,args.output,args.env_file)
    print(json.dumps(result,ensure_ascii=False))
