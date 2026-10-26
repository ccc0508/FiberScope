"""Independently grade immutable saved answers using Jev through OpenRouter Decisions."""
from __future__ import annotations

import argparse
from dataclasses import dataclass,field
from datetime import datetime
from decimal import Decimal
import math
import os
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

import judge_qa_eval as judge
import qa_jev_prompt as prompt
from score_qa_eval_v2 import source_basis

HARNESS=(*judge.HARNESS,'qa_jev_prompt.py','judge_qa_jev.py')


@dataclass(frozen=True)
class Config:
    base_url:str
    model:str
    api_key:str=field(repr=False)
    timeout:float=120

    def public(self):
        return dict(base_url=self.base_url,requested_model=self.model,api='openrouter_decisions',
                    timeout_seconds=self.timeout,automatic_retries=0,previous_scores_provided=False,
                    scope=['key_point_coverage','claim_support','citation_support'],
                    independent_requests=True,sampling='Native typed decisions; no sampling overrides or conversation identifiers.')


def load_config(path):
    values=dotenv_values(path,interpolate=False)
    def get(key,default=''):return (os.environ.get('QA_JEV_'+key,values.get('QA_JEV_'+key,default)) or '').strip()
    base=get('BASE_URL','https://openrouter.ai/api').rstrip('/')
    judge.require(base=='https://openrouter.ai/api','Jev must use the explicitly configured OpenRouter API')
    model=get('MODEL','typesafe/jev-1.14');key=get('API_KEY');timeout=float(get('TIMEOUT_SECONDS','120'))
    judge.require(model=='typesafe/jev-1.14' and bool(key),'Pinned Jev model or private OpenRouter key missing')
    judge.require(math.isfinite(timeout) and 1<=timeout<=600,'Invalid Jev timeout')
    return Config(base,model,key,timeout)


def number(value):return type(value) in (int,float) and math.isfinite(value)


def validate_response(body,request):
    judge.require(isinstance(body,dict) and isinstance(body.get('answers'),dict),'Jev answer map missing')
    judge.require(isinstance(body.get('model'),str) and (body['model']==request['model'] or body['model'].startswith(request['model']+'-')), 'Unexpected returned Jev model')
    judge.require(body.get('provider')=='TypeSafe','Unexpected Jev provider')
    answers=body['answers'];judge.require(set(answers)==set(request['questions']),'Jev answer coverage mismatch')
    for key,item in answers.items():
        criteria=request['questions'][key]['criteria'];prob=item.get('probabilities')
        judge.require(item.get('type')=='choice' and item.get('choice') in criteria,'Invalid Jev choice')
        judge.require(isinstance(prob,dict) and set(prob)==set(criteria),'Invalid probability options')
        judge.require(all(number(v) and 0<=v<=1 for v in prob.values()) and abs(sum(prob.values())-1)<=.01,'Invalid probability distribution')
        judge.require(prob[item['choice']]>=max(prob.values())-1e-6,'Choice disagrees with its distribution')
        judge.require(number(item.get('confidence')) and 0<=item['confidence']<=1,'Invalid Jev confidence')
    return answers


def decode_review(body,request,targets,case,task,result,path,sources):
    answers=validate_response(body,request)
    points={p['id']:None for p in case['key_points']};claims={};pairs=[]
    for key,target in targets.items():
        selected=answers[key]['choice'];kind=target['kind']
        if kind=='point':points[target['point_id']]=prompt.POINT_VALUES[selected]
        elif kind=='citation':pairs.append(dict(claim_id=target['claim_id'],ref=target['ref'],raw_score=int(selected=='supported')))
        else:claims.setdefault(target['claim_id'],{})[kind]=selected
    documents={p['document_id'] for p in sources['paper_texts']}
    assessments=[]
    for index,original in enumerate(result['response'].get('claims',[]),1):
        cid=f'C{index}';row=claims[cid];locator=row['basis'];basis=[];location='unlocated'
        if locator in request['state']['verifiable_passages']:
            entry=request['state']['verifiable_passages'][locator]
            item={k:v for k,v in entry.items() if k not in {'source_start','source_end'}}
            source_basis([item],result,row['claim_type'],documents,sources)
            basis=[item];location='verified_verbatim_passage'
        elif locator=='FULL_TEXT_SCOPE' and row['claim_type']=='scope':
            basis=[dict(type='full_pdf_review',document_id=next(iter(documents)),
                        explanation='Jev selected full-paper/corpus scope review for this pure scope statement; no free-text rationale was generated.')]
            location='fulltext_scope_selected'
        assessments.append(dict(id=cid,text=original['text'],claim_type=row['claim_type'],support=row['support'],
                                source_locator=locator,basis=basis,evidence_location_status=location))
    by_claim={c['id']:c for c in assessments};evidence={e['ref']:e for e in result['response'].get('retrieved_evidence',[])}
    for pair in pairs:
        pair['score']=pair['raw_score'] if by_claim[pair['claim_id']]['claim_type']=='fact' else None
        pair['chunk_id']=evidence[pair['ref']]['chunk_id']
    return dict(task_id=task['id'],case_id=case['id'],run_id=result['run_id'],response_file_sha256=judge.digest(path),
                reviewer_type='ai',reviewer=body['model']+' via OpenRouter',participated_in_authoring=False,
                review_status='ai_typed_shared_dimensions',key_point_scores=points,claim_assessments=assessments,
                citation_assessments=pairs,free_text_rationale=None,
                not_assessed=['full_strict_pass','manual_critical_error_rationale','reference_answer_expert_validation'])


