"""One fresh FS8-020 attempt with current runtime; keep earlier answers intact."""
import json,subprocess,sys,time,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.tools import ToolTraceStore
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-coverage-priority-20261109'
LIB=ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'
RID='rag-coverage-priority-20261109-FS8-020'
def main():
    global RUN,RID
    parser=argparse.ArgumentParser();parser.add_argument('--revision',type=int,default=1);args=parser.parse_args()
    if args.revision!=1:
        RUN=RUN.with_name(RUN.name+f'-r{args.revision}');RID+=f'-r{args.revision}'
    assert not RUN.exists(),'Preserve existing attempt'
    RUN.mkdir()
    cases=json.loads((RUN.parent/'cases.json').read_text('utf8'));c=next(c for c in cases if c['id']=='FS8-020')
    files=list((ROOT/'backend/literature_rag').rglob('*.py'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (RUN/'manifest.json').write_text(json.dumps(dict(case=c,runtime=hashes,budget='20 model / 12 tools / 2 searches / 360s; 16384 chars reserve',policy='fresh independent attempt; changed scheduling and reserve together, not isolated ablation'),ensure_ascii=False,indent=2),encoding='utf8')
    start=time.perf_counter()
    proc=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--architecture','specialists','--question',c['input'],'--library',str(LIB),'--max-model-calls','20','--max-tools','12','--seconds','360','--run-id',RID],capture_output=True)
    (RUN/'stdout.log').write_bytes(proc.stdout);(RUN/'stderr.log').write_bytes(proc.stderr)
    state_dir=ROOT/'.rag-data/agent-runs'/RID
    x=json.loads((state_dir/'state.json').read_text('utf8'))
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    x.update(case_id=c['id'],suite='rag',question=c['question'],end_to_end_ms=round((time.perf_counter()-start)*1000),worker_returncode=proc.returncode,tool_trace=store.read(RID),evidence=store.evidence(RID),langfuse=json.loads((state_dir/'langfuse.json').read_text('utf8')) if (state_dir/'langfuse.json').exists() else None)
    (RUN/'FS8-020.json').write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    print(json.dumps(dict(status=x['status'],answer=x.get('answer'),budget=x.get('budget_usage')),ensure_ascii=False))
if __name__=='__main__':main()
