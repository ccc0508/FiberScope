"""Audit fresh Qwen answers and two independent five-dimension judges, no model calls."""
from collections import Counter
from html import escape
import json
from pathlib import Path

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_qwen_twojudges_20261102 import ROOT,OUTPUT,RUN,IMPORT,STUDY,OLD_RUN,KINDS
from report_embedding_20261102 import retrieval_diff,runtime
from report_mineru_current_20261101 import quality_cells
from report_qa_citation_failures import read_records
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/qwen-twojudges-20261102-r2'
DOC=ROOT/'docs/QA_QWEN_TWOJUDGES_EVAL_20261102.md'
PREVIOUS=ROOT/'data/literature/qa-evaluation/reports/embedding-20261102'
LABELS={'jev':'Jev','luna':'Luna'}


def eligible(metrics):return sorted(t for t,m in metrics.items() if not m['reference_concern'])


def changes(before,after,ids):
    result={k:[] for k in ['point_wins','point_losses','joint_wins','joint_losses']}
    for tid in ids:
        a,b=before[tid],after[tid]
        if b['point_mean']>a['point_mean']:result['point_wins'].append(tid)
        if b['point_mean']<a['point_mean']:result['point_losses'].append(tid)
        if b['all_five_pass'] and not a['all_five_pass']:result['joint_wins'].append(tid)
        if a['all_five_pass'] and not b['all_five_pass']:result['joint_losses'].append(tid)
    return result


def disagreements(reviews,ids):
    dimensions={'key_points':lambda k:k.startswith('point_'),
        'claim_support':lambda k:k.startswith('support_'),
        'citation_support':lambda k:k.startswith('citation_'),
        'citation_group_coverage':lambda k:k.startswith('group_'),
        'answerability':lambda k:k=='boundary'}
    result={}
    for tid in ids:
        a,b=(reviews[k][tid]['decisions'] for k in KINDS)
        require(set(a)==set(b),'Judges did not assess the same decisions')
        delta={d:[dict(item=key,jev=a[key],luna=b[key]) for key in sorted(a) if predicate(key) and a[key]!=b[key]]
               for d,predicate in dimensions.items()}
        result[tid]=delta
    return result


def failed_jobs(study,reviews):
    rows=[]
    for entry in study['jobs']:
        kind,tid=entry['judge'],entry['task_id']
        if tid in reviews[kind]:continue
        saved=judge.read_json(STUDY/'inputs'/(entry['name']+'.json'));attempts=[]
        for path in sorted((STUDY/'records'/entry['name']).glob('*.json')):
            record=judge.read_json(path);message=None
            if record.get('raw_response') is not None:
                try:grading.decode(kind,record['raw_response'],saved['request'],saved['questions'],saved['targets'],saved['state'])
                except (ValueError,KeyError,TypeError,IndexError) as error:message=str(error)
            attempts.append(dict(attempt=record['attempt'],status=record['status'],usage=record.get('usage'),
                validation_message=message,record_sha256=judge.digest(path)))
        require(attempts and attempts[-1]['status']!='pending','Unfinished judge request')
        rows.append(dict(judge=kind,task_id=tid,score=None,attempts=attempts))
    return rows


