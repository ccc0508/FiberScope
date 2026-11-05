"""Independent Jev review of the eight-paper suite; no answer generation or selection."""
import json, time, copy, re
from pathlib import Path
import httpx
import fitz
import judge_qa_eval as j
import judge_qa_jev as jev
import qa_system_judge as g
from grade_agent_search2_20261105 import segments, delivered_refs
from evaluate_agent_eightpapers_20261105 import ROOT, RUN, LIBRARY

OUT=RUN/'jev'
PACK=ROOT/'fiberscope-eval-8papers-v1'

def prepare(case, config):
    tid=case['id'];x=j.read_json(RUN/(tid+'.json'))
    sources=j.read_json(PACK/'sources.json');by_id={s['document_id']:s for s in sources}
    by_short={s['id']:s for s in sources}
    visible=delivered_refs(x);claims=segments(x.get('answer',''));cites=[];texts=[]
    used={r for c in claims for r in c['citation_refs']}
    pages={}
    for r in case['evidence']:pages.setdefault(by_short[r['document']]['document_id'],set()).update(r['pages'])
    for e in x.get('evidence',[]):
        if e['ref'] not in visible:continue
        c=e['content'];kind=e['kind'];doc=c.get('document_id')
        if kind=='source_text':text=c['text'];start,end=c['page_start'],c['page_end']
        elif kind=='source_image':
            text='IMAGE metadata only; Jev cannot inspect pixels: '+json.dumps(c,ensure_ascii=False)
            start=end=c['asset']['page'];doc=c['asset'].get('document_id',doc)
        else:text='DERIVED CALCULATION: '+json.dumps(c,ensure_ascii=False);start=end=1
        texts.append(dict(ref=e['ref'],document_id=doc,text=text))
        if doc in by_id and kind!='calculation':pages.setdefault(doc,set()).update(range(start,end+1))
        if e['ref'] in used:cites.append(dict(ref=e['ref'],text=text,page_start=start,page_end=end,document_id=doc,verification=dict(status='immutable_run_ledger'),evidence_kind=kind))
    # Preserve invented/missing citation references as explicit unavailable citations.
    for ref in sorted(used-{c['ref'] for c in cites}):
        cites.append(dict(ref=ref,text='UNAVAILABLE: this reference was not delivered to the answer model.',page_start=1,page_end=1,verification=dict(status='unavailable')))
    papers=[]
    for doc,nums in pages.items():
        s=by_id[doc]
        with fitz.open(LIBRARY/s['library_relative_path']) as pdf:
            text='\n'.join(f'\n[PDF physical page {p}]\n'+pdf[p-1].get_text() for p in sorted(nums) if 1<=p<=len(pdf))
        papers.append(dict(document_id=doc,title=s['title'],text=text,pages=sorted(nums)))
    ref=dict(question=case['question'],category=case['group'],expected_behavior=case['tool_expectation'],reference_answer=case['reference_answer'],
        key_points=[dict(id=f'K{i}',text=p,optional=False,capability='text') for i,p in enumerate(case['key_points'],1)],critical_errors=case['critical_errors'])
    candidate=dict(answer=x.get('answer',''),claims=claims,citations=cites,available_context=dict(kind='supplied_excerpts',texts=texts))
    state,questions,targets=g.packet(dict(candidate=candidate,reference_case=ref,task=dict(capabilities=['text'])),dict(source_documents=sources),dict(reference_evidence=[],paper_texts=papers),{})
    state['policy']['evidence']='Verified original PDF pages below establish truth, alongside the supplied reference. They are not automatically seen or cited by the answer model. Do not assume unprovided pages are absent from the full paper. Image metadata is not pixels; uncertain visual claims require manual review.'
    state['reference_case']['grading_notes']=case['grading_notes']
    state['suite_rubric']=j.read_json(PACK/'rubric.json')
    if case['group']=='no_paper':
        state['policy']['evidence']='No paper is required. Ground claims in the user input, arithmetic, unit conversion and requested transformation. Greetings/formatting are not scientific facts. Do not demand literature citations. Missing prior conversation requires clarification.'
        for k in list(questions):
            if targets[k]['kind'] in {'group','citation'}:del questions[k];del targets[k]
            elif targets[k]['kind']=='claim_type':questions[k]['criteria']={'fact':'Verifiable arithmetic, conversion, or claim about the provided input.','scope':'Greeting, clarification request, purely stylistic transformation or nonfactual instruction.'}
    request=g.request_for('jev',config,state,questions)
    return dict(request=request,questions=questions,targets=targets,state=state,result_sha256=j.digest(RUN/(tid+'.json')))

