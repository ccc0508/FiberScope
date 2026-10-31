"""Fresh A/B on sealed MinerU107 contexts: delete only actual fallback extras."""
from argparse import ArgumentParser
from dataclasses import asdict
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import judge_qa_eval as judge
import run_qa_baseline as baseline
import section_context_20261031 as engine
import grade_answer_guidance_20261031 as grader
from validate_qa_eval import require
from literature_rag.application.fallback_ablation import remove_fallback_extras
from literature_rag.domain.models import Evidence,EvidenceSource

TAG='fallback-ablation-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
PRIOR=ROOT/'.rag-data/evaluations/section-context-20261031'
ARMS=('control','guidance')
ENGINES=('fallback_ablation_20261031.py','report_fallback_ablation_20261031.py','section_context_20261031.py',
    'context_expansion_worker.py','grade_answer_guidance_20261031.py','report_section_context_20261031.py')


def evidence(raw):
    return [Evidence(**{**e,'source_chunks':tuple(EvidenceSource(**s) for s in e['source_chunks']),
        'seed_chunk_ids':tuple(e['seed_chunk_ids'])}) for e in raw]


def prepare():
    require(not OUTPUT.exists(),'Never overwrite a prepared or paid experiment')
    original=PRIOR/'runs/guidance';source=judge.read_json(original/'run.json');parent=judge.read_json(PRIOR/'experiment.json')
    fixtures={};proofs={};affected=[];totals=Counter()
    for task in source['tasks']:
        tid=task['id'];path=PRIOR/'fixtures/guidance'/(tid+'.json');old=judge.read_json(path)
        new,info=remove_fallback_extras(evidence(old['evidences']),evidence(old['seeds']),old['assembly'])
        wire=json.loads(json.dumps([asdict(e) for e in new],ensure_ascii=False))
        ablation=info['fallback_ablation'];totals.update({k:ablation[k] for k in ['fallback_decisions','changed_groups','removed_source_chars','context_chars_removed']})
        totals['removed_question_chunks']+=len(ablation['removed_chunk_ids'])
        if ablation['removed_chunk_ids']:affected.append(tid)
        require([e['ref'] for e in wire]==[e['ref'] for e in old['evidences']],'Evidence references changed')
        removed=set(ablation['removed_chunk_ids'])
        for previous,current in zip(old['evidences'],wire):
            require([s for s in previous['source_chunks'] if s['chunk_id'] not in removed]==current['source_chunks'],'A retained source changed')
            if previous['source_chunks']==current['source_chunks']:require(previous==current,'Untouched evidence changed')
        fixtures[tid]={};proofs[tid]=dict(original_fixture_sha256=judge.digest(path),**ablation)
        for a in ARMS:
            f={**old,'strategy':'original_section_context' if a=='control' else 'delete_fallback_extras_only',
                'evidences':old['evidences'] if a=='control' else wire,
                'assembly':old['assembly'] if a=='control' else info,'assembly_ms':0}
            f['evidences_sha256']=engine.canonical(f['evidences'])
            target=OUTPUT/'fixtures'/a/(tid+'.json');engine.save(target,f)
            fixtures[tid][a]=dict(fixture_sha256=judge.digest(target),seeds_sha256=f['seeds_sha256'],evidences_sha256=f['evidences_sha256'])
    require(totals['fallback_decisions']==25 and len(affected)==10,'Unexpected original fallback coverage')
    arms={}
    for a in ARMS:
        d=OUTPUT/'runs'/a
        for name in ['backend','dataset','harness']:shutil.copytree(original/name,d/name)
        (d/'results').mkdir();(d/'attempts').mkdir();(d/'library').mkdir()
        shutil.copytree(original/'library/papers',d/'library/papers')
        for name in ['metadata.sqlite3','structure.json']:shutil.copyfile(original/'library'/name,d/'library'/name)
        run={**source,'run_id':TAG+'-'+a,'created_at':judge.now(),'execution_mode':'fixed_evidence_fallback_deletion_ab',
            'context_strategy':'original_section_context' if a=='control' else 'delete_fallback_extras_only',
            'initial_library_files':{p.relative_to(d/'library').as_posix():judge.digest(p) for p in (d/'library').rglob('*') if p.is_file()},
            'vector_index_policy':'Original107 metadata reused; no retrieval or vector client invoked in fixed-evidence generation.'}
        engine.save(d/'run.json',run)
        arms[a]=dict(run_dir=str(d),run_sha256=judge.digest(d/'run.json'),source_files=run['source_files'],configuration_probe=run['configuration_probe'])
    c=dict(version='context-expansion-fixed-seeds-v1',created_at=judge.now(),arms=arms,fixtures=fixtures,
        task_ids=[t['id'] for t in source['tasks']],affected_tasks=affected,
        unaffected_tasks=[t['id'] for t in source['tasks'] if t['id'] not in affected],deletion_totals=dict(totals),deletion_proofs=proofs,
        source_run_sha256=parent['source_run_sha256'],source_results_sha256=parent['source_results_sha256'],
        prior_run_sha256=judge.digest(original/'run.json'),prior_experiment_sha256=judge.digest(PRIOR/'experiment.json'),
        app_env_sha256=judge.digest(ROOT/'backend/.env.literature'),engine_sha256={n:judge.digest(ROOT/'scripts'/n) for n in ENGINES},
        deletion_module_sha256=judge.digest(ROOT/'backend/literature_rag/application/fallback_ablation.py'),
        planned_answers=64,planned_jev_jobs=64,default_configuration_changed=False,
        policy='Only delete non-primary sources actually inserted by same_page_fallback from sealed contexts. No regrouping, renumbering, new classification, replacement context, or budget redistribution. Fresh A/B and first-valid Jev.')
    engine.save(OUTPUT/'experiment.json',c)
    return dict(prepared=64,affected_tasks=len(affected),unchanged_input_tasks=32-len(affected),deletion_totals=dict(totals),provider_calls=0)


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(all(judge.digest(ROOT/'scripts'/n)==v for n,v in c['engine_sha256'].items()),'Frozen study engine changed')
    require(judge.digest(ROOT/'backend/literature_rag/application/fallback_ablation.py')==c['deletion_module_sha256'],'Deletion rule changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['app_env_sha256'],'Website configuration changed')
    require(judge.digest(PRIOR/'experiment.json')==c['prior_experiment_sha256'] and
        judge.digest(PRIOR/'runs/guidance/run.json')==c['prior_run_sha256'],'Historical context contract changed')
    for tid in c['task_ids']:
        require(judge.digest(PRIOR/'fixtures/guidance'/(tid+'.json'))==c['deletion_proofs'][tid]['original_fixture_sha256'],'Historical fixture changed')
        for a in ARMS:require(judge.digest(OUTPUT/'fixtures'/a/(tid+'.json'))==c['fixtures'][tid][a]['fixture_sha256'],'Generation context changed')
    for a,e in c['arms'].items():
        d=Path(e['run_dir']);run=judge.read_json(d/'run.json')
        require(judge.digest(d/'run.json')==e['run_sha256'] and baseline.source_hashes(d/'backend')==e['source_files'],'Runtime changed')
        require(baseline.configuration_probe(d/'backend')==e['configuration_probe'],'Generation configuration changed')
        require(all(judge.digest(d/'library'/n)==v for n,v in run['initial_library_files'].items()),'Runtime library changed')
    return c


def execute(action):
    if action=='prepare':return prepare()
    check_contract()
    if action=='run':
        engine.OUTPUT=OUTPUT;engine.check_contract=check_contract;return engine.run()
    if action in ['grade-prepare','grade']:
        grader.OUTPUT=OUTPUT;grader.experiment=SimpleNamespace(check_contract=check_contract)
        return grader.prepare() if action=='grade-prepare' else grader.run()
    import report_fallback_ablation_20261031 as report
    return report.collect(ROOT,OUTPUT) if action=='collect' else report.publish(ROOT,OUTPUT)


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report']);a=p.parse_args()
    try:print(json.dumps(execute(a.action),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Keep all sealed inputs, paid attempts and original outcomes.')));raise SystemExit(1)
