"""Run the frozen eight-paper 30-case suite with the current Agentic RAG runtime."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,subprocess,sys,shutil,sqlite3
from hashlib import sha256
from time import perf_counter
import judge_qa_eval as j
from filelock import FileLock
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-regression-baseline-20261106'
LIBRARY=RUN/'library'

def sources():
    paths=list((ROOT/'backend/literature_rag').rglob('*.py'))+[ROOT/'backend/literature_worker.py',ROOT/'scripts/run_literature_agent.py']
    return {p.relative_to(ROOT).as_posix():j.digest(p) for p in paths}

def logical_index():
    db=sqlite3.connect((LIBRARY/'chroma/chroma.sqlite3').as_uri()+'?mode=ro',uri=True)
    tables=['embeddings','embedding_metadata','embeddings_queue','collection_metadata']
    result={}
    for table in tables:
        rows=db.execute('SELECT * FROM '+table).fetchall()
        result[table]=sha256(repr(sorted(rows,key=repr)).encode()).hexdigest()
    db.close()
    return result


def prepare():
    assert not RUN.exists(),'Preserve existing study'
    RUN.mkdir(parents=True);(RUN/'attempts').mkdir()
    shutil.copytree(ROOT/'fiberscope-eval-8papers-v1',RUN/'pack')
    shutil.copytree(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106',LIBRARY)
    cases=j.read_jsonl(ROOT/'fiberscope-eval-8papers-v1/questions.jsonl')
    assert len(cases)==30
    j.write(RUN/'cases.json',cases)
    j.write(RUN/'manifest.json',dict(created_at=j.now(),source_files=sources(),cases_sha256=j.digest(RUN/'cases.json'),
        pack_hashes={p.name:j.digest(p) for p in (ROOT/'fiberscope-eval-8papers-v1').glob('*') if p.is_file()},
        logical_index=logical_index(),env_sha256=j.digest(ROOT/'backend/.env.literature'),library=str(LIBRARY),
        budget=dict(max_model_calls=10,max_tool_calls=8,max_search_calls=2,total_seconds=240,reserve_seconds=45,max_output_tokens=8192,max_context_chars=160000),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        policy='30-case regression baseline; independent first attempt per case; no answer selection; failures included; extension3 excluded',
        library_hashes={p.relative_to(LIBRARY).as_posix():j.digest(p) for p in LIBRARY.rglob('*') if p.is_file()}))
    return dict(prepared=30)

def verify():
    m=j.read_json(RUN/'manifest.json')
    assert m['source_files']==sources(),'Runtime changed during study'
    assert m['env_sha256']==j.digest(ROOT/'backend/.env.literature')
    assert m['cases_sha256']==j.digest(RUN/'cases.json')
    assert m['logical_index']==logical_index(),'Logical index changed'
    return m

def run():
    verify()
    def one(case):
        tid=case['id'];out=RUN/(tid+'.json');ap=RUN/'attempts'/(tid+'.json')
        if out.exists():return
        assert not ap.exists(),'Inspect interrupted paid run before retry'
        rid='agent-regression-baseline-20261106-'+tid
        j.write(ap,dict(status='started',run_id=rid,started_at=j.now()));start=perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
            '--question',(ROOT/'fiberscope-eval-8papers-v1/tasks'/(tid+'.md')).read_text(encoding='utf-8'),'--library',str(LIBRARY),'--run-id',rid],
            capture_output=True,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        state_path=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        x=j.read_json(state_path) if state_path.exists() else dict(status='failed',answer='',stop_reason='worker_failed')
        sys.path.insert(0,str(ROOT/'backend'))
        from literature_rag.application.tools import ToolTraceStore
        store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        x.update(case_id=tid,question=case['question'],end_to_end_ms=round((perf_counter()-start)*1000),
            worker_returncode=p.returncode,tool_trace=store.read(rid),evidence=store.evidence(rid))
        j.write(out,x);j.write(ap,dict(status='completed',result_sha256=j.digest(out)))
    with FileLock(str(RUN/'.lock'),timeout=0),ThreadPoolExecutor(max_workers=1) as pool:
        for f in as_completed([pool.submit(one,c) for c in j.read_json(RUN/'cases.json')]):
            f.result();rows=[j.read_json(p) for p in sorted(RUN.glob('FS8-*.json'))]
            summary=[dict(case_id=r['case_id'],status=r['status'],stop_reason=r.get('stop_reason'),
                model_calls=len(r.get('model_calls',[])),tool_calls=len(r.get('tool_calls',[]))) for r in rows]
            j.write(RUN/'summary.json',summary);print(j.encode(dict(completed=len(rows),failed=sum(r['status']=='failed' for r in rows),last_finished=max(rows,key=lambda r:r['case_id'])['case_id'])),flush=True)
    verify()

if __name__=='__main__':print(j.encode(dict(prepare=prepare,run=run,verify=verify)[sys.argv[1]]()))
