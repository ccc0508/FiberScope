"""Build an isolated text-RAG index from sealed MinerU native content blocks."""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.config import Settings
from literature_rag.domain.models import Chunk,DocumentStatus,VectorRecord

VERSION='mineru-native-blocks-v1'
AUXILIARY={'header','footer','page_number'}


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def native_units(blocks,page_count,max_chars=8000):
    """Retain native boundaries and errors; never invent visual content or repair text."""
    included=[];excluded=[];previous_page=-1
    for index,block in enumerate(blocks):
        page=block.get('page_idx');bbox=block.get('bbox')
        if type(page) is not int or not 0<=page<page_count or page<previous_page:
            raise ValueError('Invalid or out-of-order native page')
        previous_page=page
        if not isinstance(bbox,list) or len(bbox)!=4 or any(type(v) not in {int,float} or not 0<=v<=1000 for v in bbox):
            raise ValueError('Invalid normalized native bbox')
        if bbox[2]<bbox[0] or bbox[3]<bbox[1]:raise ValueError('Reversed native bbox')
        kind=block['type'];source_id=f'mineru_block_{index:04}'
        if kind in AUXILIARY:
            excluded.append(dict(source_id=source_id,native_type=kind,reason='page_auxiliary'));continue
        if kind in {'text','ref_text','equation'}:
            text=block.get('text','')
            unit_kind='heading' if block.get('text_level') else {'text':'paragraph','ref_text':'reference','equation':'equation'}[kind]
        elif kind=='table':
            text='\n\n'.join([*block.get('table_caption',[]),block.get('table_body',''),*block.get('table_footnote',[])])
            unit_kind='table'
        elif kind in {'image','chart'}:
            text='\n\n'.join([*block.get(kind+'_caption',[]),block.get('content',''),*block.get(kind+'_footnote',[])])
            unit_kind='figure_caption'
        else:raise ValueError('Unsupported native block type: '+str(kind))
        if not isinstance(text,str):raise ValueError('Native block text must be a string')
        text=text.strip()
        if not text:
            excluded.append(dict(source_id=source_id,native_type=kind,reason='no_textual_content'));continue
        if len(text)>max_chars:raise ValueError('Native block exceeds the evidence budget; no truncation permitted')
        included.append(dict(source_id=source_id,native_block_index=index,page=page+1,bbox=bbox,
            native_type=kind,native_text_level=block.get('text_level'),kind=unit_kind,text=text,
            image_path=block.get('img_path')))
    return included,excluded


def plan(source,parse_dir,max_chars=8000):
    source,parse_dir=Path(source).resolve(),Path(parse_dir).resolve()
    publication=json.loads((parse_dir/'publication.json').read_text(encoding='utf-8'))
    content=parse_dir/'mineru-content-list.json';summary=json.loads((parse_dir/'summary.json').read_text(encoding='utf-8'))
    if digest(content)!=publication['files']['mineru-content-list.json']:raise ValueError('Sealed native content changed')
    with sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        documents=[SqliteMetadataStore._to_document(row) for row in conn.execute("SELECT * FROM documents WHERE status='completed'")]
    if len(documents)!=1 or documents[0].file_hash!=summary['source_pdf_sha256']:raise ValueError('Different original PDF corpus')
    document=documents[0];pdf=(source/document.file_path).resolve()
    if not pdf.is_relative_to((source/'papers').resolve()) or digest(pdf)!=document.file_hash:raise ValueError('Original PDF fingerprint mismatch')
    blocks=json.loads(content.read_text(encoding='utf-8'))
    units,excluded=native_units(blocks,document.page_count,max_chars)
    return document,pdf,blocks,units,excluded,summary


def build(source,parse_dir,output,settings):
    output=Path(output).resolve();source=Path(source).resolve()
    if output.exists() or output==source or source.is_relative_to(output):raise ValueError('Use a new isolated index directory')
    document,pdf,blocks,units,excluded,summary=plan(source,parse_dir,settings.context_max_evidence_chars)
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,
        settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    chunks=[];mapping={}
    for index,unit in enumerate(units):
        chunk_id='chk_'+sha256(f'{VERSION}|{document.id}|{unit["source_id"]}|{unit["text"]}'.encode()).hexdigest()[:20]
        chunks.append(Chunk(chunk_id,document.id,document.filename,unit['page'],unit['page'],index,unit['text'],
            (len(unit['text'])+3)//4,settings.embedding_model,kind=unit['kind']))
        mapping[chunk_id]={k:v for k,v in unit.items() if k!='text'}
        mapping[chunk_id]['text_sha256']=sha256(unit['text'].encode()).hexdigest()
    output.mkdir(parents=True);(output/'papers').mkdir()
    relative=Path('papers')/(document.file_hash+'.pdf');shutil.copyfile(pdf,output/relative)
    store=SqliteMetadataStore(output/'metadata.sqlite3');store.initialize()
    store.upsert_document(replace(document,file_path=relative,status=DocumentStatus.PENDING,chunk_count=0))
    snapshots=[dict(document_id=document.id,page_start=page,page_end=page,
        text='\n\n'.join(u['text'] for u in units if u['page']==page),
        native_blocks=[dict(source_id=f'mineru_block_{i:04}',**b) for i,b in enumerate(blocks) if b['page_idx']==page-1])
        for page in range(1,document.page_count+1)]
    save(output/'source-pages.json',snapshots)
    manifest=dict(version=VERSION,status='building',source_pdf_sha256=document.file_hash,
        source_documents=[dict(id=document.id,file_hash=document.file_hash,filename=document.filename)],
        native_content_sha256=digest(Path(parse_dir)/'mineru-content-list.json'),native_blocks=len(blocks),
        reported_parser_version=summary['reported_mineru_version'],reported_backend=summary['reported_mineru_backend'],
        chunks=len(chunks),chunk_kinds=dict(Counter(c.kind for c in chunks)),excluded_native_blocks=excluded,
        unit_policy='One nonempty native text/table/equation/reference/caption block per retrieval chunk; no text repair or heading correction.',
        visual_policy='Only textual captions/content are indexed; image pixels are not supplied to the answering model.',
        max_evidence_chars=settings.context_max_evidence_chars,embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,mapping=mapping,embedding_calls=[],
        source_pages_sha256=digest(output/'source-pages.json'),builder_sha256=digest(Path(__file__)))
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
        manifest.update(status='ready',metadata_sha256=digest(output/'metadata.sqlite3'));save(output/'structure.json',manifest)
    except Exception:
        manifest['status']='failed';save(output/'structure.json',manifest);raise
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--parse-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path);parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    parser.add_argument('--embed',action='store_true');args=parser.parse_args()
    try:
        settings=Settings(_env_file=args.env_file)
        if args.embed:
            if args.output is None:raise ValueError('--output is required')
            manifest=build(args.source_dir,args.parse_dir,args.output,settings)
            result={k:manifest[k] for k in ['status','native_blocks','chunks','chunk_kinds','embedding_calls']}
        else:
            _,_,blocks,units,excluded,_=plan(args.source_dir,args.parse_dir,settings.context_max_evidence_chars)
            result=dict(native_blocks=len(blocks),chunks=len(units),chunk_kinds=dict(Counter(u['kind'] for u in units)),excluded=len(excluded),provider_calls=0)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print('MinerU index operation failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
