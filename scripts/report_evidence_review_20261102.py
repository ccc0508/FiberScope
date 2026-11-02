"""Offline fixed-draft review report: original Jev, separately logged Codex review, and net edits."""
from collections import Counter
from hashlib import sha256
from html import escape
from pathlib import Path
import json
import statistics
import sys

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from report_answer_models_20261102 import final_review,cells
from evaluate_evidence_review_v2_20261102 import ROOT,OUTPUT,RUN,SOURCE,ARMS,verify
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/evidence-review-20261102-v2'
ADJUDICATION=OUTPUT/'codex-adjudication.json'
LABELS=dict(control='DeepSeek原稿',review='DeepSeek审校后')


def load():
    verify();arms={}
    for arm in ARMS:
        root=OUTPUT/arm;meta,jobs,study,reviews,records,statuses,proofs=scoring.audit(root/'import',root/'judges')
        require(all(s!='pending' for _,_,s in statuses),'Wait for active grading')
        jobs={j['task_id']:j for j in jobs if j['system']=='rag'};rows={}
        for tid,job in sorted(jobs.items()):
            entry=next(e for e in study['jobs'] if e['task_id']==tid)
            path=(SOURCE if arm=='control' else RUN)/'results'/(tid+'.json')
            rows[tid]=dict(job=job,response=judge.read_json(path)['response'],result_sha256=judge.digest(path),
                raw_review=reviews.get(('jev','rag',tid)),grader_input_sha256=entry['input_sha256'],
                saved=judge.read_json(root/'judges/inputs'/(entry['name']+'.json')))
        require(len(rows)==32,'Need all 32 questions')
        arms[arm]=dict(rows=rows,records=records['jev'],statuses={':'.join(k):v for k,v in statuses.items()},proofs=proofs)
    for tid in arms['control']['rows']:
        a,b=(arms[arm]['rows'][tid] for arm in ARMS);review=b['response']['evidence_review']
        require(a['response']['retrieved_evidence']==b['response']['retrieved_evidence'],'Scientific inputs changed')
        require(a['job']['reference_case']==b['job']['reference_case'],'Question/gold changed')
        require(review['draft']['claims']==a['response']['claims'],'Review used another draft')
        require(review['draft']['answer']==a['response']['answer'],'Review used another answer')
        require(review['draft_sha256']==sha256(json.dumps(review['draft'],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'Draft integrity failed')
        if review['status']!='revised':
            require(a['job']['candidate']==b['job']['candidate'],'Retained answer content changed')
        original_images=a['response']['generation_calls'][-1]['model_info']['images']
        require(review['model_info']['images']==original_images,'Review saw different original images')
    return arms


def packets():
    arms=load();rows=[]
    for tid in sorted(arms['control']['rows']):
        case=arms['control']['rows'][tid]['job']['reference_case']
        rows.append(dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
            key_points=case['key_points'],arms={arm:dict(candidate=data['rows'][tid]['job']['candidate'],
            raw_review=data['rows'][tid]['raw_review'],result_sha256=data['rows'][tid]['result_sha256'],
            grader_input_sha256=data['rows'][tid]['grader_input_sha256']) for arm,data in arms.items()},
            evidence_review=arms['review']['rows'][tid]['response']['evidence_review']))
    path=OUTPUT/'review-packets.jsonl';path.write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    return dict(packets=32,path=str(path))


def usage_summary(calls):
    aliases=dict(input_tokens='prompt_tokens',output_tokens='completion_tokens',total_tokens='total_tokens')
    result=dict(calls=len(calls),usage_unknown_calls=sum(not c.get('usage') for c in calls),reported_cost_usd=None)
    for key,alias in aliases.items():
        values=[(c.get('usage') or {}).get(key,(c.get('usage') or {}).get(alias)) for c in calls]
        result[key]=sum(values) if all(type(v) is int for v in values) else None
    return result


def difference(a,b):
    return dict(point_macro_percentage_points=100*(b['point_macro_average']-a['point_macro_average']),
        citation_precision_percentage_points=100*(b['citation_precision']['value']-a['citation_precision']['value']),
        citation_coverage_percentage_points=100*(b['citation_coverage']['value']-a['citation_coverage']['value']),
        boundary_mean=b['boundary_mean']-a['boundary_mean'],all_five_pass=b['all_five_pass']-a['all_five_pass'])


def publish():
    require(not PUBLIC.exists(),'Publish to a new immutable directory')
    arms=load();adj=judge.read_json(ADJUDICATION)
    require(adj['reviewer']=='Codex' and adj['policy_sha256']==grading.POLICY_SHA,'Adjudication contract changed')
    require(adj['final_evidence_unit']=='actual_attached_text_and_verified_images','Disclose source-image evidence unit')
    index={(x['arm'],x['task_id']):x for x in adj['items']}
    require(len(index)==len(adj['items'])==64,'Review both arms of all 32 questions')
    summaries={};records=[];metrics={};changes=[]
    common=sorted(set(t for t,r in arms['control']['rows'].items() if r['raw_review'] is not None and not r['raw_review']['reference_concern'])&
        set(t for t,r in arms['review']['rows'].items() if r['raw_review'] is not None and not r['raw_review']['reference_concern']))
    for arm,data in arms.items():
        metrics[arm]={};raw_metrics={}
        for tid,row in data['rows'].items():
            a=index[(arm,tid)];review=final_review(row,a);job=row['job'];case=job['reference_case'];caps=job['task']['capabilities']
            m=scoring.metrics(review,case,caps);metrics[arm][tid]=m
            raw=scoring.metrics(row['raw_review'],case,caps) if row['raw_review'] is not None else None
            if raw is not None:raw_metrics[tid]=raw
            records.append(dict(arm=arm,task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
                key_points=case['key_points'],critical_errors=case['critical_errors'],candidate=job['candidate'],
                raw_jev_review=row['raw_review'],raw_jev_metrics=raw,final_codex_review=review,final_codex_metrics=m,
                adjudication=a,evidence_review=arms['review']['rows'][tid]['response']['evidence_review']))
        summaries[arm]=dict(raw_jev_valid_tasks=len(raw_metrics),raw_jev=scoring.summarize(list(raw_metrics.values())) if raw_metrics else None,
            raw_jev_paired=scoring.summarize([raw_metrics[t] for t in common]) if common else None,
            final_codex=scoring.summarize(list(metrics[arm].values())),judge_accounting=scoring.accounting(data['records'],'jev'),
            supplemented_question_ids=sorted(t for t,r in data['rows'].items() if r['raw_review'] is None),
            adjusted_question_ids=sorted(t for t in data['rows'] if index[(arm,t)]['changes']))
    traces=[r['response']['evidence_review'] for r in arms['review']['rows'].values()]
    for tid in sorted(metrics['control']):
        a,b=(metrics[arm][tid] for arm in ARMS)
        traces_row=arms['review']['rows'][tid]['response']['evidence_review']
        if traces_row['status']!='revised':require(a==b,'Identical answer received inconsistent final semantic grades')
        changes.append(dict(task_id=tid,status=traces_row['status'],answer_changed=traces_row['status']=='revised',
            raw_jev_identical_answer_drift=(arms['control']['rows'][tid]['raw_review']['decisions']!=arms['review']['rows'][tid]['raw_review']['decisions'])
                if traces_row['status']!='revised' and all(arms[arm]['rows'][tid]['raw_review'] is not None for arm in ARMS) else None,
            point_before=a['point_mean'],point_after=b['point_mean'],joint_before=a['all_five_pass'],joint_after=b['all_five_pass'],
            analysis=adj['question_analysis'][tid]))
    latency=[t['latency_ms']/1000 for t in traces]
    pilot=[judge.read_json(p)['response']['evidence_review'] for p in sorted((ROOT/'.rag-data/evaluations/pfi-evidence-review-20261102-v1/results').glob('*.json'))]
    original_calls=[c for row in arms['control']['rows'].values() for c in row['response']['generation_calls']]
    runtime=dict(review=usage_summary(traces),pilot=usage_summary(pilot),original_generation=usage_summary(original_calls),
        review_status_counts=dict(Counter(t['status'] for t in traces)),
        review_status_question_ids={s:sorted(t for t,r in arms['review']['rows'].items() if r['response']['evidence_review']['status']==s)
            for s in sorted(set(t['status'] for t in traces))},
        review_latency_median_seconds=statistics.median(latency),review_latency_sum_seconds=sum(latency),
        final_characters={arm:sum(len(r['job']['candidate']['answer']) for r in data['rows'].values()) for arm,data in arms.items()},
        incremental_retrieval_calls=0,incremental_primary_generation_calls=0,
        cost_note='DeepSeek monetary cost not returned; no price conversion invented. Pilot use is separate and included in disclosure.')
    summary=dict(version='fixed-draft-source-review-20261102-v2',questions=32,matched_sources_and_original_drafts=32,
        raw_jev_paired_question_ids=common,summaries=summaries,
        raw_jev_paired_delta=difference(*(summaries[a]['raw_jev_paired'] for a in ARMS)),
        final_codex_delta=difference(*(summaries[a]['final_codex'] for a in ARMS)),
        question_changes=changes,runtime=runtime,adoption=adj['adoption'],
        evidence_unit_note=adj['scope_note'],adjudication_sha256=judge.digest(ADJUDICATION),
        contract=judge.read_json(OUTPUT/'contract.json'),
        limitations=['One paper and 32 previously seen development questions; no generalization or stability claim.',
            'Control reuses exact original delivered answers; this estimates net one-pass review effect, not two fresh full RAG runs.',
            'Jev uses unchanged text-only grading; Codex final additionally checks only actual attached original images, symmetrically.',
            'Fresh Jev grades of byte-identical answers can differ; deterministic source adjudication uses the same final decision for identical content.',
            'Source quote verification proves location, not semantic correctness; an accepted review may miss or introduce defects.',
            'No RAG retrieval or question rewrite improvement is tested. Missing source evidence cannot be supplied by this review.'])
    PUBLIC.mkdir(parents=True)
    for name,value in [('comparison.json',summary),('adjudication.json',adj)]:scoring.save(PUBLIC/name,value)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in records),encoding='utf-8',newline='\n')
    render(summary,records)
    scoring.save(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir()}))
    return dict(final_codex_delta=summary['final_codex_delta'],runtime=runtime,adoption=adj['adoption'])


