"""Small online coverage ledger; availability checks are not semantic verification."""
from copy import deepcopy
from .task_coverage import CoverageItem, coverage_report

INSTRUCTIONS = '''
For EVERY tool call include target_requirements (assigned need IDs), coverage_updates
(compact changed coverage entries after the PREVIOUS result; [] before first lookup),
and revisit_reason (empty normally; a specific contradiction/essential check if revisiting
verified work while other needs are open). These are scheduling metadata, not tool arguments
or citations. Update each paper separately. Prioritize a paper with no substantive evidence,
then unmet required facts, then essential contradictions. Do not exhaustively read one paper
before obtaining core evidence for the others. Once a requested part is supported, stop
expanding it. Use targeted sections/search, not optional background. Directory listings
are lookup paths, not scientific evidence. Missing evidence after a lookup is not proof of
absence. If no useful untried path remains, retain a precise gap and say where you checked.
Final JSON still needs the full coverage list. Do not force a verified label to end the task.
'''

class CoveragePriority:
    def __init__(self, requirements):
        self.requirements=requirements
        self.items={}
        self.warned=set()

    def schemas(self, schemas):
        out=deepcopy(schemas)
        item=dict(type='object',additionalProperties=False,properties={
            'requirement_id':{'type':'string'},
            'status':{'type':'string','enum':['verified','partial','missing','not_attempted']},
            'document_id':{'type':'string'},'refs':{'type':'array','items':{'type':'string'}},
            'finding':{'type':'string','maxLength':800},'gap':{'type':'string','maxLength':800}},
            required=['requirement_id','status','document_id','refs','finding','gap'])
        for schema in out.values():
            schema['properties'].update(target_requirements=dict(type='array',items=dict(type='string'),minItems=1,maxItems=20),
                coverage_updates=dict(type='array',items=item,maxItems=20),revisit_reason=dict(type='string',maxLength=600))
            schema.setdefault('required',[]).extend(['target_requirements','coverage_updates','revisit_reason'])
        return out

    def report(self, trace):
        return coverage_report(self.requirements,list(self.items.values()),trace)

    def snapshot(self,trace):
        report=self.report(trace)
        return dict(items=[dict(id=r['requirement']['requirement_id'],paper=r['requirement'].get('paper_quote',''),
                    need=r['requirement']['source_quote'],status=r['status'],
                    gap=r['reported'].get('gap',''),errors=r['errors']) for r in report['items']],
                    papers_without_source=self.papers_without_source(trace),
                    notice='Prioritize papers_without_source BEFORE deepening a paper already read, then unmet requested facts. Directory alone is not source coverage. Status validates availability only, not scientific truth.')

    def papers_without_source(self,trace):
        paper_ids={r['requirement_id'] for r in self.requirements if r.get('paper_quote')}
        attempted=set()
        # Merely targeting A and B in one search does NOT prove both returned.
        # Require delivered refs matching the reported document, even if the
        # finding/gap fields still need correction. This proves access, not truth.
        source_errors={'missing_source_refs','unavailable_ref','missing_document_id','document_not_supported_by_refs'}
        for row in self.report(trace)['items']:
            item=row['reported']
            if item.get('document_id') and item.get('refs') and not source_errors.intersection(row['errors']):
                attempted.add(row['requirement']['requirement_id'])
        return sorted(paper_ids-attempted)

    def needs_targeted_search(self,request,targets,unresolved,trace):
        if request.get('tool')!='read_section' or not set(targets).intersection(unresolved):return False
        if trace.get('search_calls',0)>=trace.get('max_search_calls',2):return False
        doc=request.get('document_id');reads=[]
        for event in reversed(trace.get('tool_calls',[])):
            previous=event.get('request',{})
            if previous.get('tool')=='search_literature' and (not previous.get('document_ids') or doc in previous['document_ids']):break
            if previous.get('tool')!='read_section' or previous.get('document_id')!=doc:continue
            if event.get('model_delivery',{}).get('status')!='delivered' or event.get('result',{}).get('status')!='completed':continue
            if set(event.get('coverage_schedule',{}).get('target_requirements',[])).intersection(targets):reads.append(event)
        if len(reads)<2:return False
        last=reads[0]
        # Following a returned pagination cursor is not guessing another section.
        next_offset=last.get('result',{}).get('result',{}).get('next_offset')
        if request.get('section_id')==last['request'].get('section_id') and next_offset is not None and request.get('offset',0)==next_offset:return False
        return True

    def prepare(self, request,trace):
        request=dict(request)
        targets=request.pop('target_requirements',[])
        updates=request.pop('coverage_updates',[])
        reason=request.pop('revisit_reason','')
        ids={r['requirement_id'] for r in self.requirements}
        errors=[]
        if not isinstance(targets,list) or not targets or any(not isinstance(i,str) or i not in ids for i in targets):
            errors.append('missing_or_unknown_target_requirements');targets=[]
        if not isinstance(updates,list):errors.append('invalid_coverage_updates');updates=[]
        for raw in updates[:20]:
            try:
                item=CoverageItem.model_validate(raw)
                if item.requirement_id not in ids:raise ValueError('unknown requirement')
                self.items[item.requirement_id]=item
            except ValueError:errors.append('invalid_coverage_item')
        if not isinstance(reason,str):reason='';errors.append('invalid_revisit_reason')
        report=self.report(trace)
        unresolved=[r['requirement']['requirement_id'] for r in report['items'] if r['status']!='verified']
        verified={r['requirement']['requirement_id'] for r in report['items'] if r['status']=='verified'}
        no_source=self.papers_without_source(trace)
        paper_targets={r['requirement_id'] for r in self.requirements if r.get('paper_quote')} & set(targets)
        first_coverage=bool(no_source and paper_targets and not set(targets).intersection(no_source))
        covered=bool(targets and all(t in verified for t in targets) and unresolved)
        search_needed=self.needs_targeted_search(request,targets,unresolved,trace)
        redirect='paper_without_source' if first_coverage else 'covered_targets' if covered else 'targeted_search_before_more_sections' if search_needed else None
        block=bool(redirect and not reason.strip())
        # One redirect for this covered-target set, then avoid a policy deadlock.
        signature=(redirect,request.get('document_id') if search_needed else None,tuple(sorted(targets)))
        repeated=block and signature in self.warned
        if block:self.warned.add(signature)
        decision=dict(target_requirements=targets,coverage_updates=updates,revisit_reason=reason,
                      errors=errors,unresolved=unresolved,papers_without_source=no_source,
                      redirect_reason=redirect,blocked=block and not repeated,
                      repeated_warning=repeated,report=report)
        trace.setdefault('coverage_priority_events',[]).append(decision)
        return request,decision
