"""Collect sealed three-round RAG evidence offline; never generate or grade answers.

The only output is a private, auditable input for report_rerank_stability_20261031.
No environment files, credentials, provider clients, or configuration probes are read.
"""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import report_qa_context_v1_20261029 as runtime_report
from report_mineru_rag_20261029 import override
from report_qa_rerank_20261030 import combine_grade_audits
from validate_qa_eval import require
from qa_repeat_refusal_compat import read_result

ROOT=Path(__file__).resolve().parents[1]
VERSION='rerank-stability-collection-v1'
SYSTEMS=('content','rerank')
TASK_IDS=tuple(f'PFI2-{i:03}' for i in range(1,33))
ORIGINAL_RUNS={'content':'pfi-content-units-v1-20261030-r1',
    'rerank':'pfi-candidate-rerank-v1-20261030-r1'}
ORIGINAL_IMPORTS={'content':'content-units-five-import-20261030-r1',
    'rerank':'candidate-rerank-five-import-20261030-r1'}
ORIGINAL_STUDIES={'content':'content-units-jev-20261030-r1',
    'rerank':'candidate-rerank-jev-20261030-r1'}
RECOVERY='candidate-rerank-jev-20261031-proxy-recovery'
PUBLIC_REPORT='data/literature/qa-evaluation/reports/candidate-rerank-jev-20261030'
LIMITATIONS=[
    'Only Jev original, first-valid judgments are used; invalid/missing grades remain null, never zero. No weighted grand score is calculated.',
    'Historical round 1 content PFI2-024 and rerank PFI2-023 have no valid Jev judgment; these answers are not regraded.',
    'Historical rerank PFI2-011 may be overestimated by Jev: the answer does not explicitly give the required 4000→8000 revolution numeric counterexample. Original labels are retained.',
    'Round 1 consists of separate sequential historical runs started on 2026-10-30. New rounds run the two systems concurrently for each question in independent processes, waiting for each pair, round 2 before round 3.',
    'Dates, scheduling, provider caching, network and remote service state can affect runtime and token usage. Summed question seconds are not elapsed experiment wall time.',
    'Remote model aliases and identical settings do not prove unchanged provider weights or bitwise reproducibility.',
    'Three rounds on the same 32 development questions give descriptive variation only; no statistical significance or new-paper generalization is claimed. Answer and judge variability are not separately identified.',
    'API-reported judge costs are not invoices. Failed requests and missing usage/cost remain unknown; answering, embedding and rerank actual money costs are unknown. Reasoning tokens are already included in generation tokens.',
    'Offline collection compares sealed configuration probes; it does not read credentials or rerun the live configuration probe.',
    'Round 3 rerank PFI2-025 returned a production refusal after citation validation failure. The original answer/status is preserved and graded, not regenerated; a reader-only adapter accepts the existing refused status without changing the judge harness.',
]


def validate_contract(contract):
    """Validate the frozen experiment's shape without opening private files."""
    require(contract['version']=='rerank-system-stability-v1','Unknown experiment contract')
    require(contract['task_ids']==list(TASK_IDS),'Expected original 32 tasks')
    require(contract['rounds']==[1,2,3] and contract['new_rounds']==[2,3],'Unexpected rounds')
    require(contract['planned_new_answers']==128 and contract['planned_new_jev_jobs']==128,'Unexpected experiment size')
    entries=contract['runs']
    require(len(entries)==4 and {(e['system'],e['round']) for e in entries}==
        {(s,r) for s in SYSTEMS for r in (2,3)},'Four unique repeated runs required')
    require(len({str(Path(e['run_dir']).resolve()) for e in entries})==4,'Repeated run directories overlap')
    require(contract['scheduling']['concurrency']==2 and contract['scheduling']['round_order']==[2,3],
        'Paired scheduling contract changed')
    for e in entries:
        require(Path(e['run_dir']).name==f"pfi-{e['system']}-repeat-20261031-r{e['round']}", 'Unexpected repeat destination')
        require(Path(e['original_run_dir']).name==ORIGINAL_RUNS[e['system']], 'Unexpected historical source')
        require(e['original_run_sha256']==contract['original_run_manifests'][e['system']], 'Original manifest seals disagree')
    return {(e['system'],e['round']):e for e in entries}


