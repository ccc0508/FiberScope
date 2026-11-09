"""Publish both development attempts and final source-calibrated case20 result."""
import json,html,hashlib
from pathlib import Path
from report_regression_baseline_20261106 import metrics,calibrate
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'
OUT=ROOT/'data/literature/qa-evaluation/reports/rag-coverage-priority-20261109'
def read(p):return json.loads(p.read_text('utf8'))
def main():
    case=next(json.loads(l) for l in (BASE/'latest-scored/pack/gold.jsonl').read_text('utf8').splitlines() if json.loads(l)['id']=='FS8-020')
    rows=[]
    for revision in [1,2]:
        run=BASE/('rag-coverage-priority-20261109'+('' if revision==1 else '-r2'))
        x=read(run/'FS8-020.json');raw=read(run/'jev/FS8-020/review.json')
        notes=dict(reason='',changes=[])
        def change(path,value,reason):notes['changes'].append(dict(path=path,value=value,reason=reason))
        change('citation_group_assessments.C1.coverage','complete','开头总结可继承后文明确引用，无新事实，不要求重复引文。')
        if revision==1:
            notes['reason']='开发首轮要点齐全，但读取仍不均衡，因此补充无正文论文优先提醒后再跑，不按分数挑选答案。保留C5额外断言/引用问题。Uddin原料为rice straw，写稻麦草添加了未经支持的麦草，额外事实降为部分支持。'
            change('claim_assessments.C3.support','partially_supported','原料列表原文为rice straw，不能扩大为稻麦草。')
            change('citation_group_assessments.C3.coverage','partial','引用未支持新增麦草原料。')
        else:
            notes['reason']='四必答均完整，保持100分。保留C3事实/引用部分支持：额外把解析文本中的0.34/0.4当作论文冲突，PDF结论原文为0.94（Jev输入原文也可见）。不是要点漏答，但仍是实质错误。总结和有限范围声明按既定口径校准。'
            change('citation_assessments.C4.[15].score',1,'[15]直接说明Valley分次打浆5–10分钟及纤维质量测定，支持过程维度对比。')
            change('claim_assessments.C4.support','supported','输入族、损伤中间量、处理轴、目标定义和分组建议已由前文明确说明；不能直接拼接指缺少对齐前不能混用，不解释为禁止任何统一宽表。')
            change('citation_group_assessments.C4.coverage','complete','实际引用联合覆盖对照；无需每个建议再另附论文逐字表述。')
            change('claim_assessments.C5.support','supported','仅限定可见材料未提供精确序列构成/候选输入探索；未否认论文有LSTM、回收轮次或七项输入，按有限范围说明接受。')
        final=calibrate(raw,notes)
        rows.append(dict(revision=revision,case=case,answer=x['answer'],status=x['status'],raw_jev=raw,calibrated=final,calibration=notes,raw_metrics=metrics(case,raw,x),final_metrics=metrics(case,final,x),tools=[t['request'] for t in x['tool_calls']],model_calls=len(x['model_calls']),elapsed_ms=x['end_to_end_ms'],tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in x['model_calls']),stop_reason=x['children'][0]['trace']['stop_reason'],priority=x['children'][0]['trace'].get('coverage_priority_events',[]),langfuse=x.get('langfuse'),result_sha256=hashlib.sha256((run/'FS8-020.json').read_bytes()).hexdigest()))
    old=next(r for r in read(ROOT/'data/literature/qa-evaluation/reports/rag-full-v5-20261109/results.json') if r['id']=='FS8-020')
    summary=dict(baseline=old['final_metrics'],final=rows[1]['final_metrics'],development_first_attempt=rows[0]['final_metrics'],final_tools=len(rows[1]['tools']),final_model_calls=rows[1]['model_calls'],elapsed_ms=rows[1]['elapsed_ms'],tokens=rows[1]['tokens'],priority_replay=read(BASE/'rag-coverage-priority-20261109-r2/priority-replay.json'),limitations=['Two sequential development revisions, both preserved; final revision chosen by code order, not answer score.','Reserve changed from old full30 65536 to16384 and scheduling changed; not isolated causal attribution.','Only FS8-020 rerun; no new full30 aggregate.','Coverage availability and declared targets do not prove semantic support.','Final post-run source-access guard hardening replayed: all four decisions and model-facing priority payloads identical; no additional model call.'])
    OUT.mkdir(parents=True,exist_ok=True)
    for name,value in [('results.json',rows),('summary.json',summary)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    def pre(v):return '<pre>'+html.escape(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>第20题覆盖优先验证</title><style>body{max-width:1000px;margin:30px auto;font:16px/1.7 system-ui;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccc;padding:20px 0}summary{cursor:pointer;color:#2467ac}</style><h1>第20题 · 覆盖优先验证</h1><p>旧版要点87.5 → 本次最终版100。四次工具，自然结束；额外R²解析错误仍保留扣分，不是全维度满分。</p>'+pre(summary)
    for r in reversed(rows):
        page+=f'<article><h2>修订{r["revision"]}</h2><p>{html.escape(case["question"])}</p><h3>完整回答</h3>'+pre(r['answer'])+'<h3>校准说明</h3>'+pre(r['calibration'])+'<details><summary>工具、原始评分与完整明细</summary>'+pre(r)+'</details></article>'
    (OUT/'report.html').write_text(page+'</html>',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
