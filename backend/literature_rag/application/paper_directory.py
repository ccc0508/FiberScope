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


def routing_catalog_prompt(catalog):
    """Planner needs scope anchors; full identities remain in the trace and specialist directory."""
    anchors = [[item['label'] or item['title'] or item['filename'] or item['document_id'],
                item['topics']] for item in catalog]
    return '\nCatalog [paper, scope]; routing hints only, not evidence:\n' + json.dumps(
        anchors, ensure_ascii=False, separators=(',', ':'))


def load_paper_directory(root):
    root = Path(root)
    identities = json.loads(Path(__file__).with_name('paper_identities.json').read_text('utf8'))
    with sqlite3.connect((root/'metadata.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id, filename, file_hash FROM documents WHERE EXISTS '
            '(SELECT 1 FROM chunks WHERE chunks.document_id=documents.id) ORDER BY id').fetchall()
    documents = []
    for did, filename, file_hash in rows:
        title = ''
        if re.fullmatch(r'doc_[a-f0-9]+', did):
            path = root/'imports'/f'{did}.json'
            if path.is_file():
                info = json.loads(path.read_text('utf-8'))
                title = ' / '.join(t['title'] for t in info.get('organization', {}).get('document_titles', []))[:1500]
        item = dict(document_id=did, filename=filename, title=title,
                    authors=[], year=None, label='', identity_status='unverified')
        identity = identities.get(did)
        if identity and identity['pdf_sha256'] == file_hash:
            item.update({key: identity[key] for key in ('title', 'authors', 'year', 'label')})
            item.update(identity_status='verified_pdf_metadata', identity_source=identity['provenance'])
        documents.append(item)
    return documents
