"""Publish all 30 fresh answers, independent Jev and explicit calibration."""
import json,html,hashlib
from pathlib import Path
from report_regression_baseline_20261106 import metrics,calibrate,summary
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-full-v7-20261109'
PACK=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/latest-scored/pack'
OUT=ROOT/'data/literature/qa-evaluation/reports/rag-full-v7-20261109'
def read(p):return json.loads(p.read_text('utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    notes=read(OUT/'calibration.json')
    cases=[json.loads(l) for l in (PACK/'gold.jsonl').read_text('utf8').splitlines() if l.strip()]
    rows=[]
    for c in cases:
        k=c['id'];x=read(RUN/(k+'.json'));path=RUN/'jev'/k/'review.json'
        raw=read(path) if path.exists() else None
        if raw:
            final=calibrate(raw,notes[k]);a=metrics(c,raw,x);b=metrics(c,final,x)
        else:
            assert x['status']!='completed',k+' missing judge'
            final=None
            a=b=dict(point_score=0,point_count=len(c['key_points']),fact_count=0,supported_facts=0,pair_count=0,supported_pairs=0,group_count=0,covered_groups=0,boundary=0,fact_support=None,citation_precision=None,citation_coverage=None,strict_pass=False,format_ok=False)
        rows.append(dict(id=k,case=c,answer=x.get('answer',''),status=x['status'],raw_jev=raw,calibrated=final,review=notes[k],raw_metrics=a,final_metrics=b,budget=x.get('budget_usage'),plan=x.get('plan'),langfuse=x.get('langfuse'),elapsed_ms=x.get('end_to_end_ms'),local_full_result=str(RUN/(k+'.json')),result_sha256=hashlib.sha256((RUN/(k+'.json')).read_bytes()).hexdigest(),tools=[t['request'] for t in x.get('tool_calls',[])]))
    stats=dict(count=len(rows),completed=sum(r['status']=='completed' for r in rows),raw_jev=summary(rows,'raw_metrics'),calibrated=summary(rows,'final_metrics'),groups={g:summary([r for r in rows if r['case']['group']==g],'final_metrics') for g in ['single','cross','no_paper']},integrity=read(RUN/'integrity.json'),policy='Fresh independent first attempts for all 30. Failures count as 0 keypoints and strict fail; factual/citation ratios only on assessable answers. No overlays. Jev then Codex calibration, not an independent human expert review.')
    usage=dict(answer_total_tokens=0,answer_input_tokens=0,answer_output_tokens=0,answer_cached_tokens=0,answer_calls_missing_usage=0,total_answer_elapsed_ms=0,judge_reported_cost_usd=0,judge_cost_missing_attempts=0)
    for r in rows:
        x=read(Path(r['local_full_result']));usage['total_answer_elapsed_ms']+=x.get('end_to_end_ms',0)
        for call in x.get('model_calls',[]):
            u=call.get('usage') or {};usage['answer_total_tokens']+=u.get('total_tokens',0) or 0;usage['answer_calls_missing_usage']+=not bool(u)
            for target,source in [('answer_input_tokens','prompt_tokens'),('answer_output_tokens','completion_tokens'),('answer_cached_tokens','cached_tokens')]:usage[target]+=u.get(source,0) or 0
        for path in (RUN/'jev'/r['id']).glob('attempt-*.json'):
            cost=(read(path).get('usage') or {}).get('reported_cost_usd');usage['judge_cost_missing_attempts']+=cost is None;usage['judge_reported_cost_usd']+=cost or 0
    stats['usage']=usage
    baseline=read(RUN/'manifest.json')['baseline']
    stats['configuration']={k:baseline[k] for k in ['model','thinking','reasoning_effort','architecture','budget'] if k in baseline}
    actual=read(Path(rows[0]['local_full_result']))
    stats['configuration']['budget']=actual['budget']
    stats['configuration']['pipeline_version']=actual.get('pipeline_version')
    stats['configuration']['concurrency']=2
    stats['limitations']=['每题只跑一次，不能据此估计稳定性或认定某次代码修改的因果效果。','事实单元是固定的Markdown语义段，可能包含多个事实，并非逐句原子断言。','Jev接收原文文本和图像元数据；图像相关结论按原始图及逐题校准记录核对。','沿用20261106-contextual-citations口径：总结允许承接明确上下文引用；FS8-002 K4不计入。','要点分不是六维加权总分；要点满分仍可能含额外事实错误。','Token不是费用；回答供应商未提供实际金额，本报告只列Jev回传费用。','运行通过CLI，每题有Langfuse轨迹入口；本轮不验证网页HTTP上游链路。']
    stats['usage']['answer_cost_usd']=None
    stats['execution']={'model_calls':0,'tool_calls':0,'format_repaired_cases':[],'paper_route_cases':0,'no_paper_no_paper_tools':0}
    for r in rows:
        x=read(Path(r['local_full_result']));e=stats['execution'];e['model_calls']+=len(x.get('model_calls',[]));e['tool_calls']+=len(x.get('tool_calls',[]))
        if any(c.get('status')=='repaired' for c in x.get('format_checks',[])):e['format_repaired_cases'].append(r['id'])
        names=[t.get('tool') for t in r['tools']]
        paper=any(t in {'search_literature','read_section','read_table','view_image','list_sections','find_documents'} for t in names)
        if r['case']['group']=='no_paper':e['no_paper_no_paper_tools']+=not paper
        else:e['paper_route_cases']+=paper
    baseline_dir=ROOT/'data/literature/qa-evaluation/reports/rag-full-v5-20261109'
    previous=read(baseline_dir/'summary.json')['calibrated']
    old_rows={r['id']:r for r in read(baseline_dir/'results.json')}
    stats['configuration']['collection_reserve_chars']=16384
    comparison=dict(baseline='rag-full-v5-20261109',previous=previous,current=stats['calibrated'],cases=[dict(id=r['id'],old=old_rows[r['id']]['final_metrics'],new=r['final_metrics']) for r in rows],notice='Independent fresh answers, not fixed-draft ablation. Reserve and scheduling differ; cannot attribute all changes to one edit. Semantic block denominators change across answers.')
    write(OUT/'comparison.json',comparison)
    write(OUT/'summary.json',stats);write(OUT/'results.json',rows)
    def pre(x):return '<pre>'+html.escape(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2))+'</pre>'
    m=stats['calibrated']
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>30题全量回归</title><style>body{max-width:1100px;margin:30px auto;padding:0 20px;font:16px/1.7 system-ui;background:#f5f7fb;color:#20334a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}article{background:white;border:1px solid #dbe3ec;border-radius:12px;margin:20px 0;padding:24px}table{width:100%;border-collapse:collapse;background:white}td,th{padding:9px;border:1px solid #dbe3ec;text-align:left}summary,a{color:#205da0}summary{cursor:pointer}h2{font-size:20px}</style><h1>2026-11-09 文献30题全量回归</h1>'
    page+=f'<p>独立新上下文、从检索开始全新作答：<b>{stats["completed"]}/30完成</b>。Jev评分后Codex逐题校准，保留原始决定。</p><p><b>必答要点：{m["point_score"]:.2f}/100</b>；严格通过：{m["strict_pass_count"]}/30。要点满分不代表额外陈述全部正确。</p><table><tr><th>指标</th><th>Jev原始</th><th>校准后</th></tr>'
    for key,label in [('fact_support','事实充分支持'),('citation_precision','单条引用有效'),('citation_coverage','引用组完整覆盖')]:
        a=stats['raw_jev'][key];b=m[key];page+=f'<tr><td>{label}</td><td>{a["percent"]:.2f}% ({a["numerator"]}/{a["denominator"]})</td><td>{b["percent"]:.2f}% ({b["numerator"]}/{b["denominator"]})</td></tr>'
    page+='</table><details><summary>与旧版全30题基线比较</summary>'+pre(comparison)+'</details><p>要点失分：'+html.escape('；'.join(r['id']+' '+str(r['final_metrics']['point_score']) for r in rows if r['final_metrics']['point_score']<100) or '无')+'</p><details><summary>配置、全部汇总、资源与限制</summary>'+pre(stats)+'</details><h2>逐题索引</h2><table><tr><th>题号</th><th>类型</th><th>要点分</th><th>严格通过</th><th>轨迹</th></tr>'
    for r in rows:
        url=(r.get('langfuse') or {}).get('url');link=f'<a href="{html.escape(url,quote=True)}">Langfuse</a>' if url else '无'
        page+=f'<tr><td><a href="#{r["id"]}">{r["id"]}</a></td><td>{r["case"]["group"]}</td><td>{r["final_metrics"]["point_score"]:.2f}</td><td>{"通过" if r["final_metrics"]["strict_pass"] else "未完全通过"}</td><td>{link}</td></tr>'
    page+='</table>'
    for r in rows:
        page+='<article id="'+r['id']+'"><h2>'+r['id']+' · '+str(r['final_metrics']['point_score'])+'分</h2><p>'+html.escape(r['case']['question'])+'</p><details><summary>参考答案与评分标准</summary>'+pre(r['case'])+'</details><h3>完整回答</h3>'+pre(r['answer'])+'<h3>校准说明</h3><p>'+html.escape(r['review']['reason'])+'</p><details><summary>逐项校准差异</summary>'+pre(r['review']['changes'])+'</details><details><summary>完整评分及轨迹入口</summary>'+pre({k:r[k] for k in ['raw_jev','calibrated','raw_metrics','final_metrics','langfuse','tools','budget']})+'</details></article>'
    page+='</html>'
    (OUT/'report.html').write_text(page,encoding='utf8');print(json.dumps(stats,ensure_ascii=False))
if __name__=='__main__':main()
