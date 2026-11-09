"""Twenty fresh independent mixed regression attempts; preserve all prior runs."""
from concurrent.futures import ThreadPoolExecutor
import json, subprocess, sys, time
from hashlib import sha256
from run_specialists_three_suites import ROOT,OUT as BASE,LIB,runtime,db_snapshot,write,ToolTraceStore
OUT=BASE/'mixed-full-v7-20261109'
def main():
    manifest=json.loads((BASE/'manifest.json').read_text('utf8'))
    current_runtime=runtime()
    current_runtime['routing_catalog_sha256']=sha256((ROOT/'backend/literature_rag/application/routing_catalog.json').read_bytes()).hexdigest()
    current_runtime['state_io_sha256']=sha256((ROOT/'backend/literature_rag/state_io.py').read_bytes()).hexdigest()
    original=BASE
    original_hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in original.glob('MIX*.json')}
    assert db_snapshot()==manifest['database'],'Database changed'
    assert sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash']
    assert sha256((ROOT/'backend/.env.literature').read_bytes()).hexdigest()==manifest['private_config_hash']
    OUT.mkdir(exist_ok=True)
    cases=[c for c in json.loads((BASE/'cases.json').read_text('utf8')) if c['suite']=='mixed']
    new_manifest=dict(baseline=manifest,runtime=current_runtime,policy='All original twenty MIX cases, current v7 tool selection, coverage scheduling, unit conversion and tracing, fresh independent attempts; no answer selection. Preserve all previous answers. Independent contexts; no development overlays. Fixed 16384-character collection reserve; same external budgets. Same inputs and model; 20 model calls, 12 tools, 2 searches, 360 seconds; citation namespace and JSON repair fixes enabled. Original records unchanged.')
    if (OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text('utf8'))==new_manifest
    else:write(OUT/'manifest.json',new_manifest)
    write(OUT/'cases.json',cases)
    write(OUT/'sql-references.json',json.loads((BASE/'sql-references.json').read_text('utf8')))
    write(OUT/'rubric.json',json.loads((ROOT/'data/mixed-agent-evaluation/rubric-v1.json').read_text('utf8')))
    def one(c):
        target=OUT/(c['id']+'.json');rid='mixed-full-v7-20261109-'+c['id']
        if target.exists():return json.loads(target.read_text('utf8'))
        statepath=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        assert not statepath.parent.exists(),'Inspect interrupted attempt before resuming'
        start=time.perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),'--architecture','specialists','--max-model-calls','20','--max-tools','12','--seconds','360','--question',c['input'],'--library',str(LIB),'--run-id',rid],capture_output=True)
        (OUT/(c['id']+'.stdout.log')).write_bytes(p.stdout)
        (OUT/(c['id']+'.stderr.log')).write_bytes(p.stderr)
        x=json.loads(statepath.read_text('utf8')) if statepath.exists() else dict(run_id=rid,status='failed',answer='',stop_reason='missing_worker_state',model_calls=[],tool_calls=[]);store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        x.update(case_id=c['id'],suite=c['suite'],question=c['question'],worker_returncode=p.returncode,end_to_end_ms=round((time.perf_counter()-start)*1000),tool_trace=store.read(rid),evidence=store.evidence(rid))
        link=statepath.parent/'langfuse.json'
        x['langfuse']=json.loads(link.read_text('utf8')) if link.exists() else None
        write(target,x);return x
    with ThreadPoolExecutor(max_workers=2) as pool:
        for x in pool.map(one,cases):print(json.dumps(dict(id=x['case_id'],status=x['status'],reason=x.get('stop_reason'),formats=[dict(stage=f['stage'],status=f['status']) for f in x.get('format_checks',[])]),ensure_ascii=False),flush=True)
    write(OUT/'integrity.json',dict(runtime_unchanged=dict(runtime(),routing_catalog_sha256=sha256((ROOT/'backend/literature_rag/application/routing_catalog.json').read_bytes()).hexdigest(),state_io_sha256=sha256((ROOT/'backend/literature_rag/state_io.py').read_bytes()).hexdigest())==current_runtime,original_answers_unchanged=all(sha256((original/name).read_bytes()).hexdigest()==digest for name,digest in original_hashes.items()),database_unchanged=db_snapshot()==manifest['database'],metadata_unchanged=sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash']))
if __name__=='__main__':main()
