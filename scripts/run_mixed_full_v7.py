"""Twenty fresh independent mixed regression attempts; preserve all prior runs."""
from concurrent.futures import ThreadPoolExecutor
import argparse, json, re, subprocess, sys, time
from hashlib import sha256
from run_specialists_three_suites import ROOT,OUT as BASE,LIB,runtime,db_snapshot,write,ToolTraceStore
DEFAULT_RUN='mixed-full-v7-20261109'

def runtime_snapshot():
    snapshot=runtime()
    for filename in ('application/routing_catalog.json','application/paper_identities.json','state_io.py'):
        path=ROOT/'backend/literature_rag'/filename
        snapshot[str(path.relative_to(ROOT))]=sha256(path.read_bytes()).hexdigest()
    return snapshot

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',args.run) or args.run==DEFAULT_RUN:
        parser.error('Provide a new run ID; the original baseline is frozen.')
    OUT=BASE/args.run
    manifest=json.loads((BASE/'manifest.json').read_text('utf8'))
    current_runtime=runtime_snapshot()
    original=BASE/DEFAULT_RUN
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
        target=OUT/(c['id']+'.json');rid=args.run+'-'+c['id']
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
    write(OUT/'integrity.json',dict(runtime_unchanged=runtime_snapshot()==current_runtime,original_answers_unchanged=all(sha256((original/name).read_bytes()).hexdigest()==digest for name,digest in original_hashes.items()),database_unchanged=db_snapshot()==manifest['database'],metadata_unchanged=sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash']))
if __name__=='__main__':main()
