"""Scientific section expansion with a body-only sentence-continuation fallback.

Keep the earlier role-context implementation intact for its sealed experiments.
"""
import json
from pathlib import Path

from literature_rag.application.role_context import RoleSectionCatalog
from literature_rag.application.section_context import assemble_sections
from literature_rag.domain.errors import InfrastructureError

VERSION='scientific-section-context-v3'
SECTION_TRIGGER_ROLES=('body','table','equation')


class BodySectionCatalog(RoleSectionCatalog):
    def candidates(self,seed,radius):
        c=self.chunks[seed.chunk_id];m=self.mapping[c.id]
        if m['role_status']!='identified':
            return None,[c],'uncertain_standalone'
        if m['content_role'] not in SECTION_TRIGGER_ROLES:
            return None,[c],'non_body_standalone'
        if m['content_role'] in {'table','equation'} and not self.trusted(c):
            return None,[c],'unassigned_scientific_standalone'
        # All three scientific roles may use a trusted section. Only body text
        # can fall back to same-page neighbors on sentence-continuation evidence.
        return super().candidates(seed,radius)

    def evidence_group_key(self,seed,section_id):
        if self.mapping[seed.chunk_id]['content_role'] in {'table','equation'}:
            # Keep each matched table/formula as its own anchor; reserve every
            # primary source before sharing supplemental section content.
            return seed.document_id,('scientific_source',seed.chunk_id)
        return super().evidence_group_key(seed,section_id)

    @classmethod
    def load(cls,root,metadata):
        try:
            structure=json.loads((Path(root)/'structure.json').read_text('utf-8'))
            ids=list(structure['mapping']);chunks=[]
            for start in range(0,len(ids),256):
                chunks.extend(metadata.get_chunks(ids[start:start+256]))
            if not ids:raise ValueError('Empty content-role catalog')
            return cls(chunks,structure)
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise InfrastructureError('body-section context requires valid role-classified source metadata') from None


def assemble_body_context(seeds,catalog,options):
    evidence,diagnostics=assemble_sections(seeds,catalog,options)
    diagnostics.update(version=VERSION,strategy='body_section',non_body_expansion=True,
        non_body_section_expansion=True,metadata_expansion=False,section_trigger_roles=list(SECTION_TRIGGER_ROLES),
        table_hit_expansion='reliable_section',equation_hit_expansion='reliable_section_only',
        fallback_policy='same_page_identified_body_sentence_continuation_only')
    return evidence,diagnostics
