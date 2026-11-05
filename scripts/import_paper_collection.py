"""Build a resumable, isolated multi-paper MinerU/Qwen library from cached API results."""
from pathlib import Path
import sys,json,shutil,re,sqlite3
from hashlib import sha256
from dataclasses import asdict
from collections import Counter
import fitz
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.config import Settings
from literature_rag.domain.models import Document,DocumentStatus,Chunk,VectorRecord,VisualAsset
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
from literature_rag.application.body_context import BodySectionCatalog
from literature_rag.application.table_evidence import TableRelations
from literature_rag.application.visual_evidence import VisualCatalog
from index_mineru_experiment import native_units
from mineru_roles import organize_roles
from index_table_evidence import table_rows,table_references
from freeze_qa_baseline import backup_database
SOURCE=ROOT/'.rag-data/index-versions/mineru-qwen3-vl-images-20261102'
OUT=ROOT/'.rag-data/index-versions/paper-collection-20261105'
CACHE=ROOT/'.rag-data/import-collection-20261105'
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)

def prepare():
    assert not OUT.exists(),'Preserve existing build; use embed/verify to resume'
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    shutil.copytree(SOURCE,OUT,ignore=shutil.ignore_patterns('*.lock','*-wal','*-shm'))
    for db in ['metadata.sqlite3','chroma/chroma.sqlite3']:backup_database(SOURCE/db,OUT/db)
    store=SqliteMetadataStore(OUT/'metadata.sqlite3');structure=read(OUT/'structure.json')
    tables=read(OUT/'table-retrieval.json');visual=read(OUT/'visual-retrieval.json')
    pages=read(OUT/'source-pages.json');docs=[];newchunks=[];newrows=[];assets=[];warnings=[]
    known={d.file_hash for d in store.list_documents()}
    for pdf in sorted((ROOT/'论文合集').glob('*.pdf')):
        checksum=digest(pdf)
        if checksum in known:continue
        parsed=CACHE/checksum[:16];files=list((parsed/'mineru').rglob('*_content_list.json'));assert len(files)==1
        original=read(files[0]);blocks=json.loads(json.dumps(original));extra=[]
        for i,b in enumerate(blocks):
            if b['type'] in {'page_footnote','aside_text'}:
                extra.append(i);b['type']='text';b.pop('text_level',None)
        with fitz.open(pdf) as document:count=len(document)
        assert max(b['page_idx'] for b in blocks)<count
        units,excluded=native_units(blocks,count,max_chars=1000000)
        did='doc_'+checksum[:16];result=organize_roles(units,did,blocks)
        relative=Path('papers')/(checksum+'.pdf');shutil.copyfile(pdf,OUT/relative)
        doc=Document(did,pdf.name,relative,checksum,pdf.stat().st_size,DocumentStatus.PENDING,page_count=count)
        store.upsert_document(doc);chunks=[]
        for i,u in enumerate(result['chunks']):
            cid='chk_'+sha256((did+'|'+str(i)+'|'+u['text']).encode()).hexdigest()[:20]
            c=Chunk(cid,did,pdf.name,u['page_start'],u['page_end'],i,u['text'],(len(u['text'])+3)//4,settings.embedding_model,kind=u['kind'])
            mapping={k:v for k,v in u.items() if k!='text'};mapping['text_sha256']=sha256(c.text.encode()).hexdigest()
            mapping['quality_status']='native_parser_not_visually_reviewed'
            if any(int(s['source_id'].split('_')[-1]) in extra for s in u['source_spans']):
                mapping.update(content_role='unknown',role_status='uncertain',role_signals=['native_footnote_or_aside'])
            structure['mapping'][cid]=mapping;chunks.append(c)
        store.complete_document(did,count,chunks);newchunks.extend(chunks)
        structure['sections'].extend(result['sections'])
        rowcount=0
        for c in chunks:
            if c.kind!='table':continue
            try:
                rows=table_rows(c)
                assert structure['mapping'][c.id]['content_role']=='table' and structure['mapping'][c.id]['role_status']=='identified'
            except (ValueError,AssertionError):
                warnings.append(dict(document=pdf.name,chunk_id=c.id,reason='table_row_representation_skipped_full_table_retained'));continue
            newrows.extend(rows);tables['parent_text_sha256'][c.id]=digest_text(c.text);rowcount+=len(rows)
        # Every source figure/table with text gets its own original-PDF crop, including Chinese captions.
        with fitz.open(pdf) as document:
            for i,b in enumerate(blocks):
                if b['type'] not in {'image','chart','table'}:continue
                parents=[c for c in chunks if c.kind in {'figure_caption','table'} and any(s['source_id']==f'mineru_block_{i:04}' for s in structure['mapping'][c.id]['source_spans'])]
                if len(parents)!=1:
                    warnings.append(dict(document=pdf.name,block=i,reason='image_no_unique_text_parent'));continue
                c=parents[0];box=b['bbox'];bbox=[max(0,box[0]-5),max(0,box[1]-5),min(1000,box[2]+5),min(1000,box[3]+5)]
                page=document[b['page_idx']];rect=page.rect
                clip=fitz.Rect(bbox[0]*rect.width/1000,bbox[1]*rect.height/1000,bbox[2]*rect.width/1000,bbox[3]*rect.height/1000)
                if clip.is_empty:continue
                pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=clip,alpha=False);payload=pix.tobytes('png');h=sha256(payload).hexdigest()
                path=f'visual-assets/{h}.png';(OUT/path).write_bytes(payload)
                captions=b.get('table_caption',[]) or b.get('image_caption',[]) or b.get('chart_caption',[])
                label=(' '.join(captions)[:180] or f'{b["type"]} page {b["page_idx"]+1} block {i}')
                aid='img_'+digest_text(did+'|'+str(i)+'|'+h)[:20]
                a=asdict(VisualAsset(aid,did,c.id,label,b['page_idx']+1,tuple(bbox),path,h,pix.width,pix.height,len(payload),'table' if b['type']=='table' else 'figure'))
                assets.append(a);visual['parent_text_sha256'][c.id]=digest_text(c.text)
                visual['source_regions'][aid]=[f'mineru_block_{i:04}']
        for page in range(1,count+1):pages.append(dict(document_id=did,page_start=page,page_end=page,text='\n\n'.join(u['text'] for u in units if u['page']==page),native_blocks=[dict(source_id=f'mineru_block_{i:04}',**b) for i,b in enumerate(original) if b['page_idx']==page-1]))
        save(OUT/'imports'/(did+'.json'),dict(filename=pdf.name,pdf_sha256=checksum,native_sha256=digest(files[0]),native_blocks=original,excluded=excluded,organization=result,quality='unreviewed_native'))
        docs.append(dict(id=did,filename=pdf.name,sha256=checksum,pages=count,chunks=len(chunks),table_rows=rowcount,source_coverage=result['source_coverage']))
    structure.update(status='building',chunks=len(structure['mapping']),source_documents=[dict(id=d.id,filename=d.filename,file_hash=d.file_hash) for d in store.list_documents()],collection_import=dict(source=str(SOURCE),documents=docs),metadata_sha256=digest(OUT/'metadata.sqlite3'))
    structure['chunk_kinds']=dict(Counter(m['kind'] for m in structure['mapping'].values()))
    tables['rows'].extend(newrows);visual['assets'].extend(assets)
    save(OUT/'source-pages.json',pages);structure['source_pages_sha256']=digest(OUT/'source-pages.json')
    save(OUT/'structure.json',structure);save(OUT/'table-retrieval.json',tables);save(OUT/'visual-retrieval.json',visual)
    save(OUT/'import-plan.json',dict(documents=docs,chunk_ids=[c.id for c in newchunks],row_ids=[r['id'] for r in newrows],asset_ids=[a['id'] for a in assets],warnings=warnings))
    print(json.dumps(dict(documents=len(docs),chunks=len(newchunks),rows=len(newrows),images=len(assets),warnings=len(warnings))))

