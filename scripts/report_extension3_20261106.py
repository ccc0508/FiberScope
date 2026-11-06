"""Render three new cases with preserved Jev scores and explicit calibration."""
import html,json
from pathlib import Path
import judge_qa_eval as j
from report_agent_eightpapers_20261105 import calibrate,metrics,summary
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-extension3-20261106'
OUT=ROOT/'data/literature/qa-evaluation/reports/agent-extension3-20261106'
PACK=ROOT/'fiberscope-eval-8papers-extension-v1'
def main():
    notes=j.read_json(RUN/'calibration.json');rows=[]
    for c in j.read_jsonl(PACK/'gold.jsonl'):
        tid=c['id'];x=j.read_json(RUN/(tid+'.json'));raw=j.read_json(RUN/'jev'/tid/'review.json');v=calibrate(raw,notes[tid]);v.pop('decisions',None)
        rows.append(dict(case=c,answer=x['answer'],draft=x['draft'],raw_jev=raw,calibrated=v,calibration=notes[tid],
            final=metrics(c,v,x),jev=metrics(c,raw,x),status=x['status'],review_status=x['review_status'],
            tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']],model_calls=len(x['model_calls']),elapsed_seconds=x['end_to_end_ms']/1000,
            result_sha256=j.digest(RUN/(tid+'.json')),judge_input_sha256=j.digest(RUN/'jev'/tid/'input.json'),evidence=x['evidence']))
    total=dict(latest=summary(rows,'final'),raw_jev=summary(rows,'jev'),count=3,limitations=['每类仅一题且仅首次运行，不能推断稳定性或总体泛化。','新三题独立报告，不替换或混入原30题。','按既有宽严口径校准；不是独立人工专家评审。','非论文题引用N/A，不按满分填充。'])
    OUT.mkdir(parents=True,exist_ok=True);j.write(OUT/'results.json',rows);j.write(OUT/'summary.json',total)
    j.write(OUT/'provenance.json',dict(manifest=j.read_json(RUN/'manifest.json'),task_hashes=j.read_json(RUN/'task-pack-hashes.json')))
    def f(m):return ' / '.join('N/A' if m[k] is None else str(round(m[k],2)) for k in ['point_score','fact_support','citation_precision','citation_coverage','boundary'])+' / '+('通过' if m['strict_pass'] else '未通过')
    md='# 新增三题：首次独立评测\n\n六维顺序：要点 / 事实支持% / 单引有效% / 引用覆盖% / 边界0–2 / 严格通过。\n\n'
    body=''
    for r in rows:
        c=r['case'];md+=f"## {c['id']} · {c['group']}\n\n{c['question']}\n\nJev：{f(r['jev'])}\n\n校准：{f(r['final'])}\n\n{r['calibration']['reason']}\n\n"
        (OUT/(c['id']+'-answer.md')).write_text('# '+c['id']+'\n\n'+c['question']+'\n\n'+r['answer'],encoding='utf8')
        body+='<article><h2>'+c['id']+'</h2><p>'+html.escape(c['question'])+'</p><p>校准：'+f(r['final'])+'</p><p>'+html.escape(r['calibration']['reason'])+'</p><h3>完整回答</h3><pre>'+html.escape(r['answer'])+'</pre><details><summary>参考答案、评分及依据、调用轨迹与引用</summary><pre>'+html.escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details></article>'
    md+='\n'+ '\n'.join('- '+s for s in total['limitations'])+'\n'
    (OUT/'README.md').write_text(md,encoding='utf8')
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>新增三题评测</title><style>body{font:16px/1.7 system-ui;background:#f3f6fa;color:#24364b}main{max-width:1100px;margin:auto;padding:25px}article{background:white;padding:24px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}</style><main><pre>'+html.escape(md)+'</pre>'+body+'</main></html>',encoding='utf8')
    print(json.dumps([dict(id=r['case']['id'],final=r['final']) for r in rows],ensure_ascii=False))
if __name__=='__main__':main()