def publish():
    require(not PUBLIC.exists() and not DOC.exists(),'Keep existing report immutable')
    meta,jobs,study,reviews,records,statuses,proofs=scoring.audit(IMPORT,STUDY)
    require(study['selected_systems']==['rag'] and set(study['requested_judges'])==set(KINDS),'Wrong judges/systems')
    require(all(s!='pending' for _,_,s in statuses),'Wait for active judge requests')
    jobs={j['task_id']:j for j in jobs if j['system']=='rag'}
    require(set(jobs)=={f'PFI2-{i:03}' for i in range(1,33)},'Question set changed')
    decoded={k:{tid:review for (kind,system,tid),review in reviews.items() if kind==k and system=='rag'} for k in KINDS}
    metrics={k:{tid:scoring.metrics(r,jobs[tid]['reference_case'],jobs[tid]['task']['capabilities']) for tid,r in rs.items()} for k,rs in decoded.items()}
    common=sorted(set(eligible(metrics['jev']))&set(eligible(metrics['luna'])))
    require(bool(common),'No paired unflagged grades')
    summaries={k:scoring.summarize([metrics[k][t] for t in common]) for k in KINDS}
    independent={k:scoring.summarize([metrics[k][t] for t in eligible(metrics[k])]) if eligible(metrics[k]) else None for k in KINDS}
    previous={r['task_id']:r for r in judge.read_jsonl(PREVIOUS/'questions-answers-reviews.jsonl')}
    old_metrics={t:r['qwen']['metrics'] for t,r in previous.items() if r['qwen']['metrics'] is not None}
    historical_common=sorted(set(eligible(old_metrics))&set(eligible(metrics['jev'])))
    historical=dict(common_task_ids=historical_common,
        comparison={a:scoring.summarize([ms[t] for t in historical_common]) for a,ms in [('previous_jev',old_metrics),('current_jev',metrics['jev'])]},
        changes=changes(old_metrics,metrics['jev'],historical_common),
        note='Previous Qwen and new Qwen with newly generated answers and new Jev judgments, not an embedding change or a controlled judge-repeat-only test.')
    differences=disagreements(decoded,common)
    run=judge.read_json(RUN/'run.json');progress=judge.read_json(RUN/'progress.json')
    require(progress['status']=='completed' and progress['completed']==32,'Answers not complete')
    responses={t:judge.read_json(RUN/'results'/(t+'.json')) for t in sorted(jobs)}
    traces={r['id']:r for r in read_records(RUN)}
    require(all(r['diagnostic_available'] for r in traces.values()),'New diagnostic recorder not enabled')
    rows=[]
    for tid,job in sorted(jobs.items()):
        require(all(job['reference_case'][k]==previous[tid][k] for k in ['question','key_points','reference_answer','critical_errors']),
            'Historical question or key point changed')
        response=responses[tid]['response']
        old=judge.read_json(OLD_RUN/'results'/(tid+'.json'))['response']
        require(all(c.get('model_info',{}).get('reasoning_effort')=='high' for c in response['generation_calls']),'Answer model setting changed')
        require('visual_retrieval' not in response['configuration'] and 'answer_guidance' not in response['configuration'],'Wrong answer mode')
        trace=traces[tid]['citation_validation']
        require(all(1<=a['attempt']<=len(response['generation_calls']) for a in trace['attempts']),'Validation attempts misaligned')
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference_case=job['reference_case'],
            candidate=job['candidate'],answer_status=response['status'],reason_code=response['reason_code'],
            generation_calls=response['generation_calls'],citation_validation=trace,
            judges={k:dict(review=decoded[k].get(tid),metrics=metrics[k].get(tid)) for k in KINDS},
            disagreements=differences.get(tid),previous_qwen_jev=previous[tid]['qwen'],
            retrieval_vs_previous=retrieval_diff(old,response)))
    diagnostic=dict(validation_attempts=sum(len(r['citation_validation']['attempts']) for r in rows),
        failed_attempts=[dict(task_id=r['task_id'],**a) for r in rows for a in r['citation_validation']['attempts'] if a['status']=='failed'],
        rule_counts=dict(Counter(a['rule_code'] for r in rows for a in r['citation_validation']['attempts'] if a['status']=='failed')),
        scope='Only first structural failure per generated draft; failed drafts are diagnostics, never judge candidate answers.')
    result=dict(version='qwen-twojudges-repeat-v1',source_commit=run['source_commit'],question_count=32,
        valid_grades={k:len(metrics[k]) for k in KINDS},unflagged_task_ids={k:eligible(metrics[k]) for k in KINDS},
        common_task_ids=common,comparison=summaries,all_valid_summaries=independent,
        exclusions=[dict(task_id=t,missing=[k for k in KINDS if t not in metrics[k]],
            reference_flags=[k for k in KINDS if metrics[k].get(t,{}).get('reference_concern')]) for t in sorted(set(jobs)-set(common))],
        failed_grades=failed_jobs(study,decoded),historical_jev=historical,
        disagreement_tasks={d:[t for t in common if differences[t][d]] for d in grading.POLICY['dimensions']},
        disagreement_counts={d:sum(len(differences[t][d]) for t in common) for d in grading.POLICY['dimensions']},
        runtime=runtime(list(responses.values())),answer_progress=progress,
        judges=study['requested_judges'],policy_sha256=grading.POLICY_SHA,
        judge_accounting={k:scoring.accounting(records[k],k) for k in KINDS},
        citation_diagnostics=diagnostic,
        initial_generation_input_same_as_previous=sum(r['retrieval_vs_previous']['same_initial_generation_input'] for r in rows),
        new_rewrite_api_calls=0,new_dsh_api_calls=0,new_answer_tasks=32,new_scoring_jobs=64,
        images_enabled=False,answer_guidance_enabled=False,report_model_calls=0,
        limitations=['Single paper and development set, one new answer generation per question; cannot establish generalization or stability.',
            'Luna and Jev assess the same final answers independently with the same five semantic criteria; missing grades are not zero.',
            'Historical Jev comparison includes fresh generation and fresh judging; differences are not a diagnostic-feature improvement claim.',
            'Image retrieval and visual answering disabled; no website/server deployment or configuration switch.'])
    PUBLIC.mkdir(parents=True)
    scoring.save(PUBLIC/'comparison.json',result)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'audit.json',dict(proofs=proofs,study_sha256=judge.digest(STUDY/'study.json'),
        run_sha256=judge.digest(RUN/'run.json'),contract_sha256=judge.digest(OUTPUT/'contract.json'),
        source_results={t:judge.digest(RUN/'results'/(t+'.json')) for t in sorted(jobs)},
        historical_report_sha256=judge.digest(PREVIOUS/'publication.json'),scores_changed_by_report=False,model_calls=0))
    render(result,rows)
    lines=['# Qwen文字版重跑：Jev与Luna双裁判','',
        '2026-11-02。MinerU 113块、Qwen3-VL-Embedding、双路查询、原问题重排与统一补全；图片和回答指引关闭。32题全部重新回答一次，同一份最终回答由Jev与Luna独立评分，旧答案不覆盖。','',
        f"共同有效且无标准疑点的题目：{len(common)}/32。有效评分：{judge.encode(result['valid_grades'])}。",'',
        '| 裁判 | 共同题 | 必答要点 | 事实支持 | 单引有效 | 引用组完整 | 边界/2 | 全达标 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |',
        *['| '+LABELS[k]+' | '+' | '.join(quality_cells(summaries[k]))+' |' for k in KINDS],
        '', '不计算加权总分；比例分母随实际陈述/引用数量变化。主表使用同一组共同有效题，缺失不记零；每位裁判各自全量有效题另保存在JSON中。','',
        '## 与上轮Qwen的Jev比较','',
        '| 版本 | 共同题 | 必答要点 | 事实支持 | 单引有效 | 引用组完整 | 边界/2 | 全达标 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |',
        *['| '+a+' | '+' | '.join(quality_cells(s))+' |' for a,s in historical['comparison'].items()],
        '',historical['note'],'',
        '```json',json.dumps(historical['changes'],ensure_ascii=False,indent=2),'```','',
        f"32题中{result['initial_generation_input_same_as_previous']}题首次生成输入与上轮完全相同。改写沿用封存结果，无新增改写API费用。",'',
        '## 两裁判分歧','', '```json',json.dumps(dict(tasks=result['disagreement_tasks'],counts=result['disagreement_counts']),ensure_ascii=False,indent=2),'```','',
        '完整逐项原判和Luna理由见HTML。分歧不自动由报告作者裁决，不取两裁判较高分。','',
        '## 引用校验诊断','',f"共{diagnostic['validation_attempts']}次引用校验，{len(diagnostic['failed_attempts'])}次失败。",
        f"规则计数：{judge.encode(diagnostic['rule_counts'])}",'',
        '每次只记录首先触发的规则。失败草稿与最终回答分开保存，不送进裁判上下文；旧第27/32题草稿仍不可恢复，本轮是新的独立生成。','',
        '## 用量和耗时','',f"答题：{judge.encode(result['runtime'])}",
        *[f"- {LABELS[k]}：{judge.encode(result['judge_accounting'][k])}" for k in KINDS],
        '', '端到端时间不含上轮已生成的改写；推理Token已包含在生成Token，不重复相加。供应商未返回的金额记未知，裁判费用包含无效尝试。','',
        '## 排除与范围','', '```json',json.dumps(dict(exclusions=result['exclusions'],failed_grades=result['failed_grades']),ensure_ascii=False,indent=2),'```','',
        '仅一篇论文的开发题；本轮验证诊断记录并比较两裁判，不据此宣称Embedding稳定提升。网站默认配置和服务器均未切换。','',
        '[逐题HTML、两裁判原判及失败草稿](../data/literature/qa-evaluation/reports/qwen-twojudges-20261102-r2/comparison.html)',
        '[方法](QA_QWEN_TWOJUDGES_METHOD_20261102.md)']
    DOC.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir() if p.is_file()},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    return {k:result[k] for k in ['valid_grades','comparison','historical_jev','disagreement_counts','judge_accounting']}


