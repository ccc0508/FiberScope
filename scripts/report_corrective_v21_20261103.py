"""Publish audited Jev and separately attributed source adjudication; no model calls."""
from copy import deepcopy
from html import escape
from pathlib import Path
import json

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from report_answer_models_20261102 import final_review
from evaluate_corrective_v21_20261103 import ROOT,RUN,OUTPUT,BASE,verify
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/corrective-v21-20261103'


def load():
    verify()
    meta,jobs,study,reviews,records,statuses,proofs=scoring.audit(OUTPUT/'import',OUTPUT/'judges')
    jobs={j['task_id']:j for j in jobs if j['system']=='rag'}
    entries={j['task_id']:j for j in study['jobs']}
    previous={r['task_id']:r for r in (json.loads(line) for line in (BASE/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines())}
    return jobs,entries,reviews,records,statuses,previous


def inspection():
    jobs,entries,reviews,records,statuses,previous=load()
    rows=[]
    for tid,job in sorted(jobs.items()):
        entry=entries[tid];review=reviews.get(('jev','rag',tid))
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],
            reference=job['reference_case']['reference_answer'],points=job['reference_case']['key_points'],
            candidate=job['candidate'],raw_review=review,previous_final_metrics=previous[tid]['final_codex_metrics'],
            saved_input=entry['name']+'.json'))
    judge.write(OUTPUT/'inspection.json',rows)
    return dict(questions=len(rows),valid_jev=sum(r['raw_review'] is not None for r in rows))


