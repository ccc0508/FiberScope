"""Paired 7 cases x 2 prompts x 2 repeats; identical current tools, independent contexts."""
import ast
from concurrent.futures import ThreadPoolExecutor,as_completed
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.experiment_sql import connect,ALLOWED
from literature_rag.application.tools import encode
from literature_rag.config import Settings

RUN='sql-prompt-ab-20261107'
DEST=ROOT/'data/text-to-sql-evaluation/reports'/RUN
PRIVATE=ROOT/'.rag-data/text-to-sql-evaluation'/RUN
IDS=['SQL04','SQL06','SQL08','SQL12','SQL13','SQL16','SQL19']


def prompts(source):
    nodes=[]
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('PROMPT','REVIEW_PROMPT') for t in node.targets):nodes.append(node)
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='PROMPT':nodes.append(node)
    ns={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<prompt constants>','exec'),ns)
    return {key:ns[key] for key in ('PROMPT','REVIEW_PROMPT')}


def snapshot():
    with connect() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return {view:sha256(encode(sorted(db.execute('SELECT * FROM fiber.'+view).fetchall(),key=repr)).encode()).hexdigest() for view in sorted(ALLOWED)}


def main():
    DEST.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    cases=[c for c in json.loads((ROOT/'data/text-to-sql-evaluation/cases-v1.json').read_text('utf8')) if c['id'] in IDS]
    old=subprocess.check_output(['git','show','d18de1c:backend/literature_rag/application/agent_loop.py'],cwd=ROOT).decode('utf8')
    new=(ROOT/'backend/literature_rag/application/agent_loop.py').read_text('utf8')
    bundles={'old':prompts(old),'new':prompts(new)}
    for label,bundle in bundles.items():
        path=DEST/(label+'-prompts.json');raw=json.dumps(bundle,ensure_ascii=False,indent=2)
        if path.exists() and path.read_text('utf8')!=raw:raise ValueError('Frozen prompt changed')
        path.write_text(raw,encoding='utf8')
    hashes={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for folder in ('backend/app','backend/literature_rag') for p in (ROOT/folder).rglob('*.py')}
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    manifest=dict(code_hashes=hashes,cases=cases,database_hashes=snapshot(),
        model=settings.llm_model,thinking=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
        repeats=2,prompt_hashes={k:sha256((DEST/(k+'-prompts.json')).read_bytes()).hexdigest() for k in bundles},
        policy='Only PROMPT and REVIEW_PROMPT differ. Same current engine, directory, SQL preflight, citation repair and budgets. Two independent repeats per case; old/new concurrent pairs, order reversed in repeat2. No reference answers supplied. Preserve failures, no best-of selection.')
    path=DEST/'manifest.json'
    if path.exists() and json.loads(path.read_text('utf8'))!=manifest:raise ValueError('Inputs changed since frozen run')
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    def run(case,label,repeat):
        rid=f'{RUN}-{label}-r{repeat}-{case["id"]}'
        target=PRIVATE/(rid+'.json')
        if target.exists():return json.loads(target.read_text('utf8'))
        statepath=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        elapsed=None
        if not statepath.exists():
            start=perf_counter()
            p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
                '--question',case['question'],'--library',str(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'),
                '--run-id',rid,'--prompt-file',str(DEST/(label+'-prompts.json'))],capture_output=True,text=True,encoding='utf8')
            elapsed=perf_counter()-start
        s=json.loads(statepath.read_text('utf8')) if statepath.exists() else dict(status='failed',answer='',tool_calls=[],model_calls=[])
        queries=[t for t in s['tool_calls'] if t['request']['tool']=='query_experiment_data']
        result=dict(id=case['id'],variant=label,repeat=repeat,run_id=rid,status=s['status'],answer=s['answer'],
            elapsed_seconds=elapsed,tool_calls=[dict(request=t['request'],result=t.get('result')) for t in s['tool_calls']],
            sql_attempts=len(queries),sql_successes=sum(t['status']=='completed' for t in queries),
            usage=[m.get('usage') for m in s['model_calls']],citation_validation=s.get('citation_validation'),
            prompt_override=s.get('prompt_override'))
        target.write_text(encode(result),encoding='utf8')
        return result
    tasks=[(case,label,repeat) for repeat in (1,2) for case in cases for label in (('old','new') if repeat==1 else ('new','old'))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(run,*args) for args in tasks]):
            r=f.result();print(encode({k:r[k] for k in ('id','variant','repeat','status','sql_attempts')}),flush=True)
    results=[json.loads((PRIVATE/f'{RUN}-{label}-r{repeat}-{case["id"]}.json').read_text('utf8')) for case,label,repeat in tasks]
    (DEST/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    after=snapshot();(DEST/'integrity.json').write_text(json.dumps(dict(database_unchanged=after==manifest['database_hashes'],finished_at=datetime.now(timezone.utc).isoformat()),indent=2),encoding='utf8')
    print('FINISHED '+str(DEST),flush=True)


if __name__=='__main__':main()
