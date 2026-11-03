"""Commit only first-round edits whose actual source support survived supplemental assembly."""
from copy import deepcopy
from dataclasses import asdict

from .evidence_review import ReviewPayload, apply_edits, checksum, ReviewRejected
from .citations import CitationValidator
from ..domain.errors import CitationValidationError


def commit_compatible_edits(first, draft, evidences, visual_root=None):
    # Original citations must survive whole and unchanged before this is called.
    CitationValidator().validate(draft,evidences,allow_sparse_refs=True)
    refs={e.ref for e in evidences}
    issues=first.get('issues',[])
    eligible=first.get('accepted_issue_indexes',[]) if first.get('accepted') else []
    accepted=[];deferred=[]
    for index in eligible:
        raw=issues[index]
        needed={ref for c in raw['replacement_claims'] for ref in c['citation_refs']}
        needed.update(b['ref'] for b in raw['basis'] if b.get('ref'))
        missing=sorted(needed-refs)
        if missing:
            deferred.append(dict(issue_index=index,reason_code='provisional_edit_source_not_retained',missing_refs=missing))
            continue
        try:
            apply_edits(ReviewPayload.model_validate({'issues':[raw]}),draft,evidences,visual_root,allow_sparse_refs=True)
        except (ReviewRejected,CitationValidationError):
            deferred.append(dict(issue_index=index,reason_code='provisional_edit_revalidation_failed'))
            continue
        accepted.append(index)
    try:
        final,_=apply_edits(ReviewPayload.model_validate({'issues':[issues[i] for i in accepted]}),draft,
            evidences,visual_root,allow_sparse_refs=True)
    except (ReviewRejected,CitationValidationError):
        deferred.extend(dict(issue_index=i,reason_code='provisional_combination_rejected') for i in accepted)
        accepted=[];final=draft
    committed=deepcopy(first)
    committed.update(accepted=True,accepted_issue_indexes=accepted,final=asdict(final),final_sha256=checksum(asdict(final)))
    committed['rejected_issues']=committed.get('rejected_issues',[])+deferred
    return final,committed,dict(status='committed_compatible_edits',accepted_issue_indexes=accepted,
        deferred_issues=deferred,final=asdict(final),final_sha256=checksum(asdict(final)),
        draft_sha256=checksum(asdict(draft)),evidence_sha256=checksum([asdict(e) for e in evidences]))
