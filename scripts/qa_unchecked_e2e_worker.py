"""Isolated experiment: real retrieval/generation, unchecked review proposals.

Only imported by the private evaluation worker, never by the website.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json
from dataclasses import asdict
from copy import deepcopy
from time import perf_counter
from types import SimpleNamespace
from replay_review_no_validation import apply_unchecked
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim,Citation
from literature_rag.application.citations import ValidatedAnswer
from literature_rag.application import answer_question,corrective_review
from literature_rag.adapters.providers import evidence_review as provider
from literature_rag.application import review_diagnosis_unified as contract
from literature_rag.diagnostics import combined_usage

def parse_raw(content,**kwargs):
    obj=json.loads(content)
    if not isinstance(obj,dict) or not isinstance(obj.get('issues'),list):
        raise ValueError('Missing executable issue array')
    return SimpleNamespace(raw=obj,_parse_errors=[],_mechanical_repairs=[])
contract.parse_response=parse_raw
provider.DeepSeekEvidenceReviewer._complete_comparisons=lambda *a,**k:None

class UncheckedSerializer:
    def validate(self,draft,evidences,**kwargs):
        used={r for c in draft.claims for r in c.citation_refs}
        return ValidatedAnswer(draft.answer,tuple(c.text+' '+' '.join(c.citation_refs) for c in draft.claims),
            tuple(Citation(e.ref,e.filename,e.page_start,e.page_end,e.chunk_id,e.source_chunks,e.visual_assets)
                  for e in evidences if e.ref in used))
# Initial generation still uses RecordingCitationValidator; only post-review gates disabled.
answer_question.CitationValidator=UncheckedSerializer

def unchecked_review(self,question,evidences,draft):
    started=perf_counter();p=self.reviewer.provider
    self.last_evidences=list(evidences)
    t=self.last_trace=dict(enabled=True,version='unchecked-e2e-v1',status='started',rounds=[],
        original_draft=asdict(draft),initial_evidence=[asdict(e) for e in evidences],supplement_rounds=0,
        content_validation=False,initial_generation_validation=True)
    final=draft;context=None
    for number in range(2):
        r=dict(draft=asdict(final),evidence=[asdict(e) for e in self.last_evidences],status='started')
        t['rounds'].append(r)
        try:
            payload=p.review(question,self.last_evidences,final,context=context,timeout_seconds=300).raw
            r['raw_response']=deepcopy(payload)
            claims,events=apply_unchecked([asdict(c) for c in final.claims],payload['issues'])
            final=GeneratedAnswer('\n'.join(c['text']+' '+' '.join(c['citation_refs']) for c in claims),
                tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in claims))
            r.update(status='executed_unchecked',events=events,final=asdict(final))
        except Exception as exc:
            r.update(status='failed',error_type=type(exc).__name__,reason_code=p.last_failure_code)
            break
        finally:
            r.update(usage=p.last_usage,model_info=deepcopy(p.last_model_info),api_calls=p.last_api_calls,
                latency_ms=p.last_latency_ms,http_status=p.last_http_status)
        if number==1:break
        requirements=payload.get('requirements',[])
        gaps=[x for x in requirements if isinstance(x,dict) and x.get('status')=='lookup'] if isinstance(requirements,list) else []
        # Keep the existing numerical-conflict supplemental lookup, without content gates.
        from literature_rag.application.numeric_crosscheck import plan_crosscheck
        try:
            requirements,gaps,t['numeric_crosscheck']=plan_crosscheck(question,self.last_evidences,requirements,
                self.reader.retriever.body_context_catalog)
            if not gaps:break
            self.reader.deadline=perf_counter()+40
            augmented=self.reader.read(question,gaps,self.last_evidences,final)
            t['supplement_rounds']=1;t['supplement']=deepcopy(self.reader.last_trace)
            if not self.reader.last_trace.get('added_refs'):break
            self.last_evidences=augmented
            context=dict(requirements=requirements,remaining_lookup_actions=0,
                added_refs=self.reader.last_trace['added_refs'],instruction='Recheck prior requirements; no further lookup.')
        except Exception as exc:
            t['lookup_execution_error']=type(exc).__name__;break
    t.update(status='incomplete' if t['rounds'][-1]['status']=='failed' else 'executed_unchecked',
        final=asdict(final),final_evidence=[asdict(e) for e in self.last_evidences],
        api_calls=sum(r['api_calls'] for r in t['rounds']),usage=combined_usage(t['rounds']),
        latency_ms=round((perf_counter()-started)*1000))
    self.last_summary=dict(status=t['status'],notice='实验：修订未经程序内容校验',review_rounds=len(t['rounds']),supplement_rounds=t['supplement_rounds'])
    return final
corrective_review.CorrectiveReviewService.review=unchecked_review

if __name__=='__main__':
    import literature_worker
    literature_worker.main()
