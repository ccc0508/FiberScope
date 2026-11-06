"""Frozen independent rerun of case 24 after section discovery fix, followed by Jev scoring."""
import json,sys,shutil,subprocess
from pathlib import Path
from time import perf_counter
import judge_qa_eval as j
import evaluate_agent_eightpapers_20261105 as base
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-extension3-20261106'
LIBRARY=RUN/'library'

def answer():
    assert not RUN.exists(),'Preserve first attempts'
    RUN.mkdir(parents=True)
    shutil.copytree(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106',LIBRARY)
    j.write(RUN/'manifest.json',dict(source_files=base.sources(),created_at=j.now(),env_sha256=j.digest(ROOT/'backend/.env.literature'),library=str(LIBRARY),policy='one independent first attempt per case; unchanged tasks and default budgets'))
    sys.path.insert(0,str(ROOT/'backend'))
    from literature_rag.application.tools import ToolTraceStore
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    for tid in ['FSX-001','FSX-002','FSX-003']:
        rid='agent-extension3-20261106-'+tid
        question=(ROOT/'fiberscope-eval-8papers-extension-v1/tasks'/f'{tid}.md').read_text('utf-8')
        start=perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--question',question,'--library',str(LIBRARY),'--run-id',rid],capture_output=True,text=True,encoding='utf-8')
        state=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        x=j.read_json(state) if state.exists() else dict(status='failed',answer='',stop_reason='worker_failed')
        x.update(case_id=tid,end_to_end_ms=round((perf_counter()-start)*1000),worker_returncode=p.returncode,tool_trace=store.read(rid),evidence=store.evidence(rid))
        j.write(RUN/(tid+'.json'),x)
        print(json.dumps(dict(case=tid,status=x['status'],review=x.get('review_status'),stop_reason=x.get('stop_reason')),ensure_ascii=False),flush=True)
    assert base.sources()==j.read_json(RUN/'manifest.json')['source_files']

def grade():
    import grade_agent_eightpapers_20261105 as g
    g.PACK=ROOT/'fiberscope-eval-8papers-extension-v1';g.RUN=RUN;g.OUT=RUN/'jev';g.LIBRARY=LIBRARY
    g.run()

if __name__=='__main__':dict(answer=answer,grade=grade)[sys.argv[1]]()
