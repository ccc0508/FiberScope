"""Measure repeatability of independent judge ratings on immutable saved answers; no provider calls."""
from __future__ import annotations

import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory

from aggregate_qa_judges import aggregate
import judge_qa_eval as judge
from score_qa_eval_v2 import review_task
from validate_qa_eval import digest,read_json,read_jsonl,require


def fraction(n,d):
    return dict(numerator=n,denominator=d,value=n/d if d else None)


def quadratic_kappa(left,right):
    require(len(left)==len(right),'Kappa vectors differ in length')
    if not left:return None
    values=(0,.5,1)
    require(all(type(v) in (int,float) and v in values for v in [*left,*right]),'Invalid ordinal point score')
    n=len(left);a=Counter(left);b=Counter(right)
    observed=sum((x-y)**2 for x,y in zip(left,right))/n
    expected=sum((x-y)**2*a[x]*b[y]/(n*n) for x in values for y in values)
    return 1-observed/expected if expected else None


def pair_numbers(left,right,ordinal=True):
    keys=sorted(set(left)&set(right))
    differences=[abs(left[k]-right[k]) for k in keys]
    return dict(exact_agreement=fraction(sum(left[k]==right[k] for k in keys),len(keys)),
                mean_absolute_difference=statistics.mean(differences) if differences else None,
                max_absolute_difference=max(differences) if differences else None,
                weighted_kappa_quadratic=quadratic_kappa([left[k] for k in keys],[right[k] for k in keys]) if ordinal else None)


