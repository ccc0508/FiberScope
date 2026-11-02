"""Index original PDF figure/table crops from fingerprinted MinerU regions into a new library."""
from argparse import ArgumentParser
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

from filelock import FileLock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.visual_evidence import VERSION,VisualCatalog
from literature_rag.config import Settings
from literature_rag.domain.models import VisualAsset
from freeze_qa_baseline import backup_database,library_fingerprint
from reembed_literature import save,digest


def image_groups(blocks):
    """Join consecutive subfigures up to their numbered caption; exclude uncaptioned logos."""
    groups=[];pending=[]
    for i,block in enumerate(blocks):
        kind=block.get('type')
        if kind not in {'chart','image','table'}:
            pending=[];continue
        page=block.get('page_idx')
        if pending and (kind=='table' or pending[-1][1].get('page_idx')!=page):pending=[]
        if kind=='table':
            caption=' '.join(block.get('table_caption',[]));prefix='Table';regions=[(i,block)]
        else:
            pending.append((i,block));regions=list(pending)
            caption=' '.join(block.get('chart_caption',[]) or block.get('image_caption',[]));prefix='Figure'
        label=re.search(r'\b'+prefix+r'\s+(\d+)\b',caption,re.I)
        if not label:continue
        groups.append(dict(label=prefix+' '+label.group(1),kind='table' if kind=='table' else 'figure',
            page=page+1,caption=caption,regions=regions,caption_source_id=f'mineru_block_{i:04}'))
        pending=[]
    return groups


def plan(source,native):
    source,native=Path(source).resolve(),Path(native).resolve()
    structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
    if structure.get('status')!='ready' or digest(native)!=structure['native_content_sha256']:
        raise ValueError('Native MinerU output does not match the source library')
    store=SqliteMetadataStore(source/'metadata.sqlite3');documents=store.list_documents()
    if len(documents)!=1 or documents[0].status.value!='completed':
        raise ValueError('Build one fingerprinted document at a time')
    doc=documents[0];pdf=(source/doc.file_path).resolve()
    if not pdf.is_relative_to((source/'papers').resolve()) or digest(pdf)!=doc.file_hash:
        raise ValueError('Original PDF is missing or changed')
    groups=image_groups(json.loads(native.read_text(encoding='utf-8')))
    mapping=structure['mapping'];plans=[]
    for group in groups:
        role='table' if group['kind']=='table' else 'figure_caption'
        parents=[cid for cid,m in mapping.items() if m.get('content_role')==role and m.get('role_status')=='identified'
            and any(span.get('source_id')==group['caption_source_id'] for span in m.get('source_spans',[]))]
        if len(parents)!=1:raise ValueError('Image caption must map to exactly one identified original parent')
        chunk=store.get_chunks(parents)[0]
        if not re.search(r'\b'+re.escape(group['label'])+r'\b',chunk.text,re.I):
            raise ValueError('Figure/table number differs from parent text')
        boxes=[b['bbox'] for _,b in group['regions']]
        if any(len(b)!=4 or not 0<=b[0]<b[2]<=1000 or not 0<=b[1]<b[3]<=1000 for b in boxes):
            raise ValueError('Unsupported native image geometry')
        bbox=[max(0,min(b[0] for b in boxes)-5),max(0,min(b[1] for b in boxes)-5),
              min(1000,max(b[2] for b in boxes)+5),min(1000,max(b[3] for b in boxes)+5)]
        if not chunk.page_start<=group['page']<=chunk.page_end:raise ValueError('Image page and parent disagree')
        plans.append(dict(label=group['label'],kind=group['kind'],page=group['page'],bbox=bbox,
            document_id=doc.id,parent_chunk_id=chunk.id,parent_text_sha256=sha256(chunk.text.encode()).hexdigest(),
            region_source_ids=[f'mineru_block_{i:04}' for i,_ in group['regions']]))
    if len({p['label'] for p in plans})!=len(plans):raise ValueError('Ambiguous duplicate figure/table number')
    return plans,pdf


