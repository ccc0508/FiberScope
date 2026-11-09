import json
import sqlite3
from pathlib import Path
from literature_rag.application.paper_directory import load_paper_directory


def test_directory_identity_is_hash_bound_and_preserves_unknowns(tmp_path):
    metadata = json.loads((Path(__file__).parents[1]/'literature_rag/application/paper_identities.json').read_text('utf8'))
    li = 'doc_0fcf2a50cfa02d21'
    mot = 'doc_95f63c52fdb78ea6'
    with sqlite3.connect(tmp_path/'metadata.sqlite3') as db:
        db.executescript('CREATE TABLE documents(id TEXT,filename TEXT,file_hash TEXT);CREATE TABLE chunks(document_id TEXT);')
        db.executemany('INSERT INTO documents VALUES(?,?,?)', [(li,'renamed.pdf',metadata[li]['pdf_sha256']),
            (mot,'s10570.pdf',metadata[mot]['pdf_sha256']), ('new-doc','Li-2020.pdf','unknown')])
        db.executemany('INSERT INTO chunks VALUES(?)', [(li,), (mot,), ('new-doc',)])
    directory = {r['document_id']:r for r in load_paper_directory(tmp_path)}
    assert directory[li]['authors'] == ['Kunpeng Li','Lihong Zhao','Beihai He']
    assert directory[li]['year'] == 2020 and directory[li]['title']
    assert directory[mot]['year'] == 2019 and 'Motamedian' in directory[mot]['authors'][0]
    assert directory['new-doc']['identity_status'] == 'unverified'
    with sqlite3.connect(tmp_path/'metadata.sqlite3') as db:
        db.execute('UPDATE documents SET file_hash=? WHERE id=?', ('different', li))
    changed = {r['document_id']:r for r in load_paper_directory(tmp_path)}
    assert changed[li]['identity_status'] == 'unverified' and changed[li]['authors'] == []
