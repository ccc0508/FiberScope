"""Read the active library's compact paper directory without a model/tool call."""
import json
import re
import sqlite3
from pathlib import Path


def routing_catalog(directory):
    """Topic hints only for active documents; new documents retain their real identity."""
    hints = json.loads(Path(__file__).with_name('routing_catalog.json').read_text('utf8'))
    result = []
    for item in directory or []:
        did = item.get('document_id', '')
        hint = hints.get(did, {})
        result.append(dict(document_id=did, filename=str(item.get('filename', ''))[:200],
                           title=str(hint.get('title') or item.get('title', ''))[:350],
                           label=hint.get('label', ''), topics=hint.get('topics', ''),
                           metadata_status='curated_topic_hint' if hint else 'identity_only'))
    return result


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
