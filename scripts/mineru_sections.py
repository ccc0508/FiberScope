"""Deterministic section reconstruction with exact native-text span provenance.

This module reads no evaluation questions and calls no model. It changes retrieval
organization, never scientific values or the immutable native parser snapshots.
"""
from collections import Counter
from hashlib import sha256
import html
import re

VERSION = 'mineru-sections-v2'
NUMBER = re.compile(r'(?<![\d.])(?P<number>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?=[A-Za-z\u4e00-\u9fff])')
MEASUREMENT = re.compile(r'^[+−-]?\d+(?:[.,]\d+)?\s*(?:nm|[uμµ]m|mm|cm|m|mg|g|kg|ml|mL|L|s|min|h|%|°\s*[CS]|°SR)$', re.I)
NAMED_ROOTS = {'abstract', 'introduction', 'methods', 'materials and methods', 'experimental',
               'results', 'results and discussion', 'results and discussions', 'discussion',
               'conclusion', 'conclusions', 'references', 'bibliography',
               '摘要', '引言', '方法', '材料与方法', '结果', '讨论', '结论', '参考文献'}
AUXILIARY = {'header', 'footer', 'page_number'}


def plain(text):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', text)).split())


def title_label(text):
    """Only an exactly repeated display title may be collapsed; raw spans remain."""
    label = plain(text)
    for match in list(NUMBER.finditer(label))[1:]:
        left, right = label[:match.start()].strip(), label[match.start():].strip()
        if left == right:
            return left, True
    for i in range(1, len(label)):
        if label[:i].strip() == label[i:].strip():
            return label[:i].strip(), True
    return label, False


def locate_heading(unit):
    raw = unit['text']; label = plain(raw)
    native = unit['kind'] == 'heading'
    if unit['kind'] not in {'heading', 'paragraph'}:
        return None
    if MEASUREMENT.fullmatch(label):
        return dict(rejected='measurement_annotation') if native else None
    matches = list(NUMBER.finditer(raw))
    match = matches[0] if matches and (native or matches[0].start() == 0) else None
    if match:
        start = match.start() if plain(raw[:match.start()]) else 0
        label, deduplicated = title_label(raw[match.start():])
        # A numbered sentence can be a software version or a continued list item.
        # Promote unmarked text only when it has title-like punctuation.
        if not native and re.search(r'[.!?。！？]$',label):
            return None
        if len(label) > 240 or len(label.split()) > 42 or re.search(r'[!?。！？]$', label):
            return dict(rejected='ambiguous_heading') if native else None
        return dict(start=start, label=label, number=match['number'], depth=len(match['number'].split('.')),
                    deduplicated=deduplicated)
    if not native and label.casefold() not in NAMED_ROOTS:
        return None
    if len(label) > 240 or len(label.split()) > 42 or re.search(r'[.!?。！？]$', label):
        return dict(rejected='ambiguous_heading') if native else None
    label, deduplicated = title_label(raw)
    return dict(start=0, label=label, number=None,
                depth=1 if label.casefold() in NAMED_ROOTS else max(1, (unit.get('native_text_level') or 2)-1),
                deduplicated=deduplicated)


def source_span(unit, start=0, end=None):
    end = len(unit['text']) if end is None else end
    return dict(source_id=unit['source_id'], start=start, end=end, page=unit['page'],
                bbox=unit['bbox'], text=unit['text'][start:end])


