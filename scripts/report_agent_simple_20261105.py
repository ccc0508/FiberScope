"""Auditable report for first-run simplified-agent quality and budget outcomes."""
import json
from html import escape
from collections import Counter
import statistics
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from report_answer_models_20261102 import final_review
from grade_agent_simple_20261105 import RUN,ROOT,OUTPUT,verify
PUBLIC=ROOT/'data/literature/qa-evaluation/reports/agent-simple-20261105'

def runtime(rows):
    results=[j.read_json(RUN/(r['task_id']+'.json')) for r in rows]
    calls=[c for x in results for c in x.get('model_calls',[])]
    tool_providers={}
    for x in results:
        for t in x.get('tool_trace',[]):
            for name,p in (t.get('provider_calls') or {}).items():
                if not isinstance(p,dict):continue
                u=p.get('usage',p if name=='embedding' else {}) or {}
                a=tool_providers.setdefault(name,dict(records=0,known_tokens=0,missing_token_usage=0))
                a['records']+=1
                if 'total_tokens' in u:a['known_tokens']+=u['total_tokens']
                elif 'input_tokens' in u:a['known_tokens']+=u['input_tokens']+u.get('output_tokens',0)
                else:a['missing_token_usage']+=1
    durations=sorted(x['end_to_end_ms']/1000 for x in results)
    return dict(outcomes=dict(Counter(x['status'] for x in results)),
        stop_reasons=dict(Counter(str(x.get('stop_reason')) for x in results)),
        review_states=dict(Counter(x.get('review_status','missing') for x in results)),
        model_calls=len(calls),known_model_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in calls),
        unknown_usage_calls=sum(c.get('usage') is None for c in calls),
        tool_provider_usage=tool_providers,monetary_cost=None,
        token_scope='Agent model calls and tool providers reported separately; tokens are not money; unreported usage remains unknown.',
        median_seconds=statistics.median(durations),p90_seconds=durations[28],
        total_tool_requests=sum(len(x.get('tool_calls',[])) for x in results),
        tool_names=dict(Counter(t['request']['tool'] for x in results for t in x.get('tool_calls',[]))),
        failed_question_ids=[x['case_id'] for x in results if x['status']=='failed'],
        mean_answer_chars=statistics.mean(len(x.get('answer','')) for x in results if x.get('answer')),
        tool_outcomes=dict(Counter(t['status'] for x in results for t in x.get('tool_calls',[]))),
        per_question=[dict(task_id=x['case_id'],status=x['status'],review=x.get('review_status'),stop_reason=x.get('stop_reason'),
            model_calls=len(x.get('model_calls',[])),tool_requests=len(x.get('tool_calls',[])),seconds=x['end_to_end_ms']/1000,
            tool_result_chars_lower_bound=sum(len(json.dumps(t['result'],ensure_ascii=False)) for t in x.get('tool_calls',[]) if t.get('result')),
            tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in x.get('model_calls',[]))) for x in results])

