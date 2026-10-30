"""Add table-row search representations and explicit source links to an isolated existing library."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.table_evidence import VERSION
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore


def plain(text):
    import html
    return ' '.join(html.unescape(re.sub(r'</?[A-Za-z][^>]*>',' ',text)).split())


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def table_rows(chunk):
    """Expand rowspan/colspan headers, retaining source substrings and values; no language model."""
    text=chunk.text
    tables=list(re.finditer(r'<table\b[^>]*>(.*?)</table>',text,re.I|re.S))
    if len(tables)!=1:raise ValueError('Require exactly one nonnested HTML table per parent')
    table=tables[0]
    if re.search(r'<table\b',table.group(1),re.I):raise ValueError('Nested tables are unsupported')
    caption=plain(text[:table.start()])
    label=re.search(r'\bTable\s+(\d+)\b',caption,re.I)
    if not label:raise ValueError('Table has no explicit numeric caption label')
    descriptions={m.group(1).casefold():m.group(2).strip() for m in re.finditer(r'\(([a-z])\)\s*(.*?)(?=\([a-z]\)|$)',caption,re.I|re.S)}
    group='';headers=[];pending={};result=[];data_index=0
    for row_index,row in enumerate(re.finditer(r'<tr\b[^>]*>(.*?)</tr>',table.group(1),re.I|re.S)):
        grid={};new_pending={}
        for col,(cell,remaining) in pending.items():
            grid[col]=cell
            if remaining>1:new_pending[col]=(cell,remaining-1)
        col=0
        for cell in re.finditer(r'<t[dh]\b([^>]*)>(.*?)</t[dh]>',row.group(1),re.I|re.S):
            attrs=cell.group(1);value=plain(cell.group(2))
            spans={}
            for key in ['rowspan','colspan']:
                m=re.search(key+r'\s*=\s*[\"\x27]?(\d+)',attrs,re.I)
                spans[key]=int(m.group(1)) if m else 1
                if not 1<=spans[key]<=100:raise ValueError('Invalid table span')
            while col in grid:col+=1
            for offset in range(spans['colspan']):
                target=col+offset
                if target in grid:raise ValueError('Overlapping HTML spans')
                grid[target]=value
                if spans['rowspan']>1:new_pending[target]=(value,spans['rowspan']-1)
            col+=spans['colspan']
        pending=new_pending
        cells=[grid[i] for i in range(max(grid,default=-1)+1)]
        nonempty=set(c for c in cells if c)
        if len(nonempty)==1 and re.fullmatch(r'\([a-z]\)',next(iter(nonempty)),re.I):
            group=next(iter(nonempty))[1:-1].casefold();headers=[];pending={};continue
        numeric=len(cells)>1 and all(re.fullmatch(r'[-−]?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?',c) for c in cells)
        if not numeric:
            headers.append(cells)
            continue
        if not headers or any(len(h)!=len(cells) for h in headers):raise ValueError('Numeric row lacks complete column headers')
        labels=[]
        for c in range(len(cells)):
            path=[]
            for h in headers:
                if h[c] and (not path or h[c]!=path[-1]):path.append(h[c])
            if not path:raise ValueError('Column has no verified header')
            labels.append(' > '.join(path))
        assignments=[dict(header=header,value=value) for header,value in zip(labels,cells,strict=True)]
        representation='[程序生成的表格行检索表示，非原文引文]\n表题与原有注释：'+caption
        if group:representation+='\n分组 ('+group+')：'+descriptions.get(group,'('+group+')')
        representation+='\n数据行：'+'；'.join(item['header']+' = '+item['value'] for item in assignments)
        start=table.start(1)+row.start();end=table.start(1)+row.end()
        data_index+=1
        rid='row_'+sha256((chunk.id+'|'+str(row_index)+'|'+representation).encode()).hexdigest()[:20]
        result.append(dict(id=rid,parent_chunk_id=chunk.id,document_id=chunk.document_id,
            page_start=chunk.page_start,page_end=chunk.page_end,table_number=int(label.group(1)),
            group=group,row_index=row_index,data_index=data_index,assignments=assignments,text=representation,
            parent_text_start=start,parent_text_end=end,parent_raw_row=text[start:end],
            provenance='Offsets refer to the sealed parent chunk, including its program-labelled chapter prefix; raw-PDF locators remain in its quality provenance.'))
    if pending:raise ValueError('HTML rowspan extends beyond the table')
    if not result:raise ValueError('No fully labelled numeric data rows found')
    return result


def table_references(text):
    """Explicit numbered table mentions; supplementary S1 never becomes Table 1."""
    found=set()
    pattern=r'\bTables?\s+((?:\d+[a-z]?(?:\s*[,–-]\s*[a-z])?)(?:\s*(?:,|and|&)\s*\d+[a-z]?)*)'
    for match in re.finditer(pattern,plain(text),re.I):
        for number in re.findall(r'\d+',match.group(1)):found.add(int(number))
    return found


def plan(source):
    source=Path(source).resolve()
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    if structure.get('status')!='ready':raise ValueError('Only a completed source index can be extended')
    store=SqliteMetadataStore(source/'metadata.sqlite3')
    with sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        ids=[row[0] for row in conn.execute('SELECT id FROM chunks ORDER BY document_id,chunk_index')]
    chunks=store.get_chunks(ids)
    if len(chunks)!=structure['chunks']:raise ValueError('Source chunk count mismatch')
    rows=[];tables={};by_id={c.id:c for c in chunks}
    for chunk in chunks:
        if chunk.kind=='table':
            parsed=table_rows(chunk)
            key=(chunk.document_id,parsed[0]['table_number'])
            if key in tables:raise ValueError('Ambiguous duplicate table number')
            tables[key]=chunk.id
            rows.extend(parsed)
    links=[]
    for chunk in chunks:
        if chunk.kind!='paragraph':continue
        for number in sorted(table_references(chunk.text)):
            target=tables.get((chunk.document_id,number))
            if target:
                links.append(dict(source_chunk_id=chunk.id,target_chunk_id=target,
                    kind='explicit_body_table_reference',table_number=number))
    for target in tables.values():
        references=[link for link in links if link['target_chunk_id']==target]
        references.sort(key=lambda link:(abs(by_id[link['source_chunk_id']].chunk_index-by_id[target].chunk_index),link['source_chunk_id']))
        for link in references[:2]:
            links.append(dict(source_chunk_id=target,target_chunk_id=link['source_chunk_id'],
                kind='table_explicitly_discussed_by_body',table_number=link['table_number']))
    links.sort(key=lambda link:(by_id[link['source_chunk_id']].chunk_index,abs(by_id[link['source_chunk_id']].chunk_index-by_id[link['target_chunk_id']].chunk_index),link['target_chunk_id']))
    return dict(version=VERSION,source_structure_sha256=digest(source/'structure.json'),rows=rows,links=links,
        parent_text_sha256={cid:sha256(by_id[cid].text.encode()).hexdigest() for cid in tables.values()},
        policy='Row text is retrieval-only; evidence is the complete existing source table. Explicit body table references only, same document. No QA question input or manual scientific values.')


def build(source,output,env_file):
    from literature_rag.config import Settings
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists() or output.is_relative_to(source):raise ValueError('Use a new independent destination')
    manifest=plan(source)
    settings=Settings(_env_file=env_file)
    if not manifest['rows']:raise ValueError('No table rows')
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    if structure['embedding_model']!=settings.embedding_model or structure['embedding_dimensions']!=settings.embedding_dimensions:
        raise ValueError('Use the source embedding model and dimensions')
    # Copy unchanged full sources, primary vectors and correction ledger before adding a sidecar.
    shutil.copytree(source,output)
    manifest.update(embedding=dict(provider=settings.embedding_provider,model=settings.embedding_model,dimensions=settings.embedding_dimensions),embedding_calls=[])
    embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    vectors=[]
    for start in range(0,len(manifest['rows']),settings.embedding_batch_size):
        batch=manifest['rows'][start:start+settings.embedding_batch_size]
        call=dict(status='started',row_count=len(batch),usage=None)
        manifest['embedding_calls'].append(call)
        save(output/'table-retrieval.json',manifest)
        try:
            values=embedder.embed_documents([r['text'] for r in batch])
            call.update(status='completed',usage=embedder.last_usage)
            vectors.extend(dict(id=row['id'],vector=vector) for row,vector in zip(batch,values,strict=True))
        finally:save(output/'table-retrieval.json',manifest)
    save(output/'table-row-vectors.json',dict(rows=vectors))
    manifest['row_vectors_sha256']=digest(output/'table-row-vectors.json')
    save(output/'table-retrieval.json',manifest)
    structure.update(table_evidence=dict(version=VERSION,rows=len(manifest['rows']),links=len(manifest['links']),
        manifest_sha256=digest(output/'table-retrieval.json'),vectors_sha256=manifest['row_vectors_sha256'],
        source_structure_sha256=manifest['source_structure_sha256']),
        activation='Opt-in experimental table retrieval, no default configuration change.')
    save(output/'structure.json',structure)
    return {k:manifest[k] for k in ['version','embedding_calls','policy']} | dict(rows=len(manifest['rows']),links=len(manifest['links']),source_chunks=structure['chunks'])


def preview(source,output):
    output=Path(output)
    if output.exists():raise ValueError('Use a new preview directory')
    result=plan(source);output.mkdir(parents=True)
    save(output/'table-retrieval.json',result)
    e=lambda value:escape(str(value),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>表格行检索与原表关联</title><style>body{font:15px/1.7 system-ui;margin:30px;background:#f4f7fb;color:#203247}main{max-width:1200px;margin:auto}article{background:white;padding:18px;margin:14px 0;border:1px solid #dce5ef;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><main><h1>表格行检索与原表关联</h1>',
        '<p>完整原表与正文95块保留。下列表示仅参与检索，命中后返回完整表格；不作为逐字原文引用。</p>']
    for row in result['rows']:
        html.append('<article><h2>Table '+str(row['table_number'])+' · 分组 '+e(row['group'])+' · 数据行 '+str(row['data_index'])+'</h2><pre>'+e(row['text'])+'</pre><details><summary>原始行与父表位置</summary><pre>'+e(json.dumps({k:v for k,v in row.items() if k!='text'},ensure_ascii=False,indent=2))+'</pre></details></article>')
    html.append('<article><h2>正文与表格关联</h2><pre>'+e(json.dumps(result['links'],ensure_ascii=False,indent=2))+'</pre></article></main></html>')
    (output/'comparison.html').write_text(''.join(html),encoding='utf-8',newline='\n')
    save(output/'publication.json',dict(version=VERSION,builder_sha256=digest(Path(__file__)),files={p.name:digest(p) for p in output.iterdir() if p.is_file()}))
    return dict(rows=len(result['rows']),links=len(result['links']),provider_calls=0)


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preview','build'])
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    args=parser.parse_args()
    result=preview(args.source_dir,args.output) if args.action=='preview' else build(args.source_dir,args.output,args.env_file)
    print(json.dumps(result,ensure_ascii=False))
