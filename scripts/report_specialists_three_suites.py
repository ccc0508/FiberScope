"""Publish first attempts, provenance and separated suite metrics; never pool unlike rubrics."""
from collections import Counter
from hashlib import sha256
from html import escape
import json, statistics
from pathlib import Path
from report_regression_baseline_20261106 import metrics,calibrate

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'
OUT=ROOT/'data/agent-evaluation/reports/specialists-three-suites-20261107'
def read(p):return json.loads(p.read_text('utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def pre(x):return '<pre>'+escape(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2))+'</pre>'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cases=read(RUN/'cases.json');gold={c['id']:c for c in map(json.loads,(RUN/'pack/gold.jsonl').read_text('utf8').splitlines())}
    notes=read(RUN/'reviews.json') if (RUN/'reviews.json').exists() else {}
    rows=[];body=[]
    for c in cases:
        path=RUN/(c['id']+'.json')
        if not path.exists():continue
        x=read(path);record=dict(case=c,result=x,result_sha256=sha256(path.read_bytes()).hexdigest(),review=notes.get(c['id']))
        jp=RUN/'jev'/c['id']/'review.json'
        if jp.exists():
            raw=read(jp);record['raw_jev']=raw;record['raw_metrics']=metrics(gold[c['id']],raw,x)
            if record['review']:
                final=calibrate(raw,record['review']);record['calibrated']=final;record['final_metrics']=metrics(gold[c['id']],final,x)
        rows.append(record)
        trace=dict(plan=x.get('plan'),budget=x.get('budget_usage'),tools=[dict(request=t.get('request'),status=t.get('status')) for t in x.get('tool_calls',[])],
            child_results=[dict(role=h.get('role'),status=h.get('status'),result=h.get('result'),raw_answer=h.get('trace',{}).get('answer'),stop_reason=h.get('trace',{}).get('stop_reason')) for h in x.get('children',[])],citation_validation=x.get('citation_validation'))
        body.append('<article><h2>'+escape(c['id']+' · '+c['question'])+'</h2><p>'+escape(str(x['status'])+' · '+str(x.get('stop_reason') or '')+' · '+str((x.get('plan') or {}).get('route')))+f' · {x["end_to_end_ms"]/1000:.1f}秒</p><h3>完整回答</h3>'+pre(x.get('answer') or '未生成可交付的最终回答')+'<h3>复核</h3>'+pre(record.get('review') or '尚未人工核验；不以完成状态代替正确性')+'<details><summary>参考要求</summary>'+pre(gold.get(c['id'],c))+'</details><details><summary>评分详情</summary>'+pre({k:record.get(k) for k in ['raw_metrics','final_metrics','raw_jev','calibrated']})+'</details><details><summary>路由、工具和子 Agent 交接</summary>'+pre(trace)+'</details></article>')
    summary={}
    for suite in ['rag','sql','mixed']:
        selected=[r for r in rows if r['case']['suite']==suite];xs=[r['result'] for r in selected]
        usage=[m.get('usage') for x in xs for m in x.get('model_calls',[])]
        s=dict(attempted=len(xs),expected=30 if suite=='rag' else 20,completed=sum(x['status']=='completed' for x in xs),
            statuses=dict(Counter(x['status'] for x in xs)),failure_reasons=dict(Counter(x.get('stop_reason') for x in xs if x['status']!='completed')),
            routes=dict(Counter((x.get('plan') or {}).get('route') for x in xs)),
            total_question_seconds=sum(x['end_to_end_ms'] for x in xs)/1000,
            model_calls=len(usage),total_tokens=sum((u or {}).get('total_tokens',0) or 0 for u in usage),usage_missing=sum(not u for u in usage),cost_usd=None)
        if suite=='rag':
            for key in ['raw_metrics','final_metrics']:
                scored=[r[key] for r in selected if key in r];den=len(scored)
                failed=sum(x['status']!='completed' for x in xs)
                stats=dict(scored_answers=den,completed_answers_pending_review=s['completed']-den,failed_no_answer=failed,
                    point_mean_completed=statistics.mean(m['point_score'] for m in scored) if den else None,
                    point_mean_all_attempts_failure_zero=sum(m['point_score'] for m in scored)/(den+failed) if den+failed and den==s['completed'] else None,
                    strict_pass_count=sum(m['strict_pass'] for m in scored))
                for name,n,d in [('fact_support','supported_facts','fact_count'),('citation_precision','supported_pairs','pair_count'),('citation_coverage','covered_groups','group_count')]:
                    nn=sum(m[n] for m in scored);dd=sum(m[d] for m in scored);stats[name]=dict(numerator=nn,denominator=dd,percent=100*nn/dd if dd else None)
                s[key]=stats
        elif suite=='sql':
            graded=[r['review'] for r in selected if r.get('review') and 'scores' in r['review']]
            s.update(graded=len(graded),score=sum(sum(v['scores']) for v in graded),max_score=len(graded)*10)
        else:
            s['scoring_note']='首轮综合开发题，尚无独立核验完整标准答案；逐题定性复核，不发布伪精确总分。'
            s['review_outcomes']=dict(Counter((r.get('review') or {}).get('outcome','pending') for r in selected))
        summary[suite]=s
    summary['manifest']=read(RUN/'manifest.json')
    summary['integrity']=read(RUN/'integrity.json') if (RUN/'integrity.json').exists() else None
    summary['method']='每题独立上下文、首次作答，无挑选或补跑替换。RAG Jev评分与Codex校准分开；SQL对照冻结数据库参考结果；综合题只报告核验发现。完成率不是正确率。费用未知，不把token计为费用。'
    summary['jev_usage']={'reported_cost_usd':sum(float((read(p).get('usage') or {}).get('reported_cost_usd') or 0) for p in (RUN/'jev').glob('*/attempt-*.json'))}
    previous=ROOT/'data/literature/qa-evaluation/reports/agent-regression-baseline-20261106/summary.json'
    if previous.exists():
        old=read(previous)
        summary['previous_rag_reference']={k:old.get(k) for k in ['completed','count','calibrated','usage']}
        summary['comparison_limit']='同一30题的旧单Agent基线供参考；本轮为新分工架构12模型调用预算，旧版预算不同，且每题只有一次；不是多次配对稳定性结论。'
    failures=RUN/'failure-diagnosis.json'
    if failures.exists():
        write(OUT/'failure-diagnosis.json',read(failures))
        summary['failure_stages']=dict(Counter(r['stage'] for r in read(failures)))
    write(OUT/'summary.json',summary)
    # Full provider/tool payloads remain immutable in the local run; publish a compact audit bundle.
    published=[]
    for r in rows:
        x=r['result'];clean={k:v for k,v in x.items() if k not in {'model_calls','tool_calls','tool_trace','children','evidence'}}
        clean['model_calls']=[{k:m.get(k) for k in ['stage','status','error_type','usage']} for m in x.get('model_calls',[])]
        clean['tool_calls']=[dict(request=t.get('request'),status=t.get('status'),child_id=t.get('child_id')) for t in x.get('tool_calls',[])]
        clean['children']=[dict(role=h.get('role'),status=h.get('status'),result=h.get('result'),stop_reason=h.get('trace',{}).get('stop_reason'),raw_answer=h.get('trace',{}).get('answer')) for h in x.get('children',[])]
        clean['evidence_manifest']=[{k:e.get(k) for k in ['ref','kind','id']} for e in x.get('evidence',[])]
        published.append(dict(r,result=clean,local_full_result=str(RUN/(r['case']['id']+'.json'))))
    write(OUT/'results.json',published)
    write(OUT/'sql-references.json',read(RUN/'sql-references.json'))
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>三套评测 · Specialists</title><style>body{background:#f4f6fa;color:#21334a;font:16px/1.7 system-ui;margin:0}main{max-width:1100px;margin:auto;padding:28px}article{background:white;padding:24px;margin:20px 0;border:1px solid #d5dfeb;border-radius:10px}h2{font-size:19px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}summary{cursor:pointer;color:#245d9b}details{margin:14px 0}</style><main><h1>最新版 Planner＋SQL／文献子 Agent · 三套评测</h1><p>'+escape(summary['method'])+'</p><details open><summary>汇总与固定配置</summary>'+pre(summary)+'</details>'+''.join(body)+'</main></html>'
    (OUT/'report.html').write_text(page,encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k in ['rag','sql','mixed']},ensure_ascii=False))

if __name__=='__main__':main()
