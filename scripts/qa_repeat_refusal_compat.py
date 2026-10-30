"""Accept production refused results without changing sealed answers or judge rules."""
from argparse import ArgumentParser
from contextlib import contextmanager
from pathlib import Path

import judge_qa_eval as judge
from validate_qa_eval import child,require

ORIGINAL_READ_RESULT=judge.read_result


def read_result(directory,run,case,task):
    path=child(Path(directory)/'results',task['id']+'.json')
    result=judge.read_json(path)
    if result['status']!='refused':return ORIGINAL_READ_RESULT(directory,run,case,task)
    require(result['run_id']==run['run_id'] and result['task_id']==task['id'] and
        result['case_id']==case['id'] and result['question']==case['question'],'Source result identity mismatch')
    attempt=judge.read_json(Path(directory)/'attempts'/(task['id']+'.json'))
    require(attempt.get('result_sha256')==judge.digest(path),'Source answer checksum mismatch')
    response=result.get('response')
    require(isinstance(response,dict) and response.get('status')=='refused' and
        isinstance(response.get('answer'),str) and response['answer'].strip(),'Invalid production refusal body')
    require(response.get('claims')==[] and response.get('citations')==[],'Refusal has unsupported scientific claims/citations')
    return path,result


@contextmanager
def compatible_results():
    previous=judge.read_result;judge.read_result=read_result
    try:yield
    finally:judge.read_result=previous


def prepare_round(round_number):
    import grade_qa_rerank_repeats_20261031 as repeat_grading
    import import_qa_system_answers as importer
    import qa_system_judge as grading
    repeat_grading.repeat.validate_contract()
    settings=grading.configs(['jev']);repeat_grading.settings_contract(settings)
    root=repeat_grading.ROOT;out=repeat_grading.OUTPUT
    log=out/f'refusal-import-compat-r{round_number}.json'
    require(not log.exists(),'Compatibility import already recorded; keep existing outputs')
    records=[]
    for e in repeat_grading.plan(round_number):
        progress=judge.read_json(e['run_dir']/'progress.json')
        require(progress['status']=='completed' and progress['completed']==32,'Wait for all answers')
        require(set(progress['outcomes'])<={'answered','refused'},'Failed outcomes need separate inspection')
        imp=e['import_dir'];study=e['study_dir']
        if not imp.exists():
            pdfs=list((e['run_dir']/'library/papers').glob('*.pdf'));require(len(pdfs)==1,'Expected one original PDF')
            with compatible_results():
                importer.prepare(root/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer.txt',
                    [root/'.rag-data/evaluations/dsh-rag-five-import-20261028-r1/raw/answer_PFI2-013.json'],
                    pdfs[0],e['run_dir'],e['run_dir'],imp,verify_rag_quotes=True)
        if not study.exists():
            study.parent.mkdir(parents=True,exist_ok=True);grading.prepare(imp,study,settings,['rag'])
        repeat_grading.validate_study_binding(e,judge.read_json(study/'study.json'))
        records.append(dict(system=e['system'],round=round_number,outcomes=progress['outcomes'],
            import_sha256=judge.digest(imp/'import.json'),study_sha256=judge.digest(study/'study.json')))
    details=dict(version='refusal-status-compat-v1',compat_source_sha256=judge.digest(Path(__file__)),
        original_read_result_source_sha256=judge.digest(root/'scripts/judge_qa_eval.py'),
        policy_sha256=grading.POLICY_SHA,behavior='Only validate production refused status; scientific answer and source results remain unchanged.',
        original_status_preserved=True,new_generation_calls=0,records=records)
    judge.write(log,details)
    return details


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('--round',type=int,choices=[2,3],required=True);a=p.parse_args()
    import json
    print(json.dumps(prepare_round(a.round),ensure_ascii=False))
