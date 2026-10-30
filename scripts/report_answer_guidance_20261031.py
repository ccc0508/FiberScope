"""Offline fixed-evidence prompt A/B report; never call a model or alter judgments.

Input records contain both control/guidance arms for every task, with original
candidate, reference_case, review|null, metrics|null, capabilities?, grading_status?,
answer_status?, reason_code?, and optional full input_evidence_sha256. Both candidates
must retain the identical supplied_excerpts available_context. Missing grades are
explicit null records, not omitted tasks or fabricated zero scores.
"""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import statistics

import report_qa_system_benchmark as scoring

VERSION='answer-guidance-fixed-evidence-v1'
ARMS=('control','guidance')
LABELS={'control':'原回答要求','guidance':'完整性与边界要求'}
QUALITY_KEYS=('point_macro_average','fact_support_rate','citation_precision_rate',
              'citation_coverage_rate','boundary_mean','all_five_pass_rate')
QUALITY_LABELS=('必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项全部达标率')


def require(condition,message):
    if not condition:raise ValueError(message)


def json_digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def audit_arm(arm,import_dir,study_dir):
    """Optional offline bridge to the established first-valid raw-response audit."""
    require(arm in ARMS,'Unknown A/B arm')
    audit=scoring.audit(import_dir,study_dir);study=audit[2]
    require(set(study['requested_judges'])=={'jev'},'Only unchanged Jev judgments are allowed')
    require(all(e['judge']=='jev' and e['system']=='rag' for e in study['jobs']),'Unexpected judge or answer system')
    require(all(status!='pending' for _,_,status in audit[5]),'Wait for an in-flight or interrupted judge request')
    statuses={e['task_id']:'missing' for e in study['jobs']}
    for e in study['jobs']:
        paths=sorted((Path(study_dir)/'records'/e['name']).glob('*.json'),key=lambda p:int(p.stem))
        if paths:statuses[e['task_id']]=json.loads(paths[-1].read_text('utf-8'))['status']
    rows=[]
    for job in audit[1]:
        if job['system']!='rag':continue
        tid=job['task_id'];review=audit[3].get(('jev','rag',tid));capabilities=job['task']['capabilities']
        rows.append(dict(arm=arm,task_id=tid,reference_case=job['reference_case'],candidate=job['candidate'],
            review=review,metrics=scoring.metrics(review,job['reference_case'],capabilities) if review else None,
            capabilities=capabilities,grading_status='completed' if review else statuses.get(tid,'missing')))
    return rows,dict(grade_proofs=audit[6],accounting=scoring.accounting(audit[4].get('jev',[]),'jev'))


def checked_records(payload):
    require(isinstance(payload,dict) and isinstance(payload.get('records'),list),'records must be a list')
    records={};standards={}
    for row in payload['records']:
        arm,tid=row.get('arm'),row.get('task_id')
        require(arm in ARMS and isinstance(tid,str) and tid,'Unknown arm or missing task ID')
        require((arm,tid) not in records,'Duplicate arm/task record')
        case=row.get('reference_case');candidate=row.get('candidate')
        require(isinstance(case,dict) and isinstance(case.get('question'),str),'Missing reference question')
        require(isinstance(candidate,dict) and isinstance(candidate.get('answer'),str),'Missing candidate answer')
        if tid in standards:require(case==standards[tid],'Reference standard changed between arms')
        else:standards[tid]=case
        review=row.get('review');metric=row.get('metrics')
        if review is None:require(metric is None,'Missing grade cannot have numeric metrics')
        else:
            computed=scoring.metrics(review,case,row.get('capabilities',['text']))
            if metric is not None:require(metric==computed,'Metrics differ from original Jev judgments')
            metric=computed
        records[(arm,tid)]={**row,'metrics':metric}
    tids=sorted(standards);require(bool(tids),'No question records')
    require(set(records)=={(a,t) for a in ARMS for t in tids},'Every task requires two explicit records, including null grades')
    return records,tids,standards


