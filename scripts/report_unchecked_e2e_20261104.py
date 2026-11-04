"""Publish independent raw Jev and separately sealed Codex source adjudication."""
from html import escape
import json
from pathlib import Path
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from report_answer_models_20261102 import final_review
from grade_unchecked_e2e_20261104 import ROOT,RUN,OUTPUT,verify
PUBLIC=ROOT/'data/literature/qa-evaluation/reports/unchecked-e2e-20261104'
BASE=ROOT/'data/literature/qa-evaluation/reports/unified-v31-full32-20261104'

def publish():
    verify();assert not PUBLIC.exists()
    _,jobs,study,reviews,records,statuses,_=s.audit(OUTPUT/'import',OUTPUT/'judges')
    entries={e['task_id']:e for e in study['jobs']}
    adj=j.read_json(OUTPUT/'codex-adjudication.json');assert adj['policy_sha256']==g.POLICY_SHA
    changes={x['task_id']:x for x in adj['items']};assert len(changes)==32
    prior={x['task_id']:x for x in j.read_jsonl(BASE/'questions-answers-reviews.jsonl')}
    rows=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];entry=entries[tid];raw=reviews.get(('jev','rag',tid));x=j.read_json(RUN/(tid+'.json'))
        saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        final=final_review(dict(result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=entry['input_sha256'],
            raw_review=raw,saved=saved),changes[tid])
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference=job['reference_case'],
            candidate=job['candidate'],raw_jev_review=raw,final_codex_review=final,adjudication=changes[tid],
            raw_jev_metrics=s.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None,
            final_codex_metrics=s.metrics(final,job['reference_case'],job['task']['capabilities']),
            previous_final_metrics=prior[tid]['final_codex_metrics'],initial_answer=x['evidence_review']['original_draft'],
            evidence_review=x['evidence_review'],retrieval=x['context_assembly'],generation_calls=x['generation_calls']))
    rows.sort(key=lambda r:r['task_id'])
    traces=[r['evidence_review'] for r in rows]
    rounds=[x for t in traces for x in t['rounds']]
    summary=dict(questions=32,weighted_grand_score=None,policy_sha256=g.POLICY_SHA,
        final=s.summarize([r['final_codex_metrics'] for r in rows]),
        previous_fixed_input=s.summarize([r['final_codex_metrics'] for r in prior.values()]),
        raw_jev=s.summarize([r['raw_jev_metrics'] for r in rows if r['raw_jev_metrics']]),
        jev_valid=sum(r['raw_jev_review'] is not None for r in rows),jev_accounting=s.accounting(records['jev'],'jev'),
        not_all_pass=[r['task_id'] for r in rows if not r['final_codex_metrics']['all_five_pass']],
        adjudicated=[r['task_id'] for r in rows if r['adjudication']['changes']],
        supplemented=[r['task_id'] for r in rows if r['raw_jev_review'] is None],
        runtime=dict(review_calls=sum(t['api_calls'] for t in traces),
            incomplete=[r['task_id'] for r in rows if r['evidence_review']['status']=='incomplete'],
            lookup_errors=[r['task_id'] for r in rows if r['evidence_review'].get('lookup_execution_error')],
            supplements=[r['task_id'] for r in rows if r['evidence_review']['supplement_rounds']],
            proposal_count=sum(len(x.get('raw_response',{}).get('issues',[])) for x in rounds),
            execution_events=[dict(task_id=r['task_id'],round=i+1,event=e) for r in rows for i,x in enumerate(r['evidence_review']['rounds']) for e in x.get('events',[])],
            known_review_tokens=sum((x.get('usage') or {}).get('total_tokens',0) for x in rounds),
            generation_calls=sum(len(r['generation_calls']) for r in rows),
            known_generation_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for r in rows for c in r['generation_calls'])),
        limitations=['Fresh retrieval and fresh drafts differ from prior fixed-draft review-only results; not a paired causal ablation.',
            'Only one paper, 32 repeatedly used development questions, one answer per question; no stability/generalization estimate.',
            'Initial generation citation format validation retained; review content/schema checks and final citation rejection disabled.',
            'JSON/index executability and bounded supplemental lookup remain; no content normalization or metadata completion calls.',
            'Jev scores retained separately. Codex calibration is not an independent human expert gold.'])
    pct=lambda v:f'{100*v:.2f}%'
    measures=[('必答要点',lambda x:pct(x['point_macro_average'])),
        ('事实充分支持率',lambda x:pct(x['support_counts'].get('supported',0)/sum(x['support_counts'].values()))),
        ('单引有效率',lambda x:pct(x['citation_precision']['value'])),
        ('引用组完整率',lambda x:pct(x['citation_coverage']['value'])),
        ('边界均分 / 2',lambda x:f"{x['boundary_mean']:.4f}"),
        ('五项全部达标',lambda x:f"{x['all_five_pass']}/{x['tasks']}")]
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>关闭审校校验 · 32题端到端评测</title><style>body{max-width:1160px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f5f7fa;color:#18324b}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd6e1;text-align:left}article{background:#fff;padding:24px;margin:20px 0;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer}</style><h1>关闭审校校验：32题端到端评测</h1><p>全新查询改写、检索、重排、初答与审校。没有复用旧答案；初次生成的格式检查保留，审校修改不再受内容及引用校验拦截。没有加权综合总分。</p><p>旧结果为固定初答的审校评测，本次为端到端运行；分差不能全部归因于关闭校验。</p><table><tr><th>指标</th><th>Jev原始评分</th><th>Codex校准后（最终）</th><th>之前固定初答结果（参考）</th></tr>']
    for label,fn in measures:html.append('<tr><td>'+label+'</td>'+''.join('<td>'+fn(summary[k])+'</td>' for k in ['raw_jev','final','previous_fixed_input'])+'</tr>')
    html+=['</table><p>Jev有效评分 '+str(summary['jev_valid'])+'/32。来源校准记录保留每项旧值、新值及依据。</p><p><a href="comparison.json">汇总</a> · <a href="adjudication.json">校准明细</a> · <a href="questions-answers-reviews.jsonl">逐题数据</a></p>']
    for row in rows:
        html+=['<article><h2>'+escape(row['task_id']+' '+row['question'])+'</h2><p>最终要点：'+pct(row['final_codex_metrics']['point_mean'])+'</p><pre>'+escape(row['candidate']['answer'])+'</pre><p>'+escape(row['adjudication']['summary'])+'</p>']
        for label,key in [('初始回答','initial_answer'),('参考答案与评分规则','reference'),('原始Jev评分','raw_jev_review'),('最终校准评分','final_codex_review'),('校准依据','adjudication'),('审校原始响应与实际执行','evidence_review')]:
            html+=['<details><summary>'+label+'</summary><pre>'+escape(json.dumps(row[key],ensure_ascii=False,indent=2))+'</pre></details>']
        html+=['</article>']
    html+=['</html>']
    files={'comparison.json':j.encode(summary),'adjudication.json':j.encode(adj),'comparison.html':''.join(html),
        'questions-answers-reviews.jsonl':''.join(j.encode(r)+'\n' for r in rows)}
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for k,v in dotenv_values(p).items():
            if v and len(v)>=12 and k.upper().endswith(('API_KEY','PASSWORD','TOKEN','BEARER_TOKEN')):
                assert all(v not in text for text in files.values()),'Secret in report'
    PUBLIC.mkdir(parents=True)
    for name,text in files.items():(PUBLIC/name).write_text(text,encoding='utf-8',newline='\n')
    (PUBLIC/'publication.json').write_text(j.encode(dict(files={n:j.digest(PUBLIC/n) for n in files},
        manifest_sha256=j.digest(RUN/'manifest.json'))),encoding='utf-8',newline='\n')
    return summary

if __name__=='__main__':print(j.encode(publish()))