def digest_text(t):return sha256(t.encode()).hexdigest()

def parse():
    import parse_mineru_pfi_20261029 as api
    for pdf in sorted((ROOT/'论文合集').glob('*.pdf')):
        api.PDF=pdf;api.FILENAME='paper-'+digest(pdf)[:16]+'.pdf';api.OUT=CACHE/digest(pdf)[:16]
        state=api.OUT/'api-state.json'
        if not state.exists():
            if api.main('submit')!=0:raise RuntimeError('MinerU submission failed')
        if api.main('poll')!=0:raise RuntimeError('MinerU parse incomplete; retain state and resume')
        with fitz.open(pdf) as d:count=len(d)
        save(api.OUT/'source.json',dict(filename=pdf.name,pdf_sha256=digest(pdf),pages=count))

def embed():
    if (OUT/'import-verification.json').exists() and read(OUT/'structure.json')['status']=='ready':
        return verify()
    settings=Settings(_env_file=ROOT/'backend/.env.literature');plan=read(OUT/'import-plan.json')
    embedder=DashScopeEmbedder(settings.embedding_model,settings.embedding_dimensions,settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    store=SqliteMetadataStore(OUT/'metadata.sqlite3');vectors=ChromaVectorStore(OUT/'chroma',settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    tables=read(OUT/'table-retrieval.json');visual=read(OUT/'visual-retrieval.json')
    groups=[('text',store.get_chunks(plan['chunk_ids'])),('rows',[r for r in tables['rows'] if r['id'] in plan['row_ids']]),('images',[a for a in visual['assets'] if a['id'] in plan['asset_ids']])]
    for kind,items in groups:
        batchsize=5 if kind=='images' else 20
        for start in range(0,len(items),batchsize):
            batch=items[start:start+batchsize];path=OUT/'import-vectors'/f'{kind}-{start:05}.json'
            if path.exists():data=read(path)
            else:
                mark=path.with_suffix('.pending');assert not mark.exists(),'Inspect interrupted paid batch before resuming'
                save(mark,dict(kind=kind,start=start))
                try:
                    vs=embedder.embed_images([OUT/a['image_path'] for a in batch]) if kind=='images' else embedder.embed_documents([c.text for c in batch] if kind=='text' else [r['text'] for r in batch])
                    data=dict(vectors=vs,usage=embedder.last_usage,calls=embedder.last_calls);save(path,data);mark.unlink()
                except Exception as e:save(mark,dict(status='failed',error_type=type(e).__name__));raise
            if kind=='text':vectors.upsert([VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename) for c in batch],data['vectors'])
            print(json.dumps(dict(kind=kind,done=min(start+batchsize,len(items)),total=len(items))),flush=True)
    for kind,name,idkey in [('rows','table-row-vectors.json','row_ids'),('images','visual-vectors.json','asset_ids')]:
        payload=read(OUT/name);oldids=set(plan[idkey]);payload['rows']=[r for r in payload['rows'] if r['id'] not in oldids]
        items=groups[1 if kind=='rows' else 2][1];batchsize=20 if kind=='rows' else 5
        for start in range(0,len(items),batchsize):
            vs=read(OUT/'import-vectors'/f'{kind}-{start:05}.json')['vectors']
            payload['rows'].extend(dict(id=x['id'],vector=v) for x,v in zip(items[start:start+batchsize],vs,strict=True))
        save(OUT/name,payload)
    structure=read(OUT/'structure.json');structure.update(status='ready',vector_index_built=True);save(OUT/'structure.json',structure)
    tables.update(row_vectors_sha256=digest(OUT/'table-row-vectors.json'),source_structure_sha256=digest(OUT/'structure.json'));save(OUT/'table-retrieval.json',tables)
    visual.update(status='ready',vectors_sha256=digest(OUT/'visual-vectors.json'),structure_sha256=digest(OUT/'structure.json'));save(OUT/'visual-retrieval.json',visual)
    verify()

def verify():
    settings=Settings(_env_file=ROOT/'backend/.env.literature');store=SqliteMetadataStore(OUT/'metadata.sqlite3')
    identity=dict(provider=settings.embedding_provider,model=settings.embedding_model,dimensions=settings.embedding_dimensions)
    catalog=BodySectionCatalog.load(OUT,store);tables=TableRelations.load(OUT,store,**identity);tables.validate_body_catalog(catalog)
    visual=VisualCatalog.load(OUT,store,**identity)
    vectors=ChromaVectorStore(OUT/'chroma',**identity)
    assert vectors.collection.count()==len(catalog.chunks)
    for d in store.list_documents():assert digest(OUT/d.file_path)==d.file_hash and d.status==DocumentStatus.COMPLETED
    result=dict(documents=len(store.list_documents()),chunks=len(catalog.chunks),rows=len(tables.rows),images=len(visual.assets),status='verified')
    save(OUT/'import-verification.json',result);print(json.dumps(result))

def exclude_portrait():
    """A visually verified author portrait is not a scientific figure; preserve PDF and text."""
    m=read(OUT/'visual-retrieval.json');v=read(OUT/'visual-vectors.json')
    removed=[a for a in m['assets'] if a['document_id']=='doc_fc10c27084432887' and a['page']==1 and a['label']=='image page 1 block 2']
    ids={a['id'] for a in removed}
    m['assets']=[a for a in m['assets'] if a['id'] not in ids]
    v['rows']=[r for r in v['rows'] if r['id'] not in ids]
    save(OUT/'visual-vectors.json',v);m['vectors_sha256']=digest(OUT/'visual-vectors.json')
    save(OUT/'visual-retrieval.json',m)
    if removed:save(OUT/'visual-exclusions.json',dict(reason='verified author portrait, not research figure; original asset preserved',assets=removed))
    verify()

def smoke():
    import subprocess
    results=[]
    for d in read(OUT/'import-plan.json')['documents']:
        path=OUT/'smoke'/(d['id']+'.json')
        native=read(OUT/'imports'/(d['id']+'.json'))
        title=next((b['text'] for b in native['native_blocks'] if b['type']=='text' and b.get('text_level') and len(b.get('text',''))>20),d['filename'])
        if path.exists():x=read(path)
        else:
            body=dict(data_dir=str(OUT),run_id='collection-smoke-'+d['id'],tool_call=dict(tool='search_literature',query=title,reason='Verify imported document retrieval'))
            p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'backend/literature_worker.py')],input=json.dumps(body),text=True,encoding='utf8',capture_output=True,timeout=180)
            if p.returncode:raise RuntimeError('Retrieval worker failed; inspect private logs')
            x=json.loads(p.stdout);save(path,x)
        ids=[e['document_id'] for e in x.get('result',{}).get('evidence',[])]
        results.append(dict(document_id=d['id'],filename=d['filename'],query=title,matched=d['id'] in ids,status=x.get('status'),returned_documents=list(dict.fromkeys(ids))))
    assert len(results)==7 and all(r['matched'] and r['status']=='completed' for r in results)
    save(OUT/'retrieval-evidence-check.json',results);print(json.dumps(dict(passed=len(results),answer_model_calls=0)))

if __name__=='__main__':{'parse':parse,'prepare':prepare,'embed':embed,'verify':verify,'exclude-portrait':exclude_portrait,'smoke':smoke}[sys.argv[1]]()
