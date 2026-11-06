"""Merge latest accepted per-case answers and calibrated scores, never best-of scores."""
import copy,hashlib,html,json
from pathlib import Path
from report_agent_eightpapers_20261105 import summary,metrics
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/literature/qa-evaluation/reports'
OUT=BASE/'agent-all-latest-20261106'
SELECT={17:'agent-scoped-case17-repeat2-20261106',19:'agent-scoped-case19-20-20261106',20:'agent-scoped-case19-20-20261106',21:'agent-scoped-case21-22-20261106',22:'agent-scoped-case21-22-20261106',23:'agent-scoped-case23-24-20261106',24:'agent-section-recovery-case24-20261106'}
def read(p):return json.loads(p.read_text(encoding='utf8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def main():
    previous=read(BASE/'agent-eightpapers-latest-20261106/results.json');rows=copy.deepcopy(previous);manifest=[]
    for row in rows:
        tid=row['case']['id'];n=int(tid[-3:]);source=BASE/'agent-eightpapers-latest-20261106/results.json'
        if n in SELECT:
            name=SELECT[n];source=BASE/name/'grading.json';g=read(source)
            if isinstance(g,list):g=next(v for v in g if v['case']['id']==tid)
            run=ROOT/'.rag-data/evaluations'/name/(tid+'.json');x=read(run)
            assert x['status']=='completed' and x['answer']
            info=g.get('summary',g);expected=g.get('result_sha256',info.get('result_sha256'))
            assert not expected or digest(run)==expected,tid
            row.update(case=g['case'],answer=x['answer'],draft=x['draft'],raw_jev=g['raw_jev'],calibrated=g['calibrated'],source_run=name,result_sha256=digest(run))
            final=info['final_metrics']
            # Case 17 explicitly excludes arithmetic / local-gap groups from citation denominator.
            if n!=17:assert metrics(g['case'],g['calibrated'],x)==final,tid
            row['summary']=dict(id=tid,group=g['case']['group'],status=x['status'],review_status=x['review_status'],final=final,jev=info['raw_metrics'],reason=g.get('reason',info.get('notes','')),changes=g.get('changes',info.get('changes',[])))
            row.pop('latest_audit',None)
        row['calibrated'].pop('decisions',None)
        row['answer_sha256']=hashlib.sha256(row['answer'].encode()).hexdigest()
        manifest.append(dict(case_id=tid,source_run=row['source_run'],grading_source=source.relative_to(ROOT).as_posix(),grading_sha256=digest(source),answer_sha256=row['answer_sha256']))
    assert len(rows)==30 and len({r['case']['id'] for r in rows})==30
    for n in range(1,31):
        if n not in SELECT:assert rows[n-1]['answer']==previous[n-1]['answer'] and rows[n-1]['summary']['final']==previous[n-1]['summary']['final']
    totals=dict(report_type='latest selected mixed-version results; not a new end-to-end test',answer_regenerated=False,judge_rerun=False,
        latest=summary([r['summary'] for r in rows],'final'),previous_summary=summary([r['summary'] for r in previous],'final'),
        groups={g:summary([r['summary'] for r in rows if r['case']['group']==g],'final') for g in ['single','cross','no_paper']},
        below_full_points=[dict(id=r['case']['id'],score=r['summary']['final']['point_score']) for r in rows if r['summary']['final']['point_score']<100],
        strict_pass_cases=[r['case']['id'] for r in rows if r['summary']['final']['strict_pass']],
        limitations=['不同版本、不同时间的指定结果合并，不是最新版一次完整30题端到端测试。','按题选择最新指定回答，不按最高分挑选；保留各题已确认校准。','非论文题不适用引用指标，不以100填补N/A。','要点分按题平均；事实/引用按有效分子分母合并，不平均百分比。','第17题沿用已确认的算术及局部证据不足说明引用分母豁免。','事实核查单位是复合语义段，不是单句；Codex校准不等于独立人类专家审核。','第24题等历史失败尝试保留在原报告；本汇总不用于估计首次运行成功率。'])
    OUT.mkdir(parents=True,exist_ok=True)
    write(OUT/'results.json',rows);write(OUT/'summary.json',totals);write(OUT/'manifest.json',manifest)
    def val(x):return 'N/A' if x is None else f'{x:.2f}'
    def score(m):return ' / '.join([val(m['point_score']),val(m['fact_support']),val(m['citation_precision']),val(m['citation_coverage']),str(m['boundary'])+'/2','通过' if m['strict_pass'] else '未通过'])
    t=totals['latest'];md='# 30题最新评分总汇\n\n本次未生成新回答、未调用评委；逐题纳入已确认的最新回答和校准分。\n\n'
    md+=f"要点均分：{t['point_score']:.2f}；严格通过：{t['strict_pass_count']}/30；边界均分：{t['boundary_mean']:.2f}/2。\n\n"
    for k,label in [('fact_support','事实充分支持'),('citation_precision','单引有效'),('citation_coverage','引用组覆盖')]:
        v=t[k];md+=f"- {label}：{v['percent']:.2f}%（{v['numerator']}/{v['denominator']}）。\n"
    md+='\n| 题号 | 要点 | 事实支持% | 单引有效% | 引用覆盖% | 严格通过 |\n|---|---:|---:|---:|---:|---|\n'
    for r in rows:
        m=r['summary']['final'];md+=f"| {r['case']['id']} | {val(m['point_score'])} | {val(m['fact_support'])} | {val(m['citation_precision'])} | {val(m['citation_coverage'])} | {'是' if m['strict_pass'] else '否'} |\n"
    md+='\n'+ '\n'.join('- '+s for s in totals['limitations'])+'\n'
    (OUT/'README.md').write_text(md,encoding='utf8')
    esc=html.escape;body=''
    for r in rows:
        body+=f"<article id='{r['case']['id']}'><h2>{r['case']['id']} · {esc(r['case']['question'])}</h2><p>来源：{esc(r['source_run'])}</p><p>{score(r['summary']['final'])}</p><p>{esc(r['summary']['reason'])}</p><details><summary>完整回答</summary><pre>{esc(r['answer'])}</pre></details><details><summary>参考答案、Jev及最终校准</summary><pre>{esc(json.dumps(dict(case=r['case'],raw_jev=r['raw_jev'],calibrated=r['calibrated'],summary=r['summary']),ensure_ascii=False,indent=2))}</pre></details></article>"
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>30题最新评分总汇</title><style>body{font:16px/1.7 system-ui;background:#f3f6fa;color:#20354a}main{max-width:1200px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}article{background:white;margin:18px 0;padding:24px;border-radius:10px}summary{cursor:pointer}</style><main><pre>'+esc(md)+'</pre><p>逐题六维顺序：要点 / 事实支持 / 单引有效 / 引用覆盖 / 边界 / 严格通过。</p>'+body+'</main></html>'
    (OUT/'report.html').write_text(page,encoding='utf8')
    print(json.dumps(totals,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
