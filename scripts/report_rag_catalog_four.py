"""Four-case RAG rerun plus explicitly labelled latest-answer overlay."""
import hashlib
import html
import json
from pathlib import Path
from report_regression_baseline_20261106 import metrics, calibrate, summary

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-catalog-four-20261108'
OUT=ROOT/'data/literature/qa-evaluation/reports/rag-catalog-four-20261108'
OLD=ROOT/'data/agent-evaluation/reports/specialists-three-suites-20261107/latest-scored'
PACK=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/latest-scored/pack'

def read(p):return json.loads(p.read_text('utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def pre(x):return '<pre>'+html.escape(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2))+'</pre>'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    notes=read(ROOT/'data/literature/qa-evaluation/calibration-rag-catalog-four-20261108.json')
    gold={c['id']:c for c in map(json.loads,(PACK/'gold.jsonl').read_text('utf8').splitlines())}
    old={r['case']['id']:r for r in read(OLD/'results.json') if r['case']['suite']=='rag'}
    previous_four={r['id']:r for r in read(ROOT/'data/literature/qa-evaluation/reports/rag-four-latest-20261108/results.json')}
    rows=[]
    for k in ('FS8-019','FS8-020','FS8-023','FS8-024'):
        x=read(RUN/(k+'.json'));raw=read(RUN/'jev'/k/'review.json');final=calibrate(raw,notes[k])
        rows.append(dict(id=k,case=gold[k],answer=x['answer'],status=x['status'],raw_jev=raw,calibrated=final,
                         review=notes[k],raw_metrics=metrics(gold[k],raw,x),final_metrics=metrics(gold[k],final,x),
                         before=previous_four[k]['final_metrics'],result_sha256=hashlib.sha256((RUN/(k+'.json')).read_bytes()).hexdigest(),
                         local_full_result=str(RUN/(k+'.json')),plan=x.get('plan'),budget=x.get('budget_usage'),
                         tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']],
                         children=[dict(role=c['role'],result=c.get('result'),coverage=c.get('coverage_report'),
                                        stop_reason=c.get('trace',{}).get('stop_reason')) for c in x.get('children',[])]))
    by={r['id']:r for r in rows};selected=[by.get(k,r) for k,r in old.items()]
    totals=dict(four_raw=summary(rows,'raw_metrics'),four_final=summary(rows,'final_metrics'),
                latest_30_overlay=summary(selected,'final_metrics'),previous_30=read(ROOT/'data/literature/qa-evaluation/reports/rag-four-latest-20261108/summary.json')['latest_30_overlay'],
                integrity=read(RUN/'integrity.json'),
                policy='Only four new independent answers; remaining 26 answers/scores preserved. Same 20/12/2/360 budget as preceding four-case run; new catalog/routing/coverage/fallback code. Other26 preserved from older results. Not a new full30 run or isolated causal/stability test.')
    write(OUT/'results.json',rows);write(OUT/'summary.json',totals)
    write(OUT/'selection.json',{k:by[k]['local_full_result'] if k in by else old[k]['local_full_result'] for k in old})
    write(OUT/'calibration.json',notes)
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>文献四题最新版补测</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{padding:20px;border-top:1px solid #ccc}</style><h1>文献19、20、23、24题补测</h1><p>Jev初评后按既定口径校准；旧结果保留，30题指标为仅替换四题的组合成绩。</p>'+pre(totals)
    for r in rows:
        page+='<article id="'+r['id']+'"><h2>'+r['id']+'：'+str(r['before']['point_score'])+' → '+str(r['final_metrics']['point_score'])+'</h2>'+pre(r['case'])+'<h3>完整回答</h3>'+pre(r['answer'])+'<h3>校准说明</h3>'+pre(r['review'])+'<details><summary>完整评分</summary>'+pre({k:r[k] for k in ['raw_metrics','final_metrics','raw_jev','calibrated']})+'</details><details><summary>路由与工具轨迹</summary>'+pre({k:r[k] for k in ['plan','budget','tools','children']})+'</details></article>'
    (OUT/'report.html').write_text(page+'</html>',encoding='utf8')
    print(json.dumps(totals,ensure_ascii=False))

if __name__=='__main__':main()