def evidence_controls(records,tids,controls):
    proofs=[]
    for tid in tids:
        rows=[records[(a,tid)] for a in ARMS]
        contexts=[r['candidate'].get('available_context') for r in rows]
        for context in contexts:
            require(isinstance(context,dict) and context.get('kind')=='supplied_excerpts' and
                isinstance(context.get('texts'),list) and all(isinstance(t,str) for t in context['texts']),
                'Fixed-evidence A/B requires the actual supplied excerpts for both arms')
        require(contexts[0]==contexts[1],'A/B supplied evidence text, order or scope changed')
        full=[r.get('input_evidence_sha256') for r in rows]
        if any(x is not None for x in full):
            require(all(isinstance(x,str) and len(x)==64 and all(c in '0123456789abcdef' for c in x) for x in full),
                'Malformed complete evidence fingerprint')
            require(full[0]==full[1],'Complete evidence metadata or locators changed')
        proofs.append(dict(task_id=tid,available_context_sha256=json_digest(contexts[0]),
            excerpt_count=len(contexts[0]['texts']),source_chars=sum(map(len,contexts[0]['texts'])),
            full_input_evidence_sha256=full[0],full_locator_fingerprint_present=full[0] is not None))
    if settings:=controls.get('generation_settings'):
        require(set(settings)==set(ARMS) and isinstance(settings['control'],dict) and
            settings['control']==settings['guidance'],'Answering model or controlled generation settings changed')
    return dict(all_supplied_contexts_identical=True,tasks=len(proofs),per_question=proofs,
        method='Exact equality of supplied context values and order; optional complete source/locator fingerprint equality. No semantic evidence scoring.',
        generation_settings_equal=True if controls.get('generation_settings') else None)


def select_common(records,tids):
    selected=[];exclusions=[]
    for tid in tids:
        reasons=[]
        for arm in ARMS:
            row=records[(arm,tid)];metric=row['metrics']
            if metric is None or metric['reference_concern']:
                reasons.append(dict(arm=arm,reason='reference_concern' if metric else row.get('grading_status') or 'no_valid_grade'))
        if reasons:exclusions.append(dict(task_id=tid,excluded_arms=reasons))
        else:selected.append(tid)
    return selected,exclusions


def summarize(metrics):
    if not metrics:return None
    result=scoring.summarize(metrics);facts=sum(result['support_counts'].values())
    return dict(**result,fact_support_rate=result['support_counts'].get('supported',0)/facts if facts else None,
        citation_precision_rate=result['citation_precision']['value'],citation_coverage_rate=result['citation_coverage']['value'],
        all_five_pass_rate=result['all_five_pass']/result['tasks'])


def paired(records,tids):
    scores={a:summarize([records[(a,t)]['metrics'] for t in tids]) for a in ARMS}
    return dict(tasks=len(tids),task_ids=tids,scores=scores,
        deltas={k:scores['guidance'][k]-scores['control'][k] if scores['control'] and
            scores['guidance'][k] is not None and scores['control'][k] is not None else None for k in QUALITY_KEYS},
        point_wins=[t for t in tids if records[('guidance',t)]['metrics']['point_mean']>records[('control',t)]['metrics']['point_mean']],
        point_losses=[t for t in tids if records[('guidance',t)]['metrics']['point_mean']<records[('control',t)]['metrics']['point_mean']],
        all_five_wins=[t for t in tids if records[('guidance',t)]['metrics']['all_five_pass'] and not records[('control',t)]['metrics']['all_five_pass']],
        all_five_losses=[t for t in tids if records[('control',t)]['metrics']['all_five_pass'] and not records[('guidance',t)]['metrics']['all_five_pass']])