def render(summary,records):
    e=lambda x:escape(str(x),quote=True)
    pre=lambda v:'<pre>'+e(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>DeepSeek证据审校：固定草稿对照</title><style>body{font:15px/1.75 system-ui;background:#f4f7fb;color:#233348;max-width:1260px;margin:30px auto;padding:0 18px}article,section{border:1px solid #dbe4f0;background:white;padding:20px;border-radius:10px;margin:18px 0}table{border-collapse:collapse;display:block;overflow:auto;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #dbe4f0;white-space:nowrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fb;padding:12px}summary{cursor:pointer;font-weight:600}.changed{border-left:4px solid #337dbd}</style>',
        '<h1>DeepSeek证据审校：32题固定草稿对照</h1><p>原稿与同一原稿审校后的比较；检索、原图、DeepSeek模型及High档位保持不变。审校最多一次，没有参考答案或旧分数输入。</p>',
        '<section><h2>结果</h2><table><tr><th>组别</th><th>口径</th><th>要点均分</th><th>事实充分支持</th><th>单条引用</th><th>引用组完整</th><th>边界均分</th><th>全部达标</th></tr>']
    for arm in ARMS:
        for title,key in [('Jev原始共同有效题','raw_jev_paired'),('Codex最终复核全部32题','final_codex')]:
            m=summary['summaries'][arm][key]
            if m:parts.append('<tr><td>'+e(LABELS[arm])+'</td><td>'+title+'</td>'+''.join('<td>'+e(v)+'</td>' for v in cells(m))+'</tr>')
    parts+=['</table><p>'+e(summary['evidence_unit_note'])+'</p><h3>采用决定</h3>'+pre(summary['adoption'])+'</section>',
        '<section><h2>调用与变化概况</h2>'+pre(summary['runtime'])+'</section>']
    by={(r['arm'],r['task_id']):r for r in records}
    for tid in sorted({r['task_id'] for r in records}):
        r=by[('review',tid)];control=by[('control',tid)];trace=r['evidence_review'];changed=trace['status']=='revised'
        parts+=['<article data-question="'+e(tid)+'" class="'+('changed' if changed else '')+'"><h2>'+e(tid)+' · '+e(r['question'])+'</h2>',
            '<p>审校状态：'+e(trace['status'])+'；'+e(summary['question_changes'][int(tid[-3:])-1]['analysis'])+'</p>',
            '<details><summary>参考答案与必答要点</summary>'+pre(r['reference_answer'])+pre(r['key_points'])+'</details>']
        for arm in ARMS:
            v=by[(arm,tid)];m=v['final_codex_metrics']
            parts+=['<section><h3>'+e(LABELS[arm])+'</h3>'+pre(v['candidate']['answer']),
                '<p>最终要点 '+f"{m['point_mean']*100:.2f}%"+'；边界 '+str(m['boundary'])+'/2；全部维度达标：'+('是' if m['all_five_pass'] else '否')+'</p>',
                '<details><summary>Jev原始评分与最终复核评分</summary>'+pre(v['raw_jev_review'])+pre(v['final_codex_review'])+'</details>',
                '<details><summary>复核调整与补评依据</summary>'+pre(v['adjudication'])+'</details></section>']
        parts+=['<details><summary>审校发现的问题、原文依据及接受/拒绝原因</summary>'+pre(trace)+'</details>',
            '<details><summary>实际引用证据</summary>'+pre(control['candidate']['citations'])+'</details></article>']
    parts+=['<section><h2>适用范围</h2>'+pre(summary['limitations'])+'</section></html>']
    (PUBLIC/'comparison.html').write_text(''.join(parts),encoding='utf-8',newline='\n')


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in {'packets','publish'},'Choose packets or publish')
    print(judge.encode(packets() if sys.argv[1]=='packets' else publish()))
