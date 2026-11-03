"""Offline Q32 budget replay; reuse recorded candidate and score, no model/gold calls."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from qa_answer_replay_worker import evidence
from literature_rag.application.corrective_review import TargetedEvidenceReader
from literature_rag.application.context import ContextOptions
from literature_rag.application.review_commit import commit_compatible_edits
from literature_rag.application.citations import CitationValidator
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim


def answer(d):return GeneratedAnswer(d['answer'],tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in d['claims']))


def main():
    out=ROOT/'data/literature/qa-evaluation/reports/supplement-budget-20261103'
    if out.exists():raise ValueError('Preserve previous verification')
    results=[]
    for name in ['2-v3','3-v3']:
        path=ROOT/'.rag-data/evaluations/minimal-revision-paired-20261103'/name/'PFI2-032.json'
        row=json.loads(path.read_text(encoding='utf-8'));t=row['evidence_review'];first=t['rounds'][0]
        sources=[evidence(e) for e in t['initial_evidence']];draft=answer(t['original_draft']);provisional=answer(first['final'])
        action=t['supplement']['actions'][0];candidates=[evidence(e) for e in action['candidate_evidence']]
        scores={x['chunk_id']:x['score'] for x in action['ranked_candidates']}
        r=NS(context_options=ContextOptions(True,1,8000,24000),last_candidate_evidences=[],visual_catalog=None,
            reranker=NS(rerank=lambda q,texts,**kwargs:[scores[c.chunk_id] for c in candidates]))
        reader=TargetedEvidenceReader(r)
        reader._located=lambda *args:[NS(id=c.chunk_id,document_id=c.document_id,filename=c.filename,
            page_start=c.page_start,page_end=c.page_end,text=c.text,chunk_index=4,kind='paragraph') for c in candidates]
        gaps=[v for v in t['action_requirements'] if v['status']=='lookup']
        old=reader.read(row['question'],gaps,sources,provisional);old_trace=reader.last_trace
        assert not old_trace['added_refs']
        augmented=reader.read(row['question'],gaps,sources,draft);new_trace=reader.last_trace
        assert new_trace['added_refs']==['[7]']
        final,committed,commit=commit_compatible_edits(first,draft,augmented,ROOT/'.rag-data/index-versions/mineru-qwen3-vl-images-20261102')
        CitationValidator().validate(final,augmented,allow_sparse_refs=True)
        used={ref for c in draft.claims for ref in c.citation_refs};by_ref={e.ref:e for e in augmented}
        assert all(by_ref[e.ref]==e for e in sources if e.ref in used)
        assert sum(len(e.text) for e in augmented)<=24000
        assert '0.888' in by_ref['[7]'].text
        results.append(dict(attempt=name,source_sha256=sha256(path.read_bytes()).hexdigest(),
            old_protected_chars=old_trace['protected_chars'],new_protected_chars=new_trace['protected_chars'],
            old_omissions=old_trace['actions'][0]['omissions'],added_refs=new_trace['added_refs'],
            dropped_uncited_refs=new_trace['dropped_uncited_refs'],final_context_chars=sum(len(e.text) for e in augmented),
            original_cited_sources_unchanged=True,second_review_draft=asdict(final),
            second_review_evidence=[asdict(e) for e in augmented],commit=commit))
    out.mkdir(parents=True)
    (out/'verification.json').write_text(json.dumps(dict(paid_calls=0,quality_score=None,
        scope='Offline historical assembly and compatible commit; second model answer not generated.',results=results),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ['second_review_draft','second_review_evidence','commit']} for r in results],ensure_ascii=False))


if __name__=='__main__':main()
