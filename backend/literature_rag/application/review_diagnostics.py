"""Diagnostic facts only: an applied edit is not proof of semantic correctness."""
import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError


def validation_details(error):
    if isinstance(error, ValidationError):
        return [{'type':e['type'],'location':list(e['loc'])} for e in error.errors(include_input=False,include_url=False)][:20]
    if isinstance(error,json.JSONDecodeError):
        return [dict(type='invalid_json',line=error.lineno,column=error.colno,position=error.pos)]
    known={'invalid_review_envelope','invalid_diagnosis_envelope'}
    return [dict(type=type(error).__name__,code=str(error) if str(error) in known else 'unspecified_parse_failure')]


def archive_response(directory, content, metadata):
    """Private local artifact. Do not return file paths, raw response, credentials or request headers."""
    if directory is None:return dict(status='disabled')
    if not isinstance(content,str):return dict(status='no_text_response')
    ident=uuid4().hex
    try:
        root=Path(directory);root.mkdir(parents=True,exist_ok=True)
        path=root/(ident+'.json')
        body=json.dumps(dict(response=content,metadata=metadata),ensure_ascii=False).encode('utf-8')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body)
        return dict(status='saved',artifact_id=ident,response_sha256=sha256(content.encode()).hexdigest())
    except OSError:
        return dict(status='write_failed')


def review_outcome(trace, final):
    """Classify historical findings and final ledger separately without rewriting old scores."""
    final_claims=json.loads(json.dumps(final['claims']));events=[];rounds=[]
    for number,r in enumerate(trace['rounds'],1):
        code=r.get('reason_code')
        stage=('output_limit' if code=='review_output_truncated' else
               'response_parse' if code=='review_response_invalid' else
               'request' if r.get('status')=='failed' else
               'time_budget' if r.get('status')=='skipped' else
               'edit_validation' if r.get('rejected_issues') else
               'diagnosis_validation' if r.get('diagnosis_errors') else 'completed')
        rounds.append(dict(round=number,status=r['status'],stage=stage,reason_code=code,
            response_validation=(r.get('model_info') or {}).get('response_validation',[]),
            failure_artifact=(r.get('model_info') or {}).get('failure_artifact')))
        accepted=set(r.get('accepted_issue_indexes',[])) if r.get('accepted') else set()
        deferred=set()
        if number==1 and trace.get('first_round_commit'):
            accepted=set(trace['first_round_commit']['accepted_issue_indexes'])
            deferred={x['issue_index'] for x in trace['first_round_commit']['deferred_issues']}
        for i,issue in enumerate(r.get('issues',[])):
            replacements=issue.get('replacement_claims',[])
            retained=bool(replacements) and all(any(c==new for c in final_claims) for new in replacements)
            state=('deferred' if i in deferred else 'rejected' if i not in accepted else
                   'applied_present' if retained else 'applied_then_changed_or_deleted')
            events.append(dict(round=number,issue_index=i,claim_index=issue.get('claim_index'),
                category=issue['category'],status=state,semantic_verification='not_independently_verified'))
        for e in r.get('diagnosis_errors',[]):
            indexes=e.get('claim_indexes',[])
            if 'claim_index' in e:indexes=[e['claim_index']]
            source_claims=json.loads(json.dumps(r.get('draft',{}).get('claims',[])))
            present=any(0<=i<len(source_claims) and source_claims[i] in final_claims for i in indexes)
            # Superseded only means the audited text changed, never that the defect was fixed.
            scope='historical' if number<len(trace['rounds']) else 'current_record'
            if indexes and not present:scope='original_claim_changed_needs_recheck'
            events.append(dict(round=number,kind='diagnosis_error',scope=scope,detail=e))
    histories={}
    for number,r in enumerate(trace['rounds'],1):
        for req in r.get('requirements',[]):
            histories.setdefault(req['id'],dict(id=req['id'],requirement=req['requirement'],history=[]))['history'].append(
                dict(round=number,reported_status=req['status'],reason=req['reason'],issue_indexes=req.get('issue_indexes',[])))
    remaining={x['id']:x for x in trace['summary']['unresolved']}
    for rid,item in histories.items():
        item['final_state']='unresolved' if rid in remaining else 'not_reported_unresolved'
        item['semantic_verification']='not_independently_verified'
    return dict(version='review-outcome-v1',rounds=rounds,findings=events,requirement_history=list(histories.values()),
        remaining_requirements=trace['summary']['unresolved'],
        pipeline_status=trace['status'],semantic_quality='not_guaranteed',
        caution='Applied edits and completed diagnostics are not independent semantic verification.')
