"""Render reviewed baseline without sending answers to another model."""
import argparse
from html import escape
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);a=p.parse_args()
    folder=ROOT/'.rag-data/text-to-sql-evaluation'/a.run
    data=ROOT/'data/text-to-sql-evaluation'
    cases=json.loads((data/'cases-v1.json').read_text('utf8'))
    manifest=json.loads((folder/'manifest.json').read_text('utf8'))
    if manifest.get('selected_cases'):cases=[c for c in cases if c['id'] in manifest['selected_cases']]
    scores=json.loads((data/'reports'/a.run/'reviews.json').read_text('utf8'))
    references=json.loads((folder/'references.json').read_text('utf8'))
    results=[json.loads((folder/(c['id']+'.json')).read_text('utf8')) for c in cases]
    for c in cases:
        points=scores[c['id']]['scores']
        assert len(points)==4 and all(0<=n<=cap for n,cap in zip(points,[4,3,2,1]))
    total=sum(sum(s['scores']) for s in scores.values())
    attempts=sum(r['sql_attempts'] for r in results)
    successes=sum(r['sql_successes'] for r in results)
    tokens=sum(u.get('total_tokens',0) for r in results for u in r['usage'] if u)
    summary=dict(run=a.run,cases=len(cases),score=total,max_score=len(cases)*10,
        normalized_score=total/(len(cases)*10)*100,
        completed=sum(r['status']=='completed' for r in results),
        sql_attempts=attempts,sql_successes=successes,
        citation_passed=sum(r['citation_validation']['status'] in ('passed','repaired') for r in results),
        citation_repairs=sum(r['citation_validation']['status']=='repaired' for r in results),
        total_tokens=tokens,usage_records_missing=sum(u is None for r in results for u in r['usage']),
        cost='unknown',end_to_end_seconds='unknown',grader='Codex manual review against reference SQL and actual tool traces; no Jev/Luna scoring')
    dest=data/'reports'/a.run;dest.mkdir(parents=True,exist_ok=True)
    (dest/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (dest/'results.json').write_text(json.dumps(dict(cases=cases,results=results,references=references,review=scores),ensure_ascii=False,indent=2),encoding='utf8')
    def pre(value):return '<pre>'+escape(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'
    html=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>Text-to-SQL 基线</title><style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;color:#22334a;background:#f5f7fa}article{background:white;padding:24px;margin:24px 0;border:1px solid #dce2ea;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 system-ui}summary{cursor:pointer}h1,h2{line-height:1.4}small{color:#52657c}</style><h1>Text-to-SQL 开发基线 v1</h1>']
    html.append(f'<p>本轮固定{len(cases)}题，每题独立上下文，参考答案不提供给答题模型。每题一次，不挑选结果。评分为人工校准；不是Jev评分，不是holdout，也不是稳定性结论。</p>')
    html.append(pre(summary))
    html.append('<p>每题10分：核心结果4、查询口径3、单位与解释2、来源可追溯1。重点看实质错误，不要求字面SQL相同或每句重复引用。完整规则见同目录上两级README.md。</p>')
    for case,r in zip(cases,results):
        review=scores[case['id']]
        html.append('<article><h2>'+escape(case['id']+' · '+case['category'])+f' · {sum(review["scores"])}/10</h2>')
        html.append('<h3>题目</h3>'+pre(case['question'])+'<h3>参考要求</h3>'+pre(case['criteria']))
        html.append('<details><summary>参考 SQL 与真实结果</summary>'+pre(references[case['id']])+'</details>')
        html.append('<h3>完整回答</h3>'+pre(r['answer'])+'<h3>人工评分与依据</h3>'+pre(review))
        html.append('<details><summary>实际 SQL、结果、单位和引用检查</summary>'+pre(dict(queries=r['queries'],citation_validation=r['citation_validation']))+'</details></article>')
    html.append('</html>');(dest/'report.html').write_text('\n'.join(html),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