def equal_run_controls(repeated,original):
    """Every setting and all original source/corpus fingerprints must stay equal."""
    keys=('tasks','dataset_manifest_sha256','dataset_files','configuration','configuration_probe',
          'source_files','initial_library_files','baseline_manifest_sha256','archive_sha256','timeout_seconds')
    for key in keys:require(repeated[key]==original[key],'Repeated run control changed: '+key)
    return dict(equal_fields=list(keys),configuration_probe_equal=True,reference_dataset_equal=True,
        runtime_source_equal=True,initial_library_fingerprints_equal=True)


def verify_run(directory,expected_sha256=None,runner_sha256=None):
    directory=Path(directory)
    if expected_sha256 is not None:
        require(judge.digest(directory/'run.json')==expected_sha256,'Sealed run manifest changed')
    run,manifest,cases,_=judge.verify_run(directory)
    require([t['id'] for t in run['tasks']]==list(TASK_IDS),'Run task order or coverage changed')
    sources={p.relative_to(directory/'backend').as_posix():judge.digest(p)
        for p in (directory/'backend').rglob('*.py')}
    require(sources==run['source_files'],'Frozen runtime source changed')
    require({p.stem for p in (directory/'results').glob('*.json')}==set(TASK_IDS),'Answer coverage incomplete or unexpected')
    results={};result_seals={}
    for task in run['tasks']:
        tid=task['id'];path,result=read_result(directory,run,cases[task['case_id']],task)
        if runner_sha256 is not None:require(result['runner_sha256']==runner_sha256,'Answer used a different runner')
        results[tid]=result;result_seals[tid]=judge.digest(path)
    return dict(run=run,manifest=manifest,cases=cases,results=results,result_sha256=result_seals,
        run_sha256=judge.digest(directory/'run.json'))


def scientific_candidate(result,task_id):
    """Reproduce the importer's scientific projection without PDF extraction or APIs."""
    response=result.get('response') or {}
    evidence={e['ref']:e for e in response.get('retrieved_evidence',[])}
    claims=[dict(id=f'C{i+1}',text=c['text'],citation_refs=c['citation_refs'])
        for i,c in enumerate(response.get('claims',[]))]
    cited={ref for c in claims for ref in c['citation_refs']}
    require(cited<=evidence.keys(),'Saved answer has a missing citation')
    citations=[{k:e[k] for k in ('ref','page_start','page_end','text')}
        for e in evidence.values() if e['ref'] in cited]
    return dict(task_id=task_id,answer=response.get('answer',''),claims=claims,citations=citations,
        available_context=dict(kind='supplied_excerpts',texts=[e['text'] for e in evidence.values()]))


def verify_import_binding(audit,bundle):
    """Bind every imported scientific packet to its actual sealed generation result."""
    meta,jobs=audit[:2];run=bundle['run'];tasks={t['id']:t for t in run['tasks']}
    require(meta['dataset_manifest_sha256']==run['dataset_manifest_sha256'],'Import dataset changed')
    selected=[j for j in jobs if j['system']=='rag']
    require(len(selected)==32 and {j['task_id'] for j in selected}==set(TASK_IDS),'Imported RAG job coverage changed')
    for job in selected:
        tid=job['task_id'];task=tasks[tid];origin=meta['rag_origins'][tid]
        require(job['task']==task and job['reference_case']==bundle['cases'][task['case_id']], 'Imported reference/task changed')
        require(origin['source_run_id']==run['run_id'] and origin['source_run_sha256']==bundle['run_sha256'],
            'Import bound to another run')
        require(origin['result_sha256']==bundle['result_sha256'][tid],'Imported result seal changed')
        candidate=deepcopy(job['candidate'])
        for citation in candidate['citations']:citation.pop('verification',None)
        require(candidate==scientific_candidate(bundle['results'][tid],tid),'Imported candidate differs from saved answer')


