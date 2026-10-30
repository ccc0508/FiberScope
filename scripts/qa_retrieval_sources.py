"""Load exact page/native span coordinates for the three frozen retrieval libraries."""
import json
from pathlib import Path
import sqlite3

from index_mineru_experiment import native_units
from qa_retrieval_alignment import locate_evidence,source_pages


def load_library(library,evidence):
    library=Path(library)
    manifest=json.loads((library/'structure.json').read_text(encoding='utf-8'))
    pages=json.loads((library/'source-pages.json').read_text(encoding='utf-8'))
    with sqlite3.connect((library/'metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as connection:
        connection.row_factory=sqlite3.Row
        chunks={row['id']:dict(row) for row in connection.execute('SELECT * FROM chunks ORDER BY chunk_index')}
    spans={}
    if manifest['version']=='text-structure-v1':
        units=[dict(source_id='page_'+str(p['page_start']),page=p['page_start'],text=p['text'],kind='page') for p in pages]
        for cid,m in manifest['mapping'].items():
            spans[cid]=[dict(source_id='page_'+str(m['page_start']),start=m['page_text_start'],end=m['page_text_end'])]
    else:
        raw=[block for page in pages for block in page['native_blocks']]
        units,_=native_units(raw,len(pages),max_chars=1000000)
        by_id={u['source_id']:u for u in units}
        for cid,m in manifest['mapping'].items():
            if 'source_spans' in m:
                spans[cid]=[{k:s[k] for k in ['source_id','start','end']} for s in m['source_spans']]
            else:
                sid=m['source_id'];spans[cid]=[dict(source_id=sid,start=0,end=len(by_id[sid]['text']))]
    if set(spans)!=set(chunks):
        raise ValueError('Index mapping does not match SQLite chunks')
    unit_text={u['source_id']:u['text'] for u in units}
    for cid,locations in spans.items():
        for span in locations:
            text=unit_text[span['source_id']]
            if not 0<=span['start']<span['end']<=len(text):
                raise ValueError('Chunk source span outside its original text')
    normalized_pages=source_pages(units)
    alignment={e['id']:locate_evidence(e,units,normalized_pages) for e in evidence}
    return dict(manifest=manifest,chunks=chunks,chunk_spans=spans,units=units,alignment=alignment)
