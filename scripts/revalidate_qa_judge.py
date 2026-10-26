"""Revalidate rejected API scorecards with deterministic structural normalization; no provider calls."""
from __future__ import annotations

import argparse
from pathlib import Path
import json

import judge_qa_eval as judge
from score_qa_eval_v2 import retrieval_scalar
from validate_qa_eval import digest,read_json,require


def revalidate(run_dir,records,output):
    run_dir,output=Path(run_dir).resolve(),Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(run_dir),'Use a new separate revalidation directory')
    run,manifest,cases,sources=judge.verify_run(run_dir)
    tasks={t['id']:t for t in run['tasks']}
    assembled=[];sources_by_task={};settings=None;protocol=None
    rubric=read_json(run_dir/'dataset/rubric.json')
    for path in map(Path,records):
        original=read_json(path);tid=original['task_id']
        require(tid in tasks and tid not in sources_by_task,'Unknown or duplicate revalidation task')
        require(original['status']=='invalid_scorecard','Only rejected API scorecards may be structurally revalidated')
        metadata_path=path.parent.parent/'judge-run.json'
        meta=read_json(metadata_path)['contract']
        require(meta['run_sha256']==digest(run_dir/'run.json') and meta['source_run_id']==run['run_id'],
                'Source answer run changed')
        component_protocol=judge.grading_prompt(meta['contract_version'])
        if protocol is None:protocol=component_protocol
        require(component_protocol.VERSION==protocol.VERSION,'Mixed scoring policy versions')
        require(meta['prompt_sha256']==judge.hashlib.sha256(protocol.SYSTEM.encode()).hexdigest(),
                'Source grading instructions changed')
        if settings is None:settings=meta['judge']
        require(settings==meta['judge'],'Mixed judge configurations')
        config=judge.Config(settings['base_url'],settings['requested_model'],'',settings['api'],
                            settings['timeout_seconds'],settings['max_output_tokens'])
        task=tasks[tid];case=cases[task['case_id']]
        result_path,result=judge.read_result(run_dir,run,case,task)
        feedback=meta.get('validation_repairs',{}).get(tid,{}).get('feedback')
        request=judge.request_body(config,judge.packet(case,task,result,manifest,sources,rubric,feedback,
                                                      prompt_version=protocol.VERSION))
        require(judge.sha(request)==original['request_sha256'],'Original grader request changed')
        body=original['raw_response']
        require(judge.sha(body)==original['response_sha256'],'Original API response changed')
        raw=judge.strict_json(judge.extract(body,settings['api']))
        provenance=dict(contract_version=protocol.VERSION,requested_model=settings['requested_model'],
                        returned_model=body.get('model'),base_url=settings['base_url'],api=settings['api'],
                        request_sha256=original['request_sha256'],response_sha256=original['response_sha256'],
                        prompt_sha256=meta['prompt_sha256'],provider_response_id=body.get('id'),
                        provider_request_id=original.get('provider_request_id'),
                        structural_revalidation_of_sha256=digest(path),reference_concerns_unresolved=bool(raw.get('reference_concerns')))
        review=judge.validate_review(raw,case,task,result,result_path,
                                     {d['id'] for d in manifest['source_documents']},sources,config,provenance,
                                     normalize_structure=True)
        require(bool(review.get('structure_normalizations')),'No structural normalization was needed; inspect original rejection')
        review['reviewed_at']=original['finished_at']
        # The model-authored judgments, free text, and quotations are immutable.
        require(all(review[k]==value for k,value in raw.items()
                    if k not in {'defects','retrieval_point_assessments'}),'Semantic score fields changed')
        before=raw['retrieval_point_assessments'];after=review['retrieval_point_assessments']
        require(set(before)==set(after) and all(after[k]==v or (retrieval_scalar(v) is not None
                and retrieval_scalar(v)[0]==after[k]) for k,v in before.items()),'Selected retrieval labels changed')
        require([d['description'] for d in review['defects']]==[d['description'] for d in raw['defects']],
                'Defect descriptions changed')
        sources_by_task[tid]=dict(original_record_sha256=digest(path),original_metadata_sha256=digest(metadata_path),
                                  original_review_run=path.parent.parent.name,feedback=feedback)
        assembled.append((tid,dict(task_id=tid,status='completed',api_calls=0,usage=None,
                                  source_record_sha256=digest(path),raw_response=body,
                                  response_sha256=original['response_sha256'],request_sha256=original['request_sha256'],review=review)))
    require(bool(assembled),'No revalidation records selected')
    output.mkdir(parents=True,mode=0o700)
    (output/'tasks').mkdir();(output/'harness').mkdir()
    harness=list(judge.HARNESS)+['revalidate_qa_judge.py']
    for name in harness:
        (output/'harness'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    judge.write(output/'judge-run.json',dict(created_at=judge.now(),contract=dict(
        contract_version=protocol.VERSION,assessment_mode='structural_revalidation_without_provider_calls',
        source_run_id=run['run_id'],run_sha256=digest(run_dir/'run.json'),
        dataset_manifest_sha256=run['dataset_manifest_sha256'],judge=settings,
        task_ids=[tid for tid,_ in assembled],
        source_result_hashes={tid:digest(run_dir/'results'/(tid+'.json')) for tid,_ in assembled},
        prompt_sha256=judge.hashlib.sha256(protocol.SYSTEM.encode()).hexdigest(),
        harness_files={name:digest(output/'harness'/name) for name in harness},
        revalidated_sources=sources_by_task,previous_scores_in_prompt=False,provider_calls=0,
        normalization_policy='Fill missing diagnostic IDs; repair only a unique one-to-one diagnostic link; '
                             'split an explicit retrieval enum and colon-delimited explanation, preserving both; '
                             'never infer or change selected labels, scores, rationale or source quotes.')))
    for tid,record in assembled:judge.write(output/'tasks'/(tid+'.json'),record)
    (output/'reviews.jsonl').write_text(''.join(judge.encode(record['review'])+'\n' for _,record in assembled),encoding='utf-8',newline='\n')
    progress=dict(completed=len(assembled),provider_calls=0,semantic_scores_changed=False,
                  normalizations={tid:record['review']['structure_normalizations'] for tid,record in assembled})
    judge.write(output/'progress.json',progress)
    return progress


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--record',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try:result=revalidate(args.run_dir,args.record,args.output_dir)
    except Exception as error:parser.exit(1,'Structural revalidation failed: '+type(error).__name__+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