def publish():
    require(not PUBLIC.exists(),'Preserve existing publications')
    jobs,entries,reviews,records,statuses,previous=load()
    adj=judge.read_json(OUTPUT/'codex-adjudication.json')
    require(adj['policy_sha256']==grading.POLICY_SHA,'Adjudication uses a different policy')
    changes={r['task_id']:r for r in adj['items']}
    require(set(changes)==set(jobs),'Every final grade requires review attribution')
    require(adj['reviewer']=='Codex','Declare the source adjudicator')
    rows=[]
    for tid,job in sorted(jobs.items()):
        raw=reviews.get(('jev','rag',tid));entry=entries[tid]
        saved=judge.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        result=judge.read_json(RUN/(tid+'.json'))
        final=final_review(dict(result_sha256=judge.digest(RUN/(tid+'.json')),
            grader_input_sha256=entry['input_sha256'],raw_review=raw,saved=saved),changes[tid])
        rows.append(dict(task_id=tid,question=job['reference_case']['question'],reference_answer=job['reference_case']['reference_answer'],
            key_points=job['reference_case']['key_points'],candidate=job['candidate'],raw_jev_review=raw,
            raw_jev_metrics=scoring.metrics(raw,job['reference_case'],job['task']['capabilities']) if raw else None,
            final_codex_review=final,final_codex_metrics=scoring.metrics(final,job['reference_case'],job['task']['capabilities']),
            previous_final_metrics=previous[tid]['final_codex_metrics'],adjudication=changes[tid],
            evidence_review=result['evidence_review']))
    common=[r['task_id'] for r in rows if r['raw_jev_review'] is not None and previous[r['task_id']]['raw_jev_review'] is not None]
    trace=[r['evidence_review'] for r in rows]
    usages=[round.get('usage') for t in trace for round in t['rounds'] if round.get('api_calls')]
    matched_after=[r['raw_jev_metrics'] for r in rows if r['task_id'] in common]
    summary=dict(version='corrective-v21-evaluation-20261103',questions=32,weighted_grand_score=None,
        policy_sha256=grading.POLICY_SHA,
        final=dict(previous_v2=scoring.summarize([r['final_codex_metrics'] for r in previous.values()]),
            current=scoring.summarize([r['final_codex_metrics'] for r in rows])),
        raw_jev=dict(valid_tasks=sum(r['raw_jev_review'] is not None for r in rows),
            current_available=scoring.summarize([r['raw_jev_metrics'] for r in rows if r['raw_jev_metrics']]),
            matched_task_ids=common,previous_matched=scoring.summarize([previous[tid]['raw_jev_metrics'] for tid in common]),
            current_matched=scoring.summarize(matched_after)),
        review_runtime=dict(calls=sum(t['api_calls'] for t in trace),
            supplement_questions=[r['task_id'] for r in rows if r['evidence_review']['supplement_rounds']],
            incomplete_questions=[r['task_id'] for r in rows if r['evidence_review']['status']=='incomplete'],
            known_total_tokens=sum(u.get('total_tokens',0) for u in usages if u),
            usage_unknown_calls=sum(u is None for u in usages),cost=None,
            per_question_latency_ms={r['task_id']:r['evidence_review']['latency_ms'] for r in rows}),
        jev_accounting=scoring.accounting(records['jev'],'jev'),
        not_all_pass=[r['task_id'] for r in rows if not r['final_codex_metrics']['all_five_pass']],
        supplemented_tasks=[r['task_id'] for r in rows if r['raw_jev_review'] is None],
        adjudicated_tasks=[r['task_id'] for r in rows if r['adjudication']['changes']],
        changed_task_metrics=[dict(task_id=r['task_id'],before=r['previous_final_metrics'],
            after=r['final_codex_metrics']) for r in rows if r['previous_final_metrics']!=r['final_codex_metrics']],
        repetitions=[],
        controls=dict(initial_input_sha256=judge.digest(RUN/'inputs.json'),manifest_sha256=judge.digest(RUN/'manifest.json'),
            scoring_contract_sha256=judge.digest(OUTPUT/'contract.json'),first_answer_only=True,
            previous_baseline='corrective-v2 full32 20261103; identical original drafts and initial evidence'),
        limitations=['Only one paper and repeatedly used development questions.',
            'One full run per version; no new stability repetitions or answer selection.',
            'Raw Jev and Codex source adjudication are reported separately; no independent human gold.',
            'Failed or rejected correction attempts remain in all-32 results; never select best repeats.'])
    def pct(v):return f'{v*100:.2f}%'
    measures=[('要点得分',lambda s:pct(s['point_macro_average'])),
        ('事实充分支持率',lambda s:pct(s['support_counts'].get('supported',0)/sum(s['support_counts'].values()))),
        ('单条引用有效率',lambda s:pct(s['citation_precision']['value'])),
        ('引用组完整率',lambda s:pct(s['citation_coverage']['value'])),
        ('边界均分 / 2',lambda s:f"{s['boundary_mean']:.5f}"),
        ('五项全部达标',lambda s:f"{s['all_five_pass']}/{s['tasks']}")]
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>有限纠正v2.1：32题评测</title>',
        '<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{max-width:1120px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui;color:#18324b;background:#f5f7fa}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd6e1;padding:10px;text-align:left}article{background:white;padding:22px;margin:20px 0;border:1px solid #dde4ed;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer}</style>',
        '<h1>有限纠正v2.1：32题评测</h1><p>固定原始草稿和首次证据；只运行新的诊断、有限补查与修订。Jev独立评分，另列来源复核。失败和拒绝修订均保留，不从重复验证中挑选答案。没有加权综合总分。</p>',
        '<p>对照为此前已发布的有限纠正v2完整32题结果，两侧原始草稿及初始证据逐题一致；本次未混入四题定点验证的答案。</p>',
        '<table><tr><th>指标（来源复核后）</th><th>此前v2全量结果</th><th>本次v2.1</th></tr>']
    for label,fn in measures:html.append('<tr><td>'+label+'</td><td>'+fn(summary['final']['previous_v2'])+'</td><td>'+fn(summary['final']['current'])+'</td></tr>')
    html+=['</table><p>Jev有效评分：'+str(summary['raw_jev']['valid_tasks'])+'/32；来源补评题：'+
        escape('、'.join(summary['supplemented_tasks']) or '无')+'。原始Jev记录与Codex复核结果分别保存，后者不是独立人工专家评分。</p>',
        '<h2>原始Jev：相同有效题目的配对比较</h2><p>共同有效题数：'+str(len(common))+'。无效评分不记零，也不计入此子集。</p>',
        '<table><tr><th>指标</th><th>此前v2</th><th>本次v2.1</th></tr>']
    if common:
        for label,fn in measures:
            html+=['<tr><td>'+label+'</td><td>'+fn(summary['raw_jev']['previous_matched'])+'</td><td>'+fn(summary['raw_jev']['current_matched'])+'</td></tr>']
    html+=['</table><h2>执行状况</h2><p>本次审校不完整：'+str(len(summary['review_runtime']['incomplete_questions']))+
        '/32；补查题号：'+escape('、'.join(summary['review_runtime']['supplement_questions']) or '无')+
        '。失败后保留的回答仍参加评分；流程完成不等于答案正确。</p>',
        '<p><a href="comparison.json">全部汇总、逐题变化与开销</a> · <a href="adjudication.json">来源复核明细</a> · <a href="questions-answers-reviews.jsonl">32题完整数据</a></p>']
    for row in rows:
        html+=['<article><h2>'+escape(row['task_id']+' '+row['question'])+'</h2><p>要点：'+pct(row['final_codex_metrics']['point_mean'])+
            '；纠正流程状态：'+escape(row['evidence_review']['status'])+'</p><h3>最终回答</h3><pre>'+escape(row['candidate']['answer'])+'</pre>']
        for label,key in [('参考答案','reference_answer'),('评分要点','key_points'),('Jev原评分','raw_jev_review'),('来源复核','adjudication'),('最终评分','final_codex_review'),('诊断与补查记录','evidence_review')]:
            value=row[key];text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
            html+=['<details><summary>'+label+'</summary><pre>'+escape(text)+'</pre></details>']
        html+=['</article>']
    html+=['</html>']
    files=dict({'comparison.json':judge.encode(summary)+'\n','adjudication.json':judge.encode(adj)+'\n',
        'questions-answers-reviews.jsonl':''.join(judge.encode(r)+'\n' for r in rows),'comparison.html':''.join(html)})
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for key,value in dotenv_values(p).items():
            if value and len(value)>=12 and key.upper().endswith(('API_KEY','PASSWORD','TOKEN','BEARER_TOKEN')):
                require(all(value not in text for text in files.values()),'Private configuration value in report')
    PUBLIC.mkdir(parents=True)
    for name,text in files.items():(PUBLIC/name).write_text(text,encoding='utf-8',newline='\n')
    judge.write(PUBLIC/'publication.json',dict(files={n:judge.digest(PUBLIC/n) for n in files}))
    return dict(final=summary['final'],raw_jev_valid=summary['raw_jev']['valid_tasks'],report=str(PUBLIC))


if __name__=='__main__':
    import sys
    print(judge.encode(inspection() if sys.argv[-1]=='inspect' else publish()),flush=True)