def risk_summary(records,tids):
    """Count original labels and program states only; not a new hallucination judge."""
    by_arm={}
    for arm in ARMS:
        rows=[records[(arm,t)] for t in tids];facts=Counter();boundary=Counter();statuses=Counter()
        for row in rows:
            statuses[row.get('answer_status') or 'unknown']+=1
            boundary[str(row['metrics']['boundary'])]+=1
            facts.update(c['support'] for c in row['review']['claim_assessments'] if c['claim_type']=='fact')
        by_arm[arm]=dict(questions=len(rows),program_answer_statuses=dict(statuses),factual_labels=dict(facts),
            boundary_scores=dict(boundary),questions_with_unsupported_or_contradicted_facts=[t for t in tids if
                any(c['claim_type']=='fact' and c['support'] in {'unsupported','contradicted'} for c in records[(arm,t)]['review']['claim_assessments'])],
            questions_with_partial_facts=[t for t in tids if any(c['claim_type']=='fact' and c['support']=='partially_supported'
                for c in records[(arm,t)]['review']['claim_assessments'])])
    return dict(by_arm=by_arm,new_unsupported_or_contradicted_questions=sorted(
        set(by_arm['guidance']['questions_with_unsupported_or_contradicted_facts'])-set(by_arm['control']['questions_with_unsupported_or_contradicted_facts'])),
        new_program_refusals=[t for t in tids if records[('guidance',t)].get('answer_status')=='refused' and
            records[('control',t)].get('answer_status')=='answered'],
        new_boundary_regressions=[t for t in tids if records[('guidance',t)]['metrics']['boundary']<records[('control',t)]['metrics']['boundary']],
        notes='Counts reflect Jev original factual labels and explicit application statuses. A refusal is not automatically excessive; no new semantic labels or sixth scoring dimension are generated.')


def output_diagnostics(records,tids):
    return {a:dict(questions=len(tids),answer_characters=sum(len(records[(a,t)]['candidate']['answer']) for t in tids),
        mean_answer_characters=statistics.mean(len(records[(a,t)]['candidate']['answer']) for t in tids),
        claims=sum(len(records[(a,t)]['candidate'].get('claims',[])) for t in tids),
        citations=sum(len(records[(a,t)]['candidate'].get('citations',[])) for t in tids),
        answer_statuses=dict(Counter(records[(a,t)].get('answer_status') or 'unknown' for t in tids)),
        grading_statuses=dict(Counter(records[(a,t)].get('grading_status') or ('completed' if records[(a,t)]['review'] else 'no_valid_grade') for t in tids))) for a in ARMS}


def runtime_by_arm(payload):
    rows=payload.get('runtimes',[])
    require(isinstance(rows,list),'runtimes must be a list')
    result={}
    for row in rows:
        arm=row.get('arm');require(arm in ARMS and arm not in result,'Unknown or duplicate runtime arm')
        result[arm]=row
    return result


