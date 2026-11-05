"""Replace exactly 11 frozen rows; preserve the other 21 calibrated results."""
import json
from html import escape
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as scoring
from report_answer_models_20261102 import final_review
import report_agent_compact_20261105 as runtime_report
from grade_agent_search2_20261105 import ROOT,RUN,OUTPUT,verify
BASE=ROOT/'data/literature/qa-evaluation/reports/agent-compact-20261105'
PUBLIC=ROOT/'data/literature/qa-evaluation/reports/agent-search2-20261105'
SELECTED={f'PFI2-{n:03}' for n in [4,15,16,24,25,26,27,28,29,30,31]}

def publish():
    verify()
    _,jobs,study,reviews,records,_,_=scoring.audit(OUTPUT/'import',OUTPUT/'judges')
    entries={e['task_id']:e for e in study['jobs']};assert set(entries)==SELECTED
    adj=j.read_json(OUTPUT/'codex-adjudication.json');changes={a['task_id']:a for a in adj['items']}
    previous=j.read_jsonl(BASE/'questions-answers-reviews.jsonl');old={r['task_id']:r for r in previous};new={}
    for job in jobs:
        tid=job['task_id']
        if job['system']!='rag' or tid not in SELECTED:continue
        e=entries[tid];raw=reviews.get(('jev','rag',tid));saved=j.read_json(OUTPUT/'judges/inputs'/(e['name']+'.json'))
        final=final_review(dict(result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=e['input_sha256'],raw_review=raw,saved=saved),changes[tid])
        new[tid]=dict(task_id=tid,question=job['reference_case']['question'],reference=job['reference_case'],candidate=job['candidate'],raw_jev_review=raw,final_codex_review=final,adjudication=changes[tid],raw_jev_metrics=scoring.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None,final_codex_metrics=scoring.metrics(final,job['reference_case'],job['task']['capabilities']))
    merged=[new.get(r['task_id'],r) for r in previous]
    assert len(merged)==32 and set(new)==SELECTED
    assert all(r==old[r['task_id']] for r in merged if r['task_id'] not in SELECTED)
    runtime_report.RUN=RUN
    current_runtime=runtime_report.runtime(list(new.values()))
    runtime_report.RUN=ROOT/'.rag-data/evaluations/agent-compact-serial-20261105'
    old_runtime=runtime_report.runtime([old[i] for i in sorted(SELECTED)])
    def totals(rows):return scoring.summarize([r['final_codex_metrics'] for r in rows])
    summary=dict(kind='11-new-plus-21-inherited',selected=sorted(SELECTED),baseline_sha256=j.digest(BASE/'questions-answers-reviews.jsonl'),old_total=totals(previous),merged_total=totals(merged),old_11=totals([old[i] for i in SELECTED]),new_11=totals(list(new.values())),new_jev_raw=scoring.summarize([r['raw_jev_metrics'] for r in new.values() if r['raw_jev_metrics']]),old_runtime_11=old_runtime,new_runtime_11=current_runtime,judge_accounting=scoring.accounting(records['jev'],'jev'),origins={r['task_id']:RUN.name if r['task_id'] in SELECTED else 'agent-compact-serial-20261105' for r in merged},notes=['All 11 replaced regardless of outcome; no answer selection.','Question19 retains prior interrupted-before-review answer and prior calibration.','Single fresh sample; changes cannot be causally attributed solely to the search cap.','Each factual unit is a verbatim Markdown paragraph/list/table; denominators may differ.'])
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>最多两次检索：11题重跑与32题合并</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;color:#193049;background:#f5f7fa}article{background:white;padding:20px;margin:18px 0}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><h1>最多两次检索：11题重跑与32题合并</h1><p>仅重跑4、15、16、24、25、26、27、28、29、30、31；DeepSeek独立答题→一次整答复核→Jev→Codex原文校准。其余21题完整沿用，19题仍为旧轮复核中断状态。所有新结果替换旧结果，没有择优。</p><table><tr><th>指标</th><th>旧32题</th><th>合并32题</th></tr>']
    def vals(x):
        return [x['point_macro_average'],x['support_counts'].get('supported',0)/sum(x['support_counts'].values()),x['citation_precision']['value'],x['citation_coverage']['value']]
    for name,a,b in zip(['必答要点','事实充分支持','单条引用有效','引用组完整覆盖'],vals(summary['old_total']),vals(summary['merged_total'])):
        html.append(f'<tr><td>{name}</td><td>{a:.2%}</td><td>{b:.2%}</td></tr>')
    html.append(f"<tr><td>证据边界（0–2）</td><td>{summary['old_total']['boundary_mean']:.5f}</td><td>{summary['merged_total']['boundary_mean']:.5f}</td></tr><tr><td>五项全部通过</td><td>{summary['old_total']['all_five_pass']}/32</td><td>{summary['merged_total']['all_five_pass']}/32</td></tr></table><p>不是全新32题运行；单轮随机回答不能证明稳定性。事实/引用分母随文本分组改变。Token为报告用量，不是货币账单。第15题Jev三次返回无效评分，由Codex补评；第31题回答复核截断，保留并评分初稿。原始Jev结果和校准理由分别保存。</p>")
    html.append('<h2>11题逐题变化</h2><table><tr><th>题目</th><th>旧→新要点</th><th>旧→新检索次数</th><th>原文校准结论</th></tr>')
    for tid in sorted(SELECTED):
        a=old[tid]['final_codex_metrics'];b=new[tid]['final_codex_metrics']
        def searches(path):return sum(t['request']['tool']=='search_literature' and t['status']!='blocked' for t in j.read_json(path)['tool_calls'])
        oc=searches(ROOT/'.rag-data/evaluations/agent-compact-serial-20261105'/(tid+'.json'));nc=searches(RUN/(tid+'.json'));assert nc<=2
        html.append(f'<tr><td><a href="#{tid}">{tid}</a></td><td>{a["point_mean"]:.2%} → {b["point_mean"]:.2%}</td><td>{oc} → {nc}</td><td>{escape(changes[tid]["summary"])}</td></tr>')
    html.append('</table><details><summary>完整指标、用量与来源</summary><pre>'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>')
    for r in merged:
        tid=r['task_id'];html.append('<article id="'+tid+'"><h2>'+escape(tid+' '+r['question'])+'</h2><p>'+('本轮重跑' if tid in SELECTED else '沿用上轮')+'</p><pre>'+escape(r['candidate']['answer'])+'</pre>')
        if tid in SELECTED:html.append('<details><summary>旧回答及评分</summary><pre>'+escape(json.dumps(old[tid],ensure_ascii=False,indent=2))+'</pre></details>')
        for k in ['reference','raw_jev_review','final_codex_review','adjudication']:html.append('<details><summary>'+k+'</summary><pre>'+escape(json.dumps(r[k],ensure_ascii=False,indent=2))+'</pre></details>')
        html.append('</article>')
    files={'comparison.json':j.encode(summary),'comparison.html':''.join(html)+'</html>','questions-answers-reviews.jsonl':''.join(j.encode(r)+'\n' for r in merged),'adjudication.json':j.encode(adj)}
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for k,v in dotenv_values(p).items():
            if v and len(v)>12 and k.upper().endswith(('API_KEY','TOKEN','PASSWORD')):assert all(v not in text for text in files.values())
    PUBLIC.mkdir(exist_ok=True,parents=True)
    for name,text in files.items():(PUBLIC/name).write_text(text,encoding='utf-8')
    return summary
if __name__=='__main__':print(j.encode(publish()))
