"""Offline replay of saved Q24 proposals. Added anchors are test fixtures, not new model output."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from qa_answer_replay_worker import evidence
from literature_rag.application.evidence_review import EvidenceReviewService
from literature_rag.application.review_diagnosis_bound import parse_response
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim


def main():
    source=ROOT/'.rag-data/evaluations/minimal-revision-paired-20261103/3-v3/PFI2-024.json'
    saved=json.loads(source.read_text(encoding='utf-8'));trace=saved['evidence_review'];first=trace['rounds'][0]
    draft=GeneratedAnswer(trace['original_draft']['answer'],tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in trace['original_draft']['claims']))
    sources=[evidence(e) for e in trace['initial_evidence']]
    base=dict(issues=first['issues'],requirements=first.get('raw_requirements',first['requirements']),claim_checks=first['claim_checks'])
    outputs=[]
    for mode in ['missing_anchors','intended_text_wrong_index','indexed_text_conflicting_check']:
        raw=deepcopy(base)
        if mode!='missing_anchors':
            positions=[4,6,8] if mode=='intended_text_wrong_index' else [5,7,8]
            for item,index in zip(raw['issues'],positions,strict=True):item['original_text']=draft.claims[index].text
        payload=parse_response(json.dumps(raw,ensure_ascii=False))
        provider=SimpleNamespace(diagnostic=True,diagnosis_version='v2_bound',timeout_seconds=120,
            review=lambda *args,**kwargs:payload,last_api_calls=0,last_usage=None)
        service=EvidenceReviewService(provider,visual_root=ROOT/'.rag-data/index-versions/mineru-qwen3-vl-images-20261102')
        result=service.review(saved['question'],sources,draft);t=service.last_trace
        expected=[] if mode=='missing_anchors' else [2]
        assert t['accepted_issue_indexes']==expected,(mode,t)
        assert result.claims[5]==draft.claims[5] and result.claims[7]==draft.claims[7]
        assert result.claims[:8]==draft.claims[:8]
        outputs.append(dict(mode=mode,accepted=t['accepted_issue_indexes'],rejected=t['rejected_issues'],
            preserved_original_claim_indexes=list(range(8)),final=asdict(result),api_calls=0))
    out=ROOT/'data/literature/qa-evaluation/reports/edit-binding-20261103'
    if out.exists():raise ValueError('Preserve existing result; use a new report destination')
    out.mkdir(parents=True)
    result=dict(source_sha256=sha256(source.read_bytes()).hexdigest(),case_id='PFI2-024',
        experiment='offline deterministic target validation only; anchors manually supplied as fixtures',
        quality_score=None,paid_calls=0,scenarios=outputs)
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(mode=r['mode'],accepted=r['accepted'],rejected=r['rejected']) for r in outputs],ensure_ascii=False))


if __name__=='__main__':main()
