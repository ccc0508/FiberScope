"""Frozen six-answer compact-format comparison; raw Jev and targeted audit kept separate."""
from collections import Counter
from html import escape
import statistics
from pathlib import Path
from dotenv import dotenv_values
import judge_qa_eval as judge
import report_relation_paired_20261103 as prior
import report_qa_system_benchmark as scoring
from validate_relation_compact_20261103 import ROOT, STUDY, CASES
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/relation-compact-20261103'


def main():
    require(not PUBLIC.exists(),'Keep published results immutable')
    prior.STUDY=STUDY;prior.CASES=CASES
    rows=prior.inspect()
    require(len(rows)==6,'Need all six saved results')
    plan=judge.read_json(STUDY/'plan.json')
    require(all(judge.digest(STUDY/'runtime'/p)==h for p,h in plan['source_files'].items()),'Frozen runtime changed')
    for a in plan['attempts']:
        require(judge.read_json(STUDY/a['directory']/'manifest.json')['source_files']==plan['source_files'],'Runtime differs')
    audit=judge.read_json(STUDY/'focused-source-audit.json')
    require(audit['reviewer']=='Codex' and audit['scope']=='targeted_checks_not_full_five_dimension_rescore','Audit attribution required')
    checks={(a['attempt'],a['task_id']):a for a in audit['items']}
    require(set(checks)=={(r['attempt'],r['task_id']) for r in rows},'Incomplete audit')
    for r in rows:
        a=checks[(r['attempt'],r['task_id'])]
        require(a['result_sha256']==r['result_sha256'] and type(a['target_pass']) is bool,'Audit changed')
        r['focused_source_audit']=a
    versions=['v2_relation','v2_relation_compact']
    common=[tid for tid in CASES if all(any(r['version']==v and r['task_id']==tid and r['raw_jev_review'] for r in rows) for v in versions)]
    summary={}
    for v in versions:
        rs=[r for r in rows if r['version']==v];rounds=[q for r in rs for q in r['trace']['rounds']]
        summary[v]=dict(raw_jev_matched=scoring.summarize([r['raw_jev_metrics'] for r in rs if r['task_id'] in common]) if common else None,
            targeted_checks={r['task_id']:r['focused_source_audit'] for r in rs},
            calls=sum(r['trace']['api_calls'] for r in rs), statuses=dict(Counter(r['trace']['status'] for r in rs)),
            tokens={k:sum((q.get('usage') or {}).get(k,0) or 0 for q in rounds) for k in ['prompt_tokens','completion_tokens','reasoning_tokens','total_tokens']},
            usage_unknown_calls=sum(q.get('api_calls',0) for q in rounds if not q.get('usage')),
            mean_latency_ms=statistics.mean(r['trace']['latency_ms'] for r in rs),
            truncations=sum(q.get('reason_code')=='review_output_truncated' for q in rounds),
            failure_codes=dict(Counter(q['reason_code'] for q in rounds if q.get('reason_code'))),
            monetary_cost=None)
    billing=[]
    for a in plan['attempts']:
        *_,records,statuses,unused=scoring.audit(STUDY/'grading'/a['directory']/'import',STUDY/'grading'/a['directory']/'judges')
        billing.extend(records['jev'])
    comparison=dict(summary=summary,common_tasks=common,policy_sha256=prior.grading.POLICY_SHA,
        jev_accounting=scoring.accounting(billing,'jev'),controls=plan,full32_score=None,
        limitations=['One paired run on three reused development questions, not a stability estimate.',
        'Same relation selection, semantic rules, gates and output cap; only relation record schema/prompt shortened.',
        'No new primary generation or initial retrieval; supplemental retrieval is allowed by the unchanged controller.',
        'Model judgments and Jev can be wrong; targeted source audit does not replace raw scores.',
        'No automatic rollout or server deployment.'])
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>关系核查精简对照</title>',
        '<style>body{max-width:1100px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f5f7fa;color:#17324b}article{background:white;padding:20px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style>',
        '<h1>关系核查输出精简：三题配对对照</h1><p>完整记录版v2.4与精简记录版v2.5，各三题一次。不是稳定性或32题评测。Jev原始评分和Codex指定问题核查分开。</p>',
        '<p><a href="comparison.json">控制条件、指标及成本</a> · <a href="answers.jsonl">完整逐题数据</a></p>',
        '<h2>结果与开销</h2><pre>'+escape(judge.encode(comparison))+'</pre>']
    for r in rows:
        html+=['<article><h2>'+escape(r['attempt']+' / '+r['task_id'])+'</h2><p>'+escape(r['question'])+'</p><pre>'+escape(r['answer'])+'</pre>']
        for label,key in [('指定问题核查','focused_source_audit'),('Jev原始评分','raw_jev_review'),('Jev指标','raw_jev_metrics'),('参考答案','reference_answer'),('审校轨迹','trace')]:
            html+=['<details><summary>'+label+'</summary><pre>'+escape(judge.encode(r[key]))+'</pre></details>']
        html+=['</article>']
    html+=['</html>']
    files={'comparison.html':''.join(html),'comparison.json':judge.encode(comparison),
        'answers.jsonl':''.join(judge.encode(r)+'\n' for r in rows),'focused-source-audit.json':judge.encode(audit)}
    for p in (ROOT/'backend').glob('.env*'):
        if not p.is_file():continue
        for k,v in dotenv_values(p,interpolate=False).items():
            if v and len(v)>=12 and k.upper().endswith(('API_KEY','PASSWORD','TOKEN','BEARER_TOKEN')):
                require(all(v not in value for value in files.values()),'Private value in report')
    PUBLIC.mkdir(parents=True)
    for n,s in files.items():(PUBLIC/n).write_text(s,encoding='utf-8',newline='\n')
    judge.write(PUBLIC/'publication.json',dict(files={n:judge.digest(PUBLIC/n) for n in files}))
    print(judge.encode(summary))


if __name__=='__main__':main()
