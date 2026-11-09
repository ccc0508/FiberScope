"""SQL-only full regression, explicit reference/trace review; no model judge."""
import json,html,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/sql-full-v7-20261109'
OUT=ROOT/'data/text-to-sql-evaluation/reports/sql-full-v7-20261109'
def read(p):return json.loads(p.read_text('utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    cases=read(RUN/'cases.json');refs=read(RUN/'sql-references.json');reviews=read(OUT/'reviews.json');rows=[]
    for c in cases:
        tid=c['id'];x=read(RUN/(tid+'.json'));review=reviews[tid]
        assert len(review['scores'])==4 and all(0<=v<=cap for v,cap in zip(review['scores'],[4,3,2,1]))
        rows.append(dict(case=c,answer=x.get('answer',''),status=x['status'],review=review,score=sum(review['scores']),reference=refs[tid],tools=[dict(request=t['request'],response=t.get('result')) for t in x['tool_calls']],citation_validation=x.get('citation_validation'),budget=x.get('budget_usage'),langfuse=x.get('langfuse'),result_sha256=hashlib.sha256((RUN/(tid+'.json')).read_bytes()).hexdigest(),elapsed_ms=x['end_to_end_ms']))
    queries=[t for r in rows for t in r['tools'] if t['request']['tool']=='query_experiment_data']
    xs=[read(RUN/(r['case']['id']+'.json')) for r in rows];usage=[m.get('usage') or {} for x in xs for m in x['model_calls']]
    summary=dict(count=len(rows),completed=sum(r['status']=='completed' for r in rows),score=sum(r['score'] for r in rows),max_score=10*len(rows),normalized_score=sum(r['score'] for r in rows)/len(rows)*10,full_score_count=sum(r['score']==10 for r in rows),lost=[dict(id=r['case']['id'],score=r['score'],reason=r['review']['reason']) for r in rows if r['score']<10],dimensions=[sum(r['review']['scores'][i] for r in rows) for i in range(4)],sql_attempts=len(queries),sql_completed=sum(t['response'].get('status')=='completed' for t in queries),model_calls=len(usage),total_tokens=sum(u.get('total_tokens',0) or 0 for u in usage),sum_question_seconds=sum(r['elapsed_ms'] for r in rows)/1000,answer_cost_usd=None,integrity=read(RUN/'integrity.json'),pipeline=xs[0].get('pipeline_version'),budget=xs[0].get('budget'),policy='Fresh independent first attempts. Codex checks reference SQL, actual execution and answers using 4/3/2/1 rubric. No Jev/Luna. Earlier 198/200 was a mixed-version overlay, not a paired control. Single run does not establish stability.')
    assert len(rows)==20 and all(summary['integrity'].values())
    write(OUT/'summary.json',summary);write(OUT/'results.json',rows)
    def pre(v):return '<pre>'+html.escape(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    page='<!doctype html><html lang="zh"><meta charset="utf-8"><title>SQL 20题全量回归</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ddd;padding:20px 0}summary{cursor:pointer}</style><h1>SQL专项20题 · 当前版本全量回归</h1><p>每题全新独立上下文，对照真实数据库及执行轨迹，按核心结果4、查询口径3、单位解释2、来源1评分。完成率不等于正确率。</p>'+pre(summary)
    for r in rows:
        page+=f'<article id="{r["case"]["id"]}"><h2>{r["case"]["id"]} · {r["score"]}/10</h2>'+pre(r['case']['question'])+'<h3>完整回答</h3>'+pre(r['answer'])+'<h3>评分理由</h3>'+pre(r['review'])+'<details><summary>标准、参考查询、实际调用、Trace</summary>'+pre({k:r[k] for k in ['case','reference','tools','citation_validation','langfuse']})+'</details></article>'
    (OUT/'report.html').write_text(page+'</html>',encoding='utf8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
