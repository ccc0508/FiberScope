"""Publish all paired attempts with raw Jev and separately attributed targeted source checks."""
from collections import Counter
from html import escape
import json
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from validate_qa_eval import require
from validate_minimal_revision_20261103 import ROOT, STUDY, CASES

PUBLIC = ROOT/'data/literature/qa-evaluation/reports/minimal-revision-paired-20261103'


def inspect():
    rows = []
    for attempt in judge.read_json(STUDY/'plan.json')['attempts']:
        name = attempt['directory']; folder = STUDY/'grading'/name
        if not (folder/'contract.json').exists():continue
        contract = judge.read_json(folder/'contract.json')
        require(judge.digest(folder/'judges/study.json')==contract['study_sha256'], 'Scoring study changed')
        _, jobs, study, reviews, records, statuses, _ = scoring.audit(folder/'import',folder/'judges')
        jobs = {j['task_id']:j for j in jobs if j['system']=='rag'}
        for tid in CASES:
            result_path = STUDY/name/(tid+'.json')
            require(judge.digest(result_path)==contract['answer_hashes'][tid], 'Frozen answer changed')
            result = judge.read_json(result_path); job = jobs[tid]
            raw = reviews.get(('jev','rag',tid))
            rows.append(dict(attempt=name, version=attempt['version'], repeat=attempt['repeat'], task_id=tid,
                result_sha256=judge.digest(result_path), question=result['question'], answer=result['answer'],
                candidate=job['candidate'], reference_answer=job['reference_case']['reference_answer'],
                key_points=job['reference_case']['key_points'], raw_jev_review=raw,
                raw_jev_metrics=scoring.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None,
                trace=result['evidence_review']))
    judge.write(STUDY/'inspection.json',rows)
    return rows


