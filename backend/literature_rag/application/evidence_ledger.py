"""Immutable evidence snapshots with run-local, transactional citation identities."""
from copy import deepcopy
from hashlib import sha256
import json
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def create_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS evidence_ledger ('
        'run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, digest TEXT NOT NULL, snapshot TEXT NOT NULL, '
        'PRIMARY KEY(run_id,ordinal), UNIQUE(run_id,digest))')
    db.execute('CREATE TABLE IF NOT EXISTS evidence_origins ('
        'run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, call_id TEXT NOT NULL, '
        'PRIMARY KEY(run_id,ordinal,call_id))')


def register_result(db, record):
    """Called inside the same transaction as the final successful tool trace."""
    result = deepcopy(record['result'])
    run, call = record['run_id'], record['call_id']
    hashes = {d['document_id']:d.get('file_hash') for d in record.get('provenance',{}).get('documents',[])}

    def add(kind, content):
        snapshot = dict(kind=kind, content=content)
        digest = sha256(canonical(snapshot).encode()).hexdigest()
        row = db.execute('SELECT ordinal FROM evidence_ledger WHERE run_id=? AND digest=?',(run,digest)).fetchone()
        if row: ordinal=row[0]
        else:
            ordinal=db.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM evidence_ledger WHERE run_id=?',(run,)).fetchone()[0]
            db.execute('INSERT INTO evidence_ledger VALUES (?,?,?,?)',(run,ordinal,digest,canonical(snapshot)))
        db.execute('INSERT OR IGNORE INTO evidence_origins VALUES (?,?,?)',(run,ordinal,call))
        return f'[{ordinal}]'

    def text_ref(e):
        chunks=e.get('source_chunks') or [dict(chunk_id=e['chunk_id'],text=e['text'],
            page_start=e['page_start'],page_end=e['page_end'])]
        spans=[dict(chunk_id=c['chunk_id'],page_start=c['page_start'],page_end=c['page_end'],text=c['text']) for c in chunks]
        return add('source_text',dict(document_id=e['document_id'],document_hash=hashes.get(e['document_id']),
            filename=e['filename'],page_start=e['page_start'],page_end=e['page_end'],text=e['text'],sources=spans,
            start_char=e.get('start_char',0),end_char=e.get('end_char',len(e['text'])),
            images=e.get('visual_assets',[])))

    tool=record['input']['tool']
    if tool=='search_literature':
        mapping={}
        for e in result['evidence']:
            old=e['ref'];e['ref']=text_ref(e);mapping[old]=e['ref']
        result['local_to_run_refs']=mapping
        result['reference_scope']='run'
    elif tool=='read_section':
        for e in result['sources']:e['ref']=text_ref(e)
    elif tool=='read_table':result['table']['ref']=text_ref(result['table'])
    elif tool=='view_image':
        a=result['asset']
        result['ref']=add('source_image',dict(asset=a,document_hash=hashes.get(a['document_id']),
            image_sha256=result['image_sha256'],image_bytes=result['image_bytes']))
    elif tool=='calculate_change':
        origins=[]
        for source_call in result['source_call_ids']:
            origins.extend(r[0] for r in db.execute('SELECT ordinal FROM evidence_origins WHERE run_id=? AND call_id=?',(run,source_call)))
        result['source_refs']=[f'[{i}]' for i in sorted(set(origins))]
        # Derived computation is explicitly distinct from a quotation from a paper.
        result['ref']=add('calculation',dict(result))
    result['evidence_scope']=dict(run_id=run,reference_policy='immutable_exact_snapshot',
        notice='References are unique only within this run. Text availability is not proof of visual inspection.')
    return result


def read_ledger(db,run_id,refs=None):
    selected=None
    if refs is not None:
        if any(not isinstance(r,str) or not re.fullmatch(r'\[[1-9][0-9]*\]',r) for r in refs):
            raise ValueError('Invalid reference')
        selected={int(r[1:-1]) for r in refs}
    rows=db.execute('SELECT ordinal,digest,snapshot FROM evidence_ledger WHERE run_id=? ORDER BY ordinal',(run_id,)).fetchall()
    if selected is not None and not selected <= {r[0] for r in rows}:raise LookupError('Reference unavailable in this run')
    return [dict(ref=f'[{i}]',sha256=d,**json.loads(s),call_ids=[r[0] for r in db.execute(
        'SELECT call_id FROM evidence_origins WHERE run_id=? AND ordinal=? ORDER BY rowid',(run_id,i))])
        for i,d,s in rows if selected is None or i in selected]
