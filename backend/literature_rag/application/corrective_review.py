"""A bounded controller: diagnose, read at most twice, review once more, then stop."""
from copy import deepcopy
from dataclasses import asdict, replace
from time import perf_counter
import re

from literature_rag.application.evidence_review import checksum, normalized_quote
from literature_rag.application.review_diagnosis import diagnosis_contract
from literature_rag.diagnostics import combined_usage
from literature_rag.domain.errors import InfrastructureError, ProviderError
from literature_rag.domain.models import Evidence, EvidenceSource


class LookupBudgetExhausted(Exception):
    pass


class TargetedEvidenceReader:
    """Reuse candidates and the immutable catalog; no library writes or outside documents."""
    def __init__(self, retriever, *, deadline=None):
        self.retriever = retriever
        self.deadline = deadline
        self.last_trace = {}

    def _timeout(self):
        remaining = 20 if self.deadline is None else self.deadline - perf_counter()
        if remaining < 2:
            raise LookupBudgetExhausted()
        return min(20, remaining)

    def _located(self, document_id, action):
        catalog = self.retriever.body_context_catalog
        if catalog is None or action['target'] == 'candidates':
            return []
        result = []
        for chunk in catalog.chunks.values():
            if chunk.document_id != document_id:
                continue
            info = catalog.mapping[chunk.id]
            if info.get('role_status') != 'identified':
                continue
            role = info['content_role']
            path = ' / '.join(info.get('section_path', []))
            target = action['target']
            match = (
                (target == 'abstract' and role == 'abstract')
                or (target == 'methods' and role in {'body', 'table', 'equation'}
                    and re.search(r'method|experimental|方法|实验', path, re.I))
                or (target == 'results' and role in {'body', 'table', 'equation'}
                    and re.search(r'result|discussion|结果|讨论', path, re.I))
                or (target == 'table' and role == 'table')
                or (target == 'figure' and role == 'figure_caption')
                or (target == 'section' and bool(action.get('locator'))
                    and action['locator'].casefold() in path.casefold())
            )
            locator = action.get('locator', '').strip()
            if match and (not locator or locator.casefold() in (path + '\n' + chunk.text).casefold()):
                result.append(chunk)
        return sorted(result, key=lambda c: c.chunk_index)

    def read(self, question, requirements, evidences, draft):
        started = perf_counter()
        r = self.retriever
        options = r.context_options
        original = list(evidences)
        result = list(original)
        by_ref = {e.ref: e for e in original}
        present = {e.chunk_id for e in original} | {s.chunk_id for e in original for s in e.source_chunks}
        texts = {normalized_quote(e.text) for e in original}
        texts.update(normalized_quote(s.text) for e in original for s in e.source_chunks)
        protected = {ref for c in draft.claims for ref in c.citation_refs}
        next_ref = max(int(e.ref[1:-1]) for e in original) + 1
        additions = []
        trace = self.last_trace = dict(actions=[], added_refs=[], dropped_uncited_refs=[],
            status='started', query_embedding_calls=[], rerank_calls=[], monetary_cost=None,
            protected_refs=sorted(protected),protected_chars=sum(len(e.text) for e in original if e.ref in protected),
            limits=dict(max_actions=2, max_candidates=50, max_sources_per_action=2,
                max_evidence_chars=options.max_evidence_chars, max_total_chars=options.max_total_chars))
        try:
            for requirement in requirements[:2]:
                action = requirement['lookup']
                document_id = by_ref[action['document_ref']].document_id
                event = dict(requirement_id=requirement['id'], query=action['query'],
                    document_id=document_id, target=action['target'], locator=action.get('locator', ''),
                    candidate_ids=[], added_refs=[], omissions=[], status='started')
                trace['actions'].append(event)
                self._timeout()
                cached = [e for e in r.last_candidate_evidences
                    if e.document_id == document_id and e.chunk_id not in present]
                chunks = self._located(document_id, action)
                candidates = []
                if chunks:
                    event['strategy'] = 'catalog_location'
                    for c in chunks:
                        if c.id not in present:
                            candidates.append(Evidence('', c.id, c.document_id, c.filename,
                                c.page_start, c.page_end, c.text, 0.,
                                (EvidenceSource(c.id, c.chunk_index, c.page_start, c.page_end, c.text, c.kind),)))
                    # Located evidence is not discarded just because it failed the original cosine cutoff.
                else:
                    event['strategy'] = 'cached_candidates_and_scoped_vector_query'
                    call = dict(branch='corrective', requirement_id=requirement['id'], status='started', usage=None)
                    trace['query_embedding_calls'].append(call)
                    call_started = perf_counter()
                    try:
                        vector = r.embedder.embed_query(action['query'], timeout_seconds=self._timeout())
                        call['status'] = 'completed'
                    finally:
                        call.update(usage=deepcopy(getattr(r.embedder, 'last_usage', None)),
                            latency_ms=round((perf_counter()-call_started)*1000),
                            provider_calls=deepcopy(getattr(r.embedder, 'last_calls', [])))
                    self._timeout()
                    matches = r.vectors.search(vector, 50, document_ids=[document_id])
                    scores = {m.chunk_id: m.score for m in matches}
                    fresh = {c.id: c for c in r.metadata.get_chunks(list(scores))}
                    # Bound both sources of candidates, deduplicate before reranking. No new calibrated cutoff.
                    candidates = cached[:25]
                    used = {e.chunk_id for e in candidates}
                    for match in matches:
                        c = fresh.get(match.chunk_id)
                        if c is None or c.document_id != document_id or c.id in present or c.id in used:
                            continue
                        candidates.append(Evidence('', c.id, c.document_id, c.filename, c.page_start,
                            c.page_end, c.text, match.score,
                            (EvidenceSource(c.id, c.chunk_index, c.page_start, c.page_end, c.text, c.kind),)))
                        used.add(c.id)
                    for e in cached[25:]:
                        if e.chunk_id not in used:
                            candidates.append(e); used.add(e.chunk_id)
                candidates = [e for e in candidates if e.text.strip() and normalized_quote(e.text) not in texts][:50]
                event['candidate_ids'] = [e.chunk_id for e in candidates]
                event['candidate_evidence'] = [asdict(e) for e in candidates]
                if not candidates:
                    event['status'] = 'no_new_source'
                    continue
                timeout = self._timeout()
                call_started = perf_counter()
                rerank_call = dict(requirement_id=requirement['id'], status='started', usage=None)
                trace['rerank_calls'].append(rerank_call)
                try:
                    scores = r.reranker.rerank(action['query'], [e.text for e in candidates], timeout_seconds=timeout)
                    from math import isfinite
                    if len(scores) != len(candidates) or any(type(s) not in (int, float) or not isfinite(s) or not 0 <= s <= 1 for s in scores):
                        raise InfrastructureError('Invalid supplemental rerank scores')
                    rerank_call['status'] = 'completed'
                finally:
                    provider_call = deepcopy(getattr(r.reranker, 'last_call', None))
                    rerank_call.update(provider_call=provider_call,
                        usage=provider_call.get('usage') if provider_call else None,
                        latency_ms=round((perf_counter()-call_started)*1000))
                event['ranked_candidates'] = [dict(chunk_id=candidates[i].chunk_id, score=scores[i])
                    for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i))]
                for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
                    if len(event['added_refs']) == 2:
                        break
                    e = candidates[i]
                    if e.chunk_id in present or normalized_quote(e.text) in texts:
                        continue
                    if len(e.text) > options.max_evidence_chars:
                        event['omissions'].append(dict(chunk_id=e.chunk_id, reason='single_source_budget'))
                        continue
                    retained = list(result)
                    dropped = []
                    while sum(len(x.text) for x in retained) + len(e.text) > options.max_total_chars:
                        removable = next((x for x in reversed(retained) if x.ref not in protected
                            and x.ref not in trace['added_refs']), None)
                        if removable is None:
                            break
                        retained.remove(removable); dropped.append(removable.ref)
                    if sum(len(x.text) for x in retained) + len(e.text) > options.max_total_chars:
                        event['omissions'].append(dict(chunk_id=e.chunk_id, reason='protected_evidence_budget'))
                        continue
                    e = replace(e, ref=f'[{next_ref}]', context_status='corrective_supplement', visual_assets=())
                    next_ref += 1
                    result = retained + [e]
                    additions.append(e); present.add(e.chunk_id); texts.add(normalized_quote(e.text))
                    trace['dropped_uncited_refs'].extend(dropped)
                    trace['added_refs'].append(e.ref); event['added_refs'].append(e.ref)
                event['status'] = 'sources_added' if event['added_refs'] else 'no_admissible_source'
            if additions and r.visual_catalog is not None:
                existing = {a.id: a for e in result for a in e.visual_assets}
                attached, info = r.visual_catalog.attach(additions, additions, question,
                    max(0, r.visual_max_images-len(existing)),
                    max(0, r.visual_max_total_bytes-sum(a.byte_size for a in existing.values())))
                augmented = {e.ref: replace(e, visual_assets=tuple(a for a in e.visual_assets if a.id not in existing)) for e in attached}
                result = [augmented.get(e.ref, e) for e in result]
                trace['visual_evidence'] = info
            trace['status'] = 'sources_added' if additions else 'no_new_source'
        except LookupBudgetExhausted:
            trace['status'] = 'time_budget'
            if trace['actions']:trace['actions'][-1]['status']='time_budget'
        except (ProviderError, InfrastructureError):
            trace['status'] = 'lookup_failed'
            if trace['actions']:trace['actions'][-1]['status']='lookup_failed'
        finally:
            trace['latency_ms'] = round((perf_counter()-started)*1000)
            trace['result_evidence'] = [asdict(e) for e in result]
        return result