def publish():
    require(not PUBLIC.exists(), 'Preserve published report')
    rows = inspect()
    require(len(rows)==30 and len({(r['attempt'],r['task_id']) for r in rows})==30, 'Need all 30 attempts')
    plan = judge.read_json(STUDY/'plan.json')
    for relative, digest in plan['source_files'].items():
        require(judge.digest(STUDY/'runtime'/relative)==digest,'Archived experimental runtime changed')
    for attempt in plan['attempts']:
        require(judge.read_json(STUDY/attempt['directory']/'manifest.json')['source_files']==plan['source_files'],
            'Runtime differs between frozen attempts')
    audit = judge.read_json(STUDY/'focused-source-audit.json')
    require(audit['reviewer']=='Codex' and audit['scope']=='targeted_checks_not_full_five_dimension_rescore','Declare adjudication scope')
    checks = {(r['attempt'],r['task_id']):r for r in audit['items']}
    require(set(checks)=={(r['attempt'],r['task_id']) for r in rows}, 'Incomplete targeted audit')
    for r in rows:
        a=checks[(r['attempt'],r['task_id'])]
        require(a['result_sha256']==r['result_sha256'] and type(a['target_pass']) is bool and a['reason'], 'Invalid attribution')
        r['focused_source_audit']=a
    by_pair={(r['repeat'],r['task_id'],r['version']):r for r in rows}
    common=[(i,tid) for i in (1,2,3) for tid in CASES if all(by_pair[(i,tid,v)]['raw_jev_review'] is not None for v in ('v2','v3'))]
    runtime={}; summary={}
    for v in ('v2','v3'):
        subset=[r for r in rows if r['version']==v]
        rounds=[s for r in subset for s in r['trace']['rounds']]
        runtime[v]=dict(answers=15, calls=sum(r['trace']['api_calls'] for r in subset),
            statuses=dict(Counter(r['trace']['status'] for r in subset)),
            mean_latency_ms=statistics.mean(r['trace']['latency_ms'] for r in subset),
            median_latency_ms=statistics.median(r['trace']['latency_ms'] for r in subset),
            reported_tokens=sum((s.get('usage') or {}).get('total_tokens',0) for s in rounds),
            missing_usage_calls=sum(s.get('api_calls',0) for s in rounds if not s.get('usage')), monetary_cost=None,
            failure_codes=dict(Counter(s['reason_code'] for s in rounds if s.get('reason_code'))),
            rejected_edits=dict(Counter(e['reason_code'] for s in rounds for e in s.get('rejected_issues',[]))))
        summary[v]=dict(target_pass=sum(r['focused_source_audit']['target_pass'] for r in subset), attempts=15,
            by_task={tid:dict(passed=sum(r['focused_source_audit']['target_pass'] for r in subset if r['task_id']==tid),attempts=3) for tid in CASES},
            raw_jev_valid=sum(r['raw_jev_review'] is not None for r in subset),
            raw_jev_matched=scoring.summarize([by_pair[(i,tid,v)]['raw_jev_metrics'] for i,tid in common]) if common else None)
    billing=[]
    for a in plan['attempts']:
        _,_,_,_,records,_,_=scoring.audit(STUDY/'grading'/a['directory']/'import',STUDY/'grading'/a['directory']/'judges')
        billing.extend(records['jev'])
    comparison=dict(summary=summary, runtime=runtime, jev_accounting=scoring.accounting(billing,'jev'),
        raw_jev_matched_pairs=[dict(repeat=i,task_id=tid) for i,tid in common],
        raw_jev_invalid=[dict(attempt=r['attempt'],task_id=r['task_id']) for r in rows if r['raw_jev_review'] is None],
        policy_sha256=grading.POLICY_SHA, total_answers=30, full32_score=None, weighted_grand_score=None,
        controls=plan, limitations=['Only five reused development questions, three repeats per arm.',
            'Fixed initial drafts and evidence; no initial answer/retrieval rerun.',
            'Same-call proposal self-check is not independent semantic verification.',
            'Targeted Codex source checks do not replace or modify raw Jev full-dimension scoring.',
            'No independent human gold, holdout set, or statistical significance claim.',
            'Default v1 and server unchanged; no promotion based on these results.'])
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>最小修订：五题三次配对验证</title><style>body{max-width:1120px;margin:28px auto;padding:0 20px;background:#f5f7fa;color:#16314a;font:16px/1.7 system-ui}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6df;padding:9px;text-align:left}article{background:white;padding:22px;margin:20px 0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer}</style>',
        '<h1>最小修订：五题三次配对验证</h1><p>旧版v2.1与实验版v3；每题每版3次独立审校，共30份最终回答。固定初始草稿和证据，没有重跑首次检索/生成，不挑选最好结果。</p>',
        '<p>下表只表示指定问题的来源核对结果，由Codex逐条核对；不是完整五维得分。Jev原始五维评分另列，未被覆盖。未运行完整32题。</p>',
        '<p>归因更正：第31题过强的因果链原已存在于冻结草稿；此前v2曾修好，v2.1漏修。此前称“v2.1修订新增”不准确，原评分不变，历史冻结报告保留。</p>',
        '<table><tr><th>题号</th><th>检查重点</th><th>旧版通过</th><th>实验版通过</th></tr>']
    labels={'PFI2-018':'相对峰面积≠绝对氢键数量','PFI2-024':'不以定性解释作因素贡献排名','PFI2-031':'不扩写无依据的因果链','PFI2-023':'摘要/正文系数冲突及对应引用','PFI2-032':'系数纠错、冲突和定量换算边界'}
    for tid in CASES:
        html.append(f'<tr><td>{tid}</td><td>{labels[tid]}</td><td>{summary["v2"]["by_task"][tid]["passed"]}/3</td><td>{summary["v3"]["by_task"][tid]["passed"]}/3</td></tr>')
    html+=['</table><p>同一模型在同一次请求中自检拟议修改，不是额外独立审校模型。自动检查只能保证记录和来源位置符合要求，语义仍可能漏判。</p>',
        '<p><a href="comparison.json">配对评分、运行开销与完整控制条件</a> · <a href="answers.jsonl">30份答案及原始评分</a> · <a href="focused-source-audit.json">逐条来源核对</a></p>',
        '<h2>原始Jev评分与开销</h2><pre>'+escape(judge.encode(dict(summary=summary,runtime=runtime,jev_accounting=comparison['jev_accounting'],invalid=comparison['raw_jev_invalid'])))+'</pre>']
    for r in rows:
        a=r['focused_source_audit']
        html+=['<article><h2>'+escape(r['attempt']+' / '+r['task_id'])+'</h2><p>'+escape(r['question'])+'</p>',
            '<p>指定问题：'+('通过' if a['target_pass'] else '未通过')+'。'+escape(a['reason'])+'</p><pre>'+escape(r['answer'])+'</pre>']
        for title,key in [('参考答案','reference_answer'),('评分要点','key_points'),('Jev原始评分','raw_jev_review'),('Jev指标','raw_jev_metrics'),('来源核对','focused_source_audit'),('完整审校记录','trace')]:
            html+=['<details><summary>'+title+'</summary><pre>'+escape(judge.encode(r[key]))+'</pre></details>']
        html+=['</article>']
    html+=['</html>']
    files={'comparison.html':''.join(html),'comparison.json':judge.encode(comparison),
        'focused-source-audit.json':judge.encode(audit),'answers.jsonl':''.join(judge.encode(r)+'\n' for r in rows)}
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for k,v in dotenv_values(p).items():
            if v and len(v)>=12 and k.upper().endswith(('API_KEY','PASSWORD','TOKEN','BEARER_TOKEN')):
                require(all(v not in value for value in files.values()), 'Private value in publication')
    PUBLIC.mkdir(parents=True)
    for name,body in files.items():(PUBLIC/name).write_text(body,encoding='utf-8',newline='\n')
    judge.write(PUBLIC/'publication.json',dict(files={name:judge.digest(PUBLIC/name) for name in files}))
    print(judge.encode(comparison['summary']))


if __name__=='__main__':
    import sys
    if sys.argv[-1]=='inspect':print('saved inspection rows:',len(inspect()))
    else:publish()
