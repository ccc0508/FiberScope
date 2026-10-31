"""Fixed original primary spans: fresh section-v1 versus classified regrouping and bounded context."""
from argparse import ArgumentParser
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from time import perf_counter
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import judge_qa_eval as judge
import run_qa_baseline as baseline
import section_context_20261031 as engine
import grade_answer_guidance_20261031 as grader
from validate_qa_eval import require
from literature_rag.domain.models import Chunk,Evidence
from literature_rag.application.context import ContextOptions
from literature_rag.application.role_context import RoleSectionCatalog,assemble_roles

TAG='role-context-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
PRIOR=ROOT/'.rag-data/evaluations/section-context-20261031'
LIBRARY=ROOT/'.rag-data/index-versions/content-roles-v1-20261031'
ARMS=('control','guidance')
ENGINES=('role_context_study_20261031.py','report_role_context_20261031.py','mineru_roles.py','mineru_sections.py',
    'section_context_20261031.py','context_expansion_worker.py','grade_answer_guidance_20261031.py','report_section_context_20261031.py')


def prepare():
    require(not OUTPUT.exists(),'Never overwrite a sealed or paid study')
    parent=judge.read_json(PRIOR/'experiment.json');source=judge.read_json(PRIOR/'runs/guidance/run.json')
    structure=judge.read_json(LIBRARY/'structure.json')
    require(structure['role_rules_sha256']==judge.digest(ROOT/'scripts/mineru_roles.py'),'Role preview must use current sealed classification rules')
    with sqlite3.connect((LIBRARY/'metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;chunks=[Chunk(**dict(r)) for r in db.execute('select * from chunks order by chunk_index')]
    catalog=RoleSectionCatalog(chunks,structure);by_id={c.id:c for c in chunks};options=ContextOptions(True)
    require(source['configuration_probe']['context_expansion']==dict(context_expansion_enabled=True,context_neighbor_radius=1,
        context_max_evidence_chars=8000,context_max_total_chars=24000),'Original budget changed')
    fixtures={};projections={};reproduced=0
    for task in source['tasks']:
        tid=task['id'];old=judge.read_json(PRIOR/'fixtures/guidance'/(tid+'.json'));raw=old['seeds'];projected=[];projection={}
        for e in raw:
            children=structure['projection'][e['chunk_id']];projection[e['chunk_id']]=children
            for cid in children:
                c=by_id[cid]
                projected.append(Evidence(f'[{len(projected)+1}]',cid,c.document_id,c.filename,c.page_start,c.page_end,c.text,e['score']))
        start=perf_counter();evidence,info=assemble_roles(projected,catalog,options);elapsed=(perf_counter()-start)*1000
        wire=json.loads(json.dumps([asdict(e) for e in evidence],ensure_ascii=False))
        included={s['chunk_id'] for e in wire for s in e['source_chunks']}
        require({e.chunk_id for e in projected}<=included,'Primary source span was lost')
        info['primary_projection']=projection
        fixtures[tid]={};projections[tid]=projection
        for arm in ARMS:
            f={**old,'strategy':'section_v1' if arm=='control' else 'role_safe_context',
                'evidences':old['evidences'] if arm=='control' else wire,'assembly':old['assembly'] if arm=='control' else info,
                'assembly_ms':old['assembly_ms'] if arm=='control' else elapsed}
            f['evidences_sha256']=engine.canonical(f['evidences'])
            path=OUTPUT/'fixtures'/arm/(tid+'.json');engine.save(path,f)
            fixtures[tid][arm]=dict(fixture_sha256=judge.digest(path),seeds_sha256=f['seeds_sha256'],evidences_sha256=f['evidences_sha256'])
            if arm=='control':
                require(f['evidences']==old['evidences'],'Original section context differs');reproduced+=1
    arms={}
    for arm in ARMS:
        directory=OUTPUT/'runs'/arm;original=PRIOR/'runs/guidance'
        for name in ['backend','dataset','harness']:shutil.copytree(original/name,directory/name)
        (directory/'results').mkdir();(directory/'attempts').mkdir();(directory/'library').mkdir()
        shutil.copytree(original/'library/papers',directory/'library/papers')
        src=original/'library' if arm=='control' else LIBRARY
        for name in ['metadata.sqlite3','structure.json']:shutil.copyfile(src/name,directory/'library'/name)
        run={**source,'run_id':TAG+'-'+arm,'created_at':judge.now(),'execution_mode':'fixed_primary_spans_role_ab',
            'context_strategy':'section_v1' if arm=='control' else 'role_safe_context',
            'initial_library_files':{p.relative_to(directory/'library').as_posix():judge.digest(p) for p in (directory/'library').rglob('*') if p.is_file()},
            'vector_index_policy':'No vector index in replay library. Original top8 source spans are projected exactly; not an end-to-end retrieval experiment.'}
        engine.save(directory/'run.json',run)
        arms[arm]=dict(run_dir=str(directory),run_sha256=judge.digest(directory/'run.json'),source_files=run['source_files'],configuration_probe=run['configuration_probe'])
    c=dict(version='context-expansion-fixed-seeds-v1',created_at=judge.now(),arms=arms,fixtures=fixtures,task_ids=[t['id'] for t in source['tasks']],
        source_run_sha256=parent['source_run_sha256'],source_results_sha256=parent['source_results_sha256'],
        role_structure_sha256=judge.digest(LIBRARY/'structure.json'),old_context_exactly_reproduced=reproduced,primary_projections=projections,
        prior_experiment_sha256=judge.digest(PRIOR/'experiment.json'),
        prior_fixture_sha256={t['id']:judge.digest(PRIOR/'fixtures/guidance'/(t['id']+'.json')) for t in source['tasks']},
        engine_sha256={n:judge.digest(ROOT/'scripts'/n) for n in ENGINES},
        context_sha256={n:judge.digest(ROOT/'backend/literature_rag/application'/n) for n in ['role_context.py','section_context.py','context.py']},
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),planned_answers=64,planned_jev_jobs=64,
        same_original_8_primary_spans=True,old_chunks=107,new_chunks=len(chunks),new_embedding_calls=0,new_rerank_calls=0,
        default_configuration_changed=False,policy='Fresh independent A/B; original primary text spans preserved exactly across classified child chunks. Evaluate regrouping and context filtering, not changed vector rankings.')
    engine.save(OUTPUT/'experiment.json',c)
    return dict(prepared=64,old_context_reproduced=reproduced,chunks=len(chunks),model_calls=0)


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(all(judge.digest(ROOT/'scripts'/n)==v for n,v in c['engine_sha256'].items()),'Frozen study engine changed')
    require(all(judge.digest(ROOT/'backend/literature_rag/application'/n)==v for n,v in c['context_sha256'].items()),'Context engine changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['app_env_sha256'],'Website configuration changed')
    require(judge.digest(LIBRARY/'structure.json')==c['role_structure_sha256'],'Role structure changed')
    require(judge.digest(PRIOR/'experiment.json')==c['prior_experiment_sha256'],'Historical context experiment changed')
    for tid in c['task_ids']:
        require(judge.digest(PRIOR/'fixtures/guidance'/(tid+'.json'))==c['prior_fixture_sha256'][tid],'Original context fixture changed')
        for a in ARMS:
            require(judge.digest(OUTPUT/'fixtures'/a/(tid+'.json'))==c['fixtures'][tid][a]['fixture_sha256'],'Sealed input changed')
    for a,e in c['arms'].items():
        d=Path(e['run_dir']);r=judge.read_json(d/'run.json')
        require(judge.digest(d/'run.json')==e['run_sha256'] and baseline.source_hashes(d/'backend')==e['source_files'],'Frozen runtime changed')
        require(baseline.configuration_probe(d/'backend')==e['configuration_probe'],'Model configuration changed')
        require(all(judge.digest(d/'library'/n)==v for n,v in r['initial_library_files'].items()),'Runtime source library changed')
    return c


def execute(action):
    if action=='prepare':return prepare()
    check_contract()
    if action=='run':
        engine.OUTPUT=OUTPUT;engine.check_contract=check_contract
        return engine.run()
    if action in ['grade-prepare','grade']:
        grader.OUTPUT=OUTPUT;grader.experiment=SimpleNamespace(check_contract=check_contract)
        return grader.prepare() if action=='grade-prepare' else grader.run()
    import report_role_context_20261031 as report
    return report.collect(ROOT,OUTPUT) if action=='collect' else report.publish(ROOT,OUTPUT)


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report']);a=p.parse_args()
    try:print(json.dumps(execute(a.action),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Preserve paid attempts and original source artifacts.')));raise SystemExit(1)
