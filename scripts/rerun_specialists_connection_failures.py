"""One authorized fresh attempt for MIX17/18; preserve the original baseline."""
from concurrent.futures import ThreadPoolExecutor
import json, subprocess, sys, time
from hashlib import sha256
from run_specialists_three_suites import ROOT,OUT as BASE,LIB,runtime,db_snapshot,write,ToolTraceStore
OUT=BASE/'connection-retry-1'
def main():
    manifest=json.loads((BASE/'manifest.json').read_text('utf8'))
    assert runtime()==manifest['runtime'],'Runtime differs from frozen baseline'
    assert db_snapshot()==manifest['database'],'Database changed'
    assert sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash']
    assert sha256((ROOT/'backend/.env.literature').read_bytes()).hexdigest()==manifest['private_config_hash']
    OUT.mkdir(exist_ok=True)
    cases=[c for c in json.loads((BASE/'cases.json').read_text('utf8')) if c['id'] in {'MIX17','MIX18'}]
    write(OUT/'manifest.json',dict(baseline=manifest,policy='User authorized one fresh independent attempt for exactly MIX17/MIX18. Original records unchanged.'))
    def one(c):
        target=OUT/(c['id']+'.json');rid='specialists-three-suites-20261107-retry1-'+c['id']
        if target.exists():return json.loads(target.read_text('utf8'))
        statepath=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        assert not statepath.parent.exists(),'Inspect interrupted attempt before resuming'
        start=time.perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--architecture','specialists','--max-model-calls','12','--max-tools','8','--seconds','240','--question',c['input'],'--library',str(LIB),'--run-id',rid],capture_output=True)
        x=json.loads(statepath.read_text('utf8'));store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        x.update(case_id=c['id'],suite='mixed',question=c['question'],worker_returncode=p.returncode,end_to_end_ms=round((time.perf_counter()-start)*1000),tool_trace=store.read(rid),evidence=store.evidence(rid))
        write(target,x);return x
    with ThreadPoolExecutor(max_workers=2) as pool:
        for x in pool.map(one,cases):print(json.dumps(dict(id=x['case_id'],status=x['status'],reason=x.get('stop_reason')),ensure_ascii=False),flush=True)
    write(OUT/'integrity.json',dict(runtime_unchanged=runtime()==manifest['runtime'],database_unchanged=db_snapshot()==manifest['database'],metadata_unchanged=sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash']))
if __name__=='__main__':main()
