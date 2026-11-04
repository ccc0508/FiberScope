"""Offline immutable-review replay; no answer generation, grader or provider calls."""
import json
import sys
from pathlib import Path
from hashlib import sha256
from argparse import ArgumentParser
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from qa_answer_replay_worker import evidence
from literature_rag.application import review_diagnosis_unified as contract
from literature_rag.application.evidence_review import apply_edits,ReviewPayload,checksum
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim


def main():
    cli=ArgumentParser()
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--complete-case32',action='store_true',help='One paid metadata completion on saved Q32 round 2 only')
    args=cli.parse_args()
    if args.output.exists():raise ValueError('Never overwrite a replay')
    source=ROOT/'.rag-data/evaluations/unified-v31-full32-20261104'
    library=ROOT/'.rag-data/evaluations/pfi-answer-deepseek-20261102/library'
    rows=[];provider_calls=0
    if args.complete_case32:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.with_suffix('.started').open('x').close()

    for n in range(1,33):
        path=source/f'PFI2-{n:03}.json';raw=path.read_bytes();data=json.loads(raw);e=data['evidence_review']
        for ri,r in enumerate(e['rounds']):
            artifact=(r.get('model_info') or {}).get('failure_artifact') or {}
            original=None
            if artifact.get('artifact_id'):
                file=source/'private-diagnostics'/(artifact['artifact_id']+'.json')
                if file.exists():original=json.loads(file.read_text(encoding='utf-8'))['response']
            if original is None and 'units' not in r:
                rows.append(dict(case_id=data['case_id'],round=ri+1,skipped='no_saved_output'));continue
            candidates=[e['initial_evidence'],e['final_evidence']]
            if e.get('supplement',{}).get('result_evidence'):candidates.append(e['supplement']['result_evidence'])
            sources=next((s for s in candidates if checksum(s)==r['evidence_sha256']),None)
            if sources is None:raise ValueError('Evidence hash mismatch')
            es=[evidence(s) for s in sources]
            d=r['draft'];draft=GeneratedAnswer(d['answer'],tuple(GeneratedClaim(c['text'],tuple(c['citation_refs'])) for c in d['claims']))
            obj=json.loads(original) if original else dict(issues=r.get('model_issues',r['issues']),requirements=r.get('raw_requirements',r['requirements']),units=r['units'])
            payload=contract.parse_response(json.dumps(obj,ensure_ascii=False),draft=draft)
            completion=None
            if args.complete_case32 and n==32 and ri==1:
                from time import perf_counter
                from literature_rag.config import Settings
                from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
                from literature_rag.application.prompts import evidence_prompt
                from literature_rag.application.visual_evidence import visual_content
                settings=Settings(_env_file=ROOT/'backend/.env.literature')
                provider=DeepSeekEvidenceReviewer(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
                    thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
                    timeout_seconds=180,max_output_tokens=8192,diagnostic=True,diagnosis_version='v3_unified',
                    diagnostics_dir=args.output.parent/'private-diagnostics')
                prompt,_=contract.request_prompt(data['question'],draft,es)
                content,_=visual_content(es,library,evidence_prompt(data['question'],es))
                messages=[dict(role='system',content=prompt),dict(role='user',content=content)]
                provider.last_model_info={};provider.last_usage=None;provider.last_api_calls=0
                params={}
                if settings.llm_thinking_enabled is not None:params['extra_body']={'thinking':{'type':'enabled' if settings.llm_thinking_enabled else 'disabled'}}
                if settings.llm_reasoning_effort is not None:params['reasoning_effort']=settings.llm_reasoning_effort
                provider._complete_comparisons(payload,contract,draft,es,messages,json.dumps(obj,ensure_ascii=False),params,perf_counter())
                provider_calls+=provider.last_api_calls
                completion=provider.last_model_info
            contract.prepare_payload(payload,draft,es)
            edits=[]
            for i,issue in enumerate(payload.issues):
                error=None
                try:
                    contract.validate_edit_semantics(payload,i,draft,es)
                    contract.validate_edit_target(payload,i,draft)
                    apply_edits(ReviewPayload(issues=[issue]),draft,es,library,allow_sparse_refs=True)
                except Exception as exc:error=getattr(exc,'code',type(exc).__name__)
                edits.append(dict(issue_index=i,old_accepted=i in r.get('accepted_issue_indexes',[]),accepted=error is None,error=error,
                    replacements=[c.text for c in issue.replacement_claims]))
            rows.append(dict(case_id=data['case_id'],round=ri+1,input_sha256=sha256(raw).hexdigest(),
                completion=completion,edits=edits,mechanical_repairs=payload._mechanical_repairs,
                unit_errors=[dict(index=i,errors=contract.unit_errors(u,payload,draft,es)) for i,u in enumerate(payload.units) if contract.unit_errors(u,payload,draft,es)]))
    edits=[x for r in rows for x in r.get('edits',[])]
    report=dict(version=contract.VERSION,provider_calls=provider_calls,note='Replays saved raw output where archived, otherwise saved parsed records. Includes formerly unparsed proposals; old accepted denominator differs from prior 15 parsed proposals. No new grade or end-to-end success rate.',
        totals=dict(proposals=len(edits),old_accepted=sum(x['old_accepted'] for x in edits),accepted=sum(x['accepted'] for x in edits)),rounds=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['totals']))
    for r in rows:
        if r.get('edits'):print(r['case_id'],r['round'],[(x['issue_index'],x['old_accepted'],x['accepted'],x['error']) for x in r['edits']])

if __name__=='__main__':main()
