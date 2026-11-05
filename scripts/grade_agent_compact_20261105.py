"""Import unmodified free-form agent answers into the existing Jev policy."""
import re,shutil,json
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as scoring
import evaluate_unified_v31_20261104 as shared
from evaluate_agent_compact_20261105 import ROOT,RUN,verify as verify_runtime
OUTPUT=ROOT/'.rag-data/evaluations/agent-compact-grading-20261105'
PRIOR=ROOT/'.rag-data/evaluations/evidence-review-20261102-v3/review/import'

def segments(answer):
    # Preserve actual Markdown blocks and citation attachment; no generated facts or repaired refs.
    # Tables remain complete blocks so header/column context is never invented or lost.
    blocks=[b.strip() for b in re.split(r'\n\s*\n',answer) if b.strip()]
    grouped=[];prefix='';list_scope=False
    for b in blocks:
        # Standalone Markdown headings and explicit introductions belong to their
        # following list/formula/table. Standalone citation lines belong to the
        # previous block. Preserve every character; never fabricate a citation.
        heading=bool(re.fullmatch(r'#{1,6}[^\n]+',b) or re.fullmatch(r'\*\*[^\n]+\*\*',b))
        introduction=bool(re.search(r'[：:]\s*$',b))
        is_list=bool(re.search(r'(?m)^(?:[-*] |[0-9]+[.)] )',b))
        if list_scope and is_list and not prefix:
            grouped[-1]+='\n\n'+b;continue
        if grouped and '|' in grouped[-1] and re.match(r'^(?:区段与峰位数值|上述(?:表格|数据|数值)|表中(?:数据|数值)).*?见\s*\[',b):
            grouped[-1]+='\n\n'+b;list_scope=False;continue
        if re.fullmatch(r'(?:\[[1-9][0-9]*\]\s*)+',b) and grouped and not prefix:
            grouped[-1]+='\n\n'+b;continue
        if heading or introduction:
            prefix+=b+'\n\n';continue
        list_scope=bool(is_list and re.search(r'[：:]\s*$',prefix))
        grouped.append(prefix+b);prefix=''
    if prefix:grouped.append(prefix.strip())
    return [dict(id=f'C{i}',text=b,citation_refs=list(dict.fromkeys(['['+m+']' for m in re.findall(r'[\[［]([1-9][0-9]*)[\]］](?!\s*（原文编号）)',b)])))
            for i,b in enumerate(grouped,1)]

def delivered_refs(result):
    # Only tool content present in an actual model request counts as available.
    # In particular, withheld ledger entries must not masquerade as seen evidence.
    refs=set()
    def walk(v):
        if isinstance(v,dict):
            if isinstance(v.get('ref'),str):refs.add(v['ref'])
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    for call in result.get('model_calls',[]):
        for msg in call.get('input_messages',[]):
            if msg.get('role')!='tool':continue
            try:walk(json.loads(msg.get('content','')))
            except (ValueError,TypeError):pass
    return refs

def prepare():
    verify_runtime();assert not OUTPUT.exists()
    rows=j.read_json(RUN/'summary.json');assert len(rows)==32
    meta,jobs,sources,pages=g.load_import(PRIOR)
    OUTPUT.mkdir();imported=OUTPUT/'import';shutil.copytree(PRIOR,imported);hashes={}
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];x=j.read_json(RUN/(tid+'.json'));answer=x.get('answer','')
        claims=segments(answer);citations=[];context=[]
        used={ref for c in claims for ref in c['citation_refs']}
        visible=delivered_refs(x)
        for e in x['evidence']:
            if e['ref'] not in visible:continue
            c=e['content'];kind=e['kind']
            if kind=='source_text':
                text=c['text'];start,end=c['page_start'],c['page_end']
            elif kind=='source_image':
                text='Original PDF image: '+c['asset']['label']+'; asset SHA256 '+c['image_sha256']
                start=end=c['asset']['page']
            else:
                text='DERIVED CALCULATION (not a quotation): '+json.dumps(c,ensure_ascii=False);start=end=1
            context.append(text)
            if e['ref'] in used:
                citations.append(dict(ref=e['ref'],text=text,page_start=start,page_end=end,
                    verification=dict(status='immutable_run_ledger'),evidence_kind=kind,snapshot=c))
        candidate=dict(task_id=tid,answer=answer,claims=claims,citations=citations,
            available_context=dict(kind='supplied_excerpts',texts=context))
        job['candidate']=candidate;job['blind_id']=j.sha(dict(study=OUTPUT.name,task=tid,candidate=candidate))[:20]
        j.write(imported/'answers'/('rag-'+tid+'.json'),candidate);hashes[tid]=j.digest(RUN/(tid+'.json'))
        meta['rag_origins'][tid]=dict(source_run_id=RUN.name,result_sha256=hashes[tid],source_run_sha256=j.digest(RUN/'manifest.json'))
    j.write(imported/'jobs.json',jobs);meta['files']={name:j.digest(imported/name) for name in meta['files']}
    meta['metadata']=dict(answer_runtime='compact-single-tool-agent-v2',fresh_retrieval=True,failed_answers_included=True,
        claim_policy='verbatim Markdown blocks; headings/colon introductions joined to following lists, explicit post-table source explanation retained with table, standalone citation lines joined to preceding block; explicit original-paper bibliography refs excluded; no invented citations',
        image_policy='Jev text judge receives image metadata; Codex separately inspects original image assets')
    j.write(imported/'import.json',meta)
    g.prepare(imported,OUTPUT/'judges',g.configs(['jev']),['rag'])
    j.write(OUTPUT/'contract.json',dict(study_sha256=j.digest(OUTPUT/'judges/study.json'),answer_hashes=hashes,
        policy_sha256=g.POLICY_SHA,retries='first valid, at most three failed/invalid attempts'))
    return dict(prepared=32)

def verify():
    c=j.read_json(OUTPUT/'contract.json');assert j.digest(OUTPUT/'judges/study.json')==c['study_sha256']
    assert all(j.digest(RUN/(tid+'.json'))==h for tid,h in c['answer_hashes'].items())

def grade():
    shared.OUTPUT=OUTPUT;shared.verify=verify
    return shared.grade()

def inspect():
    _,jobs,study,reviews,records,statuses,_=scoring.audit(OUTPUT/'import',OUTPUT/'judges')
    rows=[dict(task_id=x['task_id'],question=x['reference_case']['question'],reference=x['reference_case'],
        candidate=x['candidate'],review=reviews.get(('jev','rag',x['task_id']))) for x in jobs if x['system']=='rag']
    j.write(OUTPUT/'inspection.json',rows)
    return dict(valid=sum(r['review'] is not None for r in rows))

if __name__=='__main__':
    import sys
    print(j.encode(dict(prepare=prepare,grade=grade,inspect=inspect)[sys.argv[1]]()))
