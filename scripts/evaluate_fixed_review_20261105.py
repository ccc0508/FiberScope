"""Paired review-only experiment: immutable historical drafts and delivered evidence."""
from pathlib import Path
import sys,json,base64,copy,time
from hashlib import sha256
from filelock import FileLock
import judge_qa_eval as j
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.config import Settings
from literature_rag.application.agent_loop import REVIEW_PROMPT,trace_messages
from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
BASE=ROOT/'.rag-data/evaluations/agent-search2-20261105'
RUN=ROOT/'.rag-data/evaluations/fixed-review-20261105'
IDS=[f'PFI2-{n:03}' for n in [4,15,24,25,26,27,28,29,31]]

def prepare():
    assert not RUN.exists()
    RUN.mkdir(parents=True)
    manifest=dict(source_run=BASE.name,source_hashes={},input_hashes={},
        env_sha256=j.digest(ROOT/'backend/.env.literature'),model='deepseek-flash',thinking=False,
        policy='one review per arm; fixed historical draft and full delivered context; no retrieval or draft generation; no selection',
        review_prompt=REVIEW_PROMPT,selected=IDS,max_output_tokens=8192)
    for tid in IDS:
        x=j.read_json(BASE/(tid+'.json'));manifest['source_hashes'][tid]=j.digest(BASE/(tid+'.json'))
        review=[c for c in x['model_calls'] if c['stage']=='review'];assert len(review)==1
        call=review[0];msgs=copy.deepcopy(call['input_messages'])
        assert msgs[-2]['role']=='assistant' and msgs[-2]['content']==x['draft']
        # Restore precisely the already-viewed images; never add unseen images.
        images={}
        for e in x['evidence']:
            if e['kind']!='source_image':continue
            a=e['content']['asset'];p=BASE/'library'/a['image_path']
            assert j.digest(p)==e['content']['image_sha256']
            u='data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()
            images[sha256(u.encode()).hexdigest()]=u
        for m in msgs:
            if not isinstance(m.get('content'),list):continue
            for b in m['content']:
                if b.get('type')=='image_url':b['image_url']={'url':images[b['image_url']['payload_sha256']]}
        assert trace_messages(msgs)==call['input_messages']
        inp=dict(messages=msgs,timeout_seconds=call['timeout_seconds'],draft=x['draft'])
        j.write(RUN/(tid+'-input.json'),inp);manifest['input_hashes'][tid]=j.digest(RUN/(tid+'-input.json'))
    j.write(RUN/'manifest.json',manifest)
    for arm in ['old','new']:
        (RUN/arm).mkdir();j.write(RUN/arm/'manifest.json',manifest)
    return dict(prepared=len(IDS),arms=2)

def verify():
    m=j.read_json(RUN/'manifest.json')
    assert m['env_sha256']==j.digest(ROOT/'backend/.env.literature')
    assert all(j.digest(BASE/(tid+'.json'))==v for tid,v in m['source_hashes'].items())
    assert all(j.digest(RUN/(tid+'-input.json'))==v for tid,v in m['input_hashes'].items())
    assert m['review_prompt']==REVIEW_PROMPT
    return m

def run():
    m=verify();settings=Settings(_env_file=ROOT/'backend/.env.literature')
    assert settings.llm_model=='deepseek-flash' and settings.llm_thinking_enabled is False and settings.llm_reasoning_effort is None
    adapter=ChatAgentAdapter(settings)
    with FileLock(str(RUN/'.lock'),timeout=0):
        for index,tid in enumerate(IDS):
            # Alternate arm order to reduce systematic timing/order bias.
            for arm in (['old','new'] if index%2==0 else ['new','old']):
                out=RUN/arm/(tid+'.json');mark=RUN/arm/(tid+'-attempt.json')
                if out.exists():continue
                assert not mark.exists(),'Inspect interrupted request; never silently replay'
                x=j.read_json(BASE/(tid+'.json'));inp=j.read_json(RUN/(tid+'-input.json'));msgs=inp['messages']
                if arm=='new':msgs[-1]['content']=m['review_prompt']
                entry=dict(stage='review',status='started',input_messages=trace_messages(msgs),available_tools=[],usage=None)
                # Keep historical acquisition calls solely for evidence provenance. New cost is in review_call.
                x.update(answer=x['draft'],status='partial',review_status='incomplete',stop_reason=None,
                    model_calls=[c for c in x['model_calls'] if c['stage']!='review'],experiment_arm=arm)
                j.write(mark,dict(started_at=j.now(),input_sha256=j.sha(trace_messages(msgs))))
                start=time.perf_counter()
                try:
                    d=adapter.decide(msgs,{},inp['timeout_seconds'],8192)
                    entry.update(text=d.text,usage=d.usage,finish_reason=d.finish_reason,status='completed',calls=[])
                    if d.finish_reason=='length' or not d.text.strip() or d.calls:raise ValueError('Invalid or truncated review')
                    x.update(answer=d.text,status='completed',review_status='completed')
                except Exception as e:
                    entry.update(status='failed',error_type=type(e).__name__)
                    x['stop_reason']=type(e).__name__
                entry['elapsed_ms']=round((time.perf_counter()-start)*1000)
                x['model_calls'].append(entry);x['review_call']=entry
                j.write(out,x)
                print(j.encode(dict(arm=arm,task_id=tid,status=x['status'],elapsed_ms=entry['elapsed_ms'])),flush=True)
    for arm in ['old','new']:j.write(RUN/arm/'summary.json',[dict(case_id=tid,status=j.read_json(RUN/arm/(tid+'.json'))['status']) for tid in IDS])
    verify()

if __name__=='__main__':print(j.encode(dict(prepare=prepare,run=run,verify=verify)[sys.argv[1]]()))