def validate_study(audit,settings=None):
    study=audit[2]
    require(study['policy_sha256']==grading.POLICY_SHA,'Scoring policy changed')
    require(set(study['requested_judges'])=={'jev'},'Only Jev judgments allowed')
    require(len(study['jobs'])==32 and {e['task_id'] for e in study['jobs']}==set(TASK_IDS), 'Expected 32 unique Jev jobs')
    require(all(e['judge']=='jev' and e['system']=='rag' for e in study['jobs']), 'Unexpected judge or answer system')
    if settings is not None:require(study['requested_judges']==settings,'Judge configuration changed')
    require(all(status!='pending' for _,_,status in audit[5]),'Wait for in-flight or interrupted grading')
    return study['requested_judges']


def attempt_details(study_dir,phase='main',max_attempts=None):
    directory=Path(study_dir);study=judge.read_json(directory/'study.json');details=[];statuses={}
    for entry in study['jobs']:
        paths=sorted((directory/'records'/entry['name']).glob('*.json'),key=lambda p:int(p.stem))
        if max_attempts is not None:require(len(paths)<=max_attempts,'Grading exceeded frozen attempt bound')
        statuses[entry['task_id']]='missing'
        for path in paths:
            record=judge.read_json(path);status=record['status']
            require(status!='pending','Wait for in-flight or interrupted grading')
            statuses[entry['task_id']]=status
            details.append(dict(task_id=entry['task_id'],name=entry['name'],execution_phase=phase,
                attempt=record['attempt'],status=status,api_calls=record.get('api_calls',0),
                started_at=record.get('started_at'),duration_ms=record.get('duration_ms'),usage=record.get('usage'),
                record_sha256=judge.digest(path),request_sha256=record['request_sha256'],
                response_sha256=record.get('response_sha256'),prior_record_sha256=record.get('prior_record_sha256')))
    return details,statuses


def audit_records(system,round_number,audit,statuses):
    rows=[]
    for job in sorted((j for j in audit[1] if j['system']=='rag'),key=lambda j:j['task_id']):
        tid=job['task_id'];review=audit[3].get(('jev','rag',tid));capabilities=job['task'].get('capabilities',['text'])
        rows.append(dict(system=system,round=round_number,task_id=tid,reference_case=job['reference_case'],
            candidate=job['candidate'],review=review,
            metrics=scoring.metrics(review,job['reference_case'],capabilities) if review is not None else None,
            capabilities=capabilities,grading_status='completed' if review is not None else statuses.get(tid,'missing')))
    return rows


def validate_public_round(rows,public_rows):
    public={r['task_id']:r for r in public_rows}
    require(len(public)==len(public_rows)==32 and set(public)==set(TASK_IDS),'Published historical question coverage changed')
    for row in rows:
        p=public[row['task_id']];system=row['system'];value=p['systems'][system]
        require(p['reference_case']==row['reference_case'],'Published historical reference changed')
        for key in ('candidate','review','metrics'):
            require(value[key]==row[key],'Published historical '+key+' differs from audited original')
    for system,missing in [('content','PFI2-024'),('rerank','PFI2-023')]:
        own=[r for r in rows if r['system']==system]
        require({r['task_id'] for r in own if r['review'] is None}=={missing}, 'Historical missing grades changed')


def rerank_accounting(results):
    calls=[c for result in results for c in (result.get('response') or {}).get('rerank_calls',[])]
    tokens=Counter()
    for call in calls:
        for key,value in (call.get('usage') or {}).items():
            if type(value) is int:tokens[key]+=value
    latencies=[c['latency_ms'] for c in calls if type(c.get('latency_ms')) in (int,float)]
    return dict(calls=len(calls),statuses=dict(Counter(c['status'] for c in calls)),known_tokens=dict(tokens),
        usage_unknown_calls=sum(c.get('usage') is None for c in calls),
        median_call_seconds=statistics.median(latencies)/1000 if latencies else None,
        actual_billing_usd=None,independent_probe_calls_included=0)


