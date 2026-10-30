"""Offline, paired three-round RAG stability analysis. Never calls a provider or changes grades.

Input: {version, records:[{system, round, task_id, reference_case, candidate,
review, metrics?, capabilities?, grading_status?}], runtimes:[{system,round,...}],
accounting:{...}, controls:{...}, provenance:{...}, limitations:[...]}. Every task
must have an explicit record in each of content/rerank x rounds 1/2/3. A missing
or invalid judgment is represented by review:null and metrics:null, never zero.
"""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
from html import escape
import json
from math import isfinite
from pathlib import Path
import statistics

import report_qa_system_benchmark as scoring

VERSION='rerank-stability-report-v1'
SYSTEMS=('content','rerank')
ROUNDS=(1,2,3)
LABELS={'content':'85块纯向量排序','rerank':'85块＋候选重排'}
QUALITY_KEYS=('point_macro_average','fact_support_rate','citation_precision_rate',
              'citation_coverage_rate','boundary_mean','all_five_pass_rate')
QUALITY_LABELS=('必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项全部达标率')
DIMENSION_LABELS={'key_points':'必答要点','claim_support':'事实支持','citation_support':'单条引用',
                  'citation_group_coverage':'引用组完整','answerability':'边界'}


def require(condition,message):
    if not condition:raise ValueError(message)


def numeric(value):
    return type(value) in (int,float) and isfinite(value)


def series(values):
    """Descriptive variation across rounds; undefined rates stay undefined, never zero."""
    valid=[v for v in values if v is not None]
    require(all(numeric(v) for v in valid),'Nonfinite statistic')
    return dict(values=values,n=len(valid),mean=statistics.mean(valid) if valid else None,
        sample_sd=statistics.stdev(valid) if len(valid)>1 else None,
        minimum=min(valid) if valid else None,maximum=max(valid) if valid else None,
        range=max(valid)-min(valid) if valid else None)


def checked_records(payload):
    require(isinstance(payload,dict) and isinstance(payload.get('records'),list),'records must be a list')
    records={};standards={}
    for row in payload['records']:
        system,round_id,tid=row.get('system'),row.get('round'),row.get('task_id')
        require(system in SYSTEMS and type(round_id) is int and round_id in ROUNDS,'Unexpected system or round')
        require(isinstance(tid,str) and bool(tid),'Missing task ID')
        key=(system,round_id,tid);require(key not in records,'Duplicate system/round/task record')
        reference=row.get('reference_case');candidate=row.get('candidate')
        require(isinstance(reference,dict) and isinstance(reference.get('question'),str),'Missing reference question')
        require(isinstance(candidate,dict) and isinstance(candidate.get('answer'),str),'Missing candidate answer')
        if tid in standards:require(standards[tid]==reference,'Reference standard changed between rounds')
        else:standards[tid]=reference
        review=row.get('review');metric=row.get('metrics')
        if review is None:require(metric is None,'Missing grade must not have numeric metrics')
        else:
            expected=scoring.metrics(review,reference,row.get('capabilities',['text']))
            if metric is not None:require(metric==expected,'Metrics differ from original judge decisions')
            metric=expected
        records[key]={**row,'metrics':metric}
    tids=sorted(standards)
    require(bool(tids),'No question records')
    require(set(records)=={(s,r,t) for s in SYSTEMS for r in ROUNDS for t in tids},
        'Every task needs six explicit records; represent missing judgments with null')
    return records,tids,standards


def exclusion(records,tid,cells):
    missing=[]
    for system,round_id in cells:
        row=records[(system,round_id,tid)];metric=row['metrics']
        if metric is None or metric['reference_concern']:
            missing.append(dict(system=system,round=round_id,
                reason='reference_concern' if metric else row.get('grading_status') or 'no_valid_grade'))
    return dict(task_id=tid,excluded_cells=missing)


def subset(records,tids,cells):
    selected=[];excluded=[]
    for tid in tids:
        why=exclusion(records,tid,cells)
        if why['excluded_cells']:excluded.append(why)
        else:selected.append(tid)
    return selected,excluded


