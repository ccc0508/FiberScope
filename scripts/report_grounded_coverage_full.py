"""Publish mixed rubric-v1: raw Jev decisions, calibrated dimensions and full answers."""
import json,html,hashlib,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/grounded-coverage-full-20261108'
OUT=ROOT/'data/mixed-agent-evaluation/reports/grounded-coverage-full-20261108'
def read(p):return json.loads(p.read_text('utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 rubric=read(ROOT/'data/mixed-agent-evaluation/rubric-v1.json');notes=read(ROOT/'data/mixed-agent-evaluation/calibration-grounded-coverage-full-20261108.json');selection={c['id']:str((BASE/(c['id']+'.json')).relative_to(ROOT)) for c in read(BASE/'cases.json')}
 rows=[];cost=0;unknown=0
 for case in read(BASE/'cases.json'):
  if case['suite']!='mixed':continue
  k=case['id'];x=read(BASE/(k+'.json'));jp=BASE/'mixed-jev-v1'/k;raw=read(jp/'review.json');n=notes[k]
  for d,v in n['scores'].items():assert v in [rubric['dimensions'][d]['weight']*f for f in rubric['levels'].values()]
  rows.append(dict(id=k,question=case['question'],checks=case['checks'],answer=x['answer'],status=x['status'],selected_source=selection[k],answer_sha256=hashlib.sha256((BASE/(k+'.json')).read_bytes()).hexdigest(),judge_input_sha256=hashlib.sha256((jp/'input.json').read_bytes()).hexdigest() if (jp/'input.json').exists() else None,raw_jev=raw,final=n,total=sum(n['scores'].values()),changes=[dict(dimension=d,old=raw['scores'][d],new=v,reason=n['reasons'][d]) for d,v in n['scores'].items() if raw['scores'][d]!=v],tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']]))
  for ap in jp.glob('attempt-*.json'):
   u=read(ap).get('usage') or {};c=u.get('reported_cost_usd')
   if c is None:unknown+=1
   else:cost+=c
 assert len(rows)==20
 summary=dict(rubric_version=rubric['version'],count=20,completed=sum(r['status']=='completed' for r in rows),raw_jev_mean=statistics.mean(r['raw_jev']['total'] for r in rows),calibrated_mean=statistics.mean(r['total'] for r in rows),score_sum=sum(r['total'] for r in rows),max_score=2000,dimension_means={d:statistics.mean(r['final']['scores'][d] for r in rows) for d in rubric['dimensions']},bands={'>=90':sum(r['total']>=90 for r in rows),'75-<90':sum(75<=r['total']<90 for r in rows),'60-<75':sum(60<=r['total']<75 for r in rows),'<60':sum(r['total']<60 for r in rows)},judge_cost_usd=cost,judge_cost_unknown_attempts=unknown,limitations=['Rubric created after seeing answers: developmental, not preregistered or holdout.','One frozen final-code twenty-case first-attempt run; failures count zero. Comparator is prior budget20-v1 overlay. Not holdout or repeated stability evaluation.','Jev uses frozen answers, evidence ledger and tool results, not image pixels or all full papers; Codex calibrates with source/figure checks, not independent human expert review.','Scores are coarse weighted ordinal ratings, not accuracy probabilities; not comparable directly to RAG key-point metric.'])
 summary['integrity']=read(BASE/'integrity.json')
 old={r['id']:r for r in read(ROOT/'data/mixed-agent-evaluation/reports/budget20-v1/results.json')}
 summary['previous_mean']=sum(old[r['id']]['total'] for r in rows)/len(rows)
 summary['delta']=summary['calibrated_mean']-summary['previous_mean']
 successful=[r for r in rows if r['status']=='completed']
 summary['completed_subset']={'count':len(successful),'current_mean':statistics.mean(r['total'] for r in successful),'previous_same_cases_mean':statistics.mean(old[r['id']]['total'] for r in successful)}
 summary['unfinished_cases']=[{'id':r['id'],'saved_status':r['status'],'worker_returncode':read(BASE/(r['id']+'.json')).get('worker_returncode'),'stop_reason':read(BASE/(r['id']+'.json')).get('stop_reason')} for r in rows if r['status']!='completed']
 summary['paired']=[dict(id=r['id'],before=old[r['id']]['total'],after=r['total'],delta=r['total']-old[r['id']]['total']) for r in rows]
 summary['first_attempt_completed']=sum(read(BASE/(r['id']+'.json'))['status']=='completed' for r in rows)
 summary['first_attempt_mean']=summary['calibrated_mean']
 summary['format_repairs']=sum(f.get('repair_attempted',False) for r in rows for f in read(BASE/(r['id']+'.json')).get('format_checks',[]))
 summary['tokens_reported']=sum((m.get('usage') or {}).get('total_tokens',0) or 0 for r in rows for m in read(BASE/(r['id']+'.json')).get('model_calls',[]))
 summary['usage']={r['id']:read(BASE/(r['id']+'.json')).get('budget_usage') for r in rows}
 diagnostics=[]
 for r in rows:
  x=read(BASE/(r['id']+'.json'))
  diagnostics.append(dict(id=r['id'],plan=x.get('plan'),allocations=[dict(role=c['role'],allocation=c.get('allocation'),status=c.get('status'),result=c.get('result')) for c in x.get('children',[])],budget_usage=x.get('budget_usage'),review_status=x.get('review_status'),format_checks=x.get('format_checks'),task_contract=x.get('task_contract'),coverage=[dict(role=c['role'],report=c.get('coverage_report'),retry=c.get('trace',{}).get('coverage_retry_requested')) for c in x.get('children',[])],tools=r['tools']))
 write(OUT/'diagnostics.json',diagnostics)
 write(OUT/'summary.json',summary);write(OUT/'results.json',rows);write(OUT/'rubric.json',rubric)
 esc=html.escape
 def pre(v):return '<pre>'+esc(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
 labels={'database':'实验数据','literature':'文献证据','integration':'综合判断','traceability':'引用追溯','boundaries':'边界诚实'}
 table='<table><tr><th>题号</th>'+''.join('<th>'+v+'</th>' for v in labels.values())+'<th>Jev</th><th>校准</th><th>上轮</th><th>变化</th></tr>'
 for r in rows:table+='<tr><td><a href="#'+r['id']+'">'+r['id']+'</a></td>'+''.join('<td>'+str(r['final']['scores'][d])+'</td>' for d in labels)+f"<td>{r['raw_jev']['total']}</td><td>{r['total']}</td><td>{old[r['id']]['total']}</td><td>{r['total']-old[r['id']]['total']:+.1f}</td></tr>"
 table+='</table>'
 body=''
 for r in rows:
  body+='<article id="'+r['id']+'"><h2>'+r['id']+' · '+str(r['total'])+'分</h2><p>'+esc(r['question'])+'</p><ul>'+''.join('<li><b>'+labels[d]+' '+str(r['final']['scores'][d])+'分：</b>'+esc(r['final']['reasons'][d])+'</li>' for d in labels)+'</ul><details><summary>完整回答</summary>'+pre(r['answer'])+'</details><details><summary>Jev原始评分及校准差异</summary>'+pre(dict(raw_jev=r['raw_jev'],changes=r['changes']))+'</details><details><summary>题目要求、工具轨迹及来源</summary>'+pre({k:r[k] for k in ('checks','tools','selected_source','answer_sha256','judge_input_sha256')})+'</details></article>'
 page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全量20题评分</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f4f6fa;color:#23364b}article{background:white;margin:20px 0;padding:22px;border:1px solid #d8e0ea}table{border-collapse:collapse;background:white}td,th{border:1px solid #d8e0ea;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}summary{cursor:pointer}</style><h1>全量20题 · '+str(summary['calibrated_mean'])+'分</h1><p>Jev初评，Codex逐题校准；最终代码全量20题，逐题独立上下文；首轮结果完整保留，不用开发阶段答案替换。标准为事后建立的开发评分口径，不是隐藏测试或上线认证。</p><details><summary>完整评分规则</summary>'+pre(rubric)+'</details><details><summary>总体指标与限制</summary>'+pre(summary)+'</details>'+table+body+'</html>'
 (OUT/'report.html').write_text(page,encoding='utf8')
 lines=['# 原文任务清单与完成检查：全量20题评分 v1','',f"Jev初评均分：{summary['raw_jev_mean']:.2f}；校准后：{summary['calibrated_mean']:.2f}（{summary['score_sum']}/2000）。",'', '每题实验数据30、文献证据30、综合判断20、引用追溯10、边界诚实10分。按0/25/50/75/100%五档评分。第20题正确澄清后暂停文献为允许行为，不扣未检索。诚实缺口扣内容完整性，不重复扣诚实性。','', '| 题号 | Jev | 校准 |','|---|---:|---:|']
 for r in rows:lines.append(f"| {r['id']} | {r['raw_jev']['total']} | {r['total']} |")
 lines+=['',f"上轮校准均分：{summary['previous_mean']:.2f}；本轮变化：{summary['delta']:+.2f}。首轮完成{summary['first_attempt_completed']}/20；本轮完成{summary['completed']}/20。",'','本标准建立于已有答案之后，属于开发集试行口径；不是预注册验证或独立专家评分。今后修改须升级版本、全量重评。文献要点分与本评分不是相同维度，不机械合成70题统一准确率。完整扣分原因及答案见report.html。']
 (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