def answer_timing(results):
    """Separate the full timestamp span from the sum of overlapping question times."""
    starts=[];finishes=[];durations=[];incomplete=0
    for result in results:
        if result.get('started_at') and result.get('finished_at'):
            start=datetime.fromisoformat(result['started_at'].replace('Z','+00:00'))
            finish=datetime.fromisoformat(result['finished_at'].replace('Z','+00:00'))
            require(start.tzinfo is not None and finish.tzinfo is not None and finish>=start,'Invalid answer timestamps')
            starts.append(start);finishes.append(finish)
        else:incomplete+=1
        if type(result.get('end_to_end_ms')) in (int,float):durations.append(result['end_to_end_ms'])
    return dict(answer_records=len(results),timestamp_unknown_answers=incomplete,
        first_started_at=min(starts).isoformat() if starts else None,
        last_finished_at=max(finishes).isoformat() if finishes else None,
        first_start_to_last_finish_seconds=(max(finishes)-min(starts)).total_seconds() if starts and not incomplete else None,
        sum_question_end_to_end_seconds=sum(durations)/1000,
        duration_unknown_answers=len(results)-len(durations),
        note='Timestamp span includes pauses and inter-round intervals; summed question times overlap when two systems run concurrently.')


def model_observations(results):
    """Record returned identifiers and configured values, without inferring weights."""
    models=Counter();configurations=Counter();unknown=0
    for result in results:
        response=result.get('response') or {}
        for call in response.get('generation_calls',[]):
            info=call.get('model_info')
            if info is None:unknown+=1;continue
            public={k:info.get(k) for k in ('requested_model','returned_model','system_fingerprint','thinking_enabled','reasoning_effort')}
            models[json.dumps(public,sort_keys=True,ensure_ascii=False)]+=1
        if configuration:=response.get('configuration'):
            public={k:configuration.get(k) for k in ('llm_model','llm_provider','llm_thinking_enabled',
                'llm_reasoning_effort','embedding_model','embedding_dimensions','top_k','min_score','prompt_pipeline_sha256')}
            configurations[json.dumps(public,sort_keys=True,ensure_ascii=False)]+=1
    return dict(generation_model_info=[dict(model_info=json.loads(key),calls=count) for key,count in sorted(models.items())],
        model_info_unknown_calls=unknown,
        response_configuration_distribution=[dict(configuration=json.loads(key),answers=count) for key,count in sorted(configurations.items())],
        note='Returned model names/fingerprints describe provider reports only; unchanged remote weights are not verified.')


def accounting_group(entries):
    """Retain all attempts including paid-invalid and transport failures in each group."""
    all_records=[r for e in entries for r in e['audit'][4].get('jev',[])]
    results=[r for e in entries for r in e['bundle']['results'].values()]
    return dict(jev=scoring.accounting(all_records,'jev'),answer_timing=answer_timing(results),
        by_run=[dict(system=e['system'],round=e['round'],jev=scoring.accounting(e['audit'][4].get('jev',[]),'jev'),
            attempts=e['attempts'],terminal_statuses=e['statuses']) for e in entries],
        rerank=rerank_accounting([r for e in entries if e['system']=='rerank' for r in e['bundle']['results'].values()]))


