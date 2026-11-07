"""Frozen 20-case development baseline; references never enter Agent context."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.experiment_sql import connect, validate_sql
from literature_rag.application.tools import encode

DATA=ROOT/'data/text-to-sql-evaluation'
CASES=DATA/'cases-v1.json'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',required=True)
    p.add_argument('--workers',type=int,default=2,choices=[1,2])
    p.add_argument('--cases',nargs='+',help='Optional fixed subset, e.g. SQL04 SQL16; use a fresh run id')
    a=p.parse_args()
    if not a.run.replace('-','').isalnum():raise ValueError('Invalid run id')
    out=ROOT/'.rag-data/text-to-sql-evaluation'/a.run
    out.mkdir(parents=True,exist_ok=True)
    cases=json.loads(CASES.read_text('utf8'))
    if a.cases:
        if not set(a.cases)<={c['id'] for c in cases}:raise ValueError('Unknown case id')
        cases=[c for c in cases if c['id'] in a.cases]
    manifest=out/'manifest.json'
    hashes={str(f.relative_to(ROOT)):sha256(f.read_bytes()).hexdigest()
        for folder in ('backend/app','backend/literature_rag') for f in (ROOT/folder).rglob('*.py')}
    hashes['backend/app/experiment_semantics.json']=sha256((ROOT/'backend/app/experiment_semantics.json').read_bytes()).hexdigest()
    if manifest.exists():
        frozen=json.loads(manifest.read_text('utf8'))
        if frozen['code_hashes']!=hashes or frozen['cases_sha256']!=sha256(CASES.read_bytes()).hexdigest():
            raise ValueError('Frozen code or questions changed; use a new run id rather than mixing baseline versions')
        if frozen.get('selected_cases',[f'SQL{i:02d}' for i in range(1,21)])!=[c['id'] for c in cases]:
            raise ValueError('Cannot change case selection within an existing run')
    if not manifest.exists():
        manifest.write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(),
            selected_cases=[c['id'] for c in cases],
            cases_sha256=sha256(CASES.read_bytes()).hexdigest(),code_hashes=hashes,
            policy='Each case independent context; current model/config and full paper directory; no reference answers supplied; max tools 8, model calls 10, 240s. One answer per case; resume completed runs without regeneration.'),indent=2),encoding='utf8')
    # Capture the full allowed-view data snapshot for provenance, without publishing it.
    if not (out/'references.json').exists():
        references={}
        with connect() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            from app.experiment_sql import ALLOWED
            snapshots={}
            for view in sorted(ALLOWED):
                rows=db.execute('SELECT * FROM fiber.'+view).fetchall()
                snapshots[view]=dict(rows=len(rows),sha256=sha256(encode(sorted(rows,key=repr)).encode()).hexdigest())
            for case in cases:
                references[case['id']]=[]
                for query in case.get('reference_sql',[]):
                    sql,_=validate_sql(query)
                    cur=db.execute(sql)
                    references[case['id']].append(dict(sql=sql,columns=[c.name for c in cur.description],rows=cur.fetchall()))
        (out/'references.json').write_text(encode(references),encoding='utf8')
        (out/'database-snapshot.json').write_text(encode(snapshots),encoding='utf8')
    def run(case):
        rid=a.run+'-'+case['id']
        state=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        if not state.exists():
            r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
                '--question',case['question'],'--library',str(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'),
                '--run-id',rid],capture_output=True,text=True,encoding='utf8')
            if r.returncode and not state.exists():return dict(id=case['id'],error='runner_failed')
        s=json.loads(state.read_text('utf8'))
        queries=[t for t in s['tool_calls'] if t['request']['tool']=='query_experiment_data']
        result=dict(id=case['id'],run_id=rid,status=s['status'],answer=s['answer'],
            model=s.get('model'),budget=s.get('budget'),citation_validation=s.get('citation_validation'),
            tool_calls=len(s['tool_calls']),sql_attempts=len(queries),
            sql_successes=sum(t['status']=='completed' for t in queries),
            usage=[m.get('usage') for m in s['model_calls']],
            queries=[dict(request=t['request'],response=t.get('result')) for t in queries],
            manual_review='pending')
        (out/(case['id']+'.json')).write_text(encode(result),encoding='utf8')
        return dict(id=case['id'],status=s['status'],sql_attempts=len(queries))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for future in as_completed([pool.submit(run,c) for c in cases]):print(encode(future.result()),flush=True)
    print(str(out),flush=True)


if __name__=='__main__':main()