def summary(metrics):
    if not metrics:return None
    out=scoring.summarize(metrics)
    facts=sum(out['support_counts'].values())
    out.update(fact_support_rate=out['support_counts'].get('supported',0)/facts if facts else None,
        citation_precision_rate=out['citation_precision']['value'],
        citation_coverage_rate=out['citation_coverage']['value'],
        all_five_pass_rate=out['all_five_pass']/out['tasks'])
    return out


def round_pair(records,tids,round_id):
    scores={s:summary([records[(s,round_id,t)]['metrics'] for t in tids]) for s in SYSTEMS}
    deltas={k:(scores['rerank'][k]-scores['content'][k]
        if scores['rerank'] and scores['content'] and scores['rerank'][k] is not None and scores['content'][k] is not None else None)
        for k in QUALITY_KEYS}
    return dict(round=round_id,tasks=len(tids),task_ids=tids,scores=scores,deltas=deltas,
        point_wins=[t for t in tids if records[('rerank',round_id,t)]['metrics']['point_mean']>records[('content',round_id,t)]['metrics']['point_mean']],
        point_losses=[t for t in tids if records[('rerank',round_id,t)]['metrics']['point_mean']<records[('content',round_id,t)]['metrics']['point_mean']],
        all_five_wins=[t for t in tids if records[('rerank',round_id,t)]['metrics']['all_five_pass'] and not records[('content',round_id,t)]['metrics']['all_five_pass']],
        all_five_losses=[t for t in tids if records[('content',round_id,t)]['metrics']['all_five_pass'] and not records[('rerank',round_id,t)]['metrics']['all_five_pass']])


def stability(records,tids):
    rounds=[round_pair(records,tids,r) for r in ROUNDS]
    by_system={s:{k:series([p['scores'][s][k] if p['scores'][s] else None for p in rounds])
        for k in QUALITY_KEYS} for s in SYSTEMS}
    for system in SYSTEMS:
        by_system[system]['all_five_pass_count']=series([p['scores'][system]['all_five_pass'] if p['scores'][system] else None for p in rounds])
    deltas={k:series([p['deltas'][k] for p in rounds]) for k in QUALITY_KEYS}
    points=deltas['point_macro_average']['values']
    return dict(tasks=len(tids),task_ids=tids,rounds=rounds,by_system=by_system,deltas=deltas,
        point_direction_counts=dict(higher=sum(v is not None and v>0 for v in points),
            equal=sum(v==0 for v in points if v is not None),lower=sum(v is not None and v<0 for v in points)))


def per_question(records,tids,standards):
    result=[]
    for tid in tids:
        systems={}
        for s in SYSTEMS:
            values=[records[(s,r,tid)] for r in ROUNDS]
            valid=[(r,v) for r,v in zip(ROUNDS,values,strict=True) if v['metrics'] is not None and not v['metrics']['reference_concern']]
            failures=Counter()
            for _,row in valid:
                m=row['metrics'];review=row['review']
                if m['point_mean']<1:failures['key_points']+=1
                if any(c['support']!='supported' for c in review['claim_assessments']):failures['claim_support']+=1
                if m['supported_citations']<m['factual_citations']:failures['citation_support']+=1
                if m['complete_groups']<m['factual_claims']:failures['citation_group_coverage']+=1
                if m['boundary']<2:failures['answerability']+=1
            systems[s]=dict(valid_rounds=[r for r,_ in valid],missing_or_flagged_rounds=[r for r,v in zip(ROUNDS,values,strict=True) if v['metrics'] is None or v['metrics']['reference_concern']],
                point_scores=[v['metrics']['point_mean'] if v['metrics'] and not v['metrics']['reference_concern'] else None for v in values],
                all_five_passes=sum(v['metrics']['all_five_pass'] for _,v in valid),
                non_pass_rounds=[r for r,v in valid if not v['metrics']['all_five_pass']],
                failure_dimensions=dict(failures),recurrent_failure_dimensions={k:n for k,n in failures.items() if n>=2},
                point_variation=series([v['metrics']['point_mean'] if v['metrics'] and not v['metrics']['reference_concern'] else None for v in values]))
        result.append(dict(task_id=tid,question=standards[tid]['question'],systems=systems))
    return result


