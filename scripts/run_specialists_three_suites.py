"""Frozen first-attempt 30 RAG + 20 SQL + 20 mixed, opt-in specialists."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from filelock import FileLock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.tools import ToolTraceStore,encode
from literature_rag.config import Settings
from app.experiment_sql import connect,ALLOWED,validate_sql
RUN='specialists-three-suites-20261107'
OUT=ROOT/'.rag-data/evaluations'/RUN
LIB=ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'


def write(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(encode(value),encoding='utf8');tmp.replace(path)


def runtime():
    files=[p for folder in ('backend/app','backend/literature_rag') for p in (ROOT/folder).rglob('*.py')]
    files += [ROOT/'scripts/run_literature_agent.py',ROOT/'backend/literature_worker.py',ROOT/'backend/app/experiment_semantics.json']
    return {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in files}


def db_snapshot():
    with connect() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return {v:sha256(encode(sorted(db.execute('SELECT * FROM fiber.'+v).fetchall(),key=repr)).encode()).hexdigest() for v in sorted(ALLOWED)}


def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'attempts').mkdir(exist_ok=True)
    rag=[json.loads(line) for line in (ROOT/'fiberscope-eval-8papers-v1/questions.jsonl').read_text('utf8').splitlines() if line.strip()]
    sql=json.loads((ROOT/'data/text-to-sql-evaluation/cases-v1.json').read_text('utf8'))
    mixed=json.loads((ROOT/'data/mixed-agent-evaluation/cases-v1.json').read_text('utf8'))
    cases=[dict(c,suite='rag',input=(ROOT/'fiberscope-eval-8papers-v1/tasks'/(c['id']+'.md')).read_text('utf8')) for c in rag]
    cases += [dict(c,suite='sql',input=c['question']) for c in sql]
    cases += [dict(c,suite='mixed',input=c['question']) for c in mixed]
    assert len(cases)==70 and len({c['id'] for c in cases})==70
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    manifest=dict(runtime=runtime(),cases_hash=sha256(encode(cases).encode()).hexdigest(),database=db_snapshot(),
        metadata_hash=sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest(),
        private_config_hash=sha256((ROOT/'backend/.env.literature').read_bytes()).hexdigest(),
        model=settings.llm_model,thinking=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
        architecture='specialists',budget=dict(model_calls=12,tools=8,searches=2,seconds=240),
        policy='One independent first attempt per case. No answer selection. Preserve failures. Stop scheduling after 3 consecutive provider failures. References/checks never sent to candidate.')
    mp=OUT/'manifest.json'
    if mp.exists():assert json.loads(mp.read_text('utf8'))==manifest,'Frozen inputs changed'
    else:
        write(mp,manifest);write(OUT/'cases.json',cases)
        refs={}
        with connect() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            for c in sql:
                refs[c['id']]=[]
                for q in c.get('reference_sql',[]):
                    cur=db.execute(validate_sql(q)[0]);refs[c['id']].append(dict(sql=q,columns=[x.name for x in cur.description],rows=cur.fetchall()))
        write(OUT/'sql-references.json',refs)
    def one(c):
        target=OUT/(c['id']+'.json');rid=RUN+'-'+c['id'];attempt=OUT/'attempts'/(c['id']+'.json')
        if target.exists():return json.loads(target.read_text('utf8'))
        statepath=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        if attempt.exists() or statepath.exists():raise RuntimeError('Inspect interrupted attempt '+rid)
        write(attempt,dict(status='started',run_id=rid,at=datetime.now(timezone.utc).isoformat()))
        start=perf_counter()
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
            '--architecture','specialists','--max-model-calls','12','--question',c['input'],'--library',str(LIB),'--run-id',rid],
            capture_output=True,text=True,encoding='utf8')
        state=json.loads(statepath.read_text('utf8')) if statepath.exists() else dict(status='failed',answer='',stop_reason='worker_failed',model_calls=[],tool_calls=[])
        store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        state.update(case_id=c['id'],suite=c['suite'],question=c['question'],worker_returncode=p.returncode,
            end_to_end_ms=round((perf_counter()-start)*1000),tool_trace=store.read(rid),evidence=store.evidence(rid))
        write(target,state);write(attempt,dict(status='finished',result_hash=sha256(target.read_bytes()).hexdigest()))
        return state
    consecutive=0
    with FileLock(str(OUT/'.lock'),timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        for i in range(0,len(cases),2):
            for result in pool.map(one,cases[i:i+2]):
                provider=result.get('stop_reason') in ('InternalServerError','APIConnectionError','APITimeoutError','RateLimitError') or any(m.get('error_type') in ('InternalServerError','APIConnectionError','APITimeoutError','RateLimitError') for m in result.get('model_calls',[]))
                consecutive=consecutive+1 if provider else 0
                print(encode(dict(id=result['case_id'],suite=result['suite'],status=result['status'],stop_reason=result.get('stop_reason'),route=(result.get('plan') or {}).get('route'))),flush=True)
            if consecutive>=3:
                write(OUT/'paused.json',dict(reason='consecutive_provider_failures',at=datetime.now(timezone.utc).isoformat()))
                print('PAUSED_PROVIDER_FAILURES',flush=True);return
    write(OUT/'integrity.json',dict(runtime_unchanged=runtime()==manifest['runtime'],database_unchanged=db_snapshot()==manifest['database'],
        metadata_unchanged=sha256((LIB/'metadata.sqlite3').read_bytes()).hexdigest()==manifest['metadata_hash'],finished_at=datetime.now(timezone.utc).isoformat()))
    print('FINISHED '+str(OUT),flush=True)


if __name__=='__main__':main()