def decode(saved, body):
    answers=jev.validate_response(body,saved['request'],allow_auxiliary_inconsistency=True)
    # Keep model decisions even when semantic group/pair consistency is questionable:
    # these are calibrated explicitly, not regenerated to obtain a preferred score.
    selected={k:v['choice'] for k,v in answers.items()};points={};claims={};groups=[];pairs=[]
    for k,t in saved['targets'].items():
        v=selected[k];kind=t['kind']
        if kind=='point':points[t['point_id']]=g.POINT_VALUES[v]
        elif kind=='boundary':boundary={'incorrect':0,'partial':1,'appropriate':2}[v]
        elif kind=='reference':concern=v=='needs_review'
        elif kind=='citation':pairs.append(dict(claim_id=t['claim_id'],ref=t['ref'],score=int(v=='supported')))
        elif kind=='group':groups.append(dict(claim_id=t['claim_id'],coverage=v))
        else:claims.setdefault(t['claim_id'],{})[kind]=v
    rows=[dict(c,**claims[c['id']]) for c in saved['state']['candidate']['claims']]
    return dict(key_point_scores=points,claim_assessments=rows,citation_assessments=pairs,citation_group_assessments=groups,answerability_score=boundary,reference_concern=concern,decisions=selected)

def run():
    OUT.mkdir(exist_ok=True);config=jev.load_config(ROOT/'backend/.env.jev')
    cases=j.read_jsonl(PACK/'gold.jsonl');count=0
    for case in cases:
        tid=case['id']
        if not (RUN/(tid+'.json')).exists():continue
        folder=OUT/tid;folder.mkdir(exist_ok=True);inp=folder/'input.json'
        if not inp.exists():j.write(inp,prepare(case,config))
        saved=j.read_json(inp);assert saved['result_sha256']==j.digest(RUN/(tid+'.json'))
        if (folder/'review.json').exists():count+=1;continue
        for attempt in range(1,4):
            path=folder/f'attempt-{attempt}.json'
            if path.exists():
                prior=j.read_json(path)
                assert prior['status']!='pending','Inspect interrupted billed request before retry'
                continue
            rec=dict(status='pending',request_sha256=j.sha(saved['request']),started_at=j.now())
            j.write(path,rec);start=time.monotonic()
            try:
                with httpx.Client(timeout=config.timeout,trust_env=False) as client:
                    resp=client.post(config.base_url+'/alpha/decisions',json=saved['request'],headers={'Authorization':'Bearer '+config.api_key})
                rec['http_status']=resp.status_code
                if resp.status_code!=200:
                    rec['status']='api_failed'
                else:
                    body=resp.json();rec.update(raw_response=body,usage=jev.usage(body),status='invalid')
                    review=decode(saved,body);j.write(folder/'review.json',review);rec['status']='completed';count+=1
            except Exception as ex:rec.update(status='failed',error_type=type(ex).__name__)
            rec['duration_ms']=round((time.monotonic()-start)*1000);j.write(path,rec)
            print(j.encode(dict(case=tid,attempt=attempt,status=rec['status'],graded=count)),flush=True)
            if rec.get('http_status') in {401,402,403}:return
            if rec['status']=='completed':break
    print(j.encode(dict(graded_available=count)),flush=True)

if __name__=='__main__':run()
