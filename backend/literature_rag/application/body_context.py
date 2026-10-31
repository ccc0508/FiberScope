"""Body-only expansion: trusted section first, sentence-continuation fallback second.

Keep the earlier role-context implementation intact for its sealed experiments.
"""
import json
from pathlib import Path

from literature_rag.application.role_context import RoleSectionCatalog
from literature_rag.application.section_context import assemble_sections
from literature_rag.domain.errors import InfrastructureError

VERSION='body-section-context-v2'


class BodySectionCatalog(RoleSectionCatalog):
    def candidates(self,seed,radius):
        c=self.chunks[seed.chunk_id];m=self.mapping[c.id]
        if m['role_status']!='identified':
            return None,[c],'uncertain_standalone'
        if m['content_role']!='body':
            return None,[c],'non_body_standalone'
        # The inherited body path checks reliable section membership first.
        # Only when it is unavailable can a same-page body continuation qualify.
        return super().candidates(seed,radius)

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
    diagnostics.update(version=VERSION,strategy='body_section',non_body_expansion=False,
        fallback_policy='same_page_identified_body_sentence_continuation_only')
    return evidence,diagnostics
