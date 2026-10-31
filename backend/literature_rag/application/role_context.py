"""Role-aware context candidates, opt-in and compatible with bounded assembly."""
import re

from literature_rag.application.section_context import SectionCatalog, assemble_sections

VERSION='role-context-v1'
SCIENTIFIC={'body','table','equation','figure_caption'}


class RoleSectionCatalog(SectionCatalog):
    def __init__(self,chunks,structure):
        super().__init__(chunks,structure)
        for m in self.mapping.values():
            if not m.get('content_role') or m.get('role_status') not in {'identified','uncertain'}:
                raise ValueError('Role mapping missing; do not silently use legacy expansion')

    def compatible_body(self,c):
        m=self.mapping[c.id]
        return m['content_role']=='body' and m['role_status']=='identified'

    def candidates(self,seed,radius):
        c=self.chunks[seed.chunk_id];m=self.mapping[c.id];role=m['content_role']
        if m['role_status']!='identified':return None,[c],'uncertain_standalone'
        if role=='abstract':
            group=m.get('role_group')
            same=[n for n in self.documents[c.document_id] if group and
                self.mapping[n.id].get('role_group')==group and self.mapping[n.id]['content_role']=='abstract'
                and self.mapping[n.id]['role_status']=='identified']
            return 'role:'+group if group else None,same or [c],'abstract_only'
        if role not in SCIENTIFIC:return None,[c],'metadata_standalone'
        if self.trusted(c):
            sid,ns,mode=super().candidates(seed,radius)
            ns=[n for n in ns if self.mapping[n.id]['content_role'] in SCIENTIFIC
                and self.mapping[n.id]['role_status']=='identified']
            return sid,ns,mode
        # Fallback only for an actual sentence continuation between identified body blocks.
        ns=[c]
        if role=='body':
            for n in self.documents[c.document_id]:
                if (n.page_start,n.page_end)!=(c.page_start,c.page_end) or not self.compatible_body(n):continue
                if abs(n.chunk_index-c.chunk_index)!=1 or radius<1:continue
                if self.mapping[n.id].get('section_id')!=m.get('section_id'):continue
                left,right=(n,c) if n.chunk_index<c.chunk_index else (c,n)
                lt=self.mapping[left.id].get('body_text',left.text).rstrip()
                rt=self.mapping[right.id].get('body_text',right.text).lstrip()
                if lt and not re.search(r'[.!?。！？:：;；]$',lt) and re.match(r'[a-z]',rt):ns.append(n)
        return None,ns,'body_continuation_fallback' if len(ns)>1 else 'unassigned_standalone'


def assemble_roles(seeds,catalog,options):
    evidence,info=assemble_sections(seeds,catalog,options)
    info['version']=VERSION
    return evidence,info
