"""Audit three saved Jev rounds and compare shared dimensions with historical GPT reviews; no API calls."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from decimal import Decimal
import itertools
import math
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory

import aggregate_qa_judges as aggregate_gpt
import compare_qa_judges as repeatability
import judge_qa_eval as judge
import judge_qa_jev as jev
import qa_jev_prompt as prompt
import qa_scoring_policy as policy


def accounting(records,native=True,*,openrouter_chat=False):
    calls=[r for r in records if r.get('api_calls',0)]
    tokens={key:sum((r.get('usage') or {}).get(key) or 0 for r in calls) for key in ['input_tokens','output_tokens','total_tokens']}
    known=sum(all(type((r.get('usage') or {}).get(key)) is int for key in tokens) for r in calls)
    if openrouter_chat:
        reported=[((r.get('raw_response') or {}).get('usage') or {}).get('cost') for r in calls]
        reported=[c if type(c) in (int,float) and math.isfinite(c) and c>=0 else None for c in reported]
    else:
        reported=[(r.get('usage') or {}).get('reported_cost_usd') for r in calls] if native else []
    cost_available=native or openrouter_chat
    by_task=defaultdict(int)
    for r in calls:
        if type(r.get('duration_ms')) is int:by_task[r['task_id']]+=r['duration_ms']
    times=sorted(by_task.values())
    return dict(application_calls=sum(r['api_calls'] for r in calls),usage_known_calls=known,usage_unknown_calls=len(calls)-known,
                known_tokens=tokens,reported_cost_usd=str(sum((Decimal(str(c)) for c in reported if c is not None),Decimal(0))) if cost_available else None,
                cost_unknown_calls=sum(c is None for c in reported) if cost_available else len(calls),actual_invoice_cost=None,
                summed_request_time_ms=sum(times),median_task_request_time_ms=statistics.median(times) if times else None,
                p95_task_request_time_ms=times[math.ceil(.95*len(times))-1] if times else None)


def compare_labels(left,right,tasks,cases):
    grading_policy=policy.require_same_policy([*left.values(),*right.values()])
    tids=[t['id'] for t in tasks if t['id'] in left and t['id'] in right]
    vectors=[]
    for table in [left,right]:
        vectors.append({(t['id'],p['id']):table[t['id']]['key_point_scores'][p['id']]
                        for t in tasks if t['id'] in tids for p in cases[t['case_id']]['key_points']
                        if not p['optional'] and p['capability'] in t['capabilities']})
    claims=[{(tid,c['id']):c for tid in tids for c in table[tid]['claim_assessments']} for table in [left,right]]
    judge.require(set(claims[0])==set(claims[1]),'Compared claim identities differ')
    pairs=[{(tid,c['claim_id'],c['ref']):c['score'] for tid in tids for c in table[tid]['citation_assessments']} for table in [left,right]]
    judge.require(set(pairs[0])==set(pairs[1]),'Compared citation identities differ')
    common_facts=[key for key in pairs[0] if pairs[0][key] is not None and pairs[1][key] is not None]
    result=dict(compared_tasks=len(tids),task_ids=tids,required_points=repeatability.pair_numbers(*vectors),
                claim_support_agreement=repeatability.fraction(sum(claims[0][k]['support']==claims[1][k]['support'] for k in claims[0]),len(claims[0])),
                claim_type_agreement=repeatability.fraction(sum(claims[0][k]['claim_type']==claims[1][k]['claim_type'] for k in claims[0]),len(claims[0])),
                citation_score_agreement=repeatability.fraction(sum(pairs[0][k]==pairs[1][k] for k in common_facts),len(common_facts)),
                citation_applicability_flips=sum((pairs[0][k] is None)!=(pairs[1][k] is None) for k in pairs[0]),
                point_pattern_changed_tasks=[tid for tid in tids if any(vectors[0][key]!=vectors[1][key] for key in vectors[0] if key[0]==tid)])
    if grading_policy==policy.VERSION:
        groups=[{(tid,g['claim_id']):g['coverage'] for tid in tids for g in table[tid]['citation_group_assessments']}
                for table in [left,right]]
        judge.require(set(groups[0])==set(groups[1]),'Compared citation group identities differ')
        common=[k for k in groups[0] if groups[0][k] is not None and groups[1][k] is not None]
        result.update(scoring_policy_version=policy.VERSION,
                      citation_group_coverage_agreement=repeatability.fraction(sum(groups[0][k]==groups[1][k] for k in common),len(common)))
    extended=[tid for tid in tids if all('answerability_score' in table[tid]
              and 'retrieval_point_assessments' in table[tid] for table in (left,right))]
    if extended:
        judge.require(len(extended)==len(tids),'Mixed assessment scopes in comparison')
        boundary=[{tid:table[tid]['answerability_score'] for tid in extended} for table in (left,right)]
        retrieval=[{(tid,pid):value for tid in extended for pid,value in table[tid]['retrieval_point_assessments'].items()}
                   for table in (left,right)]
        judge.require(set(retrieval[0])==set(retrieval[1]),'Compared retrieval point identities differ')
        judge.require(all((retrieval[0][k]=='not_applicable')==(retrieval[1][k]=='not_applicable') for k in retrieval[0]),
                      'Compared retrieval applicability differs')
        applicable=[k for k in retrieval[0] if retrieval[0][k]!='not_applicable']
        result.update(assessment_scope='six_dimensions',boundary=repeatability.pair_numbers(*boundary),
                      retrieval_support_agreement=repeatability.fraction(sum(retrieval[0][k]==retrieval[1][k] for k in applicable),len(applicable)),
                      retrieval_not_applicable_points=len(retrieval[0])-len(applicable))
    else:
        result.update(assessment_scope='four_shared_dimensions',
                      unavailable_comparison_dimensions=['answerability','retrieval_support'])
    return result


def audit_jev(source,directory,study,cases,tasks,sources,manifest):
    metadata=judge.read_json(directory/'jev-run.json');contract=metadata['contract']
    judge.require(contract['source_run_sha256']==study['source_run_sha256'] and contract['source_result_hashes']==study['source_answer_sha256'],
                  'Jev source answer identity changed')
    judge.require(contract['request_sha256']==study['request_sha256'] and contract['judge']==study['judge'],'Jev inputs/configuration changed')
    judge.require(contract['harness_files']==study['harness_files'],'Original Jev harness contract changed')
    judge.require(all(judge.digest(directory/'harness'/n)==h for n,h in contract['harness_files'].items()),'Archived Jev harness changed')
    config=jev.Config(contract['judge']['base_url'],contract['judge']['requested_model'],'',contract['judge']['timeout_seconds'])
    rubric=judge.read_json(source/'dataset/rubric.json');run=judge.read_json(source/'run.json')
    records=[];reviews={};diagnostics={};response_ids=[];payload_sizes=[]
    for task in tasks:
        tid=task['id'];record_path=directory/'tasks'/(tid+'.json')
        if not record_path.exists():continue
        record=judge.read_json(record_path);records.append(record)
        judge.require(record['task_id']==tid and record['request_sha256']==study['request_sha256'][tid],'Jev task record changed')
        path,result=judge.read_result(source,run,cases[task['case_id']],task)
        judge.require(judge.digest(path)==study['source_answer_sha256'][tid],'Fixed answer changed')
        request,targets=prompt.build_request(config,cases[task['case_id']],task,result,manifest,sources,rubric,
                                              prompt_version=contract['contract_version'])
        judge.require(judge.sha(request)==record['request_sha256'] and judge.read_json(directory/'requests'/(tid+'.json'))==request,
                      'Reconstructed Jev request differs')
        judge.require(set(request)=={'state','model','questions','provider'},'Unexpected conversational/request fields')
        payload_sizes.append(len(judge.encode(request).encode('utf-8')))
        body=record.get('raw_response')
        if body is None:continue
        judge.require(judge.sha(body)==record['response_sha256'],'Original Jev API response changed')
        judge.require(jev.usage(body)==record['usage'],'Saved Jev usage changed')
        if body.get('id'):response_ids.append(body['id'])
        try:review=jev.decode_review(body,request,targets,cases[task['case_id']],task,result,path,sources,allow_auxiliary_inconsistency=True)
        except (ValueError,KeyError,TypeError,IndexError) as error:
            diagnostics[tid]=[dict(kind='unusable_native_response',error_type=type(error).__name__)];continue
        if record['status']=='completed':
            canonical_without_notes={k:v for k,v in review.items() if k!='native_output_diagnostics'}
            judge.require(canonical_without_notes==record['review'],'Originally valid Jev judgments changed')
        reviews[tid]=review
        if review['native_output_diagnostics']:diagnostics[tid]=review['native_output_diagnostics']
    rows=[jev.metrics(cases[t['case_id']],t,reviews[t['id']]) for t in tasks if t['id'] in reviews]
    return dict(name=directory.name,metadata_sha256=judge.digest(directory/'jev-run.json'),reviews=reviews,rows=rows,records=records,
                response_ids=response_ids,diagnostics=diagnostics,original_statuses=dict(Counter(r['status'] for r in records)),
                request_bytes_min=min(payload_sizes) if payload_sizes else None,request_bytes_max=max(payload_sizes) if payload_sizes else None,
                accounting=accounting(records),models=sorted({r['raw_response']['model'] for r in records if r.get('raw_response')}))


def audit_gpt(source,directory):
    meta=judge.read_json(directory/'aggregate-run.json')['contract']
    components=[source.parent/c['name'] for c in meta['component_metadata']]
    with TemporaryDirectory(prefix='jev-gpt-source-audit-') as temporary:
        checked=Path(temporary)/'verified'
        aggregate_gpt.aggregate(source,components,checked)
        reviews=judge.read_jsonl(directory/'reviews.jsonl')
        judge.require(reviews==judge.read_jsonl(checked/'reviews.jsonl'),'Historical GPT scores changed')
    records=[]
    for component in components:records.extend(judge.read_json(p) for p in sorted((component/'tasks').glob('*.json')))
    projected={}
    for review in reviews:
        if review.get('reference_concerns'):continue
        row=judge.deepcopy(review)
        for claim in row['claim_assessments']:claim['evidence_location_status']='verified_original_gpt_source_basis'
        projected[row['task_id']]=row
    router=(meta['judge']['base_url']=='https://openrouter.ai/api/v1'
            and meta['judge']['api']=='chat_completions')
    return dict(name=directory.name,reviews=projected,accounting=accounting(records,native=False,openrouter_chat=router))


def summarize_rows(name,table,tasks,cases,common):
    rows=[jev.metrics(cases[t['case_id']],t,table[t['id']]) for t in tasks if t['id'] in common]
    summary=dict(name=name,task_count=len(rows),point_macro_average=statistics.mean(r['point_mean'] for r in rows) if rows else None,
                shared_dimensions_pass=sum(r['shared_dimensions_pass'] for r in rows),
                citation_support=repeatability.fraction(sum(r['supported_citation_count'] for r in rows),sum(r['factual_citation_count'] for r in rows)),
                citation_coverage=repeatability.fraction(sum(r['covered_factual_claims'] for r in rows),sum(r['factual_claim_count'] for r in rows)))
    extended=[r for r in rows if 'answerability_score' in r]
    judge.require(not extended or len(extended)==len(rows),'Mixed assessment scopes in summary')
    if extended:
        summary.update(answerability_mean=statistics.mean(r['answerability_score'] for r in extended),
                       boundary_aware_pass=sum(r['boundary_aware_pass'] for r in extended),
                       retrieval_counts={k:sum(r['retrieval_counts'][k] for r in extended) for k in prompt.RETRIEVAL_LABELS},
                       retrieval_applicable_points=sum(r['retrieval_applicable_points'] for r in extended))
    return summary


def analyze(source,study_dir,jev_dirs,gpt_dirs,output):
    source,study_dir,output=map(Path,(source,study_dir,output))
    judge.require(len(jev_dirs)==3 and len(set(map(str,jev_dirs)))==3,'Three distinct Jev rounds required')
    judge.require(len(gpt_dirs)==3 and len(set(map(str,gpt_dirs)))==3,'Three distinct historical GPT rounds required')
    judge.require(not output.exists(),'Use a new offline comparison directory')
    study=judge.read_json(study_dir/'study.json')
    judge.require(study['stateless'] is True and study['previous_scores_supplied'] is False and study['conversation_identifiers_used'] is False,
                  'Independent Jev context was not guaranteed')
    judge.require([Path(d).name for d in jev_dirs]==study['round_names'],'Unexpected Jev round ordering')
    run,manifest,cases,sources=judge.verify_run(source);tasks=run['tasks']
    judge.require(judge.digest(source/'run.json')==study['source_run_sha256'],'Source run changed')
    rounds=[audit_jev(source,Path(d),study,cases,tasks,sources,manifest) for d in jev_dirs]
    models=sorted({m for r in rounds for m in r['models']})
    judge.require(len(models)==1,'Actual Jev model versions differ; do not merge')
    common=set.intersection(*[set(r['reviews']) for r in rounds]);judge.require(bool(common),'No common Jev grades')
    within=[]
    for a,b in itertools.combinations(range(3),2):
        item=compare_labels(rounds[a]['reviews'],rounds[b]['reviews'],tasks,cases);item['rounds']=[a+1,b+1];within.append(item)
    historical=[audit_gpt(source,Path(d)) for d in gpt_dirs]
    shared=set.intersection(*[set(r['reviews']) for r in [*rounds,*historical]])
    side_by_side=[summarize_rows(r['name'],r['reviews'],tasks,cases,shared) for r in [*historical,*rounds]]
    cross=[]
    for g in historical:
        for j in rounds:
            item=compare_labels(g['reviews'],j['reviews'],tasks,cases);item.update(gpt=g['name'],jev=j['name']);cross.append(item)
    ids=[rid for r in rounds for rid in r['response_ids']]
    aggregate_cost=sum((Decimal(r['accounting']['reported_cost_usd']) for r in rounds),Decimal(0))
    all_tasks={t['id'] for t in tasks}
    result=dict(scope='Typed shared-dimension judgments; agreement with GPT is not domain accuracy.',
                planned_tasks=len(tasks),canonical_valid_tasks=[len(r['reviews']) for r in rounds],
                canonical_common_tasks=len(common),canonical_missing_tasks=sorted(all_tasks-common),
                model=models[0],study_sha256=judge.digest(study_dir/'study.json'),
                independent_context=dict(identical_initial_payloads=len(study['request_sha256']),previous_scores_supplied=False,
                                         no_conversation_identifiers=True,returned_response_ids=len(ids),unique_response_ids=len(set(ids)),
                                         reused_response_ids=sorted(rid for rid,n in Counter(ids).items() if n>1),
                                         new_rag_answer_calls=0,new_embedding_queries=0),
                jev_rounds=[dict(name=r['name'],original_statuses=r['original_statuses'],canonical_valid=len(r['reviews']),
                                 diagnostics=r['diagnostics'],accounting=r['accounting'],
                                 source_location_complete=sum(row['evidence_locations_complete'] for row in r['rows']),
                                 request_bytes_range=[r['request_bytes_min'],r['request_bytes_max']],
                                 metrics=summarize_rows(r['name'],r['reviews'],tasks,cases,common)) for r in rounds],
                gpt_rounds=[dict(name=r['name'],valid_reviews=len(r['reviews']),accounting=r['accounting']) for r in historical],
                within_jev=within,gpt_jev_pairs=cross,all_six_common_tasks=len(shared),all_six_excluded=sorted(all_tasks-shared),
                shared_dimension_comparison=side_by_side,
                reported_jev_cost_usd=str(aggregate_cost),new_analysis_api_calls=0,
                compatibility_note='Only rounded probability-sum tolerance and flagged auxiliary locator argmax differences; all model labels, selected passages, raw probabilities and confidence retained.',
                timing_note='Historical workflows differ in scope, output and execution time. GPT costs are unknown; no monetary saving or pure-model speedup is established.')
    output.mkdir(parents=True)
    (output/'harness').mkdir()
    names=(*jev.HARNESS,'compare_qa_jev.py','compare_qa_judges.py','aggregate_qa_judges.py','revalidate_qa_judge.py')
    for name in dict.fromkeys(names):(output/'harness'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    for r in rounds:
        (output/(r['name']+'-reviews.jsonl')).write_text(''.join(judge.encode(v)+'\n' for v in r['reviews'].values()),encoding='utf-8',newline='\n')
    judge.write(output/'comparison.json',result)
    judge.write(output/'analysis-provenance.json',dict(api_calls=0,
                original_round_metadata={r['name']:r['metadata_sha256'] for r in rounds},
                original_api_records={r['name']:{p.stem:judge.digest(p) for p in sorted((Path(d)/'tasks').glob('*.json'))} for r,d in zip(rounds,jev_dirs)},
                analysis_harness_sha256={n:judge.digest(output/'harness'/n) for n in dict.fromkeys(names)}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--study-dir',type=Path,required=True)
    parser.add_argument('--jev-dir',type=Path,action='append',required=True);parser.add_argument('--gpt-dir',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    try:result=analyze(args.run_dir,args.study_dir,args.jev_dir,args.gpt_dir,args.output_dir)
    except Exception as error:parser.exit(1,'Jev comparison failed: '+type(error).__name__+'\n')
    print(judge.encode({k:result[k] for k in ['canonical_valid_tasks','reported_jev_cost_usd','all_six_common_tasks']}))


if __name__=='__main__':main()