def analyze_rounds(cases,tasks,rounds):
    require(len(rounds)>=2,'At least two grading rounds are required')
    required=[(t['id'],p['id']) for t in tasks for p in cases[t['case_id']]['key_points']
              if not p['optional'] and p['capability'] in t['capabilities']]
    points=[];rows=[];reviews=[];raw_points=[];initial_complete_questions=[]
    for item in rounds:
        by_review={r['task_id']:r for r in item['reviews']}
        require(set(by_review)=={t['id'] for t in tasks},'Every round must rate the same complete task set')
        reviews.append(by_review);rows.append({r['task_id']:r for r in item['summary']['rows']})
        vector={key:by_review[key[0]]['key_point_scores'][key[1]] for key in required}
        require(all(type(v) in (int,float) and v in (0,.5,1) for v in vector.values()),'Missing final required-point score')
        points.append(vector)
        raw={}
        for tid,record in item.get('initial',{}).items():
            try:body=judge.strict_json(judge.extract(record['raw_response'],item['api']))
            except (ValueError,KeyError,TypeError,IndexError):continue
            if not isinstance(body,dict):continue
            scores=body.get('key_point_scores',{})
            if not isinstance(scores,dict):continue
            for key in required:
                if key[0]==tid and type(scores.get(key[1])) in (int,float) and scores[key[1]] in (0,.5,1):
                    raw[key]=scores[key[1]]
        raw_points.append(raw)
        initial_complete_questions.append({t['id'] for t in tasks
                                           if all(key in raw for key in required if key[0]==t['id'])})
    pairs=[]
    for a,b in itertools.combinations(range(len(rounds)),2):
        tids=[t['id'] for t in tasks]
        item=dict(rounds=[rounds[a]['name'],rounds[b]['name']],required_points=pair_numbers(points[a],points[b]),
                  question_means=pair_numbers({tid:rows[a][tid]['point_mean'] for tid in tids},
                                             {tid:rows[b][tid]['point_mean'] for tid in tids},ordinal=False),
                  strict_pass_agreement=fraction(sum(rows[a][tid]['strict_pass']==rows[b][tid]['strict_pass'] for tid in tids),len(tids)),
                  critical_presence_agreement=fraction(sum(bool(rows[a][tid]['critical_errors'])==bool(rows[b][tid]['critical_errors']) for tid in tids),len(tids)),
                  boundary_score_agreement=fraction(sum(reviews[a][tid]['answerability_score']==reviews[b][tid]['answerability_score'] for tid in tids),len(tids)),
                  initial_numeric_points=pair_numbers(raw_points[a],raw_points[b]))
        ca={(tid,c['id']):c for tid,r in reviews[a].items() for c in r['claim_assessments']}
        cb={(tid,c['id']):c for tid,r in reviews[b].items() for c in r['claim_assessments']}
        require(set(ca)==set(cb),'Claim identity changed between rating rounds')
        item['claim_support_agreement']=fraction(sum(ca[k]['support']==cb[k]['support'] for k in ca),len(ca))
        item['fact_scope_agreement']=fraction(sum(ca[k]['claim_type']==cb[k]['claim_type'] for k in ca),len(ca))
        pa={(tid,c['claim_id'],c['ref']):c['score'] for tid,r in reviews[a].items() for c in r['citation_assessments']}
        pb={(tid,c['claim_id'],c['ref']):c['score'] for tid,r in reviews[b].items() for c in r['citation_assessments']}
        require(set(pa)==set(pb),'Citation identity changed between rating rounds')
        both=[k for k in pa if pa[k] is not None and pb[k] is not None]
        item['common_fact_citation_agreement']=fraction(sum(pa[k]==pb[k] for k in both),len(both))
        item['citation_applicability_flips']=sum((pa[k] is None)!=(pb[k] is None) for k in pa)
        pairs.append(item)
    questions=[]
    for task in tasks:
        tid=task['id'];means=[r[tid]['point_mean'] for r in rows];strict=[r[tid]['strict_pass'] for r in rows]
        critical=[bool(r[tid]['critical_errors']) for r in rows]
        patterns=[tuple(vector[key] for key in required if key[0]==tid) for vector in points]
        questions.append(dict(task_id=tid,case_id=task['case_id'],question=cases[task['case_id']]['question'],
                              point_means=means,score_range=max(means)-min(means),score_stdev_sample=statistics.stdev(means),
                              point_pattern_changed=len(set(patterns))>1,strict_pass=strict,strict_pass_flip=len(set(strict))>1,
                              critical_presence=critical,critical_presence_flip=len(set(critical))>1,
                              boundary_scores=[r[tid]['answerability_score'] for r in reviews]))
    common_raw_questions=set.intersection(*initial_complete_questions)
    raw_common_means=[]
    for vector in raw_points:
        means=[statistics.mean(vector[key] for key in required if key[0]==tid) for tid in sorted(common_raw_questions)]
        raw_common_means.append(statistics.mean(means) if means else None)
    macros=[statistics.mean(r[t['id']]['point_mean'] for t in tasks) for r in rows]
    return dict(round_count=len(rounds),task_count=len(tasks),required_points=len(required),
                round_scores=[dict(name=item['name'],point_macro_average=macros[i],
                                   strict_pass=sum(r['strict_pass'] for r in rows[i].values()),
                                   critical_cases=sum(bool(r['critical_errors']) for r in rows[i].values()),
                                   initial_numeric_complete_tasks=len(initial_complete_questions[i]),
                                   reference_concerns={tid:r.get('reference_concerns',[]) for tid,r in reviews[i].items() if r.get('reference_concerns')})
                              for i,item in enumerate(rounds)],
                overall=dict(macro_mean=statistics.mean(macros),macro_stdev_sample=statistics.stdev(macros),
                             macro_range=max(macros)-min(macros),
                             all_rounds_identical_points=fraction(sum(len({v[key] for v in points})==1 for key in required),len(required)),
                             strict_pass_flip_tasks=[q['task_id'] for q in questions if q['strict_pass_flip']],
                             strict_pass_flip_rate=sum(q['strict_pass_flip'] for q in questions)/len(questions),
                             critical_presence_flip_tasks=[q['task_id'] for q in questions if q['critical_presence_flip']]),
                raw_initial=dict(note='Initial numeric outputs can fail source or formatting checks; never interpret missing/invalid values as zero.',
                                 common_complete_task_ids=sorted(common_raw_questions),
                                 aligned_initial_macro_averages=raw_common_means),
                pairs=pairs,questions=questions)


