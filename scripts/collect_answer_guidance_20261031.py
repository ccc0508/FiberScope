"""Offline audit of fixed-evidence generations and original first-valid Jev scorecards."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import json

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import report_qa_context_v1_20261029 as runtime_report
from report_mineru_rag_20261029 import override
from collect_rerank_stability_20261031 import verify_import_binding,model_observations,answer_timing,attempt_details
from qa_repeat_refusal_compat import read_result
from run_answer_guidance_20261031 import canonical_sha
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
VERSION='answer-guidance-collection-v1'
ARMS=('control','guidance')
TASKS=[f'PFI2-{i:03}' for i in range(1,33)]
SETTINGS=['llm_provider','llm_model','llm_thinking_enabled','llm_reasoning_effort',
    'embedding_provider','embedding_model','embedding_dimensions','top_k','min_score',
    'context_expansion','table_retrieval','provider_endpoint_fingerprints']


def compare_settings(arms,source):
    require(set(arms)==set(ARMS),'Both independent arms are required')
    keep=lambda d:{k:d.get(k) for k in SETTINGS}
    values={a:keep(arms[a]) for a in ARMS}
    require(values['control']==values['guidance']==keep(source),'Original model/high/context settings changed')
    strip=lambda d:{k:v for k,v in d.items() if k!='answer_guidance'}
    require(strip(arms['control'])==strip(arms['guidance']),'Only the guidance flag may differ')
    require('answer_guidance' not in arms['control'] and arms['guidance']['answer_guidance']['enabled'],'Guidance setup differs')
    require(not any(d.get('rerank',{}).get('enabled') for d in arms.values()),'Rerank must stay disabled')
    return values


def verify_fixture(fixture,source,task_id):
    require(set(fixture)=={'version','task_id','question','evidences','documents','source_result_sha256','evidence_sha256'},'Fixture contains an extra field')
    require(fixture['version']=='answer-guidance-fixed-evidence-v1' and fixture['task_id']==task_id,'Wrong fixed-evidence fixture')
    require(fixture['question']==source['question'],'Question changed')
    require(fixture['evidences']==source['response']['retrieved_evidence'],'Original evidence text, refs, order or locators changed')
    require(fixture['documents']==source['response']['configuration']['documents'],'Document corpus changed')
    require(fixture['evidence_sha256']==canonical_sha(fixture['evidences']),'Evidence seal changed')


def verify_result(result,fixture,probe):
    response=result.get('response')
    require(result['status'] in ['answered','refused','failed'],'Unknown original program outcome')
    require(isinstance(response,dict),'A worker failed before producing auditable fixed-evidence output; preserve the result for separate diagnosis')
    require(response['status']==result['status'],'Outer/inner result status mismatch')
    require(response['retrieved_evidence']==fixture['evidences'],'Actual generated source evidence changed')
    diag=response['fixed_evidence_diagnostics']
    require(diag['evidence_sha256']==diag['generation_input_evidence_sha256']==fixture['evidence_sha256'],'Actual generation evidence hash differs')
    require(diag['source_result_sha256']==fixture['source_result_sha256'],'Fixed evidence bound to wrong historical answer')
    require(diag['retrieval_bypassed'] is True and diag['embedding_calls']==diag['rerank_calls']==0,'Unexpected additional retrieval call')
    require(response['embedding_usage'] is None and response['rerank_calls']==[],'Unexpected embedding or rerank usage')
    for k in ['llm_provider','llm_model','llm_thinking_enabled','llm_reasoning_effort','top_k','min_score','prompt_pipeline_sha256','answer_guidance']:
        require(response['configuration'].get(k)==probe.get(k),'Actual answer configuration changed: '+k)
    require(len(response['generation_calls'])<=2,'More than the original two generation attempts')
    for call in response['generation_calls']:
        if info:=call.get('model_info'):
            require(info['requested_model']==probe['llm_model'] and info['thinking_enabled']==probe['llm_thinking_enabled'] and
                info['reasoning_effort']==probe['llm_reasoning_effort'],'Wire generation model/thinking changed')
    return diag


def collect(root=ROOT,output_dir=None,analyst_notes=None):
    root=Path(root);out=Path(output_dir) if output_dir is not None else root/'.rag-data/evaluations/answer-guidance-20261031'
    c=judge.read_json(out/'experiment.json');gc=judge.read_json(out/'grading-contract.json')
    require(c['version']=='answer-guidance-fixed-evidence-v1' and c['task_ids']==TASKS,'Wrong fixed-evidence contract')
    require(c['total_new_questions']==64 and c['source_contexts']==32,'Wrong experiment size')
    for name,expected in [('run_answer_guidance_20261031.py',c['runner_sha256']),('answer_guidance_worker.py',c['worker_sha256']),
        ('grade_answer_guidance_20261031.py',gc['grader_sha256']),('grade_qa_rerank_repeats_20261031.py',gc['helper_sha256']),
        ('qa_repeat_refusal_compat.py',gc['result_reader_compat_sha256'])]:
        require(judge.digest(root/'scripts'/name)==expected,'Frozen orchestration code changed: '+name)
    require(judge.digest(root/'backend/.env.literature')==c['app_env_sha256'],'Default website configuration changed')
    require(gc['policy_sha256']==grading.POLICY_SHA and gc['first_valid_only'] and gc['max_attempts']==3 and gc['planned_jobs']==64,'Judge protocol changed')
    source_dir=root/'.rag-data/evaluations/pfi-content-units-v1-20261030-r1'
    require(judge.digest(source_dir/'run.json')==c['source_run_sha256'],'Source run manifest changed')
    source_run,_,source_cases,_=judge.verify_run(source_dir)
    fixtures={};source_seals={}
    for task in source_run['tasks']:
        tid=task['id'];p,r=read_result(source_dir,source_run,source_cases[task['case_id']],task)
        f=out/'fixtures'/(tid+'.json');fixture=judge.read_json(f);sealed=c['fixtures'][tid]
        require(judge.digest(f)==sealed['fixture_sha256'] and judge.digest(p)==sealed['source_result_sha256']==fixture['source_result_sha256'],'Historical result/fixture seal changed')
        verify_fixture(fixture,r,tid);fixtures[tid]=fixture;source_seals[tid]=judge.digest(p)
    records=[];runtimes=[];audits={};proofs={};settings={};all_results=[];source_files=None
    for arm in ARMS:
        entry=c['arms'][arm];directory=Path(entry['run_dir'])
        require(directory.resolve()==(out/'runs'/arm).resolve(),'Arm run path changed')
        require(judge.digest(directory/'run.json')==entry['run_sha256'],'A/B manifest changed')
        run,manifest,cases,_=judge.verify_run(directory);probe=run['configuration_probe'];settings[arm]=probe
        actual_files={p.relative_to(directory/'backend').as_posix():judge.digest(p) for p in (directory/'backend').rglob('*.py')}
        require(actual_files==run['source_files']==entry['source_files'],'A/B runtime code changed')
        if source_files is None:source_files=actual_files
        else:require(source_files==actual_files,'A/B code differs')
        require(run['tasks']==source_run['tasks'] and run['dataset_manifest_sha256']==source_run['dataset_manifest_sha256'],'Original questions changed')
        require(run['execution_mode']=='fixed_retrieved_evidence','Unexpected execution mode')
        require(judge.digest(directory/'harness/answer_guidance_worker.py')==c['worker_sha256'],'Frozen replay worker changed')
        require({p.stem for p in (directory/'results').glob('*.json')}==set(TASKS),'A/B result coverage incomplete')
        results={};seals={}
        for task in run['tasks']:
            tid=task['id'];path,result=read_result(directory,run,cases[task['case_id']],task)
            require(result['runner_sha256']==c['runner_sha256'],'Actual runner differs')
            verify_result(result,fixtures[tid],probe);results[tid]=result;seals[tid]=judge.digest(path)
        imp=out/'imports'/arm;study=out/'studies'/arm;audit=scoring.audit(imp,study);audits[arm]=audit
        contract=audit[2]
        require(contract['policy_sha256']==grading.POLICY_SHA and contract['requested_judges']==gc['requested_judges'],'Judge model or policy differs')
        require(contract['selected_systems']==['rag'] and len(contract['jobs'])==32 and
            all(j['judge']=='jev' and j['system']=='rag' for j in contract['jobs']),'Wrong answer systems in grading')
        require(all(status!='pending' for _,_,status in audit[5]),'Wait for interrupted/in-flight scoring')
        bundle=dict(run=run,cases=cases,results=results,run_sha256=judge.digest(directory/'run.json'),result_sha256=seals)
        verify_import_binding(audit,bundle)
        attempts,statuses=attempt_details(study,max_attempts=3)
        for job in sorted((j for j in audit[1] if j['system']=='rag'),key=lambda j:j['task_id']):
            tid=job['task_id'];review=audit[3].get(('jev','rag',tid));actual=results[tid]
            records.append(dict(arm=arm,task_id=tid,reference_case=job['reference_case'],candidate=job['candidate'],review=review,
                metrics=scoring.metrics(review,job['reference_case'],job['task']['capabilities']) if review else None,
                grading_status='completed' if review else statuses[tid],capabilities=job['task']['capabilities'],
                answer_status=actual['status'],reason_code=actual.get('reason_code'),input_evidence_sha256=fixtures[tid]['evidence_sha256']))
        with override(runtime_report,RUN=directory):runtime=runtime_report.runtime()
        runtime.update(embedding_usage_unknown_questions=0,embedding_calls=0,rerank_calls=0,
            embedding_note='Not invoked in fixed-context replay; null usage is not an unknown paid embedding call.')
        runtimes.append(dict(arm=arm,**{k:v for k,v in runtime.items() if k!='per_question'}))
        proofs[arm]=dict(run_sha256=judge.digest(directory/'run.json'),result_sha256=seals,
            import_sha256=judge.digest(imp/'import.json'),study_sha256=judge.digest(study/'study.json'),
            grade_proofs=audit[6],attempts=attempts,observed_models=model_observations(list(results.values())))
        all_results.extend(results.values())
    fixed_settings=compare_settings(settings,source_run['configuration_probe'])
    calls=[r for a in audits.values() for r in a[4].get('jev',[])]
    return dict(version=VERSION,records=records,runtimes=runtimes,
        accounting=dict(jev=scoring.accounting(calls,'jev'),by_arm={a:scoring.accounting(v[4].get('jev',[]),'jev') for a,v in audits.items()},
            generation_calls=sum(r['generation_calls'] for r in runtimes),generation_known_tokens=dict(sum((Counter(r['generation_known_tokens']) for r in runtimes),Counter())),
            embedding_calls=0,rerank_calls=0,actual_generation_cost=None,answer_timing=answer_timing(all_results)),
        controls=dict(generation_settings=fixed_settings,all_full_evidence_refs_locators_and_order_identical=True,
            same_runtime_source_code=True,source_evidence_run_sha256=c['source_run_sha256'],source_results_sha256=source_seals,
            source_contexts=32,fresh_generations=64,new_luna_calls=0,new_dsh_calls=0,default_application_configuration_unchanged=True),
        provenance=dict(experiment_sha256=judge.digest(out/'experiment.json'),grading_contract_sha256=judge.digest(out/'grading-contract.json'),
            collector_sha256=judge.digest(Path(__file__)),source_files=source_files,runs=proofs,provider_calls_by_collector=0),
        analyst_notes=analyst_notes if analyst_notes is not None else [
            '本轮不建议开启新指引。31道共同有效题的要点宏平均从94.35%升至94.89%，但单条引用有效率从99.21%降至95.80%，五项全部达标从23/31降至19/31。收益不足以证明值得增加生成请求与用量；这些是Jev本次原判，不是专家准确率。',
            '五道失去联合达标的题目为第13、23、29、30、32题；其必答要点、事实支持、引用组和边界仍全部达标，失分集中在附带的单条引用。分析者复核认为，第23、32题中正文引用确实支持复合句的“正文0.912”部分，第13、29题的引用也支持其中的实质成分，这些0分值得复核；第30题则确有未支持湿纸幅强度排序的冗余引用。不能把五题都解释成答案事实错误，原分不作修改。',
            '第15题要点从2/3升至2.5/3，但新旧答案都列出了3.33与1.77 N/mm，且新版仍未明确说差异不能只归因于纤维种类。该题有裁判波动可能，不宜将其作为已解决边界问题的证据。第4、7、11、18题的必答要点均未提高。',
            '本轮第11题封存的7条证据未包含Table 1的结晶度数值，因此不能通过提示词产生有依据的数值反例。这是所选证据缺失，不等同于先前其他运行中“已有表格却未用”的问题；本次不补充检索，以保持A/B输入相同。',
            '第26题新版把缺失范围限定到“所给摘录”，Jev边界由1升至2；其另一条范围声明仍非完全支持，因此尚未联合达标。该句由事实归为范围声明后不再进入事实支持率分母，故100%的事实支持率不等于消除了所有依据问题。第24题由未联合达标变为达标。联合条件还检查范围声明，二者分母不同。',
            '全部64份回答均成功返回；没有新增程序拒答。第3题新版三次评分都因引用组与单条引用的判断不一致而被原校验器拒绝，保留为缺失，不补第四次、不计零分。缺失不一定随机，共同31题不能等同完整32题的质量结论。',
            '32题生成请求从33次增至42次，已知Token从184,808增至272,911（+47.67%，含推理Token），生成流程中位耗时从11.965秒增至16.399秒（+37.06%）。API缓存命中不同，不能把Token增幅直接当作货币成本增幅；实际答题费用未知。Jev共66次请求，API报告费用0.187373256美元，包含三次无效评分。',
            '网站默认配置保持关闭。下一步宜先缩短指引、约束无关扩写并明确每条引用的实质贡献，再用同证据比较；对复合句引用的裁判疑点单独复核，不为提高分数而静默改动本轮协议。',
        ],limitations=[
            '生成请求保留原有最多两次格式或引用纠正；没有新增模型自检调用。',
            '相同模型别名及High设置不保证服务商远端模型权重始终相同。API报告费用不是已核验账单。'])


if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
    result=collect();path=a.output or ROOT/'.rag-data/evaluations/answer-guidance-20261031/analysis-input.json'
    scoring.save(path,result);print(json.dumps(dict(records=len(result['records']),output=str(path),provider_calls=0)))