def publish(refresh=False):
    verify()
    if PUBLIC.exists():
        assert refresh and {p.name for p in PUBLIC.iterdir()}=={'comparison.json','comparison.html','questions-answers-reviews.jsonl','adjudication.json'}
    _,jobs,study,reviews,records,_,_=s.audit(OUTPUT/'import',OUTPUT/'judges')
    entries={e['task_id']:e for e in study['jobs']}
    adj=j.read_json(OUTPUT/'codex-adjudication.json');changes={a['task_id']:a for a in adj['items']}
    assert len(changes)==32 and adj['policy_sha256']==g.POLICY_SHA
    rows=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];entry=entries[tid];raw=reviews.get(('jev','rag',tid))
        saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        final=final_review(dict(result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=entry['input_sha256'],raw_review=raw,saved=saved),changes[tid])
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference=job['reference_case'],candidate=job['candidate'],
            raw_jev_review=raw,final_codex_review=final,adjudication=changes[tid],
            raw_jev_metrics=s.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None,
            final_codex_metrics=s.metrics(final,job['reference_case'],job['task']['capabilities'])))
    rows.sort(key=lambda x:x['task_id'])
    summary=dict(questions=32,weighted_grand_score=None,library_audit=j.read_json(RUN/'library-audit.json'),final=s.summarize([r['final_codex_metrics'] for r in rows]),
        completed_answers_only=s.summarize([r['final_codex_metrics'] for r in rows if r['candidate']['answer']]),
        final_on_raw_jev_same_subset=s.summarize([r['final_codex_metrics'] for r in rows if r['raw_jev_review']]),
        raw_jev=s.summarize([r['raw_jev_metrics'] for r in rows if r['raw_jev_metrics']]),
        valid_jev=sum(r['raw_jev_review'] is not None for r in rows),accounting=s.accounting(records['jev'],'jev'),runtime=runtime(rows),
        not_all_pass=[r['task_id'] for r in rows if not r['final_codex_metrics']['all_five_pass']],
        limitations=['Single paper and repeatedly used development questions; one run does not establish stability.',
            'Chroma persistence bytes changed; source metadata and images unchanged, but no pre-run logical vector digest exists. Strict index identity is not proven.',
            'Empty failed answers receive zero required-point and boundary credit; no claims/citations are fabricated for them, so factual/citation rates alone do not measure end-to-end success.',
            'Free-form Markdown blocks rather than old atomic claims; claim/citation denominators are not directly matched.',
            'Jev receives text and image metadata; Codex separately checks actual source images.',
            'Fresh retrieval/drafts and simplified whole-answer review; no causal attribution to agent architecture alone.'])
    f=summary['final'];rt=summary['runtime'];pct=lambda v:f'{v*100:.2f}%'
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>简化Agent 32题评测</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f5f7fa;color:#193049}article{padding:22px;background:white;margin:20px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 system-ui}summary{cursor:pointer}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #d8e0e9;text-align:left}a{color:#165cb5}</style><h1>简化 Agent：32 题首次运行</h1><p>2026-11-05 · DeepSeek / MinerU / 千问多模态嵌入 · Jev 原始评分 + Codex 原文校准</p><article><h2>结论：先修上下文管理，再迁移复杂审校</h2><p>20/32 题正常完成，12 题在初答之前触发 160,000 字符上下文限制。不是模型输出截断，也不是调用次数或 240 秒时间预算耗尽。失败题保留空答案并计零分，没有补跑择优。</p><table><tr><th>指标</th><th>校准结果</th><th>口径</th></tr>']
    for label,value,scope in [('运行完成率','62.50%','20/32'),('必答要点宏平均',pct(f['point_macro_average']),'32题，失败题计0；成功20题子集为100%'),('陈述充分支持率',pct(f['support_counts'].get('supported',0)/sum(f['support_counts'].values())),'84/98个事实段落；空答案没有陈述'),('单条引用有效率',pct(f['citation_precision']['value']),'189/193'),('引用组完整覆盖率',pct(f['citation_coverage']['value']),'74/98'),('回答边界均分',str(f['boundary_mean'])+'/2','包含12份空答案'),('五项全部通过',str(f['all_five_pass'])+'/32','严格要求所有要点、事实、引用和边界均通过')]:
        html.append('<tr>'+''.join('<td>'+escape(t)+'</td>' for t in [label,value,scope])+'</tr>')
    html+=['</table><p>成功答案平均 '+str(rt['mean_answer_chars'])+' 字符；单题耗时中位数 '+str(round(rt['median_seconds'],2))+' 秒，P90 '+str(rt['p90_seconds'])+' 秒。Agent 104 次模型调用、117 次工具请求；模型报告 Token 合计 2,904,334，另有改写/嵌入/重排用量，货币费用未知。Jev 39 次调用报告费用 $0.140686224（非账单）。</p><p>Jev 有效29题，原始要点58.62%；校准相同29题的要点仍为58.62%，补入2/12/17题后全32题为62.50%。不能把覆盖范围变化当作模型评分提高。</p></article><article><h2>如何解读</h2><p>前一固定流程32题的要点分为99.48%，本次62.50%，下降36.98个百分点。成功答出的20题要点齐全，端到端下降主要来自12题未能交付。它们包含拒答/纠错类难题，不能据成功子集100%断言新系统更强。</p><p>本次为自由格式答案，按原文段落/列表/表格组织核查，保留明确的前置与后置引用范围；旧版是结构化陈述。事实及引用分母不完全可比，不作严格增减归因。单篇论文、重复使用的开发题、单次运行也不足以评价稳定性或最佳预算。</p><p>额外内容仍有问题：4题的内插断言、14题的WRV估读、17题的因果排除、22题的同批数据与样本量断言、32题把浆类写成树种。原始评分、校准理由和失败题均保留在下方。</p></article><h2>逐题结果</h2><table><tr><th>题号</th><th>运行状态</th><th>要点</th><th>五项全通过</th></tr>']
    statuses={r['task_id']:r['status'] for r in rt['per_question']}
    for r in rows:
        m=r['final_codex_metrics'];tid=r['task_id']
        html.append(f'<tr><td><a href="#{tid}">{tid}</a></td><td>{statuses[tid]}</td><td>{pct(m["point_mean"])}</td><td>{"是" if m["all_five_pass"] else "否"}</td></tr>')
    html+=['</table><p>复现限制：原文元数据库与图片哈希未变，但Chroma三个持久化文件在查询运行后发生变化；未采集运行前逻辑向量摘要，不能宣称索引严格不变。详见下方 library_audit。</p><details><summary>完整统计、预算与成本口径</summary><pre>'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>']
    for r in rows:
        html+=['<article id="'+r['task_id']+'"><h2>'+escape(r['task_id']+' '+r['question'])+'</h2><pre>'+escape(r['candidate']['answer'] or '【未生成答案：上下文预算溢出】')+'</pre><p>'+escape(r['adjudication']['summary'])+'</p>']
        for key in ['reference','raw_jev_review','final_codex_review','adjudication']:
            html+=['<details><summary>'+key+'</summary><pre>'+escape(json.dumps(r[key],ensure_ascii=False,indent=2))+'</pre></details>']
        html+=['</article>']
    files={'comparison.json':j.encode(summary),'comparison.html':''.join(html)+'</html>',
        'questions-answers-reviews.jsonl':''.join(j.encode(r)+'\n' for r in rows),'adjudication.json':j.encode(adj)}
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for k,v in dotenv_values(p).items():
            if v and len(v)>12 and k.upper().endswith(('API_KEY','TOKEN','PASSWORD')):assert all(v not in t for t in files.values())
    PUBLIC.mkdir(parents=True,exist_ok=refresh)
    for name,text in files.items():(PUBLIC/name).write_text(text,encoding='utf-8',newline='\n')
    return summary

if __name__=='__main__':
    import sys
    print(j.encode(publish(refresh='--refresh' in sys.argv)))
