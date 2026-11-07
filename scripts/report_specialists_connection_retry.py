"""Publish authorized retry separately, retaining original failed attempts."""
import json,html
from hashlib import sha256
from rerun_specialists_connection_failures import ROOT,BASE,OUT
DEST=ROOT/'data/agent-evaluation/reports/specialists-three-suites-20261107'
def main():
    reviews={
      'MIX17':'主要要求完成：精确12345转查得0行；论文PFI档位0/4000/8000/12000/16000正确；不换档、不插值、不把论文数据填成本地实测。无连接异常。部分额外引用[3][6]针对氢键章节，引用范围仍可收敛。',
      'MIX18':'主要判断正确：真实目录没有电耗字段，不能由转数翻倍证明能耗翻倍，两文PFI条件已核对。但本地字段说明附[1][2][3]，实际这些编号是论文文本而非目录，存在语义错配。还将Motamedian的有/无淀粉两组概括为加淀粉，遗漏对照条件；本地未知条件不能直接称与论文不同。'}
    rows=[]
    for tid in ['MIX17','MIX18']:
        path=OUT/(tid+'.json');x=json.loads(path.read_text('utf8'));old=json.loads((BASE/(tid+'.json')).read_text('utf8'))
        rows.append(dict(id=tid,question=x['question'],old_status=old['status'],old_reason='SQL child APIConnectionError',status=x['status'],answer=x['answer'],review=reviews[tid],
          end_to_end_ms=x['end_to_end_ms'],budget_usage=x['budget_usage'],result_sha256=sha256(path.read_bytes()).hexdigest(),
          tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']],
          usage=[m.get('usage') for m in x['model_calls']],citation_validation=x['citation_validation']))
    summary=dict(policy='仅授权重跑MIX17/18，各独立新上下文一次，配置/预算不变，原始70题基线保留。更新完成率为补跑合并视角，不能当首轮完成率或质量通过率。',
      original_mixed_completed=13,latest_mixed_completed=13+sum(x['status']=='completed' for x in rows),mixed_total=20,
      original_all_completed=54,latest_all_completed=54+sum(x['status']=='completed' for x in rows),all_total=70,
      rag_score_unchanged=79.16666666666667,sql_score_unchanged=79, mixed_quality_score=None,
      integrity=json.loads((OUT/'integrity.json').read_text('utf8')),rows=rows)
    (DEST/'connection-retry-1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    def pre(x):return '<pre>'+html.escape(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2))+'</pre>'
    page='<!doctype html><html lang="zh"><meta charset="utf-8"><title>MIX17/18补跑</title><style>body{max-width:1000px;margin:32px auto;padding:20px;font:16px/1.8 system-ui;color:#24364a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.8 system-ui}article{border-top:1px solid #ccc;padding:20px 0}</style><h1>综合第17、18题 · 连接异常补跑</h1><p>'+html.escape(summary['policy'])+'</p><p>补跑2/2完成；综合题合并完成率15/20（75%），全部56/70（80%）。原首轮分别13/20、54/70。RAG和SQL评分不变；综合题无数值总分。</p>'
    for r in rows:page+='<article><h2>'+r['id']+'</h2>'+pre(r['question'])+'<h3>复核</h3>'+pre(r['review'])+'<h3>完整新回答</h3>'+pre(r['answer'])+'<details><summary>工具与运行记录</summary>'+pre({k:v for k,v in r.items() if k not in ['answer','question']})+'</details></article>'
    (DEST/'connection-retry-1.html').write_text(page,encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