def analyze(payload):
    records,tids,standards=checked_records(payload)
    evidence=evidence_controls(records,tids,payload.get('controls',{}))
    common,exclusions=select_common(records,tids);comparison=paired(records,common);comparison['exclusions']=exclusions
    notes=[
        '本实验只比较同一批已保存证据下的新旧回答要求：两臂均重新生成，不以旧历史答案作为唯一对照；检索、Embedding和重排不参与本次生成输入。',
        '固定证据实验只能定位生成阶段变化，不能证明完整RAG端到端提升或修复证据召回。',
        '只有两臂均有效且无参考标准疑问的题目进入主比较。所有缺失或无效评分保留为空，不记零。',
        '只有一次新生成和每份答案的首个有效Jev评分，混合了回答与裁判波动；不证明稳定性、统计显著性或新论文泛化。',
        '事实支持和引用完整性按实际陈述数计分，两个回答的陈述数可不同；同时保留分子、分母，不能把更多陈述直接当成更好。',
        '五项全部达标沿用原联合条件：每个必答点满分、所有陈述（含范围声明）完全支持、所有适用引用有效、引用组完整且边界2分。事实支持率只统计科学事实，不等于所有陈述支持率。',
        '共同有效子集不能直接等同完整32题的质量；评分校验失败可能与回答复杂程度有关，不能假定缺失随机。',
        '拒答数量来自程序状态；是否过度拒答参考Jev边界标签，不能仅根据拒答字样判断。未知程序状态不从自然语言猜测。',
        '裁判原始标签可能存在误判，尤其历史第11题曾出现数值反例被宽评。新答案也需对照原文复核；报告不自行改分或生成裁判理由。',
        'Token未知和货币费用未知分别保留；推理Token已包含在生成Token中，不重复相加。',
    ]
    notes+=payload.get('limitations',[])
    sensitivity=paired(records,[t for t in common if t!='PFI2-011']) if 'PFI2-011' in common else None
    result=dict(version=VERSION,input_version=payload.get('version'),question_count=len(tids),comparison=comparison,
        evidence_controls=evidence,risks=risk_summary(records,common),output_diagnostics=output_diagnostics(records,tids),
        sensitivity_without_pfi2_011=sensitivity,runtimes=payload.get('runtimes',[]),runtime_by_arm=runtime_by_arm(payload),accounting=payload.get('accounting',{}),
        controls=payload.get('controls',{}),provenance=payload.get('provenance',{}),analyst_notes=payload.get('analyst_notes',[]),
        limitations=list(dict.fromkeys(notes)),model_calls_by_reporter=0,missing_not_zero=True,no_weighted_grand_score=True,
        all_grades_from_input=True)
    delta=comparison['deltas']['point_macro_average']
    result['conclusion']='没有共同有效题，无法比较。' if delta is None else (
        f"同证据共同有效{comparison['tasks']}题，新回答要求的必答要点变化{delta*100:+.2f}个百分点；五项全部达标"
        f"{comparison['scores']['control']['all_five_pass']}→{comparison['scores']['guidance']['all_five_pass']}题。该结果仅衡量本次生成A/B。")
    return result


def percent(value):return '未知' if value is None else f'{value*100:.2f}%'
def value_text(value,key):return '未知' if value is None else f'{value:.3f}' if key=='boundary_mean' else percent(value)


def cells(arm,score):
    if score is None:return [LABELS[arm]]+['无共同有效题']*7
    facts=score['support_counts'];n=sum(facts.values())
    return [LABELS[arm],score['tasks'],percent(score['point_macro_average']),
        scoring.ratio(scoring.fraction(facts.get('supported',0),n)),scoring.ratio(score['citation_precision']),
        scoring.ratio(score['citation_coverage']),f"{score['boundary_mean']:.3f}",f"{score['all_five_pass']}/{score['tasks']} ({percent(score['all_five_pass_rate'])})"]


HEADERS=['版本','共同题','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项全部达标']


def table(headers,rows):
    e=lambda v:escape(str(v),quote=True)
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def runtime_cells(arm,result):
    row=result['runtime_by_arm'].get(arm,{})
    value=lambda v:'未知' if v is None else v
    tokens=row.get('generation_known_tokens') or {}
    return [LABELS[arm],value(row.get('median_end_to_end_seconds')),value(row.get('generation_calls')),
        value(tokens.get('total_tokens')),result['output_diagnostics'][arm]['mean_answer_characters'],
        json.dumps(result['output_diagnostics'][arm]['answer_statuses'],ensure_ascii=False)]


