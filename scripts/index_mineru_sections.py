"""Preview and build an isolated MinerU section-organized library; no implicit activation."""
from argparse import ArgumentParser
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import index_mineru_experiment as native
from mineru_sections import VERSION,organize


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def prepare(source,parse_dir):
    document,pdf,blocks,units,excluded,summary=native.plan(source,parse_dir,max_chars=1000000)
    organized=organize(units,document.id,blocks)
    return document,pdf,blocks,units,excluded,summary,organized


def preview(source,parse_dir,output):
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('Preview destination exists; preserve the previous sealed output')
    document,pdf,blocks,units,excluded,summary,result=prepare(source,parse_dir)
    output.mkdir(parents=True)
    trace={u['source_id']:dict(old=u,new_chunk_indices=[],section_ids=[],document_title=False) for u in units}
    for i,chunk in enumerate(result['chunks']):
        chunk['preview_index']=i
        for span in chunk['source_spans']:
            if i not in trace[span['source_id']]['new_chunk_indices']:
                trace[span['source_id']]['new_chunk_indices'].append(i)
    for section in result['sections']:
        for span in section['source_spans']:
            trace[span['source_id']]['section_ids'].append(section['id'])
    for title in result['document_titles']:
        trace[title['source_span']['source_id']]['document_title']=True
    save(output/'sections.json',dict(document_titles=result['document_titles'],sections=result['sections']))
    save(output/'anomalies.json',result['anomalies'])
    save(output/'source-trace.json',trace)
    (output/'chunks.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in result['chunks']),encoding='utf-8',newline='\n')
    info=dict(version=VERSION,source_pdf_sha256=document.file_hash,
        native_content_sha256=native.digest(Path(parse_dir)/'mineru-content-list.json'),native_blocks=len(blocks),
        previous_retrieval_blocks=len(units),new_retrieval_blocks=len(result['chunks']),sections=len(result['sections']),
        chunk_kinds=result['chunk_kinds'],anomalies=dict(Counter(a['code'] for a in result['anomalies'])),
        excluded_native_blocks=excluded,source_coverage=result['source_coverage'],policy=result['policy'],
        paragraph_target_chars=result['paragraph_target_chars'],max_evidence_chars=result['max_evidence_chars'],
        parser_version=summary['reported_mineru_version'],parser_backend=summary['reported_mineru_backend'],
        cross_page_chunks=sum(c['page_start']!=c['page_end'] for c in result['chunks']),model_calls=0,
        limitations=['Only captions are used; no vision model.',
          'Chapter labels are program-generated metadata, not verbatim PDF quotations.',
          'Same-page neighbor expansion remains unchanged; this is not parent-section retrieval.',
          'Body duplicates, scientific notation, HTML tables and reference availability remain unchanged.'])
    save(output/'summary.json',info)
    e=lambda x:escape(str(x),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MinerU章节组块预览</title><style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:32px auto;padding:0 24px}article,details{background:white;border:1px solid #dce5ef;border-radius:8px;padding:16px;margin:12px 0}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.65 monospace}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;min-width:0}.pair>div{min-width:0}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #dce5ef;text-align:left;vertical-align:top}@media(max-width:950px){.pair{display:block}}</style><main>',
        '<h1>MinerU章节识别与正文组块预览</h1>',
        f'<p>原生{len(blocks)}块 → 原检索{len(units)}块 → 新检索{len(result["chunks"])}块；自动恢复{len(result["sections"])}个章节节点。无模型调用，原始字符与定位已逐段验证。</p>',
        '<p>本轮改变章节标签、标题归属和正文分组。原始科学数值、正文重复、表格HTML和参考文献保留；检索后的补全仍为同页邻块。</p><h2>自动恢复的章节目录</h2>']
    for section in result['sections']:
        html.append(f'<div style="padding-left:{20*(section["depth"]-1)}px">{e(section["title"])} · 第{section["source_spans"][0]["page"]}页 · {e(section["status"])}</div>')
    html.append('<h2>异常与自动处理记录</h2><pre>'+e(json.dumps(result['anomalies'],ensure_ascii=False,indent=2))+'</pre><h2>全部旧块与新块的对应关系</h2>')
    sections={s['id']:s for s in result['sections']}
    for unit in units:
        entry=trace[unit['source_id']]
        html.append('<details><summary>'+e(unit['source_id'])+f' · 第{unit["page"]}页 · '+e(unit['kind'])+' → '+e(entry['new_chunk_indices'] or '章节/文献信息')+'</summary><div class="pair"><div><h3>原生文字</h3><pre>'+e(unit['text'])+'</pre></div><div>')
        for sid in entry['section_ids']:
            html.append('<p>章节元数据：'+e(' > '.join(sections[sid]['path']))+'</p>')
        if entry['document_title']:
            html.append('<p>论文总标题：保存为文献信息，不单独占用检索名额。</p>')
        for i in entry['new_chunk_indices']:
            chunk=result['chunks'][i]
            html.append(f'<h3>新块{i} · 第{chunk["page_start"]}–{chunk["page_end"]}页</h3><pre>'+e(chunk['text'])+'</pre>')
        html.append('</div></div></details>')
    html.append('<h2>完整审计摘要</h2><pre>'+e(json.dumps(info,ensure_ascii=False,indent=2))+'</pre></main></html>')
    (output/'comparison.html').write_text('\n'.join(html),encoding='utf-8',newline='\n')
    save(output/'publication.json',dict(files={p.name:native.digest(p) for p in output.iterdir() if p.is_file()},
        rules_sha256=native.digest(ROOT/'scripts/mineru_sections.py'),builder_sha256=native.digest(Path(__file__)),model_calls=0))
    return info


def build(source,parse_dir,preview_dir,output,settings):
    output,preview_dir=Path(output).resolve(),Path(preview_dir).resolve()
    if output.exists() or Path(source).resolve().is_relative_to(output):
        raise ValueError('Use a new isolated index destination')
    seal=json.loads((preview_dir/'publication.json').read_text(encoding='utf-8'))
    if not all(native.digest(preview_dir/name)==digest for name,digest in seal['files'].items()):
        raise ValueError('Preview was changed after validation')
    if seal['rules_sha256']!=native.digest(ROOT/'scripts/mineru_sections.py') or seal['builder_sha256']!=native.digest(Path(__file__)):
        raise ValueError('Builder or rules changed after preview')
    document,pdf,blocks,units,excluded,summary,result=prepare(source,parse_dir)
    expected=[json.loads(l) for l in (preview_dir/'chunks.jsonl').read_text(encoding='utf-8').splitlines()]
    for i,c in enumerate(result['chunks']):
        c['preview_index']=i
    if result['chunks']!=expected:
        raise ValueError('Preview does not reproduce')
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.domain.models import Chunk,DocumentStatus,VectorRecord
    embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    chunks=[];mapping={}
    for i,unit in enumerate(result['chunks']):
        cid='chk_'+sha256(f'{VERSION}|{document.id}|{i}|{unit["text"]}'.encode()).hexdigest()[:20]
        chunks.append(Chunk(cid,document.id,document.filename,unit['page_start'],unit['page_end'],i,unit['text'],
            (len(unit['text'])+3)//4,settings.embedding_model,kind=unit['kind']))
        mapping[cid]={k:v for k,v in unit.items() if k!='text'}
        mapping[cid]['text_sha256']=sha256(unit['text'].encode()).hexdigest()
    output.mkdir(parents=True);(output/'papers').mkdir()
    relative=Path('papers')/(document.file_hash+'.pdf');shutil.copyfile(pdf,output/relative)
    store=SqliteMetadataStore(output/'metadata.sqlite3');store.initialize()
    store.upsert_document(replace(document,file_path=relative,status=DocumentStatus.PENDING,chunk_count=0))
    snapshots=[dict(document_id=document.id,page_start=p,page_end=p,text='\n\n'.join(u['text'] for u in units if u['page']==p),
        native_blocks=[dict(source_id=f'mineru_block_{i:04}',**b) for i,b in enumerate(blocks) if b['page_idx']==p-1]) for p in range(1,document.page_count+1)]
    save(output/'source-pages.json',snapshots)
    manifest=dict(version=VERSION,status='building',source_documents=[dict(id=document.id,file_hash=document.file_hash,filename=document.filename)],
        source_pdf_sha256=document.file_hash,native_content_sha256=native.digest(Path(parse_dir)/'mineru-content-list.json'),
        native_blocks=len(blocks),previous_retrieval_blocks=len(units),chunks=len(chunks),chunk_kinds=result['chunk_kinds'],
        sections=result['sections'],document_titles=result['document_titles'],anomalies=result['anomalies'],source_coverage=result['source_coverage'],
        mapping=mapping,unit_policy=result['policy'],visual_policy='Only original textual captions; no image pixels.',
        paragraph_target_chars=result['paragraph_target_chars'],max_evidence_chars=result['max_evidence_chars'],
        reported_parser_version=summary['reported_mineru_version'],reported_backend=summary['reported_mineru_backend'],
        preview_publication_sha256=native.digest(preview_dir/'publication.json'),rules_sha256=seal['rules_sha256'],builder_sha256=seal['builder_sha256'],
        source_pages_sha256=native.digest(output/'source-pages.json'),embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,embedding_calls=[])
    save(output/'structure.json',manifest)
    try:
        vectors=ChromaVectorStore(output/'chroma',settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
        for start in range(0,len(chunks),settings.embedding_batch_size):
            batch=chunks[start:start+settings.embedding_batch_size];call=dict(chunk_count=len(batch),status='started',usage=None)
            manifest['embedding_calls'].append(call);save(output/'structure.json',manifest)
            try:
                embeddings=embedder.embed_documents([c.text for c in batch])
                vectors.upsert([VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename) for c in batch],embeddings)
                call['status']='completed'
            finally:
                call['usage']=getattr(embedder,'last_usage',None);save(output/'structure.json',manifest)
        store.complete_document(document.id,document.page_count,chunks)
        manifest.update(status='ready',metadata_sha256=native.digest(output/'metadata.sqlite3'));save(output/'structure.json',manifest)
    except Exception:
        manifest['status']='failed';save(output/'structure.json',manifest);raise
    return {k:manifest[k] for k in ['status','native_blocks','chunks','chunk_kinds','embedding_calls']}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--parse-dir',type=Path,required=True)
    parser.add_argument('--preview-dir',type=Path,required=True);parser.add_argument('--index-dir',type=Path)
    parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature');parser.add_argument('--embed',action='store_true')
    args=parser.parse_args()
    try:
        if args.embed:
            from literature_rag.config import Settings
            if args.index_dir is None:
                raise ValueError('--index-dir is required')
            result=build(args.source_dir,args.parse_dir,args.preview_dir,args.index_dir,Settings(_env_file=args.env_file))
        else:
            result=preview(args.source_dir,args.parse_dir,args.preview_dir)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print('MinerU section operation failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
