"""One independent case-17 rerun after paper-scoped/table discovery changes."""
import json,sys,shutil,subprocess
from pathlib import Path
from time import perf_counter
import judge_qa_eval as j
import evaluate_agent_eightpapers_20261105 as base
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-scoped-case17-20261106'
LIBRARY=RUN/'library'
RID='agent-scoped-case17-20261106'

def answer():
    assert not RUN.exists(),'Preserve first attempt'
    RUN.mkdir(parents=True)
    shutil.copytree(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106',LIBRARY)
    j.write(RUN/'manifest.json',dict(source_files=base.sources(),created_at=j.now(),env_sha256=j.digest(ROOT/'backend/.env.literature'),library=str(LIBRARY),policy='one independent first attempt; same task and budgets; new tools and row index'))
    question=(ROOT/'fiberscope-eval-8papers-v1/tasks/FS8-017.md').read_text('utf-8')
    start=perf_counter()
    p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--question',question,'--library',str(LIBRARY),'--run-id',RID],capture_output=True,text=True,encoding='utf-8')
    state=ROOT/'.rag-data/agent-runs'/RID/'state.json'
    x=j.read_json(state) if state.exists() else dict(status='failed',answer='',stop_reason='worker_failed')
    sys.path.insert(0,str(ROOT/'backend'))
    from literature_rag.application.tools import ToolTraceStore
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    x.update(case_id='FS8-017',end_to_end_ms=round((perf_counter()-start)*1000),worker_returncode=p.returncode,tool_trace=store.read(RID),evidence=store.evidence(RID))
    j.write(RUN/'FS8-017.json',x)
    print(json.dumps(dict(status=x['status'],stop_reason=x.get('stop_reason'),answer=x.get('answer')),ensure_ascii=False))

def grade():
    import grade_agent_eightpapers_20261105 as g
    g.RUN=RUN;g.OUT=RUN/'jev';g.LIBRARY=LIBRARY
    g.run()

if __name__=='__main__':dict(answer=answer,grade=grade)[sys.argv[1]]()
