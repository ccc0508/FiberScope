"""Render all paired results and explicit manual scores; never select best runs."""
from html import escape
import json
from pathlib import Path
from statistics import mean,median

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/text-to-sql-evaluation/reports/sql-prompt-ab-20261107'


def main():
    results=json.loads((DEST/'results.json').read_text('utf8'))
    reviews=json.loads((DEST/'reviews.json').read_text('utf8'))
    manifest=json.loads((DEST/'manifest.json').read_text('utf8'))
    def key(r):return f'{r["variant"]}-r{r["repeat"]}-{r["id"]}'
    for r in results:
        points=reviews[key(r)]['scores']
        assert len(points)==4 and all(0<=n<=cap for n,cap in zip(points,[4,3,2,1]))
    summary={}
    paired={(r['id'],r['repeat']) for r in results if all(any(x['id']==r['id'] and x['repeat']==r['repeat'] and x['variant']==v and x['status']=='completed' for x in results) for v in ('old','new'))}
    for label in ('old','new'):
        group=[r for r in results if r['variant']==label]
        times=[r['elapsed_seconds'] for r in group if r['elapsed_seconds'] is not None]
        score=sum(sum(reviews[key(r)]['scores']) for r in group)
        summary[label]=dict(answers=len(group),score=score,max_score=len(group)*10,normalized=score/(len(group)*10)*100,
            paired_completed_answers=len(paired),paired_score=sum(sum(reviews[key(r)]['scores']) for r in group if (r['id'],r['repeat']) in paired),paired_max_score=len(paired)*10,
            paired_tokens=sum(u.get('total_tokens',0) for r in group if (r['id'],r['repeat']) in paired for u in r['usage'] if u),
            paired_mean_seconds=mean(r['elapsed_seconds'] for r in group if (r['id'],r['repeat']) in paired and r['elapsed_seconds'] is not None) if paired else None,
            paired_sql_attempts=sum(r['sql_attempts'] for r in group if (r['id'],r['repeat']) in paired),
            completed=sum(r['status']=='completed' for r in group),
            sql_attempts=sum(r['sql_attempts'] for r in group),sql_successes=sum(r['sql_successes'] for r in group),
            tool_calls=sum(len(r['tool_calls']) for r in group),
            total_tokens=sum(u.get('total_tokens',0) for r in group for u in r['usage'] if u),
            cached_tokens=sum(u.get('cached_tokens',0) for r in group for u in r['usage'] if u),
            usage_missing=sum(u is None for r in group for u in r['usage']),
            mean_seconds=mean(times) if times else None,median_seconds=median(times) if times else None,
            cost='unknown',round_scores={str(rep):sum(sum(reviews[key(r)]['scores']) for r in group if r['repeat']==rep) for rep in (1,2)})
    (DEST/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    def pre(v):return '<pre>'+escape(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    html=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>SQL提示词配对对照</title><style>body{max-width:1150px;margin:40px auto;padding:20px;background:#f5f7fa;color:#233348;font:16px/1.7 system-ui}article{background:white;border:1px solid #dce2ea;border-radius:10px;padding:24px;margin:24px 0}pre{font:14px/1.7 system-ui;white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><h1>原提示词与新提示词：7题 × 两次独立运行</h1><p>两版共用当前SQL预检、错误反馈、结果元数据与引用校验。每题独立上下文，无参考答案输入；保留全部28次结果。人工评分仍按结果4、口径3、单位解释2、来源1。仅两次重复，不作显著性或稳定性保证。费用未知，Token不等于费用。</p>']
    html.append(pre(summary))
    for c in manifest['cases']:
        html.append('<h2>'+escape(c['id'])+'</h2>'+pre(c['question'])+'<p>判定要求：</p>'+pre(c['criteria']))
        for repeat in (1,2):
            for label in ('old','new'):
                r=next(r for r in results if r['id']==c['id'] and r['repeat']==repeat and r['variant']==label)
                review=reviews[key(r)]
                html.append(f'<article><h3>{label} · 第{repeat}次 · {sum(review["scores"])}/10</h3>'+pre(r['answer'])+pre(review))
                html.append('<details><summary>完整工具返回、耗时、用量和引用检查</summary>'+pre(r)+'</details></article>')
    html.append('</html>');(DEST/'report.html').write_text('\n'.join(html),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
