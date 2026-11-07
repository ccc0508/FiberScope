"""Lossless model-facing evidence projection; full tool records stay in storage."""
from copy import deepcopy
from hashlib import sha256
import json
import re


class EvidenceProjection:
    def __init__(self):
        self.parts = {}
        self.references = set()

    def evidence(self, source):
        row = {k: deepcopy(source[k]) for k in (
            'ref', 'document_id', 'filename', 'page_start', 'page_end', 'chunk_id',
            'locator', 'section_id', 'section_path', 'content_role', 'role_status',
            'kind', 'text_sha256', 'start_char', 'end_char', 'source_full_chars', 'source_hash',
        ) if k in source}
        text = source.get('text', '')
        identity = (source.get('document_id'), source.get('ref'), sha256(text.encode()).hexdigest())
        if identity in self.references:
            row['already_provided'] = True
        else:
            parts = []
            # Exact lines, including separators: reconstructing the parts yields
            # the original evidence byte-for-byte. No fuzzy semantic deduplication.
            for part in re.findall(r'[^\n]*\n|[^\n]+$', text):
                key = (source.get('document_id'), part)
                if len(part) >= 80 and key in self.parts:
                    parts.append(dict(reuse_text_id=self.parts[key]))
                elif len(part) >= 80:
                    tid = 'txt_' + sha256(json.dumps(key, ensure_ascii=False).encode('utf-8')).hexdigest()[:24]
                    self.parts[key] = tid
                    parts.append(dict(text_id=tid, text=part))
                else:
                    parts.append(dict(text=part))
            row['text_parts'] = parts
            self.references.add(identity)
        if source.get('visual_assets'):
            row['visual_assets'] = [self.asset(a) for a in source['visual_assets']]
        return row

    @staticmethod
    def asset(a):
        return dict(asset_id=a.get('asset_id', a.get('id')),
            **{k: a[k] for k in ('document_id','parent_chunk_id','label','page','kind','match_status') if k in a})

    def project(self, result):
        output = {k: deepcopy(v) for k,v in result.items() if k not in ('result','image')}
        if 'image' in result: output['image'] = result['image']
        r = deepcopy(result.get('result', {}))
        for key in ('local_to_run_refs','evidence_scope','citation_records'):r.pop(key, None)
        if 'evidence' in r:r['evidence'] = [self.evidence(e) for e in r['evidence']]
        if 'sources' in r:r['sources'] = [self.evidence(e) for e in r['sources']]
        if 'table' in r:r['table'] = self.evidence(r['table'])
        if 'assets' in r:r['assets'] = [self.asset(a) for a in r['assets']]
        if 'asset' in r:r['asset'] = self.asset(r['asset'])
        r['text_protocol'] = ('Concatenate text_parts in order; reuse_text_id references exact text previously supplied '
            'in this run. already_provided means this same evidence was supplied earlier. '
            'text_id and reuse_text_id are internal text reuse keys (txt_<hash>), NOT citation IDs. '
            'Cite only the enclosing evidence ref [n]. Image captions are not viewed pixels.')
        output['result'] = r
        return output