def select_comparable_tasks(tasks,rounds,allow_incomplete=False):
    expected={t['id'] for t in tasks}
    available=[{r['task_id'] for r in item['reviews'] if not r.get('reference_concerns')} for item in rounds]
    common=set.intersection(*available)
    require(all(s<=expected for s in available),'Unknown task in grading round')
    require(allow_incomplete or all(s==expected for s in available),'A grading round is incomplete or has reference concerns')
    require(bool(common),'No common validated tasks are available')
    filtered=[]
    for item in rounds:
        filtered.append({**item,'reviews':[r for r in item['reviews'] if r['task_id'] in common],
                         'summary':{'rows':[r for r in item['summary']['rows'] if r['task_id'] in common]}})
    coverage=dict(planned_tasks=len(tasks),common_validated_tasks=len(common),
                  common_task_ids=sorted(common),excluded_task_ids=sorted(expected-common),
                  validated_tasks_by_round={item['name']:len(available[i]) for i,item in enumerate(rounds)},
                  missing_or_disputed_by_round={item['name']:sorted(expected-available[i]) for i,item in enumerate(rounds)},
                  full_comparison=common==expected,
                  note='Subset means are conditional on common validated tasks; excluded tasks are unknown, never zero.')
    return [t for t in tasks if t['id'] in common],filtered,coverage


def audit_study(study,run_dir,review_dirs,allow_incomplete=False):
    run,manifest,cases,sources=judge.verify_run(run_dir)
    require(digest(run_dir/'run.json')==study['source_run_sha256'],'The fixed answer run changed')
    require(study['stateless'] is True and study['previous_scores_supplied'] is False
            and study['previous_response_id_used'] is False and study['conversation_id_used'] is False,
            'The study did not guarantee independent stateless requests')
    for task in run['tasks']:
        path,_=judge.read_result(run_dir,run,cases[task['case_id']],task)
        require(digest(path)==study['source_answer_sha256'][task['id']],'A fixed candidate answer changed')
    rounds=[];returned_ids={};duplicates=[];initial_statuses={}
    for index,directory in enumerate(review_dirs):
        directory=Path(directory)
        metadata_path=directory/('aggregate-run.json' if (directory/'aggregate-run.json').exists() else 'judge-run.json')
        meta=read_json(metadata_path)['contract']
        if index==0:
            require(digest(metadata_path)==study['reference_aggregate_sha256']
                    and digest(directory/'reviews.jsonl')==study['reference_reviews_sha256']
                    and digest(directory/'summary.json')==study['reference_summary_sha256'],'The original rating round changed')
        require(meta.get('source_run_id')==run['run_id'] and meta['dataset_manifest_sha256']==run['dataset_manifest_sha256'],
                'Grading rounds refer to different answers or datasets')
        require(meta['prompt_sha256']==study['prompt_sha256'],'Grading instructions changed')
        require({k:v for k,v in meta['judge'].items() if k!='timeout_seconds'}
                =={k:v for k,v in study['judge'].items() if k!='timeout_seconds'},'Grading model or parameters changed')
        reviews=read_jsonl(directory/'reviews.jsonl')
        for review in reviews:
            require(review['response_file_sha256']==study['source_answer_sha256'][review['task_id']],
                    'A candidate answer changed between rating rounds')
        if allow_incomplete:
            task_by_id={t['id']:t for t in run['tasks']};rows=[]
            documents={d['id'] for d in manifest['source_documents']}
            for review in reviews:
                task=task_by_id[review['task_id']];path,result=judge.read_result(run_dir,run,cases[task['case_id']],task)
                rows.append(review_task(cases[task['case_id']],task,result,review,path,documents,sources))
            summary={'rows':rows}
        else:summary=judge.summarize(run_dir,directory/'reviews.jsonl')
        component_dirs=[run_dir.parent/c['name'] for c in meta['component_metadata']] if 'component_metadata' in meta else [directory]
        initial={};initial_components=[]
        for component in component_dirs:
            contract=read_json(component/'judge-run.json')['contract']
            if contract.get('validation_repairs') or contract.get('revalidated_sources'):continue
            initial_components.append(component.name)
            require(contract['previous_scores_in_prompt'] is False,'Earlier scores leaked into a new round')
            for tid in contract['task_ids']:
                require(tid not in initial,'Duplicate initial rating in a round')
                path=component/'tasks'/(tid+'.json');record=read_json(path)
                require(record['request_sha256']==study['initial_request_sha256'][tid],'Initial rating context changed')
                if index==0:require(digest(path)==study['reference_initial_record_sha256'][tid],'Original initial rating changed')
                initial[tid]=record
                rid=record.get('provider_response_id') or (record.get('raw_response') or {}).get('id')
                if rid:
                    if rid in returned_ids:duplicates.append(dict(response_id=rid,first=returned_ids[rid],again=[directory.name,tid]))
                    else:returned_ids[rid]=[directory.name,tid]
        require(set(initial)=={t['id'] for t in run['tasks']},'Initial rating task coverage differs')
        if index:
            require(initial_components==[study['additional_initial_rounds'][index-1]],'A new round reused another round component')
        # Revalidate API outputs and retry lineage, rather than trusting a mutable summary copy.
        with TemporaryDirectory(prefix='qa-judge-repeatability-') as temporary:
            checked=Path(temporary)/'verified'
            progress=aggregate(run_dir,component_dirs,checked)
            require(allow_incomplete or progress['summary_written'],'A grading round is incomplete or has reference concerns')
            require(read_jsonl(checked/'reviews.jsonl')==reviews,'Published grades differ from verified API outputs')
            if 'component_metadata' in meta:
                require(all(digest(component/'judge-run.json')==c['sha256']
                            for component,c in zip(component_dirs,meta['component_metadata'])),
                        'A grading component fingerprint changed')
        initial_statuses[directory.name]=dict(Counter(r['status'] for r in initial.values()))
        rounds.append(dict(name=directory.name,reviews=reviews,summary=summary,initial=initial,api=meta['judge']['api']))
    tasks,comparable,coverage=select_comparable_tasks(run['tasks'],rounds,allow_incomplete)
    analysis=analyze_rounds(cases,tasks,comparable)
    analysis['coverage']=coverage
    analysis['available_pairs']=[]
    for a,b in itertools.combinations(range(len(rounds)),2):
        paired_tasks,paired,_=select_comparable_tasks(run['tasks'],[rounds[a],rounds[b]],allow_incomplete=True)
        result=analyze_rounds(cases,paired_tasks,paired)
        analysis['available_pairs'].append(dict(task_count=len(paired_tasks),required_points=result['required_points'],
                                                metrics=result['pairs'][0],
                                                strict_pass_flip_tasks=result['overall']['strict_pass_flip_tasks'],
                                                critical_presence_flip_tasks=result['overall']['critical_presence_flip_tasks']))
    analysis['raw_initial']['scope']='Common validated task subset, not all planned tasks' if not coverage['full_comparison'] else 'All planned tasks'
    analysis['independence_audit']=dict(fixed_answers=len(run['tasks']),identical_initial_payloads_per_round=len(run['tasks']),
                                        stateless=True,prior_grades_exposed=False,new_rag_answer_calls=0,new_embedding_queries=0,
                                        unique_returned_initial_response_ids=len(returned_ids),reused_response_ids=duplicates,
                                        initial_statuses=initial_statuses)
    return analysis


