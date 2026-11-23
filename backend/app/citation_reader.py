"""Resolve saved citations to normalized PDF page regions."""

from hashlib import sha256
import json


def _region(page, bbox, first, last):
    if type(page) is not int or not first <= page <= last:
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    if any(type(value) not in (int, float) or not 0 <= value <= 1000 for value in bbox):
        return None
    x0, y0, x1, y1 = bbox
    return (page, x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _text_regions(connection, library, citation):
    try:
        mapping = json.loads((library / 'structure.json').read_text(encoding='utf-8'))['mapping']
    except (OSError, ValueError, KeyError, TypeError):
        return
    if not isinstance(mapping, dict):
        return
    parts = citation.get('source_chunks') or [{
        'chunk_id': citation.get('chunk_id'),
        'text': citation.get('excerpt'),
    }]
    for part in parts:
        entry = mapping.get(part.get('chunk_id'))
        excerpt = part.get('text')
        if not entry or not excerpt:
            continue
        row = connection.execute(
            'SELECT text FROM chunks WHERE id=? AND document_id=?',
            (part['chunk_id'], citation['document_id']),
        ).fetchone()
        if row is None or excerpt not in row['text']:
            continue
        if entry.get('text_sha256') != sha256(row['text'].encode()).hexdigest():
            continue
        verified = {
            item['source_id']: item['verified_regions']
            for item in entry.get('quality_provenance', [])
            if item.get('verified_regions')
        }
        for span in entry.get('source_spans', []):
            yield from verified.get(span.get('source_id'), [span])


def citation_regions(connection, library, document, citation, first, last):
    document_hash = citation.get('document_hash')
    if document_hash and document_hash != document['file_hash']:
        return []
    if citation.get('kind') == 'source_image':
        sources = (
            asset for asset in citation.get('visual_assets', [])
            if asset.get('document_id') == citation['document_id']
        )
    else:
        sources = _text_regions(connection, library, citation)
    boxes = {
        box for source in sources
        if (box := _region(source.get('page'), source.get('bbox'), first, last)) is not None
    }
    return [
        {'page': page, 'bbox': [x0, y0, x1, y1]}
        for page, x0, y0, x1, y1 in sorted(boxes, key=lambda box: (box[0], box[2], box[1], box[4], box[3]))
    ]
