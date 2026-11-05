"""Auditable report for first-run simplified-agent quality and budget outcomes."""
import json
from html import escape
from collections import Counter
import statistics
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from report_answer_models_20261102 import final_review
from grade_agent_compact_20261105 import RUN,ROOT,OUTPUT,verify
PUBLIC=ROOT/'data/literature/qa-evaluation/reports/agent-compact-20261105'

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
    durations=sorted(x['end_to_end_ms']/1000 for x in results if x.get('end_to_end_ms') is not None)
    return dict(outcomes=dict(Counter(x['status'] for x in results)),
        stop_reasons=dict(Counter(str(x.get('stop_reason')) for x in results)),
        review_states=dict(Counter(x.get('review_status','missing') for x in results)),
        model_calls=len(calls),known_model_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in calls),
        unknown_usage_calls=sum(c.get('usage') is None for c in calls),
        tool_provider_usage=tool_providers,monetary_cost=None,
        context_delivery=dict(raw_chars=sum(e.get('raw_chars',0) for x in results for e in x.get('context_events',[])),delivered_chars=sum(e.get('delivered_chars',0) for x in results for e in x.get('context_events',[])),withheld=sum(bool(e.get('withheld')) for x in results for e in x.get('context_events',[]))),
        token_scope='Agent model calls and tool providers reported separately; tokens are not money; unreported usage remains unknown.',
        median_seconds=statistics.median(durations),p90_seconds=durations[min(len(durations)-1,int(len(durations)*.9))],
        total_tool_requests=sum(len(x.get('tool_calls',[])) for x in results),
        tool_names=dict(Counter(t['request']['tool'] for x in results for t in x.get('tool_calls',[]))),
        failed_question_ids=[x['case_id'] for x in results if x['status']=='failed'],
        mean_answer_chars=statistics.mean(len(x.get('answer','')) for x in results if x.get('answer')),
        tool_outcomes=dict(Counter(t['status'] for x in results for t in x.get('tool_calls',[]))),
        per_question=[dict(task_id=x['case_id'],status=x['status'],review=x.get('review_status'),stop_reason=x.get('stop_reason'),
            model_calls=len(x.get('model_calls',[])),tool_requests=len(x.get('tool_calls',[])),seconds=x['end_to_end_ms']/1000 if x.get('end_to_end_ms') is not None else None,
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
    summary=dict(questions=32,weighted_grand_score=None,library_audit=dict(logical_index_unchanged=True,source_code_unchanged=True,contract=RUN.name),final=s.summarize([r['final_codex_metrics'] for r in rows]),
        completed_answers_only=s.summarize([r['final_codex_metrics'] for r in rows if r['candidate']['answer']]),
        final_on_raw_jev_same_subset=s.summarize([r['final_codex_metrics'] for r in rows if r['raw_jev_review']]),
        raw_jev=s.summarize([r['raw_jev_metrics'] for r in rows if r['raw_jev_metrics']]),
        valid_jev=sum(r['raw_jev_review'] is not None for r in rows),accounting=s.accounting(records['jev'],'jev'),runtime=runtime(rows),
        not_all_pass=[r['task_id'] for r in rows if not r['final_codex_metrics']['all_five_pass']],
        limitations=['Single paper and repeatedly used development questions; one run does not establish stability.',
            'Logical index rows and runtime hashes verified before and after; persisted Chroma bytes may change during reads.',
            'Empty failed answers receive zero required-point and boundary credit; no claims/citations are fabricated for them, so factual/citation rates alone do not measure end-to-end success.',
            'Free-form Markdown blocks rather than old atomic claims; claim/citation denominators are not directly matched.',
            'Jev receives text and image metadata; Codex separately checks actual source images.',
            'Fresh retrieval/drafts and simplified whole-answer review; no causal attribution to agent architecture alone.'])
    baseline=j.read_json(ROOT/'data/literature/qa-evaluation/reports/agent-simple-20261105/comparison.json')
    summary['baseline']=dict(final=baseline['final'],runtime=baseline['runtime'])
    previous=j.read_jsonl(ROOT/'data/literature/qa-evaluation/reports/agent-simple-20261105/questions-answers-reviews.jsonl')
    common={r['task_id'] for r in previous if r['candidate']['answer']}
    summary['same_answered_20']=dict(ids=sorted(common),old=s.summarize([r['final_codex_metrics'] for r in previous if r['task_id'] in common]),new=s.summarize([r['final_codex_metrics'] for r in rows if r['task_id'] in common]))
    abandoned=[j.read_json(p) for p in (ROOT/'.rag-data/evaluations/agent-compact-20261105').glob('PFI2-*.json')]
    summary['aborted_run_known_usage']=dict(saved_cases=len(abandoned),model_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for x in abandoned for m in x.get('model_calls',[])),scope='Saved completed case files only; interrupted cases and diagnostic call excluded, not total billed spend.')

    summary['environment_interruption']=j.read_json(ROOT/'.rag-data/evaluations/agent-compact-20261105/environment-interruption.json')
    f=summary['final'];rt=summary['runtime'];pct=lambda v:f'{v*100:.2f}%'
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Agent 上下文优化：32题重测</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f5f7fa;color:#193049}article{padding:22px;background:white;margin:20px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 system-ui}summary{cursor:pointer}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #d8e0e9;text-align:left}a{color:#165cb5}</style><h1>Agent 上下文优化：32题重测</h1><p>2026-11-05 · DeepSeek / MinerU / 千问多模态嵌入 · Jev + Codex 原文校准</p><p>每题独立上下文，从检索开始。保留首次答案、全量轨迹、Jev 原评分与校准理由。无多次择优，未迁移旧版结构化审校。</p><table><tr><th>指标</th><th>上一轮简化 Agent</th><th>当前版本</th></tr>']
    def stats(f,rt):
        return [pct(rt['outcomes'].get('completed',0)/32),pct(f['point_macro_average']),pct(f['support_counts'].get('supported',0)/max(1,sum(f['support_counts'].values()))),pct(f['citation_precision']['value']),pct(f['citation_coverage']['value']),str(f['boundary_mean'])+'/2',str(f['all_five_pass'])+'/32',str(rt['known_model_tokens']),str(rt['total_tool_requests']),str(round(rt['median_seconds'],2))+' 秒']
    labels=['运行完成率','必答要点宏平均','陈述充分支持率','单条引用有效率','引用组完整覆盖率','回答边界均分','五项全部通过','Agent 模型报告 Token','工具请求次数','单题耗时中位数']
    for label,old,new in zip(labels,stats(baseline['final'],baseline['runtime']),stats(f,rt)):
        html.append('<tr>'+''.join('<td>'+escape(t)+'</td>' for t in [label,old,new])+'</tr>')
    html+=['</table><article><h2>结论</h2><p>32题均有答案，31题完成复核，第19题保留中断前初答。必答要点100%，不等于所有事实正确：扩写仍有单位解释、过拟合偏差方向、链间/链内关系、图像估读与样本量断言问题。第27题复核后输出英文，另记为体验缺陷。成功回答增加的同时，应继续改进证据利用。</p><p>只比较两轮都有答案的同20题：要点均100%，事实充分支持85.71%→84.93%，引用有效97.93%→99.13%，完整覆盖75.51%→73.97%，五项全过5→7。段落数量仍不同且本轮19题复核中断，不能由这一次运行证明稳定性。</p></article><article><h2>本轮改动与比较限制</h2><p>关闭工具内部查询改写；单次工具只返回补全后的正文；跨调用精确文本复用；每轮最多执行一个工具；接近上下文上限提前收尾。调用次数、240秒时间、8192输出与160000字符硬上限不变。本轮同时改变了多项行为，不能单独归因；每题仅一次，不证明稳定性。</p><p>首轮并发测试遭遇 Windows 系统内存不足，已中止并独立归档，没有挑选其中答案。释放资源后全32题串行重跑；第19题在初答后、复核前进程中断，保留初答并标为 partial，没有补答择优，该题完整耗时未知。用量表仅含本次串行轮；被中止轮与诊断调用是额外开销，单独记录，不混入质量评分。</p><p>事实和引用比例按实际自由格式段落计数，空答案不构造事实分母。Jev 只读文字与图片元信息，图像结论由 Codex 对原图核验。没有自创加权总分；Token 不等于货币费用。</p></article><h2>逐题结果</h2><table><tr><th>题号</th><th>状态</th><th>必答要点</th><th>五项通过</th></tr>']
    statuses={r['task_id']:r['status'] for r in rt['per_question']}
    for r in rows:
        m=r['final_codex_metrics'];tid=r['task_id']
        html.append(f'<tr><td><a href="#{tid}">{tid}</a></td><td>{statuses[tid]}</td><td>{pct(m["point_mean"])}</td><td>{"是" if m["all_five_pass"] else "否"}</td></tr>')
    html+=['</table><details><summary>完整统计与用量口径</summary><pre>'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>']
    for r in rows:
        html+=['<article id="'+r['task_id']+'"><h2>'+escape(r['task_id']+' '+r['question'])+'</h2><pre>'+escape(r['candidate']['answer'] or '【未生成答案：原因见运行状态】')+'</pre><p>'+escape(r['adjudication']['summary'])+'</p>']
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
