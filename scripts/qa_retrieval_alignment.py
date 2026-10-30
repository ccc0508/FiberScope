"""Locate frozen reference passages in parser sources; not a semantic quality judge."""
from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
import html
import re
import unicodedata

TAG=re.compile(r'</?[A-Za-z][^>]*>')
ENTITY=re.compile(r'&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);')
NUMBER=re.compile(r'[+−-]?\d+(?:,\d{3})*(?:\.\d+)?')
ALIASES={'◦':'°','−':'-','–':'-','‐':'-','’':"'",'′':"'",'⋯':'···'}


def normalized_view(text):
    """Search-only typography normalization with reversible raw-character locations."""
    skip={i for m in TAG.finditer(text) for i in range(m.start(),m.end())}
    entities={m.start():m for m in ENTITY.finditer(text)}
    chars=[];positions=[];i=0
    while i<len(text):
        if i in skip:
            i+=1;continue
        entity=entities.get(i)
        raw=html.unescape(entity[0]) if entity else text[i]
        for c in unicodedata.normalize('NFKC',raw):
            for normalized in ALIASES.get(c,c):
                if not normalized.isspace() and normalized!='\u00ad':
                    chars.append(normalized);positions.append(i)
        i=entity.end() if entity else i+1
    return ''.join(chars),positions


def source_pages(units):
    """Page text and per-character ownership, without joining unrelated pages."""
    grouped=defaultdict(list)
    for unit in units:
        grouped[unit['page']].append(unit)
    result={}
    for page,items in grouped.items():
        chars=[];locations=[]
        for unit in items:
            text,positions=normalized_view(unit['text'])
            chars.extend(text);locations.extend((unit['source_id'],position) for position in positions)
        result[page]=dict(text=''.join(chars),locations=locations)
    return result


def spans_from_locations(locations):
    grouped=defaultdict(list)
    for sid,offset in locations:
        grouped[sid].append(offset)
    return [dict(source_id=sid,start=min(offsets),end=max(offsets)+1) for sid,offsets in grouped.items()]


def numeric_table_target(evidence,units):
    """Identify the same atomic table using page, caption and all annotated data rows."""
    match=re.search(r'Table\s+(\d+)\s*\(([ab])\)',evidence['locator'],re.I)
    if not match:
        return None
    start=re.search(r'(?<![\d.])0\s+\d+\.\d+',evidence['quote'])
    if not start:
        return None
    wanted=[Decimal(x.replace(',','')) for x in NUMBER.findall(evidence['quote'][start.start():])]
    possibilities=[]
    for unit in units:
        if unit['page']!=evidence['pdf_page'] or unit.get('kind')!='table':
            continue
        if not re.search(r'Table\s+'+re.escape(match[1])+r'\b',unit['text'][:500],re.I):
            continue
        rows=[]
        for row in re.finditer(r'<tr\b[^>]*>(.*?)</tr>',unit['text'],re.I|re.S):
            cells=re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>',row[1],re.I|re.S)
            clean=[''.join(normalized_view(c)[0].split()) for c in cells]
            if len(clean)==6 and all(NUMBER.fullmatch(c) for c in clean):
                rows.append([Decimal(c.replace(',','')) for c in clean])
        flat=[n for row in rows for n in row]
        # The frozen annotations contain five complete rows of six numbers each.
        if len(wanted)!=30:
            continue
        hits=[i for i in range(0,len(flat)-len(wanted)+1,6) if flat[i:i+len(wanted)]==wanted]
        if len(hits)==1:
            possibilities.append(dict(method='verified_table_rows',status='located',pdf_page=unit['page'],
                spans=[dict(source_id=unit['source_id'],start=0,end=len(unit['text']))],
                numeric_rows=5,numeric_cells=30,table_number=match[1],row_start=hits[0]//6,
                note='Atomic table object located by caption/page and every annotated numeric cell; not a judgment of answer sufficiency.'))
    return possibilities[0] if len(possibilities)==1 else None


