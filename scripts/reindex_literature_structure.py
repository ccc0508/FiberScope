"""Build a separate structure-aware text library; never overwrite the source or activate implicitly."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict,replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.structure import VERSION,rechunk
from literature_rag.config import Settings
from literature_rag.domain.models import Chunk,DocumentStatus,VectorRecord


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def plan(source,max_chars=8000):
    source=Path(source).resolve()
    with sqlite3.connect((source/'metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('BEGIN')
        documents=[SqliteMetadataStore._to_document(r) for r in conn.execute("SELECT * FROM documents WHERE status='completed' ORDER BY id")]
        chunks=[SqliteMetadataStore._to_chunk(r) for r in conn.execute("SELECT c.* FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.status='completed' ORDER BY c.document_id,c.chunk_index")]
    if not documents or not chunks:raise ValueError('no completed source documents')
    for d in documents:
        p=(source/d.file_path).resolve()
        if not p.is_relative_to((source/'papers').resolve()) or digest(p)!=d.file_hash:
            raise ValueError('source PDF path or checksum changed')
    units,pages=rechunk(chunks,max_chars=max_chars)
    return documents,chunks,units,pages


def build(source,output,settings,*,embedder=None,vector_factory=None):
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists() or output==source or source.is_relative_to(output):
        raise ValueError('use a new separate output directory')
    documents,old_chunks,units,pages=plan(source,settings.context_max_evidence_chars)
    if not settings.embedding_model or not settings.embedding_dimensions:raise ValueError('embedding configuration missing')
    if embedder is None:
        from literature_rag.adapters.providers.openai import OpenAIEmbedder
        if not settings.embedding_api_key:raise ValueError('embedding key missing')
        embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,
                               settings.embedding_api_key.get_secret_value(),settings.embedding_base_url)
    if vector_factory is None:
        from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
        vector_factory=lambda path:ChromaVectorStore(path,settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)
    names={d.id:d.filename for d in documents};counters=Counter();new_chunks=[];mapping={}
    for document_id,unit in units:
        index=counters[document_id];counters[document_id]+=1
        cid='chk_'+sha256(f'{VERSION}|{document_id}|{unit.page_start}|{index}|{unit.kind}|{unit.text}'.encode()).hexdigest()[:20]
        # This is a storage estimate; provider-reported usage below is authoritative.
        c=Chunk(cid,document_id,names[document_id],unit.page_start,unit.page_end,index,unit.text,
                (len(unit.text)+3)//4,settings.embedding_model,kind=unit.kind)
        new_chunks.append(c);mapping[cid]=dict(kind=unit.kind,page_start=unit.page_start,page_end=unit.page_end,
            page_text_start=unit.start,page_text_end=unit.end,text_sha256=sha256(unit.text.encode()).hexdigest(),
            source_chunk_ids=list(unit.source_chunk_ids))
    output.mkdir(parents=True,mode=0o700);(output/'papers').mkdir()
    store=SqliteMetadataStore(output/'metadata.sqlite3');store.initialize()
    for d in documents:
        relative=Path('papers')/(d.file_hash+'.pdf')
        shutil.copy2(source/d.file_path,output/relative)
        store.upsert_document(replace(d,file_path=relative,status=DocumentStatus.PENDING,chunk_count=0))
    save(output/'source-pages.json',pages)
    manifest=dict(version=VERSION,status='building',source_metadata_sha256=digest(source/'metadata.sqlite3'),
        source_documents=[dict(id=d.id,file_hash=d.file_hash,filename=d.filename) for d in documents],
        source_chunks=len(old_chunks),chunks=len(new_chunks),chunk_kinds=dict(Counter(c.kind for c in new_chunks)),
        embedding_model=settings.embedding_model,embedding_dimensions=settings.embedding_dimensions,
        paragraph_target_chars=1200,max_evidence_chars=settings.context_max_evidence_chars,
        mapping=mapping,source_pages_sha256=digest(output/'source-pages.json'),embedding_calls=[],
        limitations=['Uses existing extracted text; no OCR or image understanding.',
                     'Same-page table grouping only; page-end tables are not certified complete across pages.',
                     'Oversized tables fail explicitly instead of truncating rows or inventing headers.'])
    save(output/'structure.json',manifest)
    try:
        vectors=vector_factory(output/'chroma')
        for start in range(0,len(new_chunks),settings.embedding_batch_size):
            batch=new_chunks[start:start+settings.embedding_batch_size]
            call=dict(chunk_count=len(batch),status='started',usage=None)
            manifest['embedding_calls'].append(call);save(output/'structure.json',manifest)
            try:
                embeddings=embedder.embed_documents([c.text for c in batch])
                vectors.upsert([VectorRecord(c.id,c.document_id,c.text,c.page_start,c.page_end,c.filename) for c in batch],embeddings)
                call['status']='completed'
            finally:
                call['usage']=getattr(embedder,'last_usage',None);save(output/'structure.json',manifest)
        for d in documents:store.complete_document(d.id,d.page_count,[c for c in new_chunks if c.document_id==d.id])
        manifest.update(status='ready',metadata_sha256=digest(output/'metadata.sqlite3'))
        save(output/'structure.json',manifest)
    except Exception:
        manifest['status']='failed';save(output/'structure.json',manifest);raise
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--output',type=Path)
    parser.add_argument('--env-file',type=Path,default=ROOT/'backend/.env.literature')
    parser.add_argument('--embed',action='store_true',help='Explicitly call the configured embedding provider and build the new index.')
    args=parser.parse_args();settings=Settings(_env_file=args.env_file)
    try:
        if args.embed:
            if args.output is None:raise ValueError('--output is required')
            result=build(args.source_dir,args.output,settings)
        else:
            documents,chunks,units,pages=plan(args.source_dir,settings.context_max_evidence_chars)
            result=dict(source_chunks=len(chunks),chunks=len(units),chunk_kinds=dict(Counter(u.kind for _,u in units)),
                        documents=len(documents),model_calls=0)
        print(json.dumps({k:v for k,v in result.items() if k in ['status','source_chunks','chunks','chunk_kinds','documents','model_calls']},ensure_ascii=False))
    except Exception as error:parser.exit(1,'Structure index build failed: '+type(error).__name__+'\n')


if __name__=='__main__':main()
