"""One fresh end-to-end comparison: PyMuPDF baseline versus all implemented RAG features."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import json

from filelock import FileLock
import judge_qa_eval as judge
import run_qa_baseline as runner
import repeat_qa_rerank_20261031 as scheduling
import grade_answer_guidance_20261031 as grader
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
TAG='full-stack-20261031'
OUTPUT=ROOT/'.rag-data/evaluations'/TAG
ARMS=('control','guidance')
SIDECARS=('structure.json','native-source.json','quality-ledger.json','chunk-organization.json',
    'table-retrieval.json','table-row-vectors.json')
ENGINES=('full_stack_qa_20261031.py','report_full_stack_20261031.py','run_qa_baseline.py',
    'repeat_qa_rerank_20261031.py','grade_answer_guidance_20261031.py','grade_qa_rerank_repeats_20261031.py',
    'qa_repeat_refusal_compat.py','collect_rerank_stability_20261031.py','qa_system_judge.py',
    'report_qa_system_benchmark.py','report_answer_guidance_20261031.py','report_qa_context_v1_20261029.py')


def validate_flags(probes):
    common=('llm_provider','llm_model','llm_thinking_enabled','llm_reasoning_effort',
        'embedding_provider','embedding_model','embedding_dimensions','top_k','min_score',
        'context_expansion','provider_endpoint_fingerprints')
    a,b=[probes[s] for s in ARMS]
    require({k:a.get(k) for k in common}=={k:b.get(k) for k in common},'Common model/retrieval parameters differ')
    require(a['context_expansion']['context_expansion_enabled'],'Baseline must retain its verified context optimization')
    for feature in ('table_retrieval','rerank','answer_guidance'):
        require(not a.get(feature,{}).get('enabled'),'Baseline already enables '+feature)
        require(b.get(feature,{}).get('enabled'),'Full stack did not enable '+feature)
    require(b['answer_guidance']['version']=='answer-completeness-v3','Latest guidance not enabled')
    require(b['rerank']['model']=='BAAI/bge-reranker-v2-m3','Unexpected reranking model')
    return {k:a.get(k) for k in common}


def prepare():
    require(not (OUTPUT/'experiment.json').exists(),'Never overwrite a prepared or paid study')
    OUTPUT.mkdir(parents=True,exist_ok=True);arms={};tasks=None;documents=None
    for arm in ARMS:
        directory=OUTPUT/'runs'/arm
        snapshot=ROOT/'.rag-data/baselines'/f'qa-full-stack-{arm}-20261031'
        runner.prepare(snapshot,ROOT/'fiberscope-eval-v2',ROOT/'.rag-data/configs'/f'full-stack-{arm}-20261031.env',
            directory,ROOT/'.rag-data/eval-checkouts'/TAG/'backend/literature_rag','core_text',ROOT/'.rag-data/baselines/qa-v1-20261024')
        run=judge.read_json(directory/'run.json');manifest=judge.read_json(snapshot/'manifest.json')
        if tasks is None:tasks=run['tasks'];documents=manifest['documents']
        require(run['tasks']==tasks and all(t['mode']=='retrieval' for t in tasks),'Only the original live-retrieval questions are allowed')
        require([(d['id'],d['file_hash'],d['page_count']) for d in manifest['documents']]==
            [(d['id'],d['file_hash'],d['page_count']) for d in documents],'Original paper corpus differs')
        require(manifest['chunk_count']==(81 if arm=='control' else 85),'Unexpected parser/index variant')
        arms[arm]=dict(run_dir=str(directory),run_sha256=judge.digest(directory/'run.json'),
            configuration_probe=run['configuration_probe'],source_files=run['source_files'],
            chunks=manifest['chunk_count'],timeout_seconds=run['timeout_seconds'],
            sidecars={n:judge.digest(directory/'library'/n) for n in SIDECARS if (directory/'library'/n).exists()})
    require(len(tasks)==32 and arms['control']['source_files']==arms['guidance']['source_files'],'Runtime code or task coverage differs')
    require(arms['control']['timeout_seconds']==arms['guidance']['timeout_seconds'],'Different question timeout budgets')
    settings=validate_flags({a:arms[a]['configuration_probe'] for a in ARMS})
    require(set(arms['guidance']['sidecars'])==set(SIDECARS),'Full stack lacks verified parsing/table artifacts')
    source=ROOT/'.rag-data/evaluations/pfi-content-units-v1-20261030-r1/library'
    require(all(judge.digest(source/n)==h for n,h in arms['guidance']['sidecars'].items()),'Existing corrected MinerU corpus changed')
    c=dict(version='full-stack-end-to-end-v1',created_at=judge.now(),arms=arms,task_ids=[t['id'] for t in tasks],
        common_settings=settings,application_env_sha256=judge.digest(ROOT/'backend/.env.literature'),
        engine_sha256={n:judge.digest(ROOT/'scripts'/n) for n in ENGINES},
        planned_answers=64,planned_jev_jobs=64,execution_mode='live_retrieval_normal_worker',
        parser_policy='Reuse verified PyMuPDF81 and corrected/organized MinerU85 artifacts; no new parser or document embedding calls.',
        scheduling='One independent normal worker per arm for the same question; alternate submissions, wait for both.',
        no_gold_answers_in_generation=True,default_configuration_changed=False)
    judge.write(OUTPUT/'experiment.json',c)
    return dict(prepared=64,new_provider_calls=0,mode=c['execution_mode'])


def check_contract():
    c=judge.read_json(OUTPUT/'experiment.json')
    require(c['version']=='full-stack-end-to-end-v1','Wrong study')
    require(all(judge.digest(ROOT/'scripts'/n)==h for n,h in c['engine_sha256'].items()),'Frozen execution engine changed')
    require(judge.digest(ROOT/'backend/.env.literature')==c['application_env_sha256'],'Default application configuration changed')
    for arm,e in c['arms'].items():
        d=Path(e['run_dir']);r=judge.read_json(d/'run.json')
        require(d.resolve()==(OUTPUT/'runs'/arm).resolve() and judge.digest(d/'run.json')==e['run_sha256'],'Run manifest/path changed')
        require(runner.source_hashes(d/'backend')==r['source_files'],'Frozen runtime changed')
        require(all(judge.digest(d/'library'/n)==h for n,h in e['sidecars'].items()),'Parsing or table artifacts changed')
    return c


def run():
    c=check_contract()
    with FileLock(str(OUTPUT/'.generation.lock'),timeout=0),ThreadPoolExecutor(max_workers=2) as pool:
        for i,tid in enumerate(c['task_ids']):
            order=ARMS if i%2==0 else tuple(reversed(ARMS))
            futures={a:pool.submit(scheduling.run_one,c['arms'][a],tid,c['task_ids']) for a in order}
            outcomes={a:f.result() for a,f in futures.items()}
            checkpoint=dict(task_id=tid,outcomes=outcomes,finished_at=judge.now())
            judge.write(OUTPUT/'last-pair.json',checkpoint);print(json.dumps(checkpoint),flush=True)
            require('failed' not in outcomes.values(),'A live pipeline failed; inspect the sealed outcome before more paid calls')
    return dict(completed=64)


def execute(action,notes=None,refresh=False):
    if action=='prepare':return prepare()
    c=check_contract()
    if action=='run':return run()
    if action in ('grade-prepare','grade'):
        grader.OUTPUT=OUTPUT;grader.experiment=SimpleNamespace(check_contract=check_contract)
        return grader.prepare() if action=='grade-prepare' else grader.run()
    import report_full_stack_20261031 as reporting
    if action=='collect':
        lines=[] if notes is None else judge.read_json(notes)
        require(isinstance(lines,list) and all(isinstance(s,str) for s in lines),'Analyst notes must be text, not altered scores')
        data=reporting.collect(ROOT,OUTPUT,c);data['analyst_notes']=lines
        judge.write(OUTPUT/'analysis-input.json',data)
        return dict(records=len(data['records']),provider_calls=0)
    if action=='report':return reporting.publish(ROOT,OUTPUT,refresh)
    raise ValueError('Unknown action')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run','grade-prepare','grade','collect','report'])
    p.add_argument('--notes',type=Path);p.add_argument('--refresh',action='store_true');a=p.parse_args()
    try:print(json.dumps(execute(a.action,a.notes,a.refresh),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Study halted; preserve all paid attempts and sealed outputs.')));raise SystemExit(1)