def runtime_analysis(payload):
    index={}
    for row in payload.get('runtimes',[]):
        key=(row.get('system'),row.get('round'))
        require(key[0] in SYSTEMS and type(key[1]) is int and key[1] in ROUNDS,'Unexpected runtime cell')
        require(key not in index,'Duplicate runtime cell');index[key]=row
    outputs={}
    for s in SYSTEMS:
        cells=[index.get((s,r)) for r in ROUNDS]
        outputs[s]=dict(median_end_to_end_seconds=series([v.get('median_end_to_end_seconds') if v else None for v in cells]),
            generation_calls=series([v.get('generation_calls') if v else None for v in cells]),
            generation_total_tokens=series([(v.get('generation_known_tokens') or {}).get('total_tokens') if v else None for v in cells]),
            per_round=cells)
    # These are descriptive differences of each run's median, not paired per-question latency.
    outputs['median_latency_delta_seconds']=series([
        (index[('rerank',r)]['median_end_to_end_seconds']-index[('content',r)]['median_end_to_end_seconds'])
        if ('rerank',r) in index and ('content',r) in index and
        numeric(index[('rerank',r)].get('median_end_to_end_seconds')) and numeric(index[('content',r)].get('median_end_to_end_seconds')) else None
        for r in ROUNDS])
    return outputs


def analyze(payload):
    records,tids,standards=checked_records(payload)
    own_rounds=[]
    for r in ROUNDS:
        selected,excluded=subset(records,tids,[(s,r) for s in SYSTEMS])
        own_rounds.append({**round_pair(records,selected,r),'exclusions':excluded})
    fixed_ids,fixed_exclusions=subset(records,tids,[(s,r) for s in SYSTEMS for r in ROUNDS])
    fixed=stability(records,fixed_ids);fixed['exclusions']=fixed_exclusions
    questions=per_question(records,tids,standards)
    caveats=[
        '主比较在六个版本×轮次组合均有有效、无参考答案疑问的固定共同题上计算。各轮最大配对另列，不用于计算跨轮波动。',
        '均值为三轮指标等权平均，SD为轮次间样本标准差；这是重复运行的描述统计，不是置信区间、统计显著性或新论文泛化证明。',
        '同一32题为开发集；重复生成和一次首个有效Jev判定混合了回答与裁判波动，没有单独识别两者贡献。',
        '第一轮为历史运行；新增两轮采用按题近同时运行两版，调度、缓存、网络和远端服务变化会影响延迟与用量。',
        '未知费用不记零；推理Token已包含于生成Token，不再重复相加。所有语义分数保留Jev原判定，不生成新的裁判理由。',
    ]
    sensitivity=None
    if 'PFI2-011' in tids:
        caveats.append('原轮1第11题未明确列出所要求的4000→8000转数值反例却被Jev判为满分，存在高估可能；原分不改。统一移除第11题的敏感性分析不替换主比较，也不能替代专家核验。')
        if 'PFI2-011' in fixed_ids:sensitivity=stability(records,[t for t in fixed_ids if t!='PFI2-011'])
        else:caveats.append('第11题已因缺失或参考疑问排除在固定共同题之外，不再额外计算相同题集的移除分析。')
    for system,tid in [('content','PFI2-024'),('rerank','PFI2-023')]:
        if (system,1,tid) in records and records[(system,1,tid)]['metrics'] is None:
            caveats.append(f'历史第1轮{LABELS[system]}的{tid}无有效评分，继续保留为缺失，不重评、不记零。')
    caveats+=payload.get('limitations',[])
    directions=fixed['point_direction_counts'];delta=fixed['deltas']['point_macro_average']['mean']
    conclusion=('没有共同有效题，无法比较。' if delta is None else
        f"本次重复没有证明重排稳定优于纯向量：固定{fixed['tasks']}题，重排要点分较高{directions['higher']}轮、较低{directions['lower']}轮、相同{directions['equal']}轮；三轮平均差值{delta*100:+.2f}个百分点。"
        if directions['lower'] else
        f"固定{fixed['tasks']}题，重排要点分三轮平均差值{delta*100:+.2f}个百分点；三轮结果仍只支持描述性结论。")
    return dict(version=VERSION,input_version=payload.get('version'),question_count=len(tids),expected_rounds=list(ROUNDS),
        conclusion=conclusion,analyst_notes=payload.get('analyst_notes',[]),
        per_round_maximum_pairs=own_rounds,fixed_common=fixed,
        sensitivity_without_pfi2_011=sensitivity,questions=questions,runtime=runtime_analysis(payload),
        accounting=payload.get('accounting',{}),controls=payload.get('controls',{}),provenance=payload.get('provenance',{}),
        limitations=list(dict.fromkeys(caveats)),missing_not_zero=True,no_weighted_grand_score=True,
        all_grades_from_input=True,model_calls_by_reporter=0)


