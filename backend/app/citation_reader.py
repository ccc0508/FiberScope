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


def _matching_regions(entry, text, part):
    excerpt = part['text']
    spans = entry.get('source_spans', [])
    verified = {
        item['source_id']: item['verified_regions']
        for item in entry.get('quality_provenance', [])
        if item.get('verified_regions')
    }
    if 'start_char' in part or 'end_char' in part:
        start, end = part.get('start_char'), part.get('end_char')
        if (type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or text[start:end] != excerpt):
            return
    else:
        # Older citations have no offsets. Repeated text is ambiguous.
        start = text.find(excerpt)
        if start < 0 or text.find(excerpt, start + 1) >= 0:
            return
        end = start + len(excerpt)
    if excerpt == text:
        for span in spans:
            yield from verified.get(span.get('source_id'), [span])
        return

    # MinerU chunks have an optional section prefix followed by the joined spans.
    if not all(isinstance(span.get('text'), str) for span in spans):
        return
    body = '\n\n'.join(span['text'] for span in spans)
    if not text.endswith(body):
        return
    cursor = len(text) - len(body)
    for span in spans:
        stop = cursor + len(span['text'])
        if max(start, cursor) < min(end, stop):
            regions = verified.get(span.get('source_id'), [span])
            # A corrected span may cover multiple boxes without per-box text.
            if len(regions) == 1 or (start <= cursor and stop <= end):
                yield from regions
        cursor = stop + 2


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
        if row is None:
            continue
        if entry.get('text_sha256') != sha256(row['text'].encode()).hexdigest():
            continue
        yield from _matching_regions(entry, row['text'], part)


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
