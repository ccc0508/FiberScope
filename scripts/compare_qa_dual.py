"""Audit one frozen v3 GPT/Jev round on the same saved answers; no model calls."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import compare_qa_jev as comparison
import judge_qa_eval as judge
import judge_qa_jev as jev
import qa_scoring_policy as policy


def differences(left, right, case):
    """Expose model-authored label differences, without deciding which judge is right."""
    changes=[]
    for point in case['key_points']:
        key=point['id'];a=left['key_point_scores'][key];b=right['key_point_scores'][key]
        if a!=b:
            changes.append(dict(dimension='point',point_id=key,optional=point['optional'],gpt=a,jev=b))
    claims=[{c['id']:c for c in r['claim_assessments']} for r in (left,right)]
    judge.require(set(claims[0])==set(claims[1]),'Compared claim identities differ')
    for key in claims[0]:
        for field in ('claim_type','support'):
            a=claims[0][key][field];b=claims[1][key][field]
            if a!=b:changes.append(dict(dimension=field,claim_id=key,gpt=a,jev=b))
    pairs=[{(p['claim_id'],p['ref']):p['score'] for p in r['citation_assessments']} for r in (left,right)]
    judge.require(set(pairs[0])==set(pairs[1]),'Compared citation identities differ')
    for key in pairs[0]:
        a=pairs[0][key];b=pairs[1][key]
        if a!=b:changes.append(dict(dimension='citation',claim_id=key[0],ref=key[1],gpt=a,jev=b))
    groups=[{g['claim_id']:g['coverage'] for g in r['citation_group_assessments']} for r in (left,right)]
    judge.require(set(groups[0])==set(groups[1]),'Compared citation group identities differ')
    for key in groups[0]:
        a=groups[0][key];b=groups[1][key]
        if a!=b:changes.append(dict(dimension='citation_group',claim_id=key,gpt=a,jev=b))
    return changes


def agreement_sample(task_ids, seed, size=5):
    return sorted(task_ids,key=lambda tid:hashlib.sha256((seed+':'+tid).encode()).hexdigest())[:size]


def analyze(source, study_dir, gpt_dir, jev_dir, output, *, allow_incomplete=False):
    source,study_dir,gpt_dir,jev_dir,output=map(Path,(source,study_dir,gpt_dir,jev_dir,output))
    judge.require(not output.exists(),'Use a new comparison directory')
    judge.require(not any(output.resolve().is_relative_to(p.resolve()) for p in (source,gpt_dir,jev_dir)),
                  'Comparison cannot write into source answers or judge records')
    study=judge.read_json(study_dir/'study.json')
    judge.require(study['scoring_policy_version']==policy.VERSION and study['scoring_policy_sha256']==policy.SHA256,
                  'Study scoring policy changed')
    judge.require(study['stateless'] is True and study['previous_scores_supplied'] is False
                  and study['previous_conversation_supplied'] is False,'Independent judge context was not guaranteed')
    run,manifest,cases,sources=judge.verify_run(source);tasks=run['tasks']
    judge.require(judge.digest(source/'run.json')==study['source_run_sha256'],'Source run changed')
    for task in tasks:
        path,_=judge.read_result(source,run,cases[task['case_id']],task)
        judge.require(judge.digest(path)==study['source_answer_sha256'][task['id']],'Source answer changed')

    # Verify the independent GPT initial attempts against the pre-call frozen requests.
    aggregate=judge.read_json(gpt_dir/'aggregate-run.json')['contract']
    originals=[];gpt_ids=[]
    for component in aggregate['component_metadata']:
        directory=source.parent/component['name'];meta=judge.read_json(directory/'judge-run.json')['contract']
        judge.require(meta['contract_version']==judge.prompt.VERSION,'Mixed GPT prompt versions')
        judge.require({k:v for k,v in meta['judge'].items() if k!='timeout_seconds'}
                      =={k:v for k,v in study['judge_configs']['gpt'].items() if k!='timeout_seconds'},'GPT judge configuration changed')
        for path in sorted((directory/'tasks').glob('*.json')):
            record=judge.read_json(path)
            if record.get('api_calls',0) and record.get('raw_response',{}).get('id'):
                gpt_ids.append(record['raw_response']['id'])
            if not meta.get('validation_repairs') and not meta.get('revalidated_sources'):
                judge.require(record['request_sha256']==study['request_sha256']['gpt'][record['task_id']],
                              'GPT initial request differs from frozen study')
        if not meta.get('validation_repairs') and not meta.get('revalidated_sources'):originals.append(directory.name)
    judge.require(originals==[study['initial_directories']['gpt']],'Unexpected GPT initial scoring components')
    gpt=comparison.audit_gpt(source,gpt_dir)

    native_meta=judge.read_json(jev_dir/'jev-run.json')['contract']
    judge.require(jev_dir.name==study['initial_directories']['jev'],'Unexpected Jev initial scoring directory')
    judge.require(native_meta['scoring_policy_sha256']==policy.SHA256,'Jev scoring policy changed')
    for name,value in native_meta['harness_files'].items():
        judge.require(study['harness_files'].get(name)==value,'Jev harness differs from frozen study')
    native_study=dict(source_run_sha256=study['source_run_sha256'],source_answer_sha256=study['source_answer_sha256'],
                      request_sha256=study['request_sha256']['jev'],judge=study['judge_configs']['jev'],
                      harness_files=native_meta['harness_files'])
    native=comparison.audit_jev(source,jev_dir,native_study,cases,tasks,sources,manifest)
    judge.require(policy.require_same_policy([*gpt['reviews'].values(),*native['reviews'].values()])==policy.VERSION,
                  'Both judges must use the shared v3 policy')
    common=set(gpt['reviews'])&set(native['reviews']);planned={t['id'] for t in tasks}
    judge.require(bool(common),'No common valid judgments')
    if not allow_incomplete:judge.require(common==planned,'Incomplete dual scoring; do not publish a full-round score')

    rows=[]
    for task in tasks:
        tid=task['id']
        if tid not in common:continue
        changes=differences(gpt['reviews'][tid],native['reviews'][tid],cases[task['case_id']])
        rows.append(dict(task_id=tid,case_id=task['case_id'],changes=changes,all_common_labels_agree=not changes))
    agreeing=[r['task_id'] for r in rows if r['all_common_labels_agree']]
    disagreed=[r['task_id'] for r in rows if not r['all_common_labels_agree']]
    labels=comparison.compare_labels(gpt['reviews'],native['reviews'],tasks,cases)
    result=dict(scoring_policy_version=policy.VERSION,scoring_policy_sha256=policy.SHA256,
                source_run_id=run['run_id'],source_run_sha256=study['source_run_sha256'],
                dataset_manifest_sha256=run['dataset_manifest_sha256'],study_sha256=judge.digest(study_dir/'study.json'),
                planned_tasks=len(tasks),common_valid_tasks=len(common),complete=common==planned,
                excluded_task_ids=sorted(planned-common),rounds_per_judge=1,
                gpt=comparison.summarize_rows(gpt_dir.name,gpt['reviews'],tasks,cases,common),
                jev=comparison.summarize_rows(jev_dir.name,native['reviews'],tasks,cases,common),
                gpt_accounting=gpt['accounting'],jev_accounting=native['accounting'],
                agreements=labels,disagreement_task_ids=disagreed,agreement_task_ids=agreeing,
                agreement_sample=dict(task_ids=agreement_sample(agreeing,study['source_run_sha256']),
                                      selection='Smallest SHA256(source_run_sha256:task_id) among full-agreement cases, up to five.',
                                      status='selected_for_source_review_not_expert_gold'),
                native_diagnostics=native['diagnostics'],native_original_statuses=native['original_statuses'],
                independence=dict(stateless=True,prior_scores_supplied=False,one_request_context_per_answer=True,
                                  gpt_response_ids=len(gpt_ids),gpt_unique_response_ids=len(set(gpt_ids)),
                                  jev_response_ids=len(native['response_ids']),jev_unique_response_ids=len(set(native['response_ids']))),
                new_analysis_api_calls=0,new_rag_calls=0,new_embedding_queries=0,rows=rows,
                limitations=['One scoring round per judge does not estimate repeatability.',
                             'Inter-judge agreement and confidence are not accuracy; no new expert gold labels.',
                             'GPT assesses more fields and writes reasons; latency is a workflow comparison.',
                             'Historical v2 scores are not matched v3 scores; the RAG answers were not improved.'])
    output.mkdir(parents=True)
    judge.write(output/'comparison.json',result)
    judge.write(output/'provenance.json',dict(api_calls=0,study_sha256=judge.digest(study_dir/'study.json'),
                gpt_aggregate_sha256=judge.digest(gpt_dir/'aggregate-run.json'),
                gpt_reviews_sha256=judge.digest(gpt_dir/'reviews.jsonl'),jev_metadata_sha256=judge.digest(jev_dir/'jev-run.json'),
                analysis_harness_sha256={name:judge.digest(Path(__file__).with_name(name)) for name in
                                        dict.fromkeys((*jev.HARNESS,'compare_qa_dual.py','compare_qa_jev.py','compare_qa_judges.py','aggregate_qa_judges.py','revalidate_qa_judge.py'))}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir','study-dir','gpt-dir','jev-dir','output-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args()
    try:
        result=analyze(args.run_dir,args.study_dir,args.gpt_dir,args.jev_dir,args.output_dir,allow_incomplete=args.allow_incomplete)
    except Exception as error:parser.exit(1,'Dual judge comparison failed: '+type(error).__name__+'\n')
    print(judge.encode({k:result[k] for k in ('complete','common_valid_tasks','disagreement_task_ids','new_analysis_api_calls')}))


if __name__=='__main__':main()