def percent(value):return '未知' if value is None else f'{value*100:.2f}%'


def value_text(value,key):
    if value is None:return '未知'
    if key=='boundary_mean':return f'{value:.3f}'
    return percent(value)


def stat_text(stats,key):
    if stats['mean'] is None:return '未知（0轮）'
    sd='未知' if stats['sample_sd'] is None else value_text(stats['sample_sd'],key)
    return f"{value_text(stats['mean'],key)} ± {sd}；{value_text(stats['minimum'],key)}—{value_text(stats['maximum'],key)}（{stats['n']}轮）"


def quality_cells(system,score):
    if score is None:return [LABELS[system]]+['无共同有效题']*7
    return [LABELS[system],score['tasks'],*[value_text(score[k],k) for k in QUALITY_KEYS[:-1]],f"{score['all_five_pass']}/{score['tasks']} ({percent(score['all_five_pass_rate'])})"]


def table(headers,rows):
    e=lambda v:escape(str(v),quote=True)
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def html_report(path,result,payload):
    records,tids,standards=checked_records(payload);e=lambda v:escape(str(v),quote=True)
    json_html=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))+'</pre>'
    fixed=result['fixed_common'];headers=['版本','题数',*QUALITY_LABELS[:-1],'五项全部达标']
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAG重排稳定性：两版各三轮</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1440px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}p{overflow-wrap:anywhere}.warn{border-left:4px solid #be7b18;padding-left:12px}</style><main>',
        '<h1>RAG重排稳定性：两版各三轮</h1><p>保留历史第1轮，优化前与优化后各新增2轮。每题独立请求；本报告只汇总已提供的Jev判定，不调用模型、不改分。</p>',
        '<section class="warn"><h2>本轮结论</h2><p>'+e(result['conclusion'])+'</p>'+''.join('<p>'+e(n)+'</p>' for n in result['analyst_notes'])+'</section>',
        '<section><h2>固定共同题：跨轮主比较</h2><p>六个版本×轮次组合共同有效题：'+str(fixed['tasks'])+'/'+str(result['question_count'])+'。以下三轮平均与波动均使用这同一批题。</p>',
        table(['指标','纯向量：均值±样本SD；范围','重排：均值±样本SD；范围','逐轮差值的均值±样本SD；范围'],
            [[label,stat_text(fixed['by_system']['content'][key],key),stat_text(fixed['by_system']['rerank'][key],key),stat_text(fixed['deltas'][key],key)] for key,label in zip(QUALITY_KEYS,QUALITY_LABELS,strict=True)]),
        '<p>百分比指标的差值及SD以百分点理解；边界指标以分理解。SD只描述三个轮次间的波动，不表示统计显著性。</p>',
        '<p>固定题集上，重排要点分较高 '+str(fixed['point_direction_counts']['higher'])+' 轮，相同 '+str(fixed['point_direction_counts']['equal'])+' 轮，较低 '+str(fixed['point_direction_counts']['lower'])+' 轮。</p>',
        '<details><summary>固定共同题与全部排除原因</summary>'+json_html(dict(task_ids=fixed['task_ids'],exclusions=fixed['exclusions']))+'</details></section>']
    for r in fixed['rounds']:
        h+=['<section><h2>第'+str(r['round'])+'轮 · 固定共同题</h2>',table(headers,[quality_cells(s,r['scores'][s]) for s in SYSTEMS]),
            '<p>要点提高：'+e(r['point_wins'])+'；下降：'+e(r['point_losses'])+'。</p><p>新增全部达标：'+e(r['all_five_wins'])+'；失去全部达标：'+e(r['all_five_losses'])+'。</p></section>']
    h+=['<section><h2>每轮最大配对（补充）</h2><p>每轮题数可以不同，不能把这些分数的波动当作同一题集的稳定性。</p>']
    for r in result['per_round_maximum_pairs']:
        h+=['<h3>第'+str(r['round'])+'轮：'+str(r['tasks'])+'题</h3>',table(headers,[quality_cells(s,r['scores'][s]) for s in SYSTEMS]),
            '<details><summary>本轮题集与排除原因</summary>'+json_html(dict(task_ids=r['task_ids'],exclusions=r['exclusions']))+'</details>']
    h+=['</section><section><h2>需要持续检查的题目</h2><p>失分次数以有效、无参考疑问的轮次为分母；缺失和待复核不算失败。</p>',
        table(['题号','版本','有效轮数','三轮要点分','五项全达标次数','反复失分维度（至少2轮）'],
            [[q['task_id'],LABELS[s],len(q['systems'][s]['valid_rounds']),', '.join(percent(v) for v in q['systems'][s]['point_scores']),
              str(q['systems'][s]['all_five_passes'])+'/'+str(len(q['systems'][s]['valid_rounds'])),
              '；'.join(DIMENSION_LABELS[k]+'×'+str(n) for k,n in q['systems'][s]['recurrent_failure_dimensions'].items()) or '无']
             for q in result['questions'] for s in SYSTEMS if q['systems'][s]['recurrent_failure_dimensions'] or q['systems'][s]['missing_or_flagged_rounds']]),'</section>']
    if sensitivity:=result['sensitivity_without_pfi2_011']:
        h+=['<section class="warn"><h2>第11题评分疑问：敏感性分析</h2><p>统一从固定共同题移除第11题，保留其原分和原回答；此处是补充分析，不替换主比较。</p>',
            table(['指标','纯向量','重排','逐轮差值'],[[label,stat_text(sensitivity['by_system']['content'][key],key),stat_text(sensitivity['by_system']['rerank'][key],key),stat_text(sensitivity['deltas'][key],key)] for key,label in zip(QUALITY_KEYS,QUALITY_LABELS,strict=True)]),'</section>']
    h+=['<section><h2>耗时与费用</h2><p>耗时统计使用每轮全部问题，与质量固定共同题的分母不同。历史第1轮与新增成对运行的调度方式不同；以下是各轮中位耗时的描述统计。</p>',
        table(['版本','第1轮中位秒','第2轮中位秒','第3轮中位秒','三轮均值秒','样本SD秒'],
            [[LABELS[s],*[('未知' if v is None else f'{v:.3f}') for v in result['runtime'][s]['median_end_to_end_seconds']['values']],
              '未知' if result['runtime'][s]['median_end_to_end_seconds']['mean'] is None else f"{result['runtime'][s]['median_end_to_end_seconds']['mean']:.3f}",
              '未知' if result['runtime'][s]['median_end_to_end_seconds']['sample_sd'] is None else f"{result['runtime'][s]['median_end_to_end_seconds']['sample_sd']:.3f}"] for s in SYSTEMS]),
        '<details><summary>已知Token、调用、费用与未知项（历史/新增按输入原样保留）</summary>'+json_html(dict(runtime=result['runtime'],accounting=result['accounting']))+'</details></section>',
        '<section class="warn"><h2>解释边界</h2>'+''.join('<p>'+e(n)+'</p>' for n in result['limitations'])+'</section>',
        '<details><summary>控制变量与来源记录</summary>'+json_html(dict(controls=result['controls'],provenance=result['provenance']))+'</details>',
        '<h2>全部'+str(len(tids))+'题：参考答案、每轮回答与Jev判定</h2><input id="search" placeholder="搜索题号或问题">']
    for tid in tids:
        h+=['<article data-search="'+e(tid+' '+standards[tid]['question'])+'"><h2>'+e(tid)+' · '+e(standards[tid]['question'])+'</h2>',
            '<details><summary>参考答案与评分准则</summary>'+json_html(standards[tid])+'</details>']
        for r in ROUNDS:
            h+=['<details><summary>第'+str(r)+'轮 · 两版回答与评分</summary>']
            for s in SYSTEMS:
                row=records[(s,r,tid)];m=row['metrics']
                label='有效评分缺失' if m is None else ('参考标准需复核' if m['reference_concern'] else f"要点 {m['required_point_sum']}/{m['required_point_count']}；边界 {m['boundary']}/2")
                h+=['<details><summary>'+e(LABELS[s])+' · '+e(label)+'</summary><p>'+e(row['candidate']['answer']).replace('\n','<br>')+'</p>',
                    '<details><summary>Jev逐项判定（原样保留）</summary>'+json_html(dict(metrics=m,review=row['review'],grading_status=row.get('grading_status')))+'</details>',
                    '<details><summary>原回答、引用与实际上下文</summary>'+json_html(row['candidate'])+'</details></details>']
            h+=['</details>']
        h+=['</article>']
    h+=['<script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(h),encoding='utf-8',newline='\n')


def markdown(result):
    fixed=result['fixed_common']
    lines=['# RAG候选重排稳定性：两版各三轮','',
        f"保留历史第1轮，两版各新增2轮。原{result['question_count']}题中，六个版本×轮次组合固定共同有效题{fixed['tasks']}题。",'',
        result['conclusion'],'',*sum(([n,''] for n in result['analyst_notes']),[]),
        '主比较使用固定共同题；缺失不记零，不计算加权总分。三轮等权均值与样本SD是描述统计，不是置信区间。','',
        '| 指标 | 纯向量均值±样本SD；范围 | 重排均值±样本SD；范围 | 逐轮差值均值±样本SD；范围 |',
        '| --- | --- | --- | --- |']
    for key,label in zip(QUALITY_KEYS,QUALITY_LABELS,strict=True):
        lines.append('| '+' | '.join([label,stat_text(fixed['by_system']['content'][key],key),stat_text(fixed['by_system']['rerank'][key],key),stat_text(fixed['deltas'][key],key)])+' |')
    lines+=['','百分比指标的SD与差值以“百分点”理解。','',
        '## 同一固定题集的逐轮结果','','| 轮次 | 纯向量要点 | 重排要点 | 差值/百分点 | 纯向量全达标 | 重排全达标 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in fixed['rounds']:
        a,b=[r['scores'][s] for s in SYSTEMS]
        if a and b:lines.append(f"| {r['round']} | {percent(a['point_macro_average'])} | {percent(b['point_macro_average'])} | {r['deltas']['point_macro_average']*100:+.2f} | {a['all_five_pass']}/{fixed['tasks']} | {b['all_five_pass']}/{fixed['tasks']} |")
    lines+=['','各轮最大配对仅作补充，不用其不同题集计算波动。','']
    for r in result['per_round_maximum_pairs']:
        lines+=['## 第'+str(r['round'])+'轮最大配对','',f"共同有效{r['tasks']}题。",'',
            '| 版本 | 题数 | 必答要点 | 事实支持 | 单条引用 | 引用组完整 | 边界/2 | 五项全达标 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        lines+=['| '+' | '.join(map(str,quality_cells(s,r['scores'][s])))+' |' for s in SYSTEMS]
        lines+=['','排除：'+json.dumps(r['exclusions'],ensure_ascii=False)+'。','']
    if sensitivity:=result['sensitivity_without_pfi2_011']:
        lines+=['## 第11题敏感性分析','',f"从固定共同题统一移除第11题后剩{sensitivity['tasks']}题。原分不改，不替换主比较。",'',
            '要点逐轮差值：'+json.dumps(sensitivity['deltas']['point_macro_average'],ensure_ascii=False)+'。','']
    lines+=['## 耗时与费用','','| 版本 | 第1轮中位秒 | 第2轮中位秒 | 第3轮中位秒 | 三轮中位数的平均/秒 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for s in SYSTEMS:
        v=result['runtime'][s]['median_end_to_end_seconds']
        lines.append('| '+' | '.join([LABELS[s],*[('未知' if x is None else f'{x:.2f}') for x in v['values']],
            '未知' if v['mean'] is None else f"{v['mean']:.2f}"])+' |')
    new=result['accounting'].get('new',{});jev=new.get('jev',{})
    if jev:lines+=['',f"新增Jev请求{jev['calls']}次，API报告费用${jev['reported_cost_usd']}，费用未知{jev['cost_unknown_calls']}次。历史请求未重做，历史费用另存。"]
    lines+=['','延迟使用每轮全部题，质量使用固定共同题。未知费用保留未知；输入/输出用量按原记录，不推测货币价格。','',
        '## 解释边界','',*sum(([n,''] for n in result['limitations']),[]),
        '[全部32题、六份回答与原Jev判定](../data/literature/qa-evaluation/reports/rerank-stability-20261031/comparison.html)。',
        '[完整计算、用量、控制变量与来源指纹](../data/literature/qa-evaluation/reports/rerank-stability-20261031/comparison.json)。',
        '[实验方法与独立上下文说明](QA_RERANK_STABILITY_METHOD_20261031.md)。','']
    return '\n'.join(lines)


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def publish(input_path,output_dir,document_path=None,refresh=False):
    input_path,output_dir=Path(input_path),Path(output_dir)
    document_path=Path(document_path) if document_path else None
    digest=lambda p:sha256(Path(p).read_bytes()).hexdigest()
    if refresh:
        seal=json.loads((output_dir/'publication.json').read_text('utf-8'))
        require(all(digest(output_dir/n)==h for n,h in seal['files'].items()),'Existing report bytes changed')
        if document_path:require(digest(document_path)==seal['document_sha256'],'Existing document changed')
    else:
        require(not output_dir.exists(),'Report output exists; use refresh after seal verification')
        if document_path:require(not document_path.exists(),'Document exists')
    payload=json.loads(input_path.read_text('utf-8'));result=analyze(payload)
    output_dir.mkdir(parents=True,exist_ok=refresh)
    save(output_dir/'comparison.json',result)
    records,tids,standards=checked_records(payload)
    rows=[dict(task_id=t,reference_case=standards[t],records=[records[(s,r,t)] for r in ROUNDS for s in SYSTEMS]) for t in tids]
    (output_dir/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    html_report(output_dir/'comparison.html',result,payload)
    if document_path:
        document_path.parent.mkdir(parents=True,exist_ok=True);document_path.write_text(markdown(result),encoding='utf-8',newline='\n')
    save(output_dir/'publication.json',dict(version=VERSION,input_sha256=digest(input_path),
        exporter_sha256=digest(Path(__file__)),document_sha256=digest(document_path) if document_path else None,
        files={p.name:digest(p) for p in output_dir.iterdir() if p.is_file() and p.name!='publication.json'},model_calls=0))
    return result


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=root/'.rag-data/evaluations/rerank-stability-20261031/report-input.json')
    parser.add_argument('--output',type=Path,default=root/'data/literature/qa-evaluation/reports/rerank-stability-20261031')
    parser.add_argument('--document',type=Path)
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args();result=publish(args.input,args.output,args.document,args.refresh)
    print(json.dumps(dict(fixed_common_tasks=result['fixed_common']['tasks'],
        point_delta=result['fixed_common']['deltas']['point_macro_average'],
        maximum_pairs=[r['tasks'] for r in result['per_round_maximum_pairs']],model_calls=0),ensure_ascii=False))
