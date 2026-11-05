"""Freeze and run all 32 cases with unchanged simplified-agent default budgets."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,subprocess,sys
from time import perf_counter
import judge_qa_eval as j
from filelock import FileLock
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-simple-20261105'
LIBRARY=ROOT/'.rag-data/evaluations/pfi-answer-deepseek-20261102/library'

def sources():
    paths=list((ROOT/'backend/literature_rag').rglob('*.py'))+[ROOT/'backend/literature_worker.py',ROOT/'scripts/run_literature_agent.py']
    return {p.relative_to(ROOT).as_posix():j.digest(p) for p in paths}

def prepare():
    assert not RUN.exists(),'Preserve existing study'
    RUN.mkdir(parents=True);(RUN/'attempts').mkdir()
    cases=[c for c in j.read_jsonl(ROOT/'fiberscope-eval-v2/cases.jsonl') if c['id'] in {f'PFI2-{i:03}' for i in range(1,33)}]
    assert len(cases)==32
    j.write(RUN/'cases.json',cases)
    j.write(RUN/'manifest.json',dict(created_at=j.now(),source_files=sources(),cases_sha256=j.digest(RUN/'cases.json'),
        env_sha256=j.digest(ROOT/'backend/.env.literature'),library=str(LIBRARY),
        budget=dict(max_model_calls=6,max_tool_calls=8,total_seconds=240,reserve_seconds=45,max_output_tokens=8192,max_context_chars=160000),
        policy='one first run per case, no answer selection; failures included',
        library_hashes={p.relative_to(LIBRARY).as_posix():j.digest(p) for p in LIBRARY.rglob('*') if p.is_file()}))
    return dict(prepared=32)

def verify():
    m=j.read_json(RUN/'manifest.json')
    assert m['source_files']==sources(),'Runtime changed during study'
    assert m['env_sha256']==j.digest(ROOT/'backend/.env.literature')
    assert m['cases_sha256']==j.digest(RUN/'cases.json')
    return m

def run():
    verify()
    def one(case):
        tid=case['id'];out=RUN/(tid+'.json');ap=RUN/'attempts'/(tid+'.json')
        if out.exists():return
        assert not ap.exists(),'Inspect interrupted paid run before retry'
        rid='agent-simple-20261105-'+tid
        j.write(ap,dict(status='started',run_id=rid,started_at=j.now()));start=perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
            '--question',case['question'],'--library',str(LIBRARY),'--run-id',rid],
            capture_output=True,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        state_path=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        x=j.read_json(state_path) if state_path.exists() else dict(status='failed',answer='',stop_reason='worker_failed')
        sys.path.insert(0,str(ROOT/'backend'))
        from literature_rag.application.tools import ToolTraceStore
        store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        x.update(case_id=tid,question=case['question'],end_to_end_ms=round((perf_counter()-start)*1000),
            worker_returncode=p.returncode,tool_trace=store.read(rid),evidence=store.evidence(rid))
        j.write(out,x);j.write(ap,dict(status='completed',result_sha256=j.digest(out)))
    with FileLock(str(RUN/'.lock'),timeout=0),ThreadPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(one,c) for c in j.read_json(RUN/'cases.json')]):
            f.result();rows=[j.read_json(p) for p in sorted(RUN.glob('PFI2-*.json'))]
            summary=[dict(case_id=r['case_id'],status=r['status'],stop_reason=r.get('stop_reason'),
                model_calls=len(r.get('model_calls',[])),tool_calls=len(r.get('tool_calls',[]))) for r in rows]
            j.write(RUN/'summary.json',summary);print(j.encode(dict(completed=len(rows),outcomes=summary)),flush=True)
    verify()

if __name__=='__main__':print(j.encode(dict(prepare=prepare,run=run,verify=verify)[sys.argv[1]]()))