def metrics(case,task,review):
    values=[review['key_point_scores'][p['id']] for p in case['key_points']
            if not p['optional'] and p['capability'] in task['capabilities']]
    factual=[p for p in review['citation_assessments'] if p['score'] is not None]
    facts=[c for c in review['claim_assessments'] if c['claim_type']=='fact']
    covered=sum(any(p['claim_id']==c['id'] and p['score']==1 for p in factual) for c in facts)
    located=all(c['evidence_location_status']!='unlocated' for c in review['claim_assessments'])
    return dict(task_id=task['id'],point_mean=statistics.mean(values),required_point_count=len(values),required_point_sum=sum(values),
                factual_citation_count=len(factual),supported_citation_count=sum(p['score'] for p in factual),
                factual_claim_count=len(facts),covered_factual_claims=covered,
                shared_dimensions_pass=all(v==1 for v in values) and all(c['support']=='supported' for c in review['claim_assessments'])
                    and all(p['score']==1 for p in factual) and covered==len(facts),
                evidence_locations_complete=located)


def usage(body):
    raw=body.get('usage') or {};inp=raw.get('input_tokens');out=raw.get('output_tokens');cost=raw.get('cost')
    return dict(input_tokens=inp if type(inp) is int and inp>=0 else None,
                output_tokens=out if type(out) is int and out>=0 else None,
                total_tokens=inp+out if type(inp) is int and inp>=0 and type(out) is int and out>=0 else None,
                reported_cost_usd=cost if number(cost) and cost>=0 else None)


def summarize(output,cases,tasks,records):
    complete=[r for r in records if r['status']=='completed']
    rows=[metrics(cases[t['case_id']],t,r['review']) for r in complete for t in tasks if t['id']==r['task_id']]
    costs=[(r.get('usage') or {}).get('reported_cost_usd') for r in records]
    token_rows=[r.get('usage') or {} for r in records]
    times=sorted(r['duration_ms'] for r in complete)
    models=sorted({r['returned_model'] for r in complete})
    result=dict(selected_tasks=len(tasks),recorded_tasks=len(records),valid_reviews=len(complete),
                statuses={s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})},
                unresolved_tasks=[t['id'] for t in tasks if t['id'] not in {r['task_id'] for r in complete}],
                application_calls=sum(r.get('api_calls',0) for r in records),reported_models=models,
                known_tokens={k:sum(v[k] for v in token_rows if type(v.get(k)) is int) for k in ['input_tokens','output_tokens','total_tokens']},
                usage_unknown_calls=sum(r.get('api_calls',0) for r in records if (r.get('usage') or {}).get('total_tokens') is None),
                reported_cost_usd=str(sum((Decimal(str(c)) for c in costs if c is not None),Decimal(0))),
                cost_unknown_calls=sum(r.get('api_calls',0) for r,c in zip(records,costs) if c is None),
                actual_invoice_cost=None,
                median_valid_duration_ms=statistics.median(times) if times else None,
                p95_valid_duration_ms=times[math.ceil(.95*len(times))-1] if times else None,
                all_evidence_located_tasks=sum(r['evidence_locations_complete'] for r in rows),rows=rows,
                full_strict_pass=None,summary_written=False)
    if len(complete)==len(tasks) and len(models)==1:
        result.update(summary_written=True,point_macro_average=statistics.mean(r['point_mean'] for r in rows),
                      shared_dimensions_pass=sum(r['shared_dimensions_pass'] for r in rows))
    judge.write(output/'progress.json',result)
    if result['summary_written']:judge.write(output/'summary.json',result)
    return result


