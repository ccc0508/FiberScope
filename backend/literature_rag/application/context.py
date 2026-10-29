"""Assemble bounded, same-page source context without another model or vector query."""
from collections.abc import Sequence
from dataclasses import dataclass, replace

from literature_rag.domain.errors import InfrastructureError
from literature_rag.domain.models import Chunk, Evidence, EvidenceSource
from literature_rag.ports.protocols import MetadataStore


@dataclass(frozen=True)
class ContextOptions:
    enabled: bool = False
    radius: int = 1
    max_evidence_chars: int = 8000
    max_total_chars: int = 24000

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.radius) is not int or not 0 <= self.radius <= 2:
            raise ValueError('invalid context expansion options')
        if any(type(v) is not int or not 256 <= v <= 100000 for v in (self.max_evidence_chars,self.max_total_chars)):
            raise ValueError('invalid context character budget')


def join_chunks(chunks: Sequence[Chunk]) -> str:
    """Remove only exact legacy overlap. Structural paragraph/table units stay intact."""
    out='';previous=None
    for chunk in chunks:
        overlap=0
        if previous is not None and previous.chunk_index+1==chunk.chunk_index:
            if previous.kind==chunk.kind=='text':
                for size in range(min(len(previous.text),len(chunk.text)),31,-1):
                    if previous.text[-size:]==chunk.text[:size]:
                        overlap=size;break
            separator='' if overlap else '\n\n'
        else:
            separator='\n\n[原文片段不连续]\n\n' if previous else ''
        out+=separator+chunk.text[overlap:];previous=chunk
    return out


def assemble(seeds: Sequence[Evidence], metadata: MetadataStore, options: ContextOptions):
    diagnostics=dict(enabled=options.enabled,seed_chunk_ids=[e.chunk_id for e in seeds],
                     radius=options.radius,max_evidence_chars=options.max_evidence_chars,
                     max_total_chars=options.max_total_chars,omitted_seed_chunk_ids=[],budget_limited=False)
    if not options.enabled or not seeds:
        diagnostics.update(result_count=len(seeds),context_chars=sum(len(e.text) for e in seeds),added_chunk_ids=[])
        return list(seeds),diagnostics
    chunks=metadata.get_context_chunks([e.chunk_id for e in seeds],options.radius)
    by_id={c.id:c for c in chunks}
    if len(by_id)!=len(chunks) or any(e.chunk_id not in by_id or by_id[e.chunk_id].text!=e.text
                                    or by_id[e.chunk_id].document_id!=e.document_id for e in seeds):
        raise InfrastructureError('context sources do not match authoritative seed metadata')
    if any(not any(c.document_id==e.document_id and c.page_start==e.page_start and c.page_end==e.page_end
                   and abs(c.chunk_index-by_id[e.chunk_id].chunk_index)<=options.radius for e in seeds) for c in chunks):
        raise InfrastructureError('context lookup returned unrelated source chunks')
    # Reserve space for the original ranked hits before spending it on neighbors.
    selected=[];reserved=0
    for e in seeds:
        if not e.text.strip() or len(e.text)>options.max_evidence_chars or reserved+len(e.text)>options.max_total_chars:
            diagnostics['omitted_seed_chunk_ids'].append(e.chunk_id);continue
        selected.append(e);reserved+=len(e.text)
    groups=[]
    for rank,e in enumerate(selected):
        seed=by_id[e.chunk_id]
        window={c.id for c in chunks if c.document_id==seed.document_id and c.page_start==seed.page_start
                and c.page_end==seed.page_end and abs(c.chunk_index-seed.chunk_index)<=options.radius}
        if seed.kind=='table':window={seed.id}
        touched=[g for g in groups if g['ids']&window]
        merged=dict(ids=set(window),seeds=[(rank,e)])
        for g in touched:
            merged['ids'].update(g['ids']);merged['seeds'].extend(g['seeds']);groups.remove(g)
        groups.append(merged)
    groups.sort(key=lambda g:min(rank for rank,_ in g['seeds']))
    results=[];sent=0;remaining=reserved

    def emit(source_chunks,seed_hits,status):
        nonlocal sent
        ordered=sorted(source_chunks,key=lambda c:c.chunk_index)
        anchor=min(seed_hits,key=lambda pair:pair[0])[1]
        text=join_chunks(ordered)
        sources=tuple(EvidenceSource(c.id,c.chunk_index,c.page_start,c.page_end,c.text,c.kind) for c in ordered)
        results.append(replace(anchor,ref=f'[{len(results)+1}]',text=text,
            page_start=min(c.page_start for c in ordered),page_end=max(c.page_end for c in ordered),
            source_chunks=sources,seed_chunk_ids=tuple(e.chunk_id for _,e in sorted(seed_hits)),context_status=status))
        sent+=len(text)

    for group in groups:
        hits=sorted(group['seeds']);remaining-=sum(len(e.text) for _,e in hits)
        full=sorted((by_id[cid] for cid in group['ids']),key=lambda c:c.chunk_index)
        size=len(join_chunks(full))
        available=options.max_total_chars-sent-remaining
        if size<=min(options.max_evidence_chars,available):
            emit(full,hits,'expanded' if len(full)>1 else 'original')
        else:
            diagnostics['budget_limited']=True
            for hit in hits:emit([by_id[hit[1].chunk_id]],[hit],'budget_limited')
    diagnostics['budget_limited']|=bool(diagnostics['omitted_seed_chunk_ids'])
    seed_ids={e.chunk_id for e in seeds}
    diagnostics.update(result_count=len(results),context_chars=sent,
                       added_chunk_ids=list(dict.fromkeys(s.chunk_id for e in results for s in e.source_chunks if s.chunk_id not in seed_ids)))
    return results,diagnostics
