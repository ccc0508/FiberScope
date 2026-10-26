"""Combine independently verified judge shards/retries without selecting between valid scores."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json

import judge_qa_eval as judge
from validate_qa_eval import digest,read_json,require


def aggregate(run_dir,review_dirs,output):
    run_dir,output=Path(run_dir).resolve(),Path(output).resolve()
    dirs=[Path(p).resolve() for p in review_dirs]
    require(len(set(dirs))==len(dirs) and bool(dirs),'Duplicate or empty judge components')
    require(not output.exists() and output!=run_dir and not output.is_relative_to(run_dir)
            and not any(output==p or output.is_relative_to(p) for p in dirs),'Use a new separate aggregate directory')
    run,manifest,cases,sources=judge.verify_run(run_dir)
    tasks={t['id']:t for t in run['tasks']}
    inputs={tid:judge.read_result(run_dir,run,cases[task['case_id']],task) for tid,task in tasks.items()}
    rubric=read_json(run_dir/'dataset/rubric.json')
    documents={d['id'] for d in manifest['source_documents']}
    components=[];records=[];by_hash={};settings=None;initial_tasks=set();initial_count=Counter()
    for directory in dirs:
        path=directory/'judge-run.json';metadata=read_json(path)['contract']
        require(metadata['source_run_id']==run['run_id'] and metadata['run_sha256']==digest(run_dir/'run.json')
                and metadata['dataset_manifest_sha256']==run['dataset_manifest_sha256'],'Component source mismatch')
        require(metadata['previous_scores_in_prompt'] is False,'Previous scoring judgments were exposed')
        require(metadata['prompt_sha256']==judge.hashlib.sha256(judge.prompt.SYSTEM.encode()).hexdigest(),
                'Mixed grading instructions')
        if settings is None:settings=metadata['judge']
        require({k:v for k,v in settings.items() if k!='timeout_seconds'}
                =={k:v for k,v in metadata['judge'].items() if k!='timeout_seconds'},'Mixed judge configurations')
        require(len(set(metadata['task_ids']))==len(metadata['task_ids'])
                and set(metadata['task_ids'])<=set(tasks),'Invalid component tasks')
        require(all(digest(directory/'harness'/name)==checksum for name,checksum in metadata['harness_files'].items()),
                'Archived component harness changed')
        if not metadata.get('validation_repairs') and not metadata.get('revalidated_sources'):
            initial_tasks.update(metadata['task_ids']);initial_count.update(metadata['task_ids'])
        component={'name':directory.name,'metadata_sha256':digest(path),'contract':metadata}
        components.append(component)
        for tid in metadata['task_ids']:
            record_path=directory/'tasks'/(tid+'.json');r=read_json(record_path)
            require(r['task_id']==tid and r['status']!='pending','Component is incomplete')
            require(metadata['source_result_hashes'][tid]==digest(inputs[tid][0]),'Source answer changed')
            item={'component':component,'path':record_path,'sha256':digest(record_path),'data':r}
            require(item['sha256'] not in by_hash,'Duplicate API record across components')
            by_hash[item['sha256']]=item;records.append(item)
    require(initial_tasks==set(tasks) and all(v==1 for v in initial_count.values()),
            'Every source task needs exactly one initial judge attempt')
    config=judge.Config(settings['base_url'],settings['requested_model'],'',settings['api'],
                        settings['timeout_seconds'],settings['max_output_tokens'])
    accepted={};normalizations={};origins={};unknown_usage=0;known_calls=0;calls=0
    tokens={'input_tokens':0,'output_tokens':0,'total_tokens':0}
    for item in records:
        r=item['data'];tid=r['task_id'];meta=item['component']['contract'];task=tasks[tid]
        predecessor=meta.get('validation_repairs',{}).get(tid) or meta.get('revalidated_sources',{}).get(tid)
        if predecessor:
            original=by_hash.get(predecessor['original_record_sha256'])
            require(original is not None and original['data']['task_id']==tid,'Retry source record is missing')
            require(original['component']['metadata_sha256']==predecessor['original_metadata_sha256'],
                    'Retry source metadata changed')
            require(original['data']['status'] in {'invalid_scorecard','api_failed'},'A valid grade was unnecessarily replaced')
        count=r.get('api_calls',0);calls+=count
        usage=r.get('usage')
        if count:
            if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in tokens):
                known_calls+=count
                for k in tokens:tokens[k]+=usage[k]
            else:unknown_usage+=count
        if r['status']!='completed':continue
        require(tid not in accepted,'Multiple valid grades for one answer; explicit adjudication is required')
        result_path,result=inputs[tid]
        feedback=predecessor.get('feedback') if predecessor else None
        request=judge.request_body(config,judge.packet(cases[task['case_id']],task,result,manifest,sources,rubric,feedback))
        require(judge.sha(request)==r['request_sha256'],'Grader request fingerprint mismatch')
        require(judge.sha(r['raw_response'])==r['response_sha256'],'Grader API response fingerprint mismatch')
        raw=judge.strict_json(judge.extract(r['raw_response'],config.api))
        structural=bool(meta.get('revalidated_sources'))
        if structural:
            require(count==0 and r['response_sha256']==original['data']['response_sha256'],
                    'Structural revalidation must preserve the original model output')
        review=judge.validate_review(raw,cases[task['case_id']],task,result,result_path,documents,sources,config,
                                     r['review']['judge_provenance'],normalize_structure=structural)
        review['reviewed_at']=r['review']['reviewed_at']
        require(review==r['review'],'Accepted scorecard changed')
        accepted[tid]=review
        origins[tid]={'component':item['component']['name'],'record_sha256':item['sha256']}
        if review.get('structure_normalizations'):normalizations[tid]=review['structure_normalizations']
    output.mkdir(parents=True,mode=0o700)
    (output/'harness').mkdir()
    harness=list(judge.HARNESS)+['aggregate_qa_judges.py','revalidate_qa_judge.py']
    for name in harness:(output/'harness'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    contract=dict(kind='verified_independent_judge_aggregate',source_run_id=run['run_id'],
                  source_run_sha256=digest(run_dir/'run.json'),dataset_manifest_sha256=run['dataset_manifest_sha256'],
                  judge=settings,prompt_sha256=judge.hashlib.sha256(judge.prompt.SYSTEM.encode()).hexdigest(),
                  network_timeouts_by_component={c['name']:c['contract']['judge']['timeout_seconds'] for c in components},
                  component_metadata=[{'name':c['name'],'sha256':c['metadata_sha256']} for c in components],
                  accepted_records=origins,harness_files={n:digest(output/'harness'/n) for n in harness},
                  selection_policy='Use a valid initial review; otherwise only its explicit retry or structural revalidation. Never choose between valid grades.')
    judge.write(output/'aggregate-run.json',dict(created_at=judge.now(),contract=contract))
    ordered=[accepted[tid] for tid in tasks if tid in accepted]
    reviews_path=output/'reviews.jsonl'
    reviews_path.write_text(''.join(judge.encode(r)+'\n' for r in ordered),encoding='utf-8',newline='\n')
    concerns={tid:r['reference_concerns'] for tid,r in accepted.items() if r['reference_concerns']}
    progress=dict(source_run_id=run['run_id'],selected_tasks=len(tasks),valid_reviews=len(accepted),
                  unresolved_tasks=[tid for tid in tasks if tid not in accepted],reference_concerns=concerns,
                  grader_application_calls=calls,usage_known_calls=known_calls,usage_unknown_calls=unknown_usage,
                  known_grader_tokens=tokens if known_calls else None,actual_charge=None,
                  charge_note='Known tokens include rejected and retried requests. Timed-out upstream usage and billed amount are unknown.',
                  initial_statuses=dict(Counter(item['data']['status'] for item in records
                                                if not item['component']['contract'].get('validation_repairs')
                                                and not item['component']['contract'].get('revalidated_sources'))),
                  structure_normalizations=normalizations,summary_written=False)
    if len(accepted)==len(tasks) and not concerns:
        summary=judge.summarize(run_dir,reviews_path)
        progress['summary_written']=True
        summary['independent_judge_aggregate']=dict(metadata_sha256=digest(output/'aggregate-run.json'),**progress)
        judge.write(output/'summary.json',summary)
    judge.write(output/'progress.json',progress)
    return progress


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--review-dir',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try:result=aggregate(args.run_dir,args.review_dir,args.output_dir)
    except Exception as error:parser.exit(1,'Judge aggregation failed: '+type(error).__name__+'\n')
    print(json.dumps(result,ensure_ascii=False))
    if not result['summary_written']:parser.exit(2)


if __name__=='__main__':main()