def locate_segment(segment,pages):
    needle,_=normalized_view(segment['quote']);page=pages.get(segment['pdf_page'])
    if not needle or not page:
        return dict(status='unresolved',method='no_page_or_text',pdf_page=segment['pdf_page'],spans=[])
    text=page['text'];start=text.find(needle)
    if start>=0:
        return dict(status='located',method='exact_typography',pdf_page=segment['pdf_page'],
            spans=spans_from_locations(page['locations'][start:start+len(needle)]),coverage=1.0)
    matcher=SequenceMatcher(None,needle,text,autojunk=False)
    anchor=matcher.find_longest_match()
    if anchor.size<min(40,len(needle)*.4):
        return dict(status='unresolved',method='no_long_text_anchor',pdf_page=segment['pdf_page'],spans=[])
    estimate=anchor.b-anchor.a;slack=max(80,len(needle)//2)
    left=max(0,estimate-slack);right=min(len(text),estimate+len(needle)+slack)
    window=text[left:right]
    blocks=[b for b in SequenceMatcher(None,needle,window,autojunk=False).get_matching_blocks() if b.size]
    first,last=blocks[0],blocks[-1];left+=first.b;right=left+(last.b+last.size-first.b)
    window=text[left:right];matcher=SequenceMatcher(None,needle,window,autojunk=False)
    matched=sum(b.size for b in matcher.get_matching_blocks());fraction=matched/len(needle)
    edits=[dict(operation=tag,reference=needle[a:b],parsed=window[c:d])
           for tag,a,b,c,d in matcher.get_opcodes() if tag!='equal']
    numeric_difference=any(any(ch.isdigit() for ch in edit['reference']+edit['parsed']) for edit in edits)
    if fraction<.85 or len(window)>2.0*len(needle):
        return dict(status='unresolved',method='weak_text_alignment',pdf_page=segment['pdf_page'],spans=[],coverage=fraction,edits=edits)
    return dict(status='review_required',method='near_text_anchor',pdf_page=segment['pdf_page'],
        spans=spans_from_locations(page['locations'][left:right]),coverage=fraction,
        scientific_numeric_difference=numeric_difference,edits=edits,
        note='A corresponding passage was located, but parser text differs. Presence is positional only; semantic support is not certified.')


def locate_evidence(evidence,units,pages):
    table=numeric_table_target(evidence,units)
    if table:
        return dict(evidence_id=evidence['id'],status='located',segments=[table],spans=table['spans'])
    segments=[locate_segment(s,pages) for s in [evidence,*evidence.get('continuation',[])]]
    status='unresolved' if any(s['status']=='unresolved' for s in segments) else (
        'review_required' if any(s['status']=='review_required' for s in segments) else 'located')
    return dict(evidence_id=evidence['id'],status=status,segments=segments,
                spans=[span for s in segments for span in s['spans']])


def interval_union(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if start>=end:
            continue
        if merged and start<=merged[-1][1]:
            merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        else:
            merged.append((start,end))
    return merged


def span_coverage(target,selected,chunk_spans):
    """Coverage of identified raw source intervals, never page/keyword-only hits."""
    if target['status']=='unresolved' or not target['spans']:
        return dict(status='unresolved',covered=0,total=0,ratio=None,chunk_ids=[])
    by_source=defaultdict(list);relevant=[]
    for cid in selected:
        for span in chunk_spans[cid]:
            by_source[span['source_id']].append((span['start'],span['end'],cid))
    total=covered=0
    for wanted in target['spans']:
        total+=wanted['end']-wanted['start'];overlaps=[]
        for start,end,cid in by_source[wanted['source_id']]:
            a,b=max(start,wanted['start']),min(end,wanted['end'])
            if a<b:
                overlaps.append((a,b));relevant.append(cid)
        covered+=sum(b-a for a,b in interval_union(overlaps))
    return dict(status='complete' if covered==total else 'partial' if covered else 'missing',
        covered=covered,total=total,ratio=covered/total,chunk_ids=list(dict.fromkeys(relevant)),
        alignment_status=target['status'])
