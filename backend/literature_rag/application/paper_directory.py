"""Read the active library's compact paper directory without a model/tool call."""
import json
import re
import sqlite3
from pathlib import Path


def load_paper_directory(root):
    root = Path(root)
    with sqlite3.connect((root/'metadata.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id, filename FROM documents WHERE EXISTS '
            '(SELECT 1 FROM chunks WHERE chunks.document_id=documents.id) ORDER BY id').fetchall()
    documents = []
    for did, filename in rows:
        title = ''
        if re.fullmatch(r'doc_[a-f0-9]+', did):
            path = root/'imports'/f'{did}.json'
            if path.is_file():
                info = json.loads(path.read_text('utf-8'))
                title = ' / '.join(t['title'] for t in info.get('organization', {}).get('document_titles', []))[:1500]
        documents.append(dict(document_id=did, filename=filename, title=title))
    return documents
