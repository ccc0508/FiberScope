"""Collect candidates from primary hits only, then allocate one bounded budget."""
from literature_rag.application.section_context import assemble_sections

PRIORITY={'primary':-1,'explicit_table_link':0,'section':1,'body_continuation':2}


class PrimaryCandidateCatalog:
    def __init__(self,seeds,catalog,relations=None):
        self.base=catalog
        self.chunks=catalog.chunks
        self.roots={e.chunk_id:e for e in seeds}
        self.origins={}
        self.relations=relations
        self.link_candidates=[]
        self.link_limit_omissions=[]
        self.linked_ids=set()
        if relations is not None:relations.validate_body_catalog(catalog)

    def evidence_group_key(self,seed,section_id):
        return self.base.evidence_group_key(seed,section_id)

    def candidates(self,seed,radius):
        if seed.chunk_id not in self.roots:
            raise ValueError('Only primary hits may collect expansion candidates')
        sid,candidates,mode=self.base.candidates(seed,radius)
        c=self.chunks[seed.chunk_id];mapping=self.base.mapping[c.id]
        origins=self.origins.setdefault(c.id,{})
        unique={n.id:n for n in candidates}
        for n in candidates:
            origin='primary' if n.id==c.id else ('section' if mode=='section' else 'body_continuation')
            origins.setdefault(n.id,set()).add(origin)
        if (self.relations is not None and mapping['role_status']=='identified'
                and mapping['content_role'] in {'body','table'}):
            count=0
            # The lookup never receives section candidates or newly linked targets.
            for n,link in self.relations.targets([seed.chunk_id]):
                if n.id in self.roots:continue
                if count>=2 or (n.id not in self.linked_ids and len(self.linked_ids)>=8):
                    self.link_limit_omissions.append(dict(**link,seed_chunk_id=c.id,reason='candidate_count_limit'))
                    continue
                count+=1;self.linked_ids.add(n.id);unique[n.id]=n
                origins.setdefault(n.id,set()).add('explicit_table_link')
                self.link_candidates.append(dict(**link,seed_chunk_id=c.id))
        if len(unique)>1 and mode in {'unassigned_standalone','unassigned_scientific_standalone'}:
            mode='explicit_links'
        return sid,self.order_candidates([seed],list(unique.values())),mode

    def order_candidates(self,seeds,candidates):
        def key(c):
            choices=[]
            for seed in seeds:
                reasons=self.origins.get(seed.chunk_id,{}).get(c.id)
                if reasons:
                    choices.append((min(PRIORITY[r] for r in reasons),
                        abs(c.chunk_index-self.chunks[seed.chunk_id].chunk_index)))
            priority,distance=min(choices)
            return priority,distance,c.chunk_index,c.id
        unique={c.id:c for c in candidates}
        eligible=[c for c in unique.values() if any(c.id in self.origins.get(seed.chunk_id,{}) for seed in seeds)]
        return sorted(eligible,key=key)


def assemble_unified_context(seeds,catalog,options,relations=None):
    candidates=PrimaryCandidateCatalog(seeds,catalog,relations)
    evidence,info=assemble_sections(seeds,candidates,options)
    present={s.chunk_id for e in evidence for s in e.source_chunks}
    selected=[link for link in candidates.link_candidates if link['target_chunk_id'] in present]
    omitted=[dict(**link,reason='length_budget') for link in candidates.link_candidates
        if link['target_chunk_id'] not in present]
    info.update(assembly_passes=1,candidate_roots_only=True,
        candidate_root_chunk_ids=[e.chunk_id for e in seeds],post_context_expansion=False,
        candidate_priority=['primary','explicit_table_link','section','body_continuation'],
        explicit_link_candidates=candidates.link_candidates,selected_explicit_links=selected,
        selected_explicit_link_chunk_ids=list(dict.fromkeys(link['target_chunk_id'] for link in selected)),
        omitted_explicit_links=[*candidates.link_limit_omissions,*omitted],
        candidate_origins=[dict(seed_chunk_id=root,chunk_id=cid,origins=sorted(reasons,key=PRIORITY.get))
            for root,items in candidates.origins.items() for cid,reasons in items.items()])
    return evidence,info