def collect(root=ROOT):
    """Read immutable local evidence and write nothing; callers decide where to save."""
    root=Path(root);private=root/'.rag-data/evaluations';output=private/'rerank-stability-20261031'
    contract=judge.read_json(output/'experiment.json');plan=validate_contract(contract)
    require(judge.digest(root/'scripts/repeat_qa_rerank_20261031.py')==contract['orchestrator_sha256'],'Frozen repeat orchestrator changed')
    require(judge.digest(root/'scripts/run_qa_baseline.py')==contract['runner_sha256'],'Frozen answer runner changed')
    gc=judge.read_json(output/'grading-contract.json')
    require(gc['version']=='rerank-stability-grading-v1' and gc['policy_sha256']==grading.POLICY_SHA,'Grading contract changed')
    require(gc['new_rounds']==[2,3] and gc['planned_new_jev_jobs']==128 and gc['max_attempts']==3 and gc['first_valid_only'] is True,
        'Grading bounds changed')
    require(gc['new_luna_calls']==0 and gc['historical_scores_reused'] is True,'Historical scores or judge selection changed')
    require(judge.digest(root/'scripts/grade_qa_rerank_repeats_20261031.py')==gc['grader_sha256'],'Frozen grading orchestrator changed')
    compatibility=judge.read_json(output/'refusal-import-compat-r3.json')
    require(compatibility['original_status_preserved'] and compatibility['new_generation_calls']==0,'Refusal compatibility changed scientific output')
    require(compatibility['compat_source_sha256']==judge.digest(root/'scripts/qa_repeat_refusal_compat.py'),'Refusal reader compatibility changed')
    require(compatibility['original_read_result_source_sha256']==judge.digest(root/'scripts/judge_qa_eval.py'),'Original scoring source changed')
    require(compatibility['policy_sha256']==grading.POLICY_SHA,'Refusal changed grading policy')
    entries=[];records=[];proofs=[];runtimes=[];controls={}
    for system in SYSTEMS:
        run_dir=private/ORIGINAL_RUNS[system]
        bundle=verify_run(run_dir,contract['original_run_manifests'][system])
        imp=private/ORIGINAL_IMPORTS[system];study=private/ORIGINAL_STUDIES[system]
        audit=scoring.audit(imp,study);validate_study(audit,gc['requested_judges'])
        attempts,statuses=attempt_details(study,'direct' if system=='rerank' else 'main')
        phases=[study]
        if system=='rerank':
            recovery_dir=private/RECOVERY;recovery=scoring.audit(imp,recovery_dir)
            validate_study(recovery,gc['requested_judges'])
            recovery_manifest=judge.read_json(recovery_dir/'recovery-manifest.json')
            require(recovery_manifest['original_study_sha256']==judge.digest(study/'study.json'),'Recovery original study changed')
            require(recovery_manifest['recovery_study_sha256']==judge.digest(recovery_dir/'study.json'),'Recovery study changed')
            for job in audit[2]['jobs']:
                name=job['name']+'.json'
                require((study/'inputs'/name).read_bytes()==(recovery_dir/'inputs'/name).read_bytes(),'Recovery judge input changed')
            audit=combine_grade_audits(audit,recovery)
            more,recovered_statuses=attempt_details(recovery_dir,'proxy_recovery');attempts+=more
            statuses={t:recovered_statuses[t] if recovered_statuses[t]!='missing' else statuses[t] for t in TASK_IDS}
            phases.append(recovery_dir)
            controls['historical_transport_recovery']=dict(request_bytes_identical=True,
                manifest=recovery_manifest,manifest_sha256=judge.digest(recovery_dir/'recovery-manifest.json'))
        verify_import_binding(audit,bundle)
        entries.append(dict(system=system,round=1,audit=audit,bundle=bundle,attempts=attempts,statuses=statuses,run_dir=run_dir,import_dir=imp,phases=phases))
        records+=audit_records(system,1,audit,statuses)
    public_dir=root/PUBLIC_REPORT
    publication=judge.read_json(public_dir/'publication.json')
    for name,checksum in publication['files'].items():
        require(judge.digest(judge.child(public_dir,name))==checksum,'Published historical report changed')
    validate_public_round(records,judge.read_jsonl(public_dir/'questions-answers-reviews.jsonl'))
    originals={e['system']:e['bundle'] for e in entries}
    for round_number in (2,3):
        for system in SYSTEMS:
            entry=plan[(system,round_number)];run_dir=Path(entry['run_dir'])
            bundle=verify_run(run_dir,entry['run_sha256'],contract['runner_sha256'])
            controls[f'{system}-r{round_number}']=equal_run_controls(bundle['run'],originals[system]['run'])
            imp=output/'imports'/f'{system}-r{round_number}';study=output/'studies'/f'{system}-r{round_number}'
            audit=scoring.audit(imp,study);validate_study(audit,gc['requested_judges']);verify_import_binding(audit,bundle)
            attempts,statuses=attempt_details(study,max_attempts=gc['max_attempts'])
            entries.append(dict(system=system,round=round_number,audit=audit,bundle=bundle,attempts=attempts,statuses=statuses,run_dir=run_dir,import_dir=imp,phases=[study]))
            records+=audit_records(system,round_number,audit,statuses)
    standards={}
    require(len(records)==192,'Expected all 192 explicit answer records')
    for row in records:
        tid=row['task_id']
        if tid in standards:require(standards[tid]==row['reference_case'],'Reference standard differs across systems or rounds')
        else:standards[tid]=row['reference_case']
    for e in entries:
        with override(runtime_report,RUN=e['run_dir']):runtime=runtime_report.runtime()
        runtimes.append(dict(system=e['system'],round=e['round'],**{k:v for k,v in runtime.items() if k!='per_question'}))
        proofs.append(dict(system=e['system'],round=e['round'],run_dir=str(e['run_dir']),
            run_sha256=e['bundle']['run_sha256'],result_sha256=e['bundle']['result_sha256'],
            import_sha256=judge.digest(e['import_dir']/'import.json'),
            studies=[dict(path=str(p),study_sha256=judge.digest(p/'study.json')) for p in e['phases']],grade_proofs=e['audit'][6],
            answer_timing=answer_timing(list(e['bundle']['results'].values())),
            observed_models=model_observations(list(e['bundle']['results'].values()))))
    controls.update(all_192_answers_sealed=True,new_answers=128,new_luna_calls=0,
        historical_answers_or_grades_recomputed=False,live_configuration_probe_rerun=False,
        scheduling=contract['scheduling'],experiment_boundaries=contract.get('boundaries',[]))
    return dict(version=VERSION,records=records,runtimes=runtimes,
        accounting=dict(new=accounting_group([e for e in entries if e['round']>1]),
            historical=accounting_group([e for e in entries if e['round']==1]),
            notes=['Historical calls are reused archive accounting, not new requests.',
                'All Jev attempts are counted, including invalid grades and API failures; unknown charges are not assumed free.',
                'Rerank totals cover answer calls only; the original independent probe is excluded.']),
        analyst_notes=[
            '本次三轮中，重排版在第32题持续漏掉摘要与正文的数值冲突，三轮要点均为83.33%；纯向量版该题三轮要点均满分。第25题重排版新增两轮要点分别为0与0.5，其中第3轮是引用校验失败后的程序拒答。',
            '重排版在第11题三轮要点均被Jev判为满分，纯向量版均明显失分；但第1轮的数值反例要点可能被高估。统一排除第11题后，三轮平均要点差值进一步转为重排低3.45个百分点，不能据该单题宣称整体收益。',
            '保留重排功能为可选实验开关，当前不切换默认网站配置。下一步应检查重排是否挤掉冲突证据，以及回答遗漏要点和引用校验失败；本轮不修改这些环节。',
        ],controls=controls,provenance=dict(experiment_sha256=judge.digest(output/'experiment.json'),
            grading_contract_sha256=judge.digest(output/'grading-contract.json'),
            historical_publication_sha256=judge.digest(public_dir/'publication.json'),
            collector_sha256=judge.digest(Path(__file__)),policy_sha256=grading.POLICY_SHA,runs=proofs,
            refusal_status_compatibility=compatibility,refusal_compatibility_sha256=judge.digest(output/'refusal-import-compat-r3.json'),
            provider_calls_by_collector=0),limitations=LIMITATIONS)


def main():
    parser=ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    payload=collect(args.root)
    path=args.output or args.root/'.rag-data/evaluations/rerank-stability-20261031/analysis-input.json'
    path.parent.mkdir(parents=True,exist_ok=True);scoring.save(path,payload)
    print(json.dumps(dict(output=str(path),records=len(payload['records']),provider_calls=0),ensure_ascii=False))


if __name__=='__main__':main()
