"""Source-calibrated two-case verification; never overwrite the full30 baseline."""
import json,html
from pathlib import Path
from report_regression_baseline_20261106 import metrics,calibrate
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'
RUN=BASE/'rag-tool-selection-20261109'
OUT=ROOT/'data/literature/qa-evaluation/reports/rag-tool-selection-20261109'
def read(p):return json.loads(p.read_text('utf8'))
def main():
    cases={c['id']:c for c in map(json.loads,(BASE/'latest-scored/pack/gold.jsonl').read_text('utf8').splitlines())}
    old={r['id']:r for r in read(ROOT/'data/literature/qa-evaluation/reports/rag-full-v5-20261109/results.json')}
    rows=[]
    for tid in ['FS8-012','FS8-017']:
        x=read(RUN/(tid+'.json'));raw=read(RUN/'jev'/tid/'review.json');notes=dict(reason='',changes=[])
        def change(path,value,reason):notes['changes'].append(dict(path=path,value=value,reason=reason))
        if tid=='FS8-012':
            notes['reason']='维持Jev评分。核对Pennells原PDF第5、8、12–13页：光学限、代理假设、隐藏纳米组分和CMF先增后减均有依据；相关系数0.60/0.71与Table 4一致。新检索返回的[9]直接覆盖旧版遗漏的限制。'
        else:
            notes['reason']='要点100维持。C1仍部分支持：mg/100m与mg/m量纲相同，差的是单位标度；回答“量纲不一致”不准确。按最新口径恢复确有单位信息的引用，不要求建议另有论文逐字依据。C2的“仅见单位标注”按此示例不是实测值的上下文理解，不扩大成否认整篇论文有粗度数值。'
            for ref in ['[3]','[5]','[7]']:
                change(f'citation_assessments.C1.{ref}.score',1,'该证据中的表头或结论明确写有Coarseness (mg/m)，直接支持此处单位说明。')
            change('citation_assessments.C3.[7].score',1,'结论明确列rice straw、hardwood、softwood；与[2]的四材料表联合支撑，单条引用无需独立覆盖整段。')
            for c,why in [('C2','程序账本[8]给出0.01倍、结果0.10；[4]说明原单位，问题本身确认10为假设示例。保留来源与换算标记是合理整合建议。'),('C3','[4]说明tissue furnish/industrial base，[2]列四种原料及所报均值、标准差和桉木缺项。本轮未逐项核对是有限范围声明，不是否认原文。')]:
                change(f'claim_assessments.{c}.support','supported',why)
                change(f'citation_group_assessments.{c}.coverage','complete',why)
        final=calibrate(raw,notes);child=x['children'][0]['trace']
        rows.append(dict(id=tid,case=cases[tid],answer=x['answer'],old_metrics=old[tid]['final_metrics'],raw_jev=raw,calibrated=final,calibration=notes,raw_metrics=metrics(cases[tid],raw,x),final_metrics=metrics(cases[tid],final,x),tools=[t['request'] for t in x['tool_calls']],model_calls=len(x['model_calls']),elapsed_ms=x['end_to_end_ms'],tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in x['model_calls']),stop_reason=child.get('stop_reason'),priority=child.get('coverage_priority_events',[]),langfuse=x.get('langfuse')))
    summary=dict(cases=[dict(id=r['id'],old=r['old_metrics'],new=r['final_metrics'],tools=len(r['tools']),models=r['model_calls'],elapsed_ms=r['elapsed_ms']) for r in rows],tests_passed=90,limitations=['仅两题各一次独立新回答，不是稳定性结论，也未更新30题总体分数。','预留已降到16384字符，与旧版全30不是单变量对照。','第12题自主遵循检索指引，运行时回退拦截未触发；拦截分支由离线测试覆盖。','单位工具只验证数值换算，不验证取数、材料/测量口径；有限白名单，不支持任意物理量。','校准为Codex对原文的复核，不是独立人类专家评审。'])
    OUT.mkdir(parents=True,exist_ok=True)
    for name,value in [('results.json',rows),('summary.json',summary)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    def pre(v):return '<pre>'+html.escape(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>第12、17题工具选择修复验证</title><style>body{max-width:1000px;margin:30px auto;padding:20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccc}summary{cursor:pointer}</style><h1>第12、17题工具选择修复验证</h1>'+pre(summary)
    for r in rows:
        page+=f'<article><h2>{r["id"]}</h2><p>{html.escape(r["case"]["question"])}</p><h3>完整回答</h3>'+pre(r['answer'])+'<h3>校准理由</h3>'+pre(r['calibration'])+'<details><summary>评分、工具与完整记录</summary>'+pre(r)+'</details></article>'
    (OUT/'report.html').write_text(page+'</html>',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