def settled_requirements(round_trace):
    """Carry accepted edits forward without claiming failed/partial edits were applied."""
    requirements=deepcopy(round_trace.get('requirements',[]))
    accepted=set(round_trace.get('accepted_issue_indexes',[])) if round_trace.get('accepted') else set()
    issues=round_trace.get('issues',[])
    edits={issues[i]['claim_index']:issues[i] for i in accepted if issues[i]['claim_index'] is not None}
    mapping={};cursor=0
    for old in range(len(round_trace['draft']['claims'])):
        length=len(edits[old]['replacement_claims']) if old in edits else 1
        mapping[old]=list(range(cursor,cursor+length));cursor+=length
    appended={}
    for index in sorted(accepted):
        if issues[index]['claim_index'] is None:
            size=len(issues[index]['replacement_claims'])
            appended[index]=list(range(cursor,cursor+size));cursor+=size
    for r in requirements:
        original_issues=r['issue_indexes']
        positions=[i for old in r['claim_indexes'] for i in mapping.get(old,[])]
        positions += [i for idx in original_issues for i in appended.get(idx,[])]
        r['claim_indexes']=sorted(set(positions))
        if r['status']=='edit':
            if original_issues and set(original_issues)<=accepted:
                r.update(status='covered',reason='本轮已执行通过来源和引用检查的修订；语义正确性仍需核对。')
            else:
                r.update(status='unresolved',reason='该项修订未全部通过来源或引用检查，尚未确认解决。')
        # Old edit indexes must never be interpreted as edits proposed by the next round.
        r['issue_indexes']=[]
    return requirements


