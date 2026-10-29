from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import time

import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'srp/src'))
from literature_rag.adapters.pdf.pymupdf_parser import PyMuPdfParser
from literature_rag.application.chunking import PageChunker

OUT=ROOT/'.rag-data/parsing-comparisons/mineru-vs-pymupdf-20261029'
PDF=ROOT/'.rag-data/index-versions/structure-v1-20261029/papers/0fcf2a50cfa02d214b53a8c2d40ed3f660a41b1c81b3fbea04120a81dc09d4d4.pdf'
OUT.mkdir(parents=True,exist_ok=True)
started=time.perf_counter()
pages=PyMuPdfParser().parse(PDF)
drafts=PageChunker(1200,200).split(pages)
elapsed=time.perf_counter()-started

def chunks(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        return [dict(row) for row in conn.execute('SELECT * FROM chunks ORDER BY chunk_index')]

data=dict(pdf_sha256=hashlib.sha256(PDF.read_bytes()).hexdigest(),pymupdf_version=pymupdf.VersionBind,
    parser_source_sha256=hashlib.sha256((ROOT.parent/'srp/src/literature_rag/adapters/pdf/pymupdf_parser.py').read_bytes()).hexdigest(),
    chunker_source_sha256=hashlib.sha256((ROOT.parent/'srp/src/literature_rag/application/chunking.py').read_bytes()).hexdigest(),
    extraction_and_fixed_chunk_seconds=elapsed,fresh_pages=[asdict(p) for p in pages],fresh_fixed_chunks=[asdict(c) for c in drafts],
    archived_fixed_chunks=chunks(ROOT/'.rag-data/metadata.sqlite3'),
    current_structural_chunks=chunks(ROOT/'.rag-data/index-versions/structure-v1-20261029/metadata.sqlite3'),
    archived_page_snapshots=json.loads((ROOT/'.rag-data/index-versions/structure-v1-20261029/source-pages.json').read_text(encoding='utf-8')))
(OUT/'pymupdf-baseline.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
(OUT/'pymupdf-full.txt').write_text('\n\n'.join(f'=== PDF page {p.page_number} ===\n{p.text}' for p in pages),encoding='utf-8',newline='\n')
with pymupdf.open(PDF) as document:
    for number in [6,8]:
        document[number-1].get_pixmap(matrix=pymupdf.Matrix(1.6,1.6),alpha=False).save(OUT/f'pdf-page-{number}.png')
print(json.dumps(dict(pages=len(pages),fresh_fixed_chunks=len(drafts),archived_fixed_chunks=len(data['archived_fixed_chunks']),
    current_structural_chunks=len(data['current_structural_chunks']),pymupdf_version=pymupdf.VersionBind,
    extraction_and_fixed_chunk_seconds=elapsed)))
