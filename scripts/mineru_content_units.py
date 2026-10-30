"""Deterministic metadata separation, formula bundles and conservative page continuations."""
from collections import Counter
from copy import deepcopy
import re

from mineru_sections import organize, prefix_for, MEASUREMENT
from mineru_quality import plain

VERSION='mineru-content-units-v1'


def metadata_role(unit):
    text=plain(unit['text']).strip()
    if unit['page']!=1 or unit['kind'] not in {'paragraph','heading'}:
        return None
    if re.match(r'^(?:keywords?|关键词|关键字)\s*[:：]',text,re.I):
        return 'keywords'
    if text.casefold() in {'article','research article','research paper','review','review article','communication','letter'} and unit['bbox'][1]<300:
        return 'publication_type'
    return None


def visual_target(unit,blocks):
    x0,y0,x1,y1=unit['bbox'];candidates=[]
    if not MEASUREMENT.fullmatch(plain(unit['text'])):
        return None
    for i,block in enumerate(blocks):
        if block['type'] not in {'image','chart'} or block['page_idx']!=unit['page']-1:
            continue
        a,b,c,d=block['bbox']
        overlap=max(0,min(x1,c)-max(x0,a))
        gap=max(0,b-y1,y0-d)
        if overlap >= .5*max(1,x1-x0) and gap<=60:
            candidates.append((gap,i))
    candidates.sort()
    if not candidates or len(candidates)>1 and candidates[0][0]==candidates[1][0]:
        return None
    return candidates[0][1]


def rebuild(chunk,spans,kind=None):
    value=deepcopy(chunk)
    value['source_spans']=deepcopy(spans)
    value['body_text']='\n\n'.join(s['text'] for s in spans)
    value['text']=prefix_for(value['section_path'])+value['body_text']
    value['page_start']=min(s['page'] for s in spans)
    value['page_end']=max(s['page'] for s in spans)
    if kind:value['kind']=kind
    if len(value['text'])>8000:raise ValueError('Content bundle exceeds the unchanged evidence budget')
    return value


def formula_neighbors(units,index):
    eq=units[index]
    result=[]
    if index:
        before=units[index-1]
        text=plain(before['text'])
        if before['kind']=='paragraph' and (len(text)<300 or re.search(r'\b[Ee]quations?\s*\(\d+\)|as follows|式[（(]\d+',text)):
            result.append(before['source_id'])
    result.append(eq['source_id'])
    if index+1<len(units):
        after=units[index+1];text=plain(after['text'])
        definition=re.match(r'^(?:where\b|in which\b|式中|其中)',text,re.I) or (
            text.startswith(('$','\\')) and re.search(r'\b(?:is|are|denotes?|represents?)\b',text[:180]))
        if after['kind']=='paragraph' and definition:
            result.append(after['source_id'])
    return result