def compare(study_dir,run_dir,review_dirs,output,allow_incomplete=False):
    study_dir,run_dir,output=map(Path,(study_dir,run_dir,output))
    require(len(review_dirs)==3 and len({Path(p).resolve() for p in review_dirs})==3,'Exactly three distinct rating rounds are required')
    require(not output.exists(),'Use a new comparison file')
    study=read_json(study_dir/'study.json')
    require(all(digest(study_dir/'harness'/name)==checksum for name,checksum in study.get('harness_files',{}).items()),
            'The frozen study harness changed')
    result=audit_study(study,run_dir,review_dirs,allow_incomplete)
    result['study_sha256']=digest(study_dir/'study.json')
    result['scope']='Independent judge repeatability on fixed RAG answers; not RAG-generation stability or scientific correctness.'
    output.parent.mkdir(parents=True,exist_ok=True)
    judge.write(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study-dir',type=Path,required=True)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--review-dir',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-incomplete',action='store_true',help='Explicitly compare only common validated tasks, with missingness reported; never publish a full-run mean')
    args=p.parse_args()
    try:result=compare(args.study_dir,args.run_dir,args.review_dir,args.output,args.allow_incomplete)
    except Exception as error:p.exit(1,'Judge stability analysis failed: '+type(error).__name__+'\n')
    print(json.dumps({'round_scores':result['round_scores'],'overall':result['overall']},ensure_ascii=False))


if __name__=='__main__':main()