def run(run_dir,output,config,*,limit=1,client=None,task_ids=None):
    run_dir,output=Path(run_dir).resolve(),Path(output).resolve()
    judge.require(type(limit) is int and 1<=limit<=100,'Invalid Jev request limit')
    judge.require(output!=run_dir and not output.is_relative_to(run_dir) and not run_dir.is_relative_to(output),'Use a separate Jev output directory')
    source,manifest,cases,sources=judge.verify_run(run_dir)
    tasks=[t for t in source['tasks'] if task_ids is None or t['id'] in task_ids]
    judge.require(tasks and (task_ids is None or set(task_ids)=={t['id'] for t in tasks}),'Unknown Jev task selection')
    rubric=judge.read_json(run_dir/'dataset/rubric.json');prepared={}
    for task in tasks:
        path,result=judge.read_result(run_dir,source,cases[task['case_id']],task)
        judge.require(result['status']!='failed','Cannot grade a failed source answer')
        request,targets=prompt.build_request(config,cases[task['case_id']],task,result,manifest,sources,rubric)
        prepared[task['id']]=(path,result,request,targets)
    contract=dict(contract_version=prompt.VERSION,source_run_id=source['run_id'],source_run_sha256=judge.digest(run_dir/'run.json'),
                  dataset_manifest_sha256=source['dataset_manifest_sha256'],judge=config.public(),task_ids=[t['id'] for t in tasks],
                  source_result_hashes={tid:judge.digest(value[0]) for tid,value in prepared.items()},
                  request_sha256={tid:judge.sha(value[2]) for tid,value in prepared.items()},
                  harness_files={name:judge.digest(Path(__file__).with_name(name)) for name in HARNESS})
    output.mkdir(parents=True,exist_ok=True)
    with judge.lock(output):
        metadata=output/'jev-run.json'
        if metadata.exists():
            judge.require(judge.read_json(metadata)['contract']==contract,'Jev inputs, settings or harness changed; use a new directory')
            judge.require(all(judge.digest(output/'harness'/n)==h for n,h in contract['harness_files'].items()),'Saved Jev harness changed')
        else:
            judge.write(metadata,dict(created_at=judge.now(),contract=contract));(output/'harness').mkdir()
            for name in HARNESS:(output/'harness'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
        (output/'tasks').mkdir(exist_ok=True);(output/'requests').mkdir(exist_ok=True)
        owned=client is None;client=client or httpx.Client(timeout=config.timeout,trust_env=False,follow_redirects=False)
        calls=0;records=[];started=time.monotonic()
        try:
            for task in tasks:
                tid=task['id'];path,result,request,targets=prepared[tid];record_path=output/'tasks'/(tid+'.json')
                payload_path=output/'requests'/(tid+'.json')
                if payload_path.exists():judge.require(judge.read_json(payload_path)==request,'Saved Jev request changed')
                else:judge.write(payload_path,request)
                if record_path.exists():
                    record=judge.read_json(record_path)
                    judge.require(record['request_sha256']==judge.sha(request),'Saved Jev request fingerprint mismatch')
                    if record['status']=='completed':
                        judge.require(judge.sha(record['raw_response'])==record['response_sha256'],'Saved Jev response changed')
                        review=decode_review(record['raw_response'],request,targets,cases[task['case_id']],task,result,path,sources)
                        judge.require(review==record['review'],'Saved Jev decisions changed')
                    records.append(record);continue
                if calls>=limit:continue
                record=dict(task_id=tid,status='pending',started_at=judge.now(),request_sha256=judge.sha(request),api_calls=1,usage=None)
                judge.write(record_path,record);calls+=1;clock=time.monotonic()
                try:
                    response=client.post(config.base_url+'/alpha/decisions',json=request,headers={'Authorization':'Bearer '+config.api_key})
                    record.update(http_status=response.status_code,http_ms=round((time.monotonic()-clock)*1000))
                    if not 200<=response.status_code<300:
                        record.update(status='api_failed',reason_code='http_'+str(response.status_code),error_body_sha256=judge.hashlib.sha256(response.content).hexdigest())
                    else:
                        body=judge.strict_json(response.text.replace(config.api_key,'[REDACTED]'))
                        record.update(raw_response=body,response_sha256=judge.sha(body),usage=usage(body),returned_model=body.get('model'),
                                      provider_response_id=body.get('id'),returned_provider=body.get('provider'),status='invalid_response')
                        record['review']=decode_review(body,request,targets,cases[task['case_id']],task,result,path,sources)
                        record['status']='completed'
                except httpx.HTTPError as error:record.update(status='api_failed',reason_code=type(error).__name__)
                except (ValueError,KeyError,TypeError,IndexError) as error:record.update(status='invalid_response',reason_code=type(error).__name__)
                record.update(finished_at=judge.now(),duration_ms=round((time.monotonic()-clock)*1000))
                judge.write(record_path,record);records.append(record)
                summarize(output,cases,tasks,records)
                if record.get('http_status') in {401,402,403}:break
        finally:
            if owned:client.close()
        (output/'reviews.jsonl').write_text(''.join(judge.encode(r['review'])+'\n' for r in records if r['status']=='completed'),encoding='utf-8',newline='\n')
        result=summarize(output,cases,tasks,records)
        result['api_calls_this_invocation']=calls;result['invocation_ms']=round((time.monotonic()-started)*1000)
        judge.write(output/'progress.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=judge.ROOT/'backend/.env.jev')
    parser.add_argument('--limit',type=int,default=1);parser.add_argument('--task',action='append')
    args=parser.parse_args()
    try:result=run(args.run_dir,args.output_dir,load_config(args.env_file),limit=args.limit,task_ids=args.task)
    except Exception as error:parser.exit(1,'Jev evaluation failed: '+type(error).__name__+'\n')
    print(judge.encode(result))


if __name__=='__main__':main()
