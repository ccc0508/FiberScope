"""Publish the fresh MinerU/Jev run and a paired historical PyMuPDF comparison."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_mineru_current_20261101 import RUN,OUTPUT,IMPORT,STUDY,HISTORY,ROOT
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/mineru-current-20261101'
DOC=ROOT/'docs/QA_MINERU_CURRENT_EVAL_20261101.md'
OLD_IMPORT=ROOT/'.rag-data/evaluations/context-v1-five-import-20261029-r1'


def paired_ids(current,baseline):
    return sorted(tid for tid in set(current)&set(baseline)
        if not current[tid]['reference_concern'] and not baseline[tid]['reference_concern'])


def usage_summary(calls):
    totals=Counter();unknown=0
    for call in calls:
        usage=call.get('usage') or {}
        if type(usage.get('total_tokens')) is not int:unknown+=1
        for target,names in [('input_tokens',['input_tokens','prompt_tokens']),
                             ('output_tokens',['output_tokens','completion_tokens']),('total_tokens',['total_tokens'])]:
            value=next((usage[n] for n in names if type(usage.get(n)) is int),None)
            if value is not None:totals[target]+=value
    return dict(calls=len(calls),known_tokens=dict(totals),total_token_unknown_calls=unknown)


def pct(value):return '不适用' if value is None else f'{value*100:.2f}%'


def fact_support(summary):
    n=sum(summary['support_counts'].values())
    return summary['support_counts'].get('supported',0)/n if n else None


def quality_cells(summary):
    return [str(summary['tasks']),pct(summary['point_macro_average']),pct(fact_support(summary)),
        pct(summary['citation_precision']['value']),pct(summary['citation_coverage']['value']),
        f"{summary['boundary_mean']:.3f}",f"{summary['all_five_pass']}/{summary['tasks']}"]


def audit_one(import_dir,study_dir):
    data=scoring.audit(import_dir,study_dir)
    meta,jobs,study,reviews,records,statuses,proofs=data
    require(all(status!='pending' for _,_,status in statuses),'Wait for active judge requests')
    jobs={j['task_id']:j for j in jobs if j['system']=='rag'}
    selected={tid:review for (kind,system,tid),review in reviews.items() if kind=='jev' and system=='rag'}
    metrics={tid:scoring.metrics(review,jobs[tid]['reference_case'],jobs[tid]['task']['capabilities']) for tid,review in selected.items()}
    return dict(meta=meta,jobs=jobs,study=study,reviews=selected,metrics=metrics,
        records=records.get('jev',[]),statuses=[dict(judge=k,system=s,status=t,count=n) for (k,s,t),n in statuses.items()],proofs=proofs)


def publish():
    require(not PUBLIC.exists() and not DOC.exists(),'Preserve existing publication')
    new=audit_one(IMPORT,STUDY);old=audit_one(OLD_IMPORT,HISTORY)
    require(set(new['jobs'])==set(old['jobs'])=={f'PFI2-{i:03}' for i in range(1,33)},'Question set changed')
    require(new['study']['policy_sha256']==old['study']['policy_sha256']==grading.POLICY_SHA,'Scoring rules differ')
    require(new['study']['requested_judges']['jev']==old['study']['requested_judges']['jev'],'Jev settings differ')
    for tid,job in new['jobs'].items():
        require(job['reference_case']==old['jobs'][tid]['reference_case'],'Reference case changed')
        require(job['task']==old['jobs'][tid]['task'],'Task capabilities changed')
    common=paired_ids(new['metrics'],old['metrics']);require(common,'No common unflagged grades')
    eligible=sorted(t for t,m in new['metrics'].items() if not m['reference_concern'])
    require(eligible,'No unflagged current grades')
    summaries={k:scoring.summarize([data['metrics'][t] for t in common]) for k,data in [('current',new),('baseline',old)]}
    all_current=scoring.summarize([new['metrics'][t] for t in eligible])
    changed={key:[] for key in ['point_wins','point_losses','joint_wins','joint_losses']}
    for tid in common:
        a,b=new['metrics'][tid],old['metrics'][tid]
        if a['point_mean']>b['point_mean']:changed['point_wins'].append(tid)
        if a['point_mean']<b['point_mean']:changed['point_losses'].append(tid)
        if a['all_five_pass'] and not b['all_five_pass']:changed['joint_wins'].append(tid)
        if b['all_five_pass'] and not a['all_five_pass']:changed['joint_losses'].append(tid)
    run=judge.read_json(RUN/'run.json');progress=judge.read_json(RUN/'progress.json')
    require(progress['completed']==32 and progress['status']=='completed','Answers incomplete')
    answer_rows=[judge.read_json(RUN/'results'/(tid+'.json')) for tid in sorted(new['jobs'])]
    generations=[];reranks=[];embeddings=[];durations=[]
    for row in answer_rows:
        response=row['response'];cfg=response['configuration'];ctx=response['context_assembly']
        require(cfg['pipeline_version']=='mineru-unified-rerank-v1' and 'answer_guidance' not in cfg,'Unexpected runtime/answer guidance')
        require(ctx['assembly_passes']==1 and ctx['candidate_roots_only'] and not ctx['post_context_expansion'],'Expansion changed')
        generations.extend(response['generation_calls']);reranks.extend(response['rerank_calls'])
        embeddings.append(dict(usage=response['embedding_usage']));durations.append(row['end_to_end_ms']/1000)
    runtime=dict(answer_outcomes=progress['outcomes'],median_end_to_end_seconds=statistics.median(durations),
        generation=usage_summary(generations),rerank=usage_summary(reranks),question_embedding=usage_summary(embeddings),
        generation_currency_cost=None,rerank_currency_cost=None,embedding_currency_cost=None)
    result=dict(version='mineru-current-evaluation-20261101',source_commit=run['source_commit'],
        valid_current_grades=len(new['metrics']),eligible_current_task_ids=eligible,current_summary=all_current,
        common_task_ids=common,comparison=summaries,changes=changed,
        excluded=[dict(task_id=t,current_valid=t in new['metrics'],baseline_valid=t in old['metrics'],
            current_reference_concern=new['metrics'].get(t,{}).get('reference_concern'),
            baseline_reference_concern=old['metrics'].get(t,{}).get('reference_concern')) for t in new['jobs'] if t not in common],
        runtime=runtime,judge_accounting=scoring.accounting(new['records'],'jev'),judge_statuses=new['statuses'],
        configuration=run['configuration_probe'],judge=new['study']['requested_judges']['jev'],
        scoring_policy_sha256=grading.POLICY_SHA,comparison_kind='historical_not_newly_generated_control',
        generated_questions=32,new_luna_calls=0,new_dsh_calls=0,answer_guidance_enabled=False)
    rows=[]
    for tid,job in sorted(new['jobs'].items()):
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference_answer=job['reference_case']['reference_answer'],
            key_points=job['reference_case']['key_points'],critical_errors=job['reference_case']['critical_errors'],
            current=dict(candidate=job['candidate'],review=new['reviews'].get(tid),metrics=new['metrics'].get(tid)),
            baseline=dict(candidate=old['jobs'][tid]['candidate'],review=old['reviews'].get(tid),metrics=old['metrics'].get(tid))))
    PUBLIC.mkdir(parents=True)
    judge.write(PUBLIC/'comparison.json',result)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(row)+'\n' for row in rows),encoding='utf-8',newline='\n')
    judge.write(PUBLIC/'audit.json',dict(new_valid_records=new['proofs'],old_valid_records=old['proofs'],
        source_run_sha256=judge.digest(RUN/'run.json'),source_study_sha256=judge.digest(STUDY/'study.json'),
        source_import_sha256=judge.digest(IMPORT/'import.json'),old_study_sha256=judge.digest(HISTORY/'study.json'),
        grader_harness=new['study']['harness_files'],scores_changed_by_exporter=False,report_model_calls=0))
    render_html(result,rows)
    headers=['版本','共同题','必答要点','事实完全支持','单条引用有效','引用组完整','边界/2','五项全达标']
    lines=['# 当前MinerU组合版本：32题Jev评测','',
        '2026-11-01。新增32题独立答题，只用Jev原五维规则评分。正文/表格/公式小节补全、表格行检索、BGE重排、主命中候选统一预算全部启用；回答指引关闭。',
        '',f"32题答题状态：{progress['outcomes']}。首次有效Jev评分{len(new['metrics'])}/32；当前无标准答案疑点的有效题{len(eligible)}题。无效评分不计零，不计算加权总分。",'',
        '## 与历史PyMuPDF结构81块比较','',
        '| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',
        '| 历史PyMuPDF81块 | '+' | '.join(quality_cells(summaries['baseline']))+' |',
        '| 当前MinerU113块组合 | '+' | '.join(quality_cells(summaries['current']))+' |','',
        '此为历史结果复用对比，未为旧版重新答题或评分。共同题排除缺失/参考标准被标记的评分；日期、远端模型别名与随机输出等变化未完全控制，不能把差异归因于单独某项优化，也不能据一轮证明稳定提升。',
        '',f"排除：{judge.encode(result['excluded'])}",'',
        '## 本轮全部有效题','',
        '| 版本 | '+' | '.join(headers[1:])+' |','| '+' | '.join(['---']*len(headers))+' |',
        '| 当前MinerU组合 | '+' | '.join(quality_cells(all_current))+' |','',
        '上表与共同题对照分母可能不同；事实与引用的分母还会随实际陈述数量变化。五项全达标要求必答点全覆盖、陈述支持、适用引用/引用组达标及边界2分，不是新的加权分数。','',
        '## 逐题变化','',*[f"- {key}：{', '.join(value) or '无'}" for key,value in changed.items()],
        '', '上述变化均取Jev首次有效原判；导出器没有替代模型打分。完整问题、参考标准、两版回答、引用与评分见HTML和JSONL。','',
        '## 用量和耗时','',f"- 答题端到端中位耗时：{runtime['median_end_to_end_seconds']:.2f}秒/题（含进程、检索、重排、生成）。",
        f"- 生成：{judge.encode(runtime['generation'])}",f"- 重排：{judge.encode(runtime['rerank'])}",
        f"- 问题Embedding：{judge.encode(runtime['question_embedding'])}",f"- Jev全部评分尝试及费用：{judge.encode(result['judge_accounting'])}",
        '- 推理Token已包含在生成Token中，不重复相加。供应商没有返回的货币结算金额记为未知；Jev费用包含无效尝试。','',
        '## 封存与范围','',
        f"答题源提交：`{run['source_commit']}`。从独立干净检出冻结代码、113块索引、原PDF、原32题及配置，未修改用户正在编辑的前端文件。每题新进程，不带历史回答、评分或参考答案；裁判使用原协议独立上下文，不接收旧分。",
        '', '旧导入器的数据格式包含历史DSH答案，仅为兼容导入而复制；本轮只对新RAG答案创建32个Jev任务，没有新增DSH或Luna调用。网站默认配置及服务器均未切换。','',
        '[逐题HTML报告](../data/literature/qa-evaluation/reports/mineru-current-20261101/comparison.html)',
        '[机器可读结果](../data/literature/qa-evaluation/reports/mineru-current-20261101/comparison.json)']
    DOC.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    judge.write(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir() if p.is_file()},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),report_model_calls=0))
    return {k:result[k] for k in ['valid_current_grades','current_summary','comparison','changes','judge_accounting','runtime']}


def render_html(result,rows):
    esc=lambda v:escape(str(v),quote=True)
    headers=['版本','题数','必答要点','事实支持','单引有效','引用组完整','边界/2','五项全达标']
    table=['<table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>']
    for label,key in [('历史PyMuPDF81块','baseline'),('当前MinerU113块组合','current')]:
        table.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [label,*quality_cells(result['comparison'][key])])+'</tr>')
    table.append('</table>')
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>当前MinerU组合版本：32题评测</title><style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui}main{max-width:1250px;margin:32px auto;padding:0 20px}article,details{background:white;border:1px solid #dce5ef;border-radius:10px;padding:18px;margin:16px 0}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #e6edf4}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px}summary{cursor:pointer;font-weight:600}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:800px){.pair{display:block}table{font-size:12px}td,th{padding:5px}}</style><main>',
        '<h1>当前MinerU组合版本：32题Jev评测</h1><p>2026-11-01 · 回答指引关闭 · 表格行检索、重排与统一补全启用</p>',
        '<article><h2>共同有效题对照</h2>'+''.join(table)+'<p>历史对照复用旧回答和评分；没有新增旧版答题。不计算加权总分，缺失不记零。分数不能直接归因于某个单独优化。</p></article>',
        '<details><summary>本轮有效题、排除项与用量</summary><pre>'+esc(json.dumps({k:result[k] for k in ['valid_current_grades','current_summary','excluded','changes','runtime','judge_accounting']},ensure_ascii=False,indent=2))+'</pre></details>']
    for row in rows:
        tid=row['task_id'];score=row['current']['metrics'];label=pct(score['point_mean']) if score else '评分缺失'
        html.append('<details id="'+esc(tid)+'"><summary>'+esc(tid+' · '+label+' · '+row['question'])+'</summary>')
        html.append('<h3>参考答案与必答要点</h3><pre>'+esc(json.dumps({k:row[k] for k in ['reference_answer','key_points','critical_errors']},ensure_ascii=False,indent=2))+'</pre><div class="pair">')
        for name,key in [('当前MinerU组合','current'),('历史PyMuPDF81块','baseline')]:
            data=row[key]
            html.append('<section><h3>'+name+'</h3><pre>'+esc(data['candidate']['answer'])+'</pre><p>要点：'+
                (pct(data['metrics']['point_mean']) if data['metrics'] else '无有效评分')+'</p><details><summary>Jev原判与引用原文</summary><pre>'+esc(json.dumps(data,ensure_ascii=False,indent=2))+'</pre></details></section>')
        html.append('</div></details>')
    html.append('</main></html>')
    (PUBLIC/'comparison.html').write_text(''.join(html),encoding='utf-8',newline='\n')


if __name__=='__main__':print(json.dumps(publish(),ensure_ascii=False))
