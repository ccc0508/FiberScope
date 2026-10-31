"""Grade only the fresh 32-question MinerU run using the unchanged Jev protocol."""
from argparse import ArgumentParser
from pathlib import Path
import json
import subprocess
import sys
import threading

from filelock import FileLock
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as reporting
from grade_qa_rerank_repeats_20261031 import execute_jobs,PROXY
from run_qa_baseline import source_hashes
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/pfi-mineru-current-20261101-r1'
OUTPUT=ROOT/'.rag-data/evaluations/mineru-current-20261101'
IMPORT=OUTPUT/'import'
STUDY=OUTPUT/'jev'
HISTORY=ROOT/'.rag-data/evaluations/context-v1-five-judges-20261029-r1'


def prepare():
    progress=judge.read_json(RUN/'progress.json')
    require(progress['status']=='completed' and progress['completed']==32,'Wait for all 32 answers')
    require(progress['outcomes']=={'answered':32},'Preserve failures/refusals and inspect them before importing')
    run=judge.read_json(RUN/'run.json')
    require(source_hashes(RUN/'backend')==run['source_files'],'Frozen answer source changed')
    require(run['configuration_probe']['pipeline_version']=='mineru-unified-rerank-v1','Wrong runtime')
    require('answer_guidance' not in run['configuration_probe'],'Answer guidance must remain disabled')
    settings=grading.configs(['jev']);historical=judge.read_json(HISTORY/'study.json')
    require(historical['policy_sha256']==grading.POLICY_SHA,'Historical scoring policy differs')
    require(historical['requested_judges']['jev']==grading.public_settings(settings)['jev'],'Jev settings differ')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if not IMPORT.exists():
        papers=list((RUN/'library/papers').glob('*.pdf'));require(len(papers)==1,'Expected the original paper')
        old=ROOT/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw'
        # Existing import format contains both systems. DSH is only copied for
        # compatibility; selected grading jobs below contain new RAG answers only.
        command=[sys.executable,str(ROOT/'scripts/import_qa_system_answers.py'),'--input',str(old/'answer.txt'),
            '--extra',str(old/'answer_PFI2-013.json'),'--pdf',str(papers[0]),'--rag-run',str(RUN),
            '--recovery-run',str(RUN),'--output',str(IMPORT),'--verify-rag-quotes']
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        judge.write(OUTPUT/'import-process.json',dict(returncode=result.returncode,
            stdout_sha256=judge.sha(result.stdout),stderr_sha256=judge.sha(result.stderr)))
        require(result.returncode==0,'Import failed; inspect saved answers without regenerating them')
    if not STUDY.exists():grading.prepare(IMPORT,STUDY,settings,['rag'])
    study=judge.read_json(STUDY/'study.json')
    require(study['selected_systems']==['rag'] and set(study['requested_judges'])=={'jev'},'Only new RAG/Jev jobs allowed')
    require(len(study['jobs'])==32 and {j['task_id'] for j in study['jobs']}=={t['id'] for t in run['tasks']},'Task set differs')
    meta=judge.read_json(IMPORT/'import.json')
    require(all(o['source_run_id']==run['run_id'] for o in meta['rag_origins'].values()),'Wrong answer run imported')
    contract=dict(version='mineru-current-one-run-20261101',run_manifest_sha256=judge.digest(RUN/'run.json'),
        study_sha256=judge.digest(STUDY/'study.json'),import_sha256=judge.digest(IMPORT/'import.json'),
        policy_sha256=grading.POLICY_SHA,requested_judges=grading.public_settings(settings),
        max_attempts=3,first_valid_only=True,proxy=PROXY,orchestrator_sha256=judge.digest(Path(__file__)),
        historical_comparison='Reused PyMuPDF 81-block answers and grades, not a newly generated control.',
        answer_guidance_enabled=False,new_rag_questions=32,new_luna_jobs=0,new_dsh_jobs=0,
        default_config_sha256=judge.digest(ROOT/'backend/.env.literature'))
    path=OUTPUT/'contract.json'
    if path.exists():require(judge.read_json(path)==contract,'Frozen run contract changed')
    else:judge.write(path,contract)
    return dict(prepared=32,model_calls=0,judge='jev',answer_guidance_enabled=False)


def grade(workers=4):
    contract=judge.read_json(OUTPUT/'contract.json');settings=grading.configs(['jev'])
    require(judge.digest(Path(__file__))==contract['orchestrator_sha256'],'Frozen orchestrator changed')
    require(judge.digest(RUN/'run.json')==contract['run_manifest_sha256'],'Answer run changed')
    require(judge.digest(STUDY/'study.json')==contract['study_sha256'],'Grading manifest changed')
    require(grading.public_settings(settings)==contract['requested_judges'],'Jev configuration changed')
    require(judge.digest(ROOT/'backend/.env.literature')==contract['default_config_sha256'],'Website config changed')
    study=judge.read_json(STUDY/'study.json')
    require(all(judge.digest(ROOT/'scripts'/name)==h for name,h in study['harness_files'].items()),'Grading implementation changed')
    with FileLock(str(OUTPUT/'.grading.lock'),timeout=0),judge.lock(STUDY):
        audit=reporting.audit(IMPORT,STUDY)
        require(all(status!='pending' for _,_,status in audit[5]),'Inspect interrupted requests before retrying')
        jobs=[(dict(study_dir=STUDY),entry) for entry in study['jobs']]
        result=execute_jobs(jobs,settings,threading.Event(),workers,1)
        judge.write(OUTPUT/'grading-progress.json',result)
    return result


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','grade'])
    p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    try:result=prepare() if a.action=='prepare' else grade(a.workers)
    except Exception as error:
        print(json.dumps(dict(error_type=type(error).__name__,message='Keep checkpoints; do not regenerate valid answers or grades.')))
        raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False))
