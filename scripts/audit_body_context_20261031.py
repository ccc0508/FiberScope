"""Offline verification of body-first context policy on the sealed 113-block corpus."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.body_context import BodySectionCatalog,assemble_body_context,VERSION
from literature_rag.application.context import ContextOptions
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.domain.models import Evidence


def run():
    library=ROOT/'.rag-data/index-versions/content-roles-v1-20261031'
    structure=json.loads((library/'structure.json').read_text('utf-8'))
    class ReadOnly(SqliteMetadataStore):
        def _connect(self):
            import sqlite3
            c=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
    source_hash=sha256((library/'metadata.sqlite3').read_bytes()).hexdigest()
    env_hash=sha256((ROOT/'backend/.env.literature').read_bytes()).hexdigest()
    catalog=BodySectionCatalog.load(library,ReadOnly(library/'metadata.sqlite3'))
    decisions=Counter();records=[]
    for i in range(1,33):
        tid=f'PFI2-{i:03}'
        f=json.loads((ROOT/'.rag-data/evaluations/role-context-20261031/fixtures/control'/(tid+'.json')).read_text('utf-8'))
        seeds=[]
        for raw in f['seeds']:
            for cid in structure['projection'][raw['chunk_id']]:
                c=catalog.chunks[cid]
                seeds.append(Evidence(f'[{len(seeds)+1}]',cid,c.document_id,c.filename,c.page_start,c.page_end,c.text,raw['score']))
        evidence,info=assemble_body_context(seeds,catalog,ContextOptions(True))
        primary={s.chunk_id for s in seeds};included=[s.chunk_id for e in evidence for s in e.source_chunks]
        assert primary<=set(included) and len(included)==len(set(included))
        assert all(len(e.text)<=8000 for e in evidence) and sum(len(e.text) for e in evidence)<=24000
        for d in info['decisions']:
            decisions[d['mode']]+=1
            m=catalog.mapping[d['seed_chunk_id']]
            if m['content_role']!='body' or m['role_status']!='identified':
                assert d['section_id'] is None and d['candidate_chunk_ids']==[d['seed_chunk_id']]
                own=next(e for e in evidence if d['seed_chunk_id'] in e.seed_chunk_ids)
                assert [s.chunk_id for s in own.source_chunks]==[d['seed_chunk_id']]
            elif catalog.trusted(catalog.chunks[d['seed_chunk_id']]):
                assert d['mode']=='section'
        records.append(dict(task_id=tid,primary_hits=len(seeds),evidence_count=len(evidence),context_chars=info['context_chars'],
            budget_limited=info['budget_limited'],decisions=info['decisions'],evidences_sha256=sha256(
                json.dumps([asdict(e) for e in evidence],ensure_ascii=False,sort_keys=True).encode()).hexdigest()))
    assert sha256((library/'metadata.sqlite3').read_bytes()).hexdigest()==source_hash
    assert sha256((ROOT/'backend/.env.literature').read_bytes()).hexdigest()==env_hash
    result=dict(version=VERSION,questions=32,catalog_chunks=len(catalog.chunks),decision_counts=dict(decisions),
        all_primary_hits_preserved=True,no_duplicate_sources=True,all_character_budgets_passed=True,
        non_body_hits_standalone=True,reliable_body_uses_section_only=True,metadata_unchanged=True,
        default_configuration_unchanged=True,new_provider_calls=0,new_generation_calls=0,new_embedding_calls=0,
        quality_scores_produced=False,records=records,rule_sha256=sha256((ROOT/'backend/literature_rag/application/body_context.py').read_bytes()).hexdigest())
    target=ROOT/'.rag-data/verifications/body-section-context-v2-20261031.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