def process(units,document_id,native_blocks):
    source=deepcopy(units);classified=deepcopy(units);events=[];annotations={};roles={}
    by_source={u['source_id']:u for u in source}
    source_order={u['source_id']:u['native_block_index'] for u in source}
    for unit in classified:
        role=metadata_role(unit)
        if role:
            unit['kind']='document_metadata';roles[unit['source_id']]=role
            events.append(dict(kind='metadata_separated',source_id=unit['source_id'],role=role))
        elif unit['kind'] in {'paragraph','heading'} and MEASUREMENT.fullmatch(plain(unit['text'])):
            target=visual_target(unit,native_blocks)
            if target is not None:
                unit.update(kind='figure_annotation',native_text_level=None)
                annotations[unit['source_id']]=f'mineru_block_{target:04}'
                events.append(dict(kind='figure_annotation_classified',source_id=unit['source_id'],visual_source_id=annotations[unit['source_id']],
                                   basis='same page, horizontal overlap and close layout gap; no new image interpretation'))
    result=organize(classified,document_id,native_blocks)
    original_chunks=result['chunks']
    owners={s['source_id']:c for c in original_chunks for s in c['source_spans']}
    spans={}
    for chunk in original_chunks:
        for span in chunk['source_spans']:spans.setdefault(span['source_id'],[]).append(span)
    taken=set();bundles=[]
    for i,unit in enumerate(classified):
        if unit['kind']!='equation':continue
        eq_chunk=owners[unit['source_id']]
        ids=[sid for sid in formula_neighbors(classified,i) if sid not in taken and sid in owners and
             owners[sid]['section_id']==eq_chunk['section_id'] and owners[sid]['section_status']==eq_chunk['section_status']]
        if unit['source_id'] not in ids:raise ValueError('Formula source already consumed')
        sources=[span for sid in ids for span in spans[sid]]
        # Neighbors can be on the next page only when there is no skipped non-auxiliary native unit.
        sources.sort(key=lambda s:(source_order[s['source_id']],s['start']))
        if len(prefix_for(eq_chunk['section_path']))+sum(len(s['text']) for s in sources)+2*max(0,len(sources)-1)>8000:
            events.append(dict(kind='formula_bundle_omitted',source_id=unit['source_id'],reason='length_budget'))
            continue
        bundle=rebuild(eq_chunk,sources,'equation_bundle')
        bundle['organization']=dict(kind='formula_with_name_conditions_and_definitions',equation_source_id=unit['source_id'],included_source_ids=ids)
        bundles.append(bundle);taken.update(ids)
        events.append(dict(kind='formula_bundle_created',equation_source_id=unit['source_id'],source_ids=ids))
    chunks=[];metadata=[];annotation_chunks={}
    for chunk in original_chunks:
        remaining=[s for s in chunk['source_spans'] if s['source_id'] not in taken]
        if not remaining:continue
        current=rebuild(chunk,remaining)
        if current['kind']=='document_metadata':
            current['role']=roles[current['source_spans'][0]['source_id']]
            metadata.append(current)
        elif current['kind']=='figure_annotation':
            annotation_chunks[current['source_spans'][0]['source_id']]=current
        else:chunks.append(current)
    for sid,current in annotation_chunks.items():
        target=next((c for c in chunks if c['kind']=='figure_caption' and any(s['source_id']==annotations[sid] for s in c['source_spans'])),None)
        if target is None:
            current['role']='figure_annotation_without_caption';metadata.append(current)
            events.append(dict(kind='annotation_saved_without_retrieval_caption',source_id=sid))
            continue
        combined=sorted([*target['source_spans'],*current['source_spans']],key=lambda s:(source_order[s['source_id']],s['start']))
        target.update(rebuild(target,combined))
        target['organization']=dict(kind='figure_caption_with_original_annotation',visual_source_id=annotations[sid],annotation_source_ids=[sid])
        events.append(dict(kind='annotation_attached_to_figure_caption',source_id=sid,visual_source_id=annotations[sid]))
    chunks.extend(bundles)
    chunks.sort(key=lambda c:min((source_order[s['source_id']],s['start']) for s in c['source_spans']))
    # Join only the last/first body pieces at a page boundary in the same known section.
    merged=[]
    for chunk in chunks:
        if chunk['kind']=='paragraph' and chunk['section_id'] and merged:
            previous=merged[-1]
            end=previous['source_spans'][-1];start=chunk['source_spans'][0]
            next_text=plain(start['text'])
            continuation=bool(re.match(r'^[a-z\u4e00-\u9fff]|^[)\],;]|^\d+(?:\.\d+){1,3}\s+software\b',next_text))
            body=previous['body_text']+'\n\n'+chunk['body_text']
            between=native_blocks[source_order[end['source_id']]+1:source_order[start['source_id']]]
            no_content_boundary=all(b['type'] in {'header','footer','page_number'} for b in between)
            if (previous['kind']=='paragraph' and previous['section_id']==chunk['section_id'] and
                previous['section_status']==chunk['section_status']=='inferred' and
                previous['page_end']+1==chunk['page_start'] and end['bbox'][3]>=750 and start['bbox'][1]<=220 and
                not re.search(r'[.!?。！？]\s*$',previous['body_text']) and continuation and no_content_boundary and len(body)<=1200):
                joined=rebuild(previous,[*previous['source_spans'],*chunk['source_spans']])
                joined['organization']=dict(kind='page_boundary_sentence_continuation',source_ids=[end['source_id'],start['source_id']],
                    basis='same inferred section, adjacent pages, bottom/top positions, unfinished sentence and matching continuation form')
                merged[-1]=joined
                events.append(dict(kind='page_continuation_joined',source_ids=[end['source_id'],start['source_id']],pages=[previous['page_end'],chunk['page_start']]))
                continue
        merged.append(chunk)
    chunks=merged
    # Check conservation against the corrected native text, including separated metadata/titles.
    coverage={u['source_id']:[] for u in source}
    for chunk in [*chunks,*metadata]:
        for span in chunk['source_spans']:
            if by_source[span['source_id']]['text'][span['start']:span['end']]!=span['text']:
                raise ValueError('Source text changed during content organization')
            coverage[span['source_id']].append((span['start'],span['end']))
    for section in result['sections']:
        for span in section['source_spans']:coverage[span['source_id']].append((span['start'],span['end']))
    for title in result['document_titles']:
        span=title['source_span'];coverage[span['source_id']].append((span['start'],span['end']))
    for unit in source:
        cursor=0
        for a,b in sorted(coverage[unit['source_id']]):
            if a!=cursor or b<=a:raise ValueError('Content source coverage overlaps or has gaps')
            cursor=b
        if cursor!=len(unit['text']):raise ValueError('Content was lost during organization')
    return dict(version=VERSION,chunks=chunks,document_metadata=metadata,sections=result['sections'],document_titles=result['document_titles'],
        events=events,chunk_kinds=dict(Counter(c['kind'] for c in chunks)),
        source_coverage=dict(native_units=len(source),characters=sum(len(u['text']) for u in source),exact_once=True),
        paragraph_target_chars=1200,max_evidence_chars=8000,
        policy='Reorganize source text only. No LLM calls, scientific rewriting, new semantic interpretation, reference filtering or reranker.')
