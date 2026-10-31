"""Delete only extra sources actually added by fallback; never reassemble other context."""
from copy import deepcopy
from dataclasses import replace

from literature_rag.application.context import join_chunks
from literature_rag.domain.models import Chunk

VERSION='fallback-extras-deletion-v1'


def remove_fallback_extras(evidences,seeds,assembly):
    """Offline ablation of sealed context, preserving groups, refs, seeds and all other text."""
    primary={s.chunk_id for s in seeds}
    decisions=assembly['decisions']
    if {d['seed_chunk_id'] for d in decisions}!=primary:
        raise ValueError('Assembly decisions do not match primary hits')
    fallback={d['seed_chunk_id'] for d in decisions if d['mode']=='same_page_fallback'}
    # If a source independently belongs to a retained section group, protect it.
    protected=set(primary)
    for e in evidences:
        if any(sid not in fallback for sid in e.seed_chunk_ids):
            protected.update(s.chunk_id for s in e.source_chunks)
    def joined(sources,e):
        return join_chunks([Chunk(s.chunk_id,e.document_id,e.filename,s.page_start,s.page_end,s.chunk_index,
            s.text,0,'not_invoked',kind=s.kind) for s in sources])
    out=[];removed=[];changes=[]
    for e in evidences:
        if not e.source_chunks or joined(e.source_chunks,e)!=e.text:
            raise ValueError('Sealed evidence cannot be reproduced from its source chunks')
        eligible=bool(e.seed_chunk_ids) and all(sid in fallback for sid in e.seed_chunk_ids)
        dropped=[s for s in e.source_chunks if eligible and s.chunk_id not in protected]
        if not dropped:
            out.append(e);continue
        keep=[s for s in e.source_chunks if s not in dropped]
        if not keep or not set(e.seed_chunk_ids)<={s.chunk_id for s in keep}:
            raise ValueError('A primary hit would be deleted')
        new=replace(e,text=joined(keep,e),source_chunks=tuple(keep),
                    page_start=min(s.page_start for s in keep),page_end=max(s.page_end for s in keep))
        out.append(new);removed.extend(s.chunk_id for s in dropped)
        changes.append(dict(ref=e.ref,seed_chunk_ids=list(e.seed_chunk_ids),removed_chunk_ids=[s.chunk_id for s in dropped],
            old_chars=len(e.text),new_chars=len(new.text)))
    if not primary<={s.chunk_id for e in out for s in e.source_chunks}:
        raise ValueError('Original primary hit missing')
    info=deepcopy(assembly)
    info.update(version=VERSION,context_chars=sum(len(e.text) for e in out),
        added_chunk_ids=[cid for cid in info['added_chunk_ids'] if cid not in removed],
        fallback_ablation=dict(fallback_decisions=len(fallback),changed_groups=len(changes),changes=changes,
            removed_chunk_ids=list(dict.fromkeys(removed)),removed_source_chars=sum(len(s.text) for e in evidences for s in e.source_chunks if s.chunk_id in removed),
            context_chars_removed=sum(len(e.text) for e in evidences)-sum(len(e.text) for e in out),
            same_group_count_and_refs=[e.ref for e in out]==[e.ref for e in evidences],
            no_replacement_or_budget_redistribution=True))
    return out,info
