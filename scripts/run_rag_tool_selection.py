"""Fresh independent cases 12/17, preserving all old results and freezing runtime."""
import json,subprocess,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.tools import ToolTraceStore
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-tool-selection-20261109'
LIB=ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'
def main():
    assert not RUN.exists(),'Preserve previous attempt'
    RUN.mkdir()
    cases=[c for c in json.loads((RUN.parent/'cases.json').read_text('utf8')) if c['id'] in ['FS8-012','FS8-017']]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'backend/literature_rag').rglob('*.py')}
    (RUN/'manifest.json').write_text(json.dumps(dict(cases=cases,runtime=hashes,budget='20 model / 12 tools / 2 searches / 360s; reserve 16384 chars'),ensure_ascii=False,indent=2),encoding='utf8')
    for c in cases:
        rid=RUN.name+'-'+c['id'];start=time.perf_counter()
        proc=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--architecture','specialists','--question',c['input'],'--library',str(LIB),'--max-model-calls','20','--max-tools','12','--seconds','360','--run-id',rid],capture_output=True)
        (RUN/(c['id']+'-stdout.log')).write_bytes(proc.stdout);(RUN/(c['id']+'-stderr.log')).write_bytes(proc.stderr)
        state_dir=ROOT/'.rag-data/agent-runs'/rid
        x=json.loads((state_dir/'state.json').read_text('utf8'));store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        x.update(case_id=c['id'],suite='rag',question=c['question'],end_to_end_ms=round((time.perf_counter()-start)*1000),worker_returncode=proc.returncode,tool_trace=store.read(rid),evidence=store.evidence(rid),langfuse=json.loads((state_dir/'langfuse.json').read_text('utf8')) if (state_dir/'langfuse.json').exists() else None)
        (RUN/(c['id']+'.json')).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        print(c['id'],x['status'],flush=True)
if __name__=='__main__':main()