def render(result,rows):
    e=lambda v:escape(str(v),quote=True)
    headers=['裁判','题数','要点','事实支持','单引','引用组','边界/2','全达标']
    table='<table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in [LABELS[k],*quality_cells(result['comparison'][k])])+'</tr>' for k in KINDS)+'</table>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qwen重跑：Jev与Luna</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui}main{max-width:1300px;margin:28px auto;padding:0 18px}article,details{background:white;border:1px solid #dce5ef;border-radius:9px;padding:16px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px}summary{cursor:pointer;font-weight:600}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #e1e7ee}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair section{min-width:0}@media(max-width:800px){.pair{display:block}td,th{padding:3px;font-size:12px}}</style><main>',
        '<h1>Qwen文字版重跑：Jev与Luna独立评分</h1><p>2026-11-02 · 新答32题 · MinerU全部采用的文字优化 · 图片关闭 · 相同五项规则</p><article>'+table+
        '<p>同一份最终回答交给两裁判，不计算加权总分，不取较高分。失败草稿仅供诊断，不送入评分候选答案。</p></article>',
        '<details><summary>排除、分歧、用量和上轮对照</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>']
    for row in rows:
        parts+=['<details id="'+e(row['task_id'])+'"><summary>'+e(row['task_id']+' · '+row['question'])+'</summary>',
            '<h3>最终回答 · '+e(row['answer_status'])+'</h3><pre>'+e(row['candidate']['answer'])+'</pre>',
            '<details><summary>参考答案与评分要点</summary><pre>'+e(json.dumps(row['reference_case'],ensure_ascii=False,indent=2))+'</pre></details><div class="pair">']
        for kind in KINDS:
            data=row['judges'][kind]
            parts+=['<section><h3>'+LABELS[kind]+'</h3><pre>'+e(json.dumps(data['metrics'],ensure_ascii=False,indent=2))+'</pre>']
            review=data['review']
            if review:
                parts+=['<details><summary>逐项原判与理由</summary><table><tr><th>项目</th><th>原判</th><th>理由</th></tr>']
                for key,value in review['decisions'].items():
                    reason=review['reasons'].get(key,'Jev原生选择；未生成文字理由')
                    parts+=['<tr><td>'+e(key)+'</td><td>'+e(value)+'</td><td>'+e(reason)+'</td></tr>']
                parts+=['</table></details>']
            else:parts+=['<p>评分缺失，未记零。</p>']
            parts+=['</section>']
        parts+=['</div><details><summary>本题分歧点</summary><pre>'+e(json.dumps(row['disagreements'],ensure_ascii=False,indent=2))+'</pre></details>',
            '<details><summary>引用校验规则与失败草稿（未经校验）</summary><pre>'+e(json.dumps(row['citation_validation'],ensure_ascii=False,indent=2))+'</pre></details>',
            '<details><summary>实际引用原文及可用材料</summary><pre>'+e(json.dumps(row['candidate'],ensure_ascii=False,indent=2))+'</pre></details>',
            '<details><summary>与上轮的检索输入及Jev评分对照</summary><pre>'+e(json.dumps(dict(retrieval=row['retrieval_vs_previous'],previous=row['previous_qwen_jev']),ensure_ascii=False,indent=2))+'</pre></details></details>']
    parts+=['</main></html>']
    (PUBLIC/'comparison.html').write_text(''.join(parts),encoding='utf-8',newline='\n')


if __name__=='__main__':print(json.dumps(publish(),ensure_ascii=False))