def build(source,output,native,settings,*,embedder=None,resume=False):
    import fitz
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Choose an independent destination')
    if (settings.embedding_provider,settings.embedding_model)!=('dashscope','qwen3-vl-embedding'):
        raise ValueError('Image and text retrieval must share Qwen3-VL embeddings')
    if embedder is None:
        if not settings.embedding_api_key:raise ValueError('Missing private embedding key')
        from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
        embedder=DashScopeEmbedder(settings.embedding_model,settings.embedding_dimensions,
            settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    with FileLock(str(source/'.import.lock'),timeout=0):
        plans,pdf=plan(source,native);before=library_fingerprint(source)
        identity=dict(provider=settings.embedding_provider,model=settings.embedding_model,dimensions=settings.embedding_dimensions)
        source_structure=json.loads((source/'structure.json').read_text(encoding='utf-8'))
        if (source_structure.get('embedding_provider'),source_structure.get('embedding_model'),source_structure.get('embedding_dimensions')) != (
            settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions):
            raise ValueError('Re-embed the text library with this exact model before indexing images')
        contract=dict(source=before,native_sha256=digest(native),embedding=identity,render_dpi=180,
            endpoint_sha256=sha256((settings.embedding_base_url or '').encode()).hexdigest())
        ledger_path=output/'visual-index-ledger.json'
        if output.exists():
            if not resume or not ledger_path.is_file():raise ValueError('Explicit resume is required for an existing visual index')
            ledger=json.loads(ledger_path.read_text(encoding='utf-8'))
            if ledger['contract']!=contract:raise ValueError('Visual build inputs changed')
            if any(c['status']=='started' for c in ledger['calls']):raise ValueError('Inspect the interrupted paid image request before replay')
            if ledger['status']=='ready':
                VisualCatalog.load(output,SqliteMetadataStore(output/'metadata.sqlite3'),**identity)
                return ledger
        else:
            shutil.copytree(source,output,ignore=shutil.ignore_patterns('*.lock'))
            backup_database(source/'metadata.sqlite3',output/'metadata.sqlite3')
            backup_database(source/'chroma/chroma.sqlite3',output/'chroma/chroma.sqlite3')
            for suffix in ['-wal','-shm']:
                for db in [output/'metadata.sqlite3',output/'chroma/chroma.sqlite3']:
                    extra=Path(str(db)+suffix)
                    if extra.exists():extra.unlink()
            (output/'visual-assets').mkdir()
            assets=[]
            with fitz.open(pdf) as document:
                for item in plans:
                    page=document[item['page']-1];x0,y0,x1,y1=item['bbox'];rect=page.rect
                    clip=fitz.Rect(rect.x0+x0*rect.width/1000,rect.y0+y0*rect.height/1000,
                                   rect.x0+x1*rect.width/1000,rect.y0+y1*rect.height/1000)
                    pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),clip=clip,alpha=False)
                    payload=pix.tobytes('png');checksum=sha256(payload).hexdigest()
                    relative=f'visual-assets/{checksum}.png';(output/relative).write_bytes(payload)
                    aid='img_'+sha256((item['document_id']+'|'+item['label']+'|'+checksum).encode()).hexdigest()[:20]
                    assets.append(asdict(VisualAsset(aid,item['document_id'],item['parent_chunk_id'],item['label'],
                        item['page'],tuple(item['bbox']),relative,checksum,pix.width,pix.height,len(payload),item['kind'])))
            structure=json.loads((output/'structure.json').read_text(encoding='utf-8'))
            structure['visual_extension']=dict(version=VERSION,assets=len(assets),source_structure_sha256=digest(source/'structure.json'))
            structure.get('embedding_migration',{})['images_indexed']=True
            save(output/'structure.json',structure)
            manifest=dict(version=VERSION,status='building',embedding=identity,assets=assets,
                parent_text_sha256={p['parent_chunk_id']:p['parent_text_sha256'] for p in plans},
                source_regions={a['id']:p['region_source_ids'] for a,p in zip(assets,plans,strict=True)},
                source_pdf_sha256=digest(pdf),native_sha256=digest(native),render_dpi=180,
                structure_sha256=digest(output/'structure.json'),vectors_sha256=None,
                embedding_representation='image_only_original_pdf_crop',retrieval_parent='original_caption_or_full_table')
            save(output/'visual-retrieval.json',manifest)
            ledger=dict(contract=contract,status='building',calls=[],asset_count=len(assets))
            save(ledger_path,ledger)
        with FileLock(str(output/'.visual-index.lock'),timeout=0):
            manifest=json.loads((output/'visual-retrieval.json').read_text(encoding='utf-8'))
            try:
                for asset in manifest['assets']:
                    cache=output/'visual-assets'/(asset['id']+'.vector.json')
                    good=next((c for c in ledger['calls'] if c['asset_id']==asset['id'] and c['status']=='completed'),None)
                    if good:
                        if digest(cache)!=good['cache_sha256']:raise ValueError('Image vector cache changed')
                        continue
                    call=dict(asset_id=asset['id'],status='started',usage=None)
                    ledger['calls'].append(call);save(ledger_path,ledger)
                    try:
                        vector=embedder.embed_images([output/asset['image_path']])[0]
                        save(cache,dict(id=asset['id'],vector=vector))
                        call.update(status='completed',cache_sha256=digest(cache))
                    except Exception:call['status']='failed';raise
                    finally:
                        call.update(usage=getattr(embedder,'last_usage',None),provider_calls=getattr(embedder,'last_calls',[]))
                        save(ledger_path,ledger)
                rows=[json.loads((output/'visual-assets'/(a['id']+'.vector.json')).read_text(encoding='utf-8')) for a in manifest['assets']]
                save(output/'visual-vectors.json',dict(rows=rows))
                manifest.update(status='ready',vectors_sha256=digest(output/'visual-vectors.json'))
                save(output/'visual-retrieval.json',manifest)
                VisualCatalog.load(output,SqliteMetadataStore(output/'metadata.sqlite3'),**identity)
                if library_fingerprint(source)!=before:raise ValueError('Source library changed during image indexing')
                ledger.update(status='ready',manifest_sha256=digest(output/'visual-retrieval.json'))
                save(ledger_path,ledger)
            except Exception:ledger['status']='failed';save(ledger_path,ledger);raise
    return ledger


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True)
    p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path)
    p.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.aliyun')
    p.add_argument('--embed',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
    try:
        if a.embed:
            if a.output is None:raise ValueError('Provide a new output directory')
            result=build(a.source_dir,a.output,a.native,Settings(_env_file=a.env_file),resume=a.resume)
            summary=dict(status=result['status'],images=result['asset_count'],embedding_batches=len(result['calls']))
        else:
            items,_=plan(a.source_dir,a.native);summary=dict(images=len(items),labels=[p['label'] for p in items],provider_calls=0)
        print(json.dumps(summary,ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(status='failed',error_type=type(error).__name__,message='Preserve all image/vector checkpoints; provider details are redacted.')))
        raise SystemExit(1)