class CorrectiveReviewService:
    preserve_reference_ids = True

    def __init__(self, reviewer, reader, *, deadline=None):
        self.reviewer = reviewer
        self.reader = reader
        self.deadline = deadline
        self.last_trace = {}
        self.last_evidences = []
        self.last_summary = None

    def review(self, question, evidences, draft):
        started = perf_counter()
        self.last_evidences = list(evidences)
        version=getattr(self.reviewer.provider,'diagnosis_version','v1')
        supplement_first=getattr(diagnosis_contract(version),'prioritize_supplement',False)
        trace = self.last_trace = dict(enabled=True, version=diagnosis_contract(version).VERSION, status='started', rounds=[],
            api_calls=0, supplement_rounds=0, original_draft=asdict(draft),
            initial_evidence=[asdict(e) for e in evidences], monetary_cost=None,
            guarantee='source-location-and-structure-checks-only; semantic judgment is fallible')
        final = self.reviewer.review(question, evidences, draft)
        first = deepcopy(self.reviewer.last_trace)
        trace['rounds'].append(first)
        requirements = settled_requirements(first) if version in {'v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking'} else first.get('requirements', [])
        actions_valid=first.get('diagnosis_valid') or first.get('diagnosis_actions_validated')
        gaps = [r for r in requirements if r['status'] == 'lookup'] if actions_valid else []
        if version in {'v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking'}:
            from literature_rag.application.numeric_crosscheck import plan_crosscheck
            catalog=getattr(getattr(self.reader,'retriever',None),'body_context_catalog',None)
            requirements,gaps,trace['numeric_crosscheck']=plan_crosscheck(question,evidences,requirements,catalog)
            trace['action_requirements']=deepcopy(requirements)
        reason = 'diagnosis_complete' if first.get('diagnosis_valid') else 'diagnosis_incomplete'
        if gaps:
            remaining = 300 if self.deadline is None else self.deadline-perf_counter()
            if remaining < 25:
                reason = 'insufficient_correction_time'
            else:
                # Keep time for the final review; HTTP worker's hard deadline remains the outer bound.
                self.reader.deadline = min(perf_counter()+40,
                    self.deadline-20 if self.deadline is not None else perf_counter()+40)
                # First-round edits are provisional in this mode; their new citations
                # must not crowd out evidence needed to resolve an explicit gap.
                augmented = self.reader.read(question, gaps, evidences, draft if supplement_first else final)
                trace['supplement_rounds'] = 1
                trace['supplement'] = deepcopy(self.reader.last_trace)
                if self.reader.last_trace.get('added_refs'):
                    if supplement_first:
                        from literature_rag.application.review_commit import commit_compatible_edits
                        final,committed,trace['first_round_commit']=commit_compatible_edits(
                            first,draft,augmented,getattr(self.reviewer,'visual_root',None))
                        settled={r['id']:r for r in settled_requirements(committed)}
                        requirements=[settled.get(r['id'],r) for r in requirements]
                        available={e.ref for e in augmented}
                        deferred={r['issue_index'] for r in trace['first_round_commit']['deferred_issues']}
                        for r in requirements:
                            if any(old['id']==r['id'] and deferred.intersection(old['issue_indexes'])
                                   for old in first.get('requirements',[])):
                                r['reason']='首轮拟议修改所需来源未保留或重检未通过，尚未执行；请依据本轮原文重新核对。'
                            lost=set(r['evidence_refs'])-available
                            r['evidence_refs']=[ref for ref in r['evidence_refs'] if ref in available]
                            if lost and r['status']=='covered':
                                r.update(status='unresolved',reason='原诊断依赖的部分来源未保留，本轮需重新核对。')
                        trace['committed_requirements']=deepcopy(requirements)
                    self.last_evidences = augmented
                    ledger = dict(requirements=requirements, remaining_lookup_actions=0,
                        added_refs=self.reader.last_trace['added_refs'],
                        instruction='Recheck all prior requirements. Keep IDs and requirement text exactly; no further lookup.')
                    final = self.reviewer.review(question, augmented, final, context=ledger)
                    trace['rounds'].append(deepcopy(self.reviewer.last_trace))
                    reason = 'bounded_correction_complete'
                else:
                    reason = self.reader.last_trace['status']
                    if supplement_first:
                        blocked={a['requirement_id'] for a in self.reader.last_trace.get('actions',[])
                            if any(o.get('reason') in {'protected_evidence_budget','single_source_budget'} for o in a.get('omissions',[]))}
                        if blocked:
                            reason='supplement_evidence_budget_blocked'
                            for r in requirements:
                                if r['id'] in blocked:
                                    r['reason']='已找到补查候选，但无法在原回答引用保护及长度预算内加入；缺口尚未解决。'
        last = trace['rounds'][-1]
        rejected = {r['issue_index'] for r in last.get('rejected_issues', [])}
        accepted = set(last.get('accepted_issue_indexes', [])) if last.get('accepted') else set()
        # Keep first-round gaps if the second review could not finish or validate its ledger.
        if version in {'v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking'}:
            ledger = settled_requirements(last) if len(trace['rounds'])>1 and last.get('diagnosis_actions_validated') else requirements
            # This ledger is already settled; accepted indexes belong to different rounds.
            rejected=set();accepted=set()
        else:
            ledger = last.get('requirements', []) if len(trace['rounds'])>1 and last.get('diagnosis_valid') else requirements
        unresolved = []
        for r in ledger:
            if (r['status'] in {'lookup', 'unresolved'} or rejected.intersection(r['issue_indexes'])
                    or (r['status'] == 'edit' and not set(r['issue_indexes']) <= accepted)):
                unresolved.append(dict(id=r['id'], requirement=r['requirement'], reason=r['reason']))
        incomplete = last.get('status') in {'failed', 'rejected', 'skipped'} or not last.get('diagnosis_valid')
        status = 'incomplete' if incomplete else 'unresolved' if unresolved else 'completed'
        notice = {'incomplete':'本次审校未完整完成，以下保留最近一次通过引用格式检查的回答。',
            'unresolved':'部分问题仍缺少充分证据或尚未解决，请结合下列限制阅读回答。',
            'completed':'已完成证据审校；这不等于所有结论均已得到保证。'}[status]
        self.last_summary = dict(status=status, notice=notice, unresolved=unresolved,
            supplement_rounds=trace['supplement_rounds'], review_rounds=len(trace['rounds']))
        trace.update(status=status, stop_reason=reason, final=asdict(final),
            final_sha256=checksum(asdict(final)), final_evidence=[asdict(e) for e in self.last_evidences],
            final_evidence_sha256=checksum([asdict(e) for e in self.last_evidences]),
            api_calls=sum(r.get('api_calls', 0) for r in trace['rounds']),
            usage=combined_usage(trace['rounds']), summary=self.last_summary,
            latency_ms=round((perf_counter()-started)*1000))
        from .review_diagnostics import review_outcome
        trace['outcome']=review_outcome(trace,asdict(final))
        return final
