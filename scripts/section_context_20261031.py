"""Controlled same-page versus section context experiment on fixed MinerU107 primary hits."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace

from filelock import FileLock
import judge_qa_eval as judge
import run_qa_baseline as baseline
import grade_answer_guidance_20261031 as grader
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.context import ContextOptions,assemble
from literature_rag.application.section_context import SectionCatalog,assemble_sections
from literature_rag.domain.models import Chunk,Evidence

TAG='section-context-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
SOURCE=ROOT/'.rag-data/evaluations/pfi-mineru-sections-v2-20261030-r1'
ARMS=('control','guidance')
STRATEGIES={'control':'same_page_neighbors','guidance':'bounded_section_with_neighbor_fallback'}
ENGINES=('section_context_20261031.py','context_expansion_worker.py','grade_answer_guidance_20261031.py',
    'run_qa_baseline.py','report_section_context_20261031.py','qa_system_judge.py','qa_repeat_refusal_compat.py')


def canonical(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);baseline.write_json(path,value)


class FixedMetadata:
    def __init__(self,chunks):self.chunks=chunks
    def get_context_chunks(self,ids,radius):
        seeds=[c for c in self.chunks if c.id in ids]
        return [c for c in self.chunks if any(c.document_id==s.document_id and
            (c.page_start,c.page_end)==(s.page_start,s.page_end) and abs(c.chunk_index-s.chunk_index)<=radius for s in seeds)]


def prepare():
    require(not OUTPUT.exists(),'Never overwrite a prepared study or a paid result')
    source,_,cases,_=judge.verify_run(SOURCE)
    structure=judge.read_json(SOURCE/'library/structure.json')
    with sqlite3.connect((SOURCE/'library/metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        chunks=[Chunk(**dict(r)) for r in db.execute('SELECT * FROM chunks ORDER BY document_id,chunk_index')]
    require(len(chunks)==107,'Expected the original 107-block index')
    catalog=SectionCatalog(chunks,structure);metadata=FixedMetadata(chunks)
    o=source['configuration_probe']['context_expansion']
    options=ContextOptions(True,o['context_neighbor_radius'],o['context_max_evidence_chars'],o['context_max_total_chars'])
    fixtures={};source_results={};diagnostics={a:{} for a in ARMS}
    for task in source['tasks']:
        tid=task['id'];path,result=judge.read_result(SOURCE,source,cases[task['case_id']],task)
        r=result['response'];raw=r['retrieval_seed_evidence']
        require(len(raw)==8 and result['status']=='answered','Unexpected original seed result')
        seeds=[Evidence(**{**e,'source_chunks':tuple(e['source_chunks']),'seed_chunk_ids':tuple(e['seed_chunk_ids'])}) for e in raw]
        source_results[tid]=judge.digest(path);fixtures[tid]={}
        for arm,method in [('control',lambda:assemble(seeds,metadata,options)),
                           ('guidance',lambda:assemble_sections(seeds,catalog,options))]:
            started=perf_counter();evidence,info=method();elapsed=(perf_counter()-started)*1000
            wire=json.loads(json.dumps([asdict(e) for e in evidence],ensure_ascii=False))
            if arm=='control':require(wire==r['retrieved_evidence'],'Original neighbor assembly was not reproduced exactly')
            ids=[s['chunk_id'] for e in wire for s in e['source_chunks']]
            require(set(e['chunk_id'] for e in raw)<=set(ids),'An original primary hit was lost')
            require(sum(len(e['text']) for e in wire)<=options.max_total_chars and
                    all(len(e['text'])<=options.max_evidence_chars for e in wire),'Context budget exceeded')
            require(not info['omitted_seed_chunk_ids'],'A primary hit was discarded')
            fixture=dict(version='context-expansion-fixed-seeds-v1',task_id=tid,question=result['question'],
                strategy=STRATEGIES[arm],seeds=raw,seeds_sha256=canonical(raw),evidences=wire,evidences_sha256=canonical(wire),
                documents=r['configuration']['documents'],assembly=info,assembly_ms=elapsed,source_result_sha256=judge.digest(path))
            target=OUTPUT/'fixtures'/arm/(tid+'.json');save(target,fixture)
            fixtures[tid][arm]=dict(fixture_sha256=judge.digest(target),seeds_sha256=canonical(raw),evidences_sha256=canonical(wire))
            diagnostics[arm][tid]=dict(chars=info['context_chars'],chunks=ids,added=info['added_chunk_ids'],
                budget_limited=info['budget_limited'],assembly_ms=elapsed,
                cross_page_evidences=sum(e['page_start']!=e['page_end'] for e in wire))
    arms={}
    for arm in ARMS:
        directory=OUTPUT/'runs'/arm
        baseline.prepare(ROOT/'.rag-data/baselines/qa-mineru-sections-v2-20261030',ROOT/'fiberscope-eval-v2',
            SOURCE/'backend/.env.literature',directory,SOURCE/'backend/literature_rag','core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
        run=judge.read_json(directory/'run.json');require(run['tasks']==source['tasks'],'Questions changed')
        worker=directory/'harness/context_expansion_worker.py';shutil.copyfile(ROOT/'scripts/context_expansion_worker.py',worker)
        run.update(timeout_seconds=300,execution_mode='fixed_primary_hits_context_ab',
            input_policy='Question and primary-hit-derived context only; no old answers, gold answers, scores or reference evidence.',
            controlled_harness=dict(worker_sha256=judge.digest(worker)),context_strategy=STRATEGIES[arm])
        save(directory/'run.json',run)
        arms[arm]=dict(run_dir=str(directory),run_sha256=judge.digest(directory/'run.json'),
            source_files=run['source_files'],configuration_probe=run['configuration_probe'])
    require(arms['control']['configuration_probe']==arms['guidance']['configuration_probe']==source['configuration_probe'],
            'The original pipeline and generation settings must remain identical')
    require(arms['control']['source_files']==arms['guidance']['source_files']==source['source_files'],'Frozen runtime differs')
    contract=dict(version='context-expansion-fixed-seeds-v1',created_at=judge.now(),arms=arms,fixtures=fixtures,
        task_ids=[t['id'] for t in source['tasks']],source_run_sha256=judge.digest(SOURCE/'run.json'),source_results_sha256=source_results,
        structure_sha256=judge.digest(SOURCE/'library/structure.json'),metadata_sha256=judge.digest(SOURCE/'library/metadata.sqlite3'),
        engine_sha256={n:judge.digest(ROOT/'scripts'/n) for n in ENGINES},
        assembler_sha256=judge.digest(ROOT/'backend/literature_rag/application/section_context.py'),
        legacy_assembler_sha256=judge.digest(ROOT/'backend/literature_rag/application/context.py'),
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),planned_answers=64,planned_jev_jobs=64,
        default_configuration_changed=False,new_embedding_calls=0,new_rerank_calls=0,old_context_exactly_reproduced=32,
        policy='Fresh paired generations; same 107-block corpus, original eight primary hits, model/high/prompts and 8000/24000 character caps; only context assembly changes.')
    save(OUTPUT/'experiment.json',contract);save(OUTPUT/'context-diagnostics.json',diagnostics)
    return dict(prepared=64,provider_calls=0,control_reproduced=32,
        context_characters={a:sum(v['chars'] for v in diagnostics[a].values()) for a in ARMS})


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in c['engine_sha256'].items()),'Frozen engine changed')
    for name,key in [('section_context.py','assembler_sha256'),('context.py','legacy_assembler_sha256')]:
        require(judge.digest(ROOT/'backend/literature_rag/application'/name)==c[key],'Context assembler changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['app_env_sha256'],'Website configuration changed')
    require(judge.digest(SOURCE/'run.json')==c['source_run_sha256'] and
        judge.digest(SOURCE/'library/structure.json')==c['structure_sha256'] and
        judge.digest(SOURCE/'library/metadata.sqlite3')==c['metadata_sha256'],'Historical corpus changed')
    for tid in c['task_ids']:
        require(judge.digest(SOURCE/'results'/(tid+'.json'))==c['source_results_sha256'][tid],'Historical answer changed')
        for arm in ARMS:
            f=OUTPUT/'fixtures'/arm/(tid+'.json')
            require(judge.digest(f)==c['fixtures'][tid][arm]['fixture_sha256'],'Sealed context changed')
    for arm,e in c['arms'].items():
        d=Path(e['run_dir']);r=judge.read_json(d/'run.json')
        require(judge.digest(d/'run.json')==e['run_sha256'] and baseline.source_hashes(d/'backend')==e['source_files'],'Frozen generation runtime changed')
        require(judge.digest(d/'harness/context_expansion_worker.py')==c['engine_sha256']['context_expansion_worker.py'],'Frozen worker changed')
        require(baseline.configuration_probe(d/'backend')==e['configuration_probe'],'Frozen configuration changed')
    return c


def one(arm,tid,c):
    directory=Path(c['arms'][arm]['run_dir']);run=judge.read_json(directory/'run.json')
    task=next(t for t in run['tasks'] if t['id']==tid);f=OUTPUT/'fixtures'/arm/(tid+'.json');fixture=judge.read_json(f)
    target=directory/'results'/(tid+'.json');attempt=directory/'attempts'/(tid+'.json')
    if target.exists():
        require(judge.read_json(attempt)['result_sha256']==judge.digest(target),'Saved answer changed')
        return judge.read_json(target)['status']
    require(not attempt.exists(),'Interrupted paid attempt needs inspection, not automatic replay')
    row=dict(run_id=run['run_id'],task_id=tid,case_id=task['case_id'],question=fixture['question'],suite=task['suite'],
        capabilities=task['capabilities'],variant=task.get('variant'),started_at=judge.now(),runner_sha256=judge.digest(Path(__file__)),
        execution_timeout_seconds=run['timeout_seconds'])
    save(attempt,{**row,'status':'started'});started=perf_counter()
    try:
        process=subprocess.run([sys.executable,'-I','-X','utf8',str(directory/'harness/context_expansion_worker.py')],
            input=json.dumps(dict(backend_dir=str(directory/'backend'),fixture_file=str(f),question=fixture['question']),ensure_ascii=False),
            env=baseline.clean_environment(),capture_output=True,text=True,encoding='utf-8',timeout=run['timeout_seconds'],
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        row.update(worker_returncode=process.returncode,worker_stderr_sha256=sha256(process.stderr.encode()).hexdigest(),worker_stderr_bytes=len(process.stderr.encode()))
        if process.returncode:row.update(status='failed',reason_code='context_worker_error',response=None)
        else:
            r=json.loads(process.stdout);d=r['fixed_seed_diagnostics']
            require(d['seeds_sha256']==fixture['seeds_sha256'] and d['generation_input_evidence_sha256']==fixture['evidences_sha256'],'Actual input differs')
            require(r['retrieved_evidence']==fixture['evidences'] and r['retrieval_seed_evidence']==fixture['seeds'],'Worker altered context or seeds')
            require(r['configuration']['prompt_pipeline_sha256']==run['configuration_probe']['prompt_pipeline_sha256'],'Original prompt pipeline changed')
            row.update(status=r['status'],reason_code=r.get('reason_code'),response=r)
    except subprocess.TimeoutExpired:row.update(status='failed',reason_code='context_worker_timeout',response=None)
    row.update(finished_at=judge.now(),end_to_end_ms=round((perf_counter()-started)*1000));save(target,row)
    save(attempt,dict(status='completed',result_sha256=judge.digest(target)))
    results=[judge.read_json(p) for p in (directory/'results').glob('*.json')]
    save(directory/'progress.json',dict(status='completed' if len(results)==32 else 'running',completed=len(results),total=32,
        outcomes=dict(Counter(r['status'] for r in results))))
    return row['status']


def run():
    c=check_contract()
    with FileLock(str(OUTPUT/'.generation.lock'),timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        for i,tid in enumerate(c['task_ids']):
            order=ARMS if i%2==0 else tuple(reversed(ARMS))
            fs={a:pool.submit(one,a,tid,c) for a in order};outcomes={a:f.result() for a,f in fs.items()}
            print(json.dumps(dict(task_id=tid,outcomes=outcomes)),flush=True)
            require('failed' not in outcomes.values(),'A worker failed; preserve paid attempts for inspection')
    return dict(completed=64)


def execute(action):
    if action=='prepare':return prepare()
    check_contract()
    if action=='run':return run()
    if action in ('grade-prepare','grade'):
        grader.OUTPUT=OUTPUT;grader.experiment=SimpleNamespace(check_contract=check_contract)
        return grader.prepare() if action=='grade-prepare' else grader.run()
    import report_section_context_20261031 as reporting
    if action=='collect':return reporting.collect(ROOT,OUTPUT)
    if action=='report':return reporting.publish(ROOT,OUTPUT)
    raise ValueError('Unknown operation')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report']);a=p.parse_args()
    try:print(json.dumps(execute(a.action),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Study halted; preserve sealed inputs and paid attempts.')));raise SystemExit(1)