def html_report(path,result,payload):
    records,tids,standards=checked_records(payload);e=lambda v:escape(str(v),quote=True)
    dump=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))+'</pre>'
    c=result['comparison']
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>回答完整性与边界：同证据A/B评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1440px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}p{overflow-wrap:anywhere}.warn{border-left:4px solid #be7b18;padding-left:12px}</style><main>',
        '<h1>回答完整性与证据边界：同证据A/B评测</h1><p>2026-10-31。原回答要求与新回答要求各重新生成一份答案；每题使用同一批已保存证据，未重新检索或重排。</p>',
        '<section class="warn"><h2>本次结果</h2><p>'+e(result['conclusion'])+'</p>'+''.join('<p>'+e(n)+'</p>' for n in result['analyst_notes'])+'</section>',
        '<section><h2>共同有效题比较</h2><p>五项规则不变；五项全部达标是联合条件，不是第六维或加权总分。</p>',
        table(HEADERS,[cells(a,c['scores'][a]) for a in ARMS]),
        '<p>必答要点提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'。</p>',
        '<p>新增全部达标：'+e(c['all_five_wins'])+'；失去全部达标：'+e(c['all_five_losses'])+'。</p>',
        '<details><summary>配对题集与全部排除原因</summary>'+dump(dict(task_ids=c['task_ids'],exclusions=c['exclusions']))+'</details></section>',
        '<section><h2>拒答、事实依据与引用风险</h2><p>以下仅统计Jev原始标签及显式程序状态，不构成新的语义裁判。事实不支持或矛盾、部分支持均保留原标签；不能把拒答自动视为过度拒答。</p>'+dump(result['risks'])+'</section>',
        '<section><h2>证据相等、输出长度、耗时与费用</h2><p>已逐题核验实际提供的文本及顺序完全相同；完整来源与定位指纹的存在情况另列。输出长度、陈述和引用数量只是行为诊断，不是质量评分。</p>',
        table(['版本','生成流程中位秒','生成请求','已知生成Token','平均答案字符','程序状态（全部题）'],[runtime_cells(a,result) for a in ARMS]),
        '<p>本次未执行检索或重排，生成流程耗时不能当作完整RAG的端到端延迟。生成Token含推理Token，不重复相加；货币费用以附录已知/未知原记录为准。</p>',
        '<details><summary>同证据指纹与控制变量</summary>'+dump(dict(evidence=result['evidence_controls'],controls=result['controls']))+'</details>',
        '<details><summary>生成用量、耗时、费用与输出数量</summary>'+dump(dict(runtimes=result['runtimes'],accounting=result['accounting'],outputs=result['output_diagnostics']))+'</details></section>']
    if sensitivity:=result['sensitivity_without_pfi2_011']:
        h+=['<section class="warn"><h2>第11题评分疑问：补充敏感性分析</h2><p>两臂统一移除第11题，保留其原答案和原分。此分析不替代主比较或专家核验。</p>',
            table(HEADERS,[cells(a,sensitivity['scores'][a]) for a in ARMS]),'</section>']
    h+=['<section class="warn"><h2>解释边界</h2>'+''.join('<p>'+e(n)+'</p>' for n in result['limitations'])+'</section>',
        '<details><summary>来源、封存与审计记录</summary>'+dump(result['provenance'])+'</details>',
        '<h2>全部'+str(len(tids))+'题：参考答案、两份回答与Jev原判</h2><p>Jev提供结构化判断和来源定位，不生成自由文字理由；程序不补写裁判意见。</p><input id="search" placeholder="搜索题号或问题">']
    for tid in tids:
        h+=['<article data-search="'+e(tid+' '+standards[tid]['question'])+'"><h2>'+e(tid)+' · '+e(standards[tid]['question'])+'</h2>',
            '<details><summary>参考答案与评分准则</summary>'+dump(standards[tid])+'</details>']
        for arm in ARMS:
            row=records[(arm,tid)];m=row['metrics']
            label='有效评分缺失' if m is None else '参考标准需复核' if m['reference_concern'] else f"要点 {m['required_point_sum']}/{m['required_point_count']}；边界 {m['boundary']}/2"
            h+=['<details'+(' open' if arm=='guidance' else '')+'><summary>'+e(LABELS[arm])+' · '+e(label)+'</summary>',
                '<p>'+e(row['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev逐项判定（原样保留）</summary>'+dump(dict(metrics=m,review=row['review'],grading_status=row.get('grading_status'),answer_status=row.get('answer_status'),reason_code=row.get('reason_code')))+'</details>',
                '<details><summary>原回答、引用与实际可用上下文</summary>'+dump(row['candidate'])+'</details></details>']
        h+=['</article>']
    h+=['<script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(h),encoding='utf-8',newline='\n')


def markdown(result):
    c=result['comparison'];lines=['# 回答完整性与证据边界：同证据A/B评测','','2026-10-31。两臂均重新生成，每题固定同一批原证据，仅比较回答要求。','',
        result['conclusion'],'',*sum(([n,''] for n in result['analyst_notes']),[]),
        '| '+' | '.join(HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |']
    lines+=['| '+' | '.join(map(str,cells(a,c['scores'][a])))+' |' for a in ARMS]
    lines+=['','要点提高：'+(', '.join(c['point_wins']) or '无')+'。','要点下降：'+(', '.join(c['point_losses']) or '无')+'。',
        '新增全部达标：'+(', '.join(c['all_five_wins']) or '无')+'。','失去全部达标：'+(', '.join(c['all_five_losses']) or '无')+'。','',
        '排除：'+json.dumps(c['exclusions'],ensure_ascii=False)+'。','',
        '## 生成耗时与用量','','| 版本 | 生成流程中位秒 | 生成请求 | 已知生成Token | 平均答案字符 | 程序状态 |',
        '| --- | ---: | ---: | ---: | ---: | --- |',
        *['| '+' | '.join(map(str,runtime_cells(a,result)))+' |' for a in ARMS],
        '', '本次绕过检索和重排，生成耗时不是完整RAG端到端延迟。Token含推理Token；费用与未知项在HTML/JSON附录原样保留。','',
        '## 拒答与新增事实风险','',json.dumps(result['risks'],ensure_ascii=False,indent=2),'',
        '## 解释边界','',*sum(([n,''] for n in result['limitations']),[]),
        '[全部题目、两份新回答与Jev逐项判定](../data/literature/qa-evaluation/reports/answer-guidance-20261031/comparison.html)。',
        '[完整计算、来源与用量](../data/literature/qa-evaluation/reports/answer-guidance-20261031/comparison.json)。','']
    return '\n'.join(lines)


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def publish(input_path,output_dir,document_path=None,refresh=False):
    input_path,output_dir=Path(input_path),Path(output_dir);document_path=Path(document_path) if document_path else None
    digest=lambda p:sha256(Path(p).read_bytes()).hexdigest()
    if refresh:
        seal=json.loads((output_dir/'publication.json').read_text('utf-8'))
        require(all(digest(output_dir/n)==h for n,h in seal['files'].items()),'Existing report bytes changed')
        if document_path:require(digest(document_path)==seal['document_sha256'],'Existing document changed')
    else:
        require(not output_dir.exists(),'Report output already exists')
        if document_path:require(not document_path.exists(),'Report document already exists')
    payload=json.loads(input_path.read_text('utf-8'));result=analyze(payload)
    output_dir.mkdir(parents=True,exist_ok=refresh)
    save(output_dir/'comparison.json',result);save(output_dir/'evidence-controls.json',result['evidence_controls'])
    records,tids,standards=checked_records(payload)
    rows=[dict(task_id=t,reference_case=standards[t],records=[records[(a,t)] for a in ARMS]) for t in tids]
    (output_dir/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    html_report(output_dir/'comparison.html',result,payload)
    if document_path:
        document_path.parent.mkdir(parents=True,exist_ok=True);document_path.write_text(markdown(result),encoding='utf-8',newline='\n')
    save(output_dir/'publication.json',dict(version=VERSION,input_sha256=digest(input_path),exporter_sha256=digest(Path(__file__)),
        document_sha256=digest(document_path) if document_path else None,
        files={p.name:digest(p) for p in output_dir.iterdir() if p.is_file() and p.name!='publication.json'},model_calls=0))
    return result


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    p=ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=root/'.rag-data/evaluations/answer-guidance-20261031/analysis-input.json')
    p.add_argument('--output',type=Path,default=root/'data/literature/qa-evaluation/reports/answer-guidance-20261031')
    p.add_argument('--document',type=Path);p.add_argument('--refresh',action='store_true');a=p.parse_args()
    r=publish(a.input,a.output,a.document,a.refresh)
    print(json.dumps(dict(paired_tasks=r['comparison']['tasks'],deltas=r['comparison']['deltas'],model_calls=0),ensure_ascii=False))