def paragraph_spans(unit, start, end, target, hard_limit):
    """Sentence/whitespace cuts retain every source character, including whitespace."""
    text = unit['text']; cursor = start
    while end-cursor > target:
        limit = min(end, cursor+hard_limit)
        boundaries = [cursor+m.end() for m in re.finditer(r'[.!?。！？][\"”’\)]*(?=\s|$)', text[cursor:limit])]
        before = [b for b in boundaries if cursor+target//2 <= b <= cursor+target]
        after = [b for b in boundaries if cursor+target < b <= min(limit, cursor+target*2)]
        if before:
            cut = before[-1]
        elif after:
            cut = after[0]
        else:
            spaces = [cursor+m.end() for m in re.finditer(r'\s+', text[cursor:limit])]
            before = [b for b in spaces if b <= cursor+target]
            cut = before[-1] if before else (spaces[0] if spaces else end)
        if not cursor < cut <= limit:
            raise ValueError('Oversized unsplittable source text; content was not truncated')
        yield source_span(unit, cursor, cut)
        cursor = cut
    if cursor < end:
        yield source_span(unit, cursor, end)


def prefix_for(path):
    return '[章节标签（程序整理，非原文）] '+(' > '.join(path) if path else '未确定')+'\n[原文]\n'


def organize(units, document_id, native_blocks, target_chars=1200, max_chars=8000):
    if not 64 <= target_chars < max_chars:
        raise ValueError('Invalid paragraph target or evidence budget')
    sections=[]; anomalies=[]; documents=[]; parts=[]; stack=[]; by_number={}; seen_content=False; uncertain=False

    def issue(unit, code, **detail):
        anomalies.append(dict(source_id=unit['source_id'], page=unit['page'], code=code, **detail))

    def add_part(unit, start=0, end=None, kind=None):
        nonlocal seen_content
        end=len(unit['text']) if end is None else end
        if end <= start:
            return
        seen_content=True
        node=stack[-1] if stack and not uncertain else None
        path=node['path'] if node else []
        label=prefix_for(path)
        kind=kind or unit['kind']
        spans=list(paragraph_spans(unit,start,end,target_chars,max_chars-len(label))) if kind=='paragraph' else [source_span(unit,start,end)]
        for span in spans:
            if len(label)+len(span['text']) > max_chars:
                raise ValueError('Atomic source and chapter label exceed evidence budget')
            parts.append(dict(kind=kind,section_id=node['id'] if node else None,section_path=path,
                section_status=node['status'] if node else 'unassigned',span=span,native_index=unit['native_block_index']))

    for unit in units:
        candidate=locate_heading(unit)
        if candidate and 'rejected' in candidate:
            issue(unit,candidate['rejected'])
            if candidate['rejected']=='ambiguous_heading':
                uncertain=True
            add_part(unit,kind='paragraph')
            continue
        if not candidate:
            add_part(unit)
            continue
        if (not sections and unit['page']==1 and unit['bbox'][1]<300 and unit.get('native_text_level')==1
                and candidate['number'] is None and candidate['label'].casefold() not in NAMED_ROOTS):
            documents.append(dict(title=candidate['label'],source_span=source_span(unit)))
            continue
        if candidate['start']:
            add_part(unit,0,candidate['start'],kind='paragraph')
            issue(unit,'mixed_heading_prefix_preserved',prefix=unit['text'][:candidate['start']])
        if candidate['deduplicated']:
            issue(unit,'repeated_title_label_collapsed_raw_preserved')
        number=candidate['number']; depth=candidate['depth']; parent=None; status='inferred'
        if number and '.' in number:
            parent=by_number.get(number.rsplit('.',1)[0])
            if parent is None:
                issue(unit,'numbered_parent_missing',number=number); status='parent_unresolved'
            elif parent['status']!='inferred':
                status='parent_unresolved'
        elif not number and depth>1:
            parent=next((s for s in reversed(stack) if s['depth']<depth),None)
            if parent is None:
                issue(unit,'unnumbered_parent_missing'); status='parent_unresolved'
        prior=by_number.get(number) if number else None
        if prior:
            if prior['title']==candidate['label'] and stack and stack[-1]['id']==prior['id']:
                prior['source_spans'].append(source_span(unit,candidate['start']))
                issue(unit,'repeated_heading_node_reused')
                uncertain=False
                continue
            issue(unit,'duplicate_section_number_ambiguous',number=number)
            uncertain=True
            add_part(unit,candidate['start'],kind='paragraph')
            continue
        ancestors=[]
        if parent:
            ancestors=parent['path']
        name=NUMBER.sub('',candidate['label'],count=1).strip().casefold() if number else candidate['label'].casefold()
        node=dict(id='sec_'+sha256(f'{document_id}|{unit["source_id"]}|{candidate["label"]}'.encode()).hexdigest()[:16],
            title=candidate['label'],number=number,depth=depth,parent_id=parent['id'] if parent else None,
            path=[*ancestors,candidate['label']],status=status,
            source_spans=[source_span(unit,candidate['start'])],
            role='references' if name in {'references','bibliography','参考文献'} else 'section')
        sections.append(node)
        if number:
            by_number[number]=node
        lookup={s['id']:s for s in sections}; chain=[]; cursor=node
        while cursor:
            chain.append(cursor); cursor=lookup.get(cursor['parent_id'])
        stack=list(reversed(chain)); uncertain=False

    chunks=[]; pending=[]

    def flush():
        if not pending:
            return
        first=pending[0]; spans=[p['span'] for p in pending]
        body='\n\n'.join(s['text'] for s in spans)
        text=prefix_for(first['section_path'])+body
        if len(text)>max_chars:
            raise ValueError('Combined source text exceeds evidence budget')
        chunks.append(dict(kind=first['kind'],section_id=first['section_id'],section_path=first['section_path'],
            section_status=first['section_status'],page_start=min(s['page'] for s in spans),
            page_end=max(s['page'] for s in spans),source_spans=spans,body_text=body,text=text))
        pending.clear()

    def adjacent(a,b):
        if a['native_index']==b['native_index']:
            return a['span']['end']==b['span']['start']
        between=native_blocks[a['native_index']+1:b['native_index']]
        return all(x['type'] in AUXILIARY for x in between)

    for part in parts:
        if pending:
            last=pending[-1]
            same=part['kind']==last['kind']=='paragraph' and part['section_id']==last['section_id'] and part['section_status']==last['section_status']
            size=sum(len(p['span']['text']) for p in pending)+len(part['span']['text'])+2*len(pending)
            cross_page=part['span']['page']!=last['span']['page']
            continuation=not re.search(r'[.!?。！？]\s*$',last['span']['text']) and bool(re.match(r'\s*[a-z\u4e00-\u9fff]',part['span']['text']))
            if not (same and adjacent(last,part) and size<=target_chars and (not cross_page or continuation)):
                flush()
        pending.append(part)
        if part['kind']!='paragraph':
            flush()
    flush()
    # Every retained native character must occur once in raw evidence or title provenance.
    coverage={u['source_id']:[] for u in units}
    for node in sections:
        for span in node['source_spans']:
            coverage[span['source_id']].append((span['start'],span['end']))
    for doc in documents:
        span=doc['source_span']; coverage[span['source_id']].append((span['start'],span['end']))
    for chunk in chunks:
        for span in chunk['source_spans']:
            coverage[span['source_id']].append((span['start'],span['end']))
    for unit in units:
        cursor=0
        for start,end in sorted(coverage[unit['source_id']]):
            if start!=cursor or end<=start or end>len(unit['text']):
                raise ValueError('Native text provenance overlaps or has gaps')
            cursor=end
        if cursor!=len(unit['text']):
            raise ValueError('Native text was lost')
    return dict(version=VERSION,document_titles=documents,sections=sections,chunks=chunks,anomalies=anomalies,
        paragraph_target_chars=target_chars,max_evidence_chars=max_chars,
        source_coverage=dict(native_units=len(units),characters=sum(len(u['text']) for u in units),exact_once=True),
        chunk_kinds=dict(Counter(c['kind'] for c in chunks)),
        policy='Section labels inferred automatically; raw body characters preserved exactly with source spans. No reference filtering, table row indexing, new context expansion, or prompt change.')
