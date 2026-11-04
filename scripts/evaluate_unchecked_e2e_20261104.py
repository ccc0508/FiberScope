"""Fresh 32-question unchecked-review end-to-end experiment, independently graded."""
from pathlib import Path
import json,shutil,sys,subprocess
from concurrent.futures import ThreadPoolExecutor,as_completed
from time import perf_counter
import judge_qa_eval as j
import run_qa_baseline as runner
from filelock import FileLock
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/unchecked-e2e-20261104'
SOURCE=ROOT/'.rag-data/evaluations/pfi-answer-deepseek-20261102'

def prepare():
    if RUN.exists():raise ValueError('Preserve previous experiment')
    b=RUN/'backend';b.mkdir(parents=True)
    shutil.copytree(ROOT/'backend/literature_rag',b/'literature_rag',ignore=shutil.ignore_patterns('__pycache__'))
    for src in ['backend/literature_worker.py','scripts/qa_unchecked_e2e_worker.py','scripts/replay_review_no_validation.py']:
        shutil.copyfile(ROOT/src,b/Path(src).name)
    from dotenv import dotenv_values
    config=dict(dotenv_values(SOURCE/'backend/.env.literature'))
    config.update(RAG_EVIDENCE_REVIEW_ENABLED='true',RAG_CORRECTIVE_REVIEW_ENABLED='true',
        RAG_CORRECTIVE_REVIEW_VERSION='v3_unified',RAG_EVIDENCE_REVIEW_MAX_OUTPUT_TOKENS='65536',
        RAG_EVIDENCE_REVIEW_TIMEOUT_SECONDS='300')
    # Determine the actual Settings environment prefix, not a guessed deployment variable.
    sys.path.insert(0,str(ROOT/'backend'))
    from literature_rag.config import Settings
    prefix=Settings.model_config.get('env_prefix','')
    for name,value in list(config.items()):
        if name.startswith('RAG_') and name[4:].lower() in {'evidence_review_enabled','corrective_review_enabled','corrective_review_version','evidence_review_max_output_tokens','evidence_review_timeout_seconds'}:
            config[prefix+name[4:]]=value
    (b/'.env.literature').write_text('\n'.join(k+'='+json.dumps(v) for k,v in config.items() if v is not None),encoding='utf-8')
    probe=runner.configuration_probe(b)
    shutil.copytree(SOURCE/'dataset',RUN/'dataset')
    shutil.copytree(SOURCE/'library',RUN/'library')
    tasks=j.read_json(SOURCE/'run.json')['tasks']
    manifest=dict(run_id=RUN.name,tasks=tasks,configuration_probe=probe,source_files=runner.source_hashes(b),
        created_at=j.now(),website_env_sha256=j.digest(ROOT/'backend/.env.literature'),
        scope='Fresh query rewrite, embeddings, retrieval, rerank, generation, unchecked review. No cached answers or rewrites.',
        limits=dict(review_max_tokens=65536,review_calls=2,worker_timeout_seconds=1000),
        library_files={p.relative_to(RUN/'library').as_posix():j.digest(p) for p in (RUN/'library').rglob('*') if p.is_file()})
    j.write(RUN/'manifest.json',manifest)
    return dict(prepared=len(tasks),review=probe.get('evidence_review'))

def run(limit=None):
    (RUN/'attempts').mkdir(exist_ok=True)
    m=j.read_json(RUN/'manifest.json');assert runner.source_hashes(RUN/'backend')==m['source_files']
    cases={c['id']:c for c in j.read_jsonl(RUN/'dataset/cases.jsonl')}
    def one(task):
        tid=task['id'];out=RUN/(tid+'.json');attempt=RUN/'attempts'/(tid+'.json')
        if out.exists():return
        if attempt.exists():raise ValueError('Inspect interrupted paid request')
        row=dict(case_id=tid,question=cases[task['case_id']]['question'],started_at=j.now())
        j.write(attempt,row);start=perf_counter()
        try:
            p=runner.execute_question(RUN/'backend/qa_unchecked_e2e_worker.py',RUN/'library',row['question'],1000)
            if p.returncode:
                (RUN/'attempts'/(tid+'.stderr')).write_text(p.stderr,encoding='utf-8')
                row.update(status='harness_failed',returncode=p.returncode)
            else:row.update(json.loads(p.stdout))
        except subprocess.TimeoutExpired:row.update(status='failed',reason_code='worker_timeout')
        row.update(end_to_end_ms=round((perf_counter()-start)*1000),finished_at=j.now())
        j.write(out,row);j.write(attempt,dict(status='completed',result_sha256=j.digest(out)))
    with FileLock(str(RUN/'.runner.lock'),timeout=0):
        todo=[t for t in m['tasks'] if not (RUN/(t['id']+'.json')).exists()]
        if limit:todo=todo[:limit]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for f in as_completed([pool.submit(one,t) for t in todo]):
                f.result();rows=[j.read_json(p) for p in sorted(RUN.glob('PFI2-*.json'))]
                summary=[dict(case_id=r['case_id'],status=r['status'],review=(r.get('evidence_review') or {}).get('status')) for r in rows]
                j.write(RUN/'summary.json',summary);print(j.encode(dict(completed=len(rows),latest=summary[-1])),flush=True)

if __name__=='__main__':
    from argparse import ArgumentParser
    p=ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('--limit',type=int);a=p.parse_args()
    print(j.encode(prepare() if a.action=='prepare' else run(a.limit)),flush=True)
