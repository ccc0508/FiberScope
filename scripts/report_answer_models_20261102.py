"""Offline, auditable Jev plus separate Codex adjudication for matched answer models."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import statistics
import sys

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_answer_models_20261102 import ROOT, OUTPUT, ARMS, run_path, arm_path
from validate_qa_eval import require

PUBLIC = ROOT/'data/literature/qa-evaluation/reports/answer-models-20261102'
ADJUDICATION = OUTPUT/'codex-adjudication.json'
LABELS = {'astra':'GPT-6 Astra · High','deepseek':'DeepSeek Flash · High'}


def load():
    arms = {}
    for arm in ARMS:
        meta,jobs,study,reviews,records,statuses,proofs = scoring.audit(arm_path(arm)/'import',arm_path(arm)/'judges')
        require(all(s!='pending' for _,_,s in statuses),'Finish in-flight grading first')
        selected = {j['task_id']:j for j in jobs if j['system']=='rag'}
        rows = {}
        for tid,job in sorted(selected.items()):
            entry = next(e for e in study['jobs'] if e['task_id']==tid)
            saved = judge.read_json(arm_path(arm)/'judges/inputs'/(entry['name']+'.json'))
            result = judge.read_json(run_path(arm)/'results'/(tid+'.json'))
            review = reviews.get(('jev','rag',tid))
            rows[tid] = dict(job=job, raw_review=review, saved=saved, response=result['response'],
                result_sha256=judge.digest(run_path(arm)/'results'/(tid+'.json')),
                grader_input_sha256=entry['input_sha256'])
        arms[arm]=dict(rows=rows,records=records['jev'],statuses={':'.join(k):v for k,v in statuses.items()})
    for tid in arms['astra']['rows']:
        a,b=(arms[arm]['rows'][tid] for arm in ARMS)
        require(a['response']['retrieved_evidence']==b['response']['retrieved_evidence'],'Model source inputs differ')
        require(a['job']['reference_case']==b['job']['reference_case'],'Question or gold differs')
        sent=lambda row:[c['model_info']['images'] for c in row['response']['generation_calls']
                         if c.get('model_info') and 'images' in c['model_info']]
        require(sent(a) and sent(b) and all(images==sent(a)[0] for images in sent(a)+sent(b)),
                'Actually delivered source images differ')
    return arms


def packets():
    arms = load(); path=OUTPUT/'review-packets.jsonl'
    rows=[]
    for tid in sorted(arms['astra']['rows']):
        a=arms['astra']['rows'][tid];case=a['job']['reference_case']
        rows.append(dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
            key_points=case['key_points'],critical_errors=case['critical_errors'],
            arms={arm:dict(answer=v['rows'][tid]['response']['answer'],
                claims=v['rows'][tid]['job']['candidate']['claims'],raw_review=v['rows'][tid]['raw_review'],
                result_sha256=v['rows'][tid]['result_sha256'],grader_input_sha256=v['rows'][tid]['grader_input_sha256'])
                for arm,v in arms.items()}))
    path.write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    return dict(packets=32,path=str(path))


def manual_decode(selected, saved, reasons):
    """Validate a declared Codex decision map; this is never an external model response."""
    qs,targets,state=(saved[k] for k in ['questions','targets','state'])
    require(set(selected)==set(qs),'Manual scorecard must cover every decision')
    require(all(choice in qs[k]['criteria'] for k,choice in selected.items()),'Unknown manual label')
    points={};claims={};groups=[];pairs=[]
    for key,t in targets.items():
        value=selected[key];kind=t['kind']
        if kind=='point':points[t['point_id']]=grading.POINT_VALUES[value]
        elif kind=='boundary':boundary={'incorrect':0,'partial':1,'appropriate':2}[value]
        elif kind=='reference':concern=value=='needs_review'
        elif kind=='citation':pairs.append(dict(claim_id=t['claim_id'],ref=t['ref'],raw_score=int(value=='supported'),decision_key=key))
        elif kind=='group':groups.append(dict(claim_id=t['claim_id'],raw_coverage=value,decision_key=key))
        else:claims.setdefault(t['claim_id'],{})[kind]=value
    out=[]
    for c in state['candidate']['claims']:
        v=claims[c['id']]
        out.append(dict(id=c['id'],text=c['text'],claim_type=v['claim_type'],support=v['support'],
            basis_locator=v['basis'],basis=state['verifiable_passages'].get(v['basis'])))
    kinds={c['id']:c['claim_type'] for c in out}
    for p in pairs:p['score']=p['raw_score'] if kinds[p['claim_id']]=='fact' else None
    for g in groups:
        g['coverage']=g['raw_coverage'] if kinds[g['claim_id']]=='fact' else None
        if g['coverage'] is not None:
            positive=any(p['claim_id']==g['claim_id'] and p['score']==1 for p in pairs)
            require((g['coverage'] in {'complete','partial'})==positive,'Manual group/pair conflict')
    return dict(key_point_scores=points,claim_assessments=out,citation_assessments=pairs,
        citation_group_assessments=groups,answerability_score=boundary,reference_concern=concern,
        decisions=selected,reasons=reasons)


def final_review(row, adjudication):
    require(row['result_sha256']==adjudication['result_sha256'],'Adjudicated answer changed')
    require(row['grader_input_sha256']==adjudication['grader_input_sha256'],'Adjudicated input changed')
    require(adjudication.get('summary') and adjudication.get('evidence_checked'),'Every answer needs review rationale and source locators')
    raw=row['raw_review']
    require(adjudication['raw_review_sha256']==(judge.sha(raw) if raw is not None else None),'Raw grade changed')
    selected=dict(raw['decisions']) if raw is not None else dict(adjudication['supplemental_decisions'])
    reasons=dict(raw.get('reasons',{})) if raw is not None else {}
    changed=set()
    for change in adjudication['changes']:
        key=change['decision_key'];require(key not in changed,'Duplicate adjudication')
        require(selected[key]==change['from'],'Adjudication old value mismatch')
        require(change.get('reason') and change.get('basis'),'Changed grade needs specific reasoning and evidence')
        selected[key]=change['to'];reasons[key]=change['reason'];changed.add(key)
    return manual_decode(selected,row['saved'],reasons)


def publish():
    require(not PUBLIC.exists(),'Keep published reports immutable')
    arms=load();adj=judge.read_json(ADJUDICATION)
    require(adj['reviewer']=='Codex' and adj['policy_sha256']==grading.POLICY_SHA,'Wrong adjudicator/policy')
    require(adj['final_evidence_unit']=='actual_attached_text_and_verified_images', 'Declare the multimodal review unit')
    index={(r['arm'],r['task_id']):r for r in adj['items']}
    require(len(index)==len(adj['items'])==64,'Review all 64 answers, not only one arm')
    records=[];summaries={};audit={}
    for arm,data in arms.items():
        raw_rows=[];final_rows=[];changes=[]
        for tid,row in data['rows'].items():
            job=row['job'];case=job['reference_case'];caps=job['task']['capabilities'];a=index[(arm,tid)]
            final=final_review(row,a);raw=row['raw_review']
            m=scoring.metrics(final,case,caps);final_rows.append(m)
            rm=scoring.metrics(raw,case,caps) if raw is not None else None
            if rm is not None:raw_rows.append(rm)
            if a['changes']:changes.append(tid)
            records.append(dict(arm=arm,task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
                key_points=case['key_points'],critical_errors=case['critical_errors'],
                candidate=job['candidate'],raw_jev_review=raw,raw_jev_metrics=rm,
                final_codex_review=final,final_codex_metrics=m,adjudication=a,
                citation_validation=row['response']['citation_validation'],
                sent_images=[(c.get('model_info') or {}).get('images',[]) for c in row['response']['generation_calls']],
                generation_calls=row['response']['generation_calls']))
        responses=[v['response'] for v in data['rows'].values()]
        calls=[c for r in responses for c in r['generation_calls']]
        aliases={'input_tokens':'prompt_tokens','output_tokens':'completion_tokens','total_tokens':'total_tokens'}
        usage={}
        for key,alias in aliases.items():
            values=[(c.get('usage') or {}).get(key,(c.get('usage') or {}).get(alias)) for c in calls]
            usage[key]=sum(values) if all(type(v) is int for v in values) else None
        raw_ids={tid for tid,row in data['rows'].items() if row['raw_review'] is not None}
        summaries[arm]=dict(raw_jev=scoring.summarize(raw_rows) if raw_rows else None,
            final_codex=scoring.summarize(final_rows),corrected_question_ids=changes,
            supplemented_question_ids=sorted(set(data['rows'])-raw_ids),
            runtime=dict(answered=sum(r['status']=='answered' for r in responses),
                generation_calls=len(calls),usage=usage,
                usage_unknown_calls=sum(not c.get('usage') for c in calls),
                known_usage={key:sum((c.get('usage') or {}).get(key,(c.get('usage') or {}).get(alias,0)) for c in calls)
                    for key,alias in aliases.items()},
                returned_models=dict(Counter((c.get('model_info') or {}).get('returned_model') or '<not_returned>' for c in calls)),
                validation_failed_attempts=sum(a['status']=='failed' for r in responses for a in r['citation_validation']['attempts']),
                actual_image_inputs=sum((c.get('model_info') or {}).get('image_count',0) for c in calls),
                reported_answer_cost_usd=None,answer_price_note='Third-party invoice price not supplied; do not derive it from official prices.'),
            judge_accounting=scoring.accounting(data['records'],'jev'))
        audit[arm]=dict(statuses=data['statuses'],results={tid:v['result_sha256'] for tid,v in data['rows'].items()})
    common=sorted(set(t for t,v in arms['astra']['rows'].items() if v['raw_review'] is not None and not v['raw_review']['reference_concern']) &
                  set(t for t,v in arms['deepseek']['rows'].items() if v['raw_review'] is not None and not v['raw_review']['reference_concern']))
    for arm in ARMS:
        summaries[arm]['raw_jev_paired']=scoring.summarize([
            scoring.metrics(arms[arm]['rows'][t]['raw_review'],arms[arm]['rows'][t]['job']['reference_case'],
                arms[arm]['rows'][t]['job']['task']['capabilities']) for t in common]) if common else None
    success_ids=[tid for tid in sorted(arms['astra']['rows']) if all(
        arms[arm]['rows'][tid]['response']['status']=='answered' for arm in ARMS)]
    by_final={(r['arm'],r['task_id']):r for r in records}
    for arm in ARMS:
        summaries[arm]['final_codex_successful_subset']=scoring.summarize([
            by_final[(arm,tid)]['final_codex_metrics'] for tid in success_ids])
    summary=dict(version='matched-answer-models-adjudicated-v1',questions=32,matched_text_and_images=32,
        raw_jev_paired_task_ids=common,
        final_successful_subset_task_ids=success_ids,
        successful_subset_note='Diagnostic only: excludes answers blocked by the platform. The primary result remains all 32 questions.',
        external_judge='typesafe/jev-1.14',final_authority='Codex source review; not independent human expert labels',
        summaries=summaries,policy_sha256=grading.POLICY_SHA,
        adjudication_sha256=judge.digest(ADJUDICATION),contract=judge.read_json(OUTPUT/'contract.json'),
        limitations=['One run per model on one paper; no significance or generalization claim.',
            'Current image-enabled retrieval differs from earlier text-only runs; main comparison is the newly matched pair.',
            'Jev raw uses its unchanged attached-text protocol. Codex final additionally checks the exact verified images actually attached to the same citation ref; this evidence-unit extension applies to both arms and is disclosed separately.',
            'Generation calls count application-level attempts. SDK automatic transport retries, if any, are not separate observable billed records.',
            'End-to-end latencies are not compared: DeepSeek replays retrieval while Astra performs it.',
            'Third-party actual model routing and invoice cost cannot be independently established from client response.'])
    PUBLIC.mkdir(parents=True)
    for name,val in [('comparison.json',summary),('audit.json',audit),('adjudication.json',adj)]:
        scoring.save(PUBLIC/name,val)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in records),encoding='utf-8',newline='\n')
    html_report(summary,records)
    scoring.save(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir()}))
    return summary


def cells(m):
    support=m['support_counts'];n=sum(support.values())
    return [f"{m['point_macro_average']*100:.2f}%",f"{support.get('supported',0)}/{n}",
        f"{m['citation_precision']['numerator']}/{m['citation_precision']['denominator']}",
        f"{m['citation_coverage']['numerator']}/{m['citation_coverage']['denominator']}",
        f"{m['boundary_mean']:.3f}/2",f"{m['all_five_pass']}/{m['tasks']}"]


def html_report(summary,records):
    e=lambda v:escape(str(v),quote=True)
    pre=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2) if not isinstance(v,str) else v)+'</pre>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>GPT-6 Astra 与 DeepSeek：同证据对照及评分复核</title><style>body{font:15px/1.75 system-ui;background:#f5f7fb;color:#203047;max-width:1280px;margin:32px auto;padding:0 20px}h1{font-size:29px}article,section{background:white;border:1px solid #dce4ef;border-radius:12px;padding:22px;margin:20px 0}table{border-collapse:collapse;width:100%;display:block;overflow:auto}td,th{border-bottom:1px solid #dce4ef;text-align:left;padding:10px;white-space:nowrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fb;padding:14px;border-radius:8px}summary{cursor:pointer;font-weight:600}small{color:#63758c}.changed{border-left:4px solid #d48824}a{color:#2469b1}</style>',
        '<h1>回答模型对照与评分复核</h1><p>32题 × 两个模型；同一份 MinerU＋千问检索证据、引用编号及原图。外部评委仅 Jev，最终以 Codex 对照原文复核为准。原始评分完整保留。</p><p>口径说明：Jev原始分沿用文字引用协议；Codex最终分同时核查该引用编号下实际交付的原图，不能用库里存在但当时未交付的图片补证据。要点和边界准则保持原样。两侧统一适用。</p>',
        '<section><h2>汇总指标</h2><table><tr><th>回答模型</th><th>口径</th><th>要点均分</th><th>事实充分支持</th><th>单条引用</th><th>引用组完整</th><th>边界均分</th><th>全部达标</th></tr>']
    for arm in ARMS:
        s=summary['summaries'][arm]
        for label,key in [('Jev原始（两侧有效共同题）','raw_jev_paired'),('Codex最终复核（全部32题）','final_codex')]:
            if s[key] is not None:parts.append('<tr><td>'+e(LABELS[arm])+'</td><td>'+label+'</td>'+''.join('<td>'+e(v)+'</td>' for v in cells(s[key]))+'</tr>')
    parts+=['</table><p>没有加权总分。原始结果和复核结果分别比较；协议无效结果由 Codex 补评，不作为 Jev 零分。一次测试不能证明稳定性或统计显著性。</p></section>',
        '<section><h2>32道题与逐项复核</h2><p>“事实支持”看论文是否支持陈述；“引用支持”只看回答实际附上的证据。含图引用的像素依据在复核中单独注明。纯资料缺失说明按scope检查，不混入科学事实的引用分母。</p></section>']
    by={(r['arm'],r['task_id']):r for r in records}
    for tid in sorted({r['task_id'] for r in records}):
        a=by[('astra',tid)]
        parts+=['<article data-question="'+e(tid)+'"><h2>'+e(tid)+' · '+e(a['question'])+'</h2>',
            '<details><summary>参考答案与评分要点</summary>'+pre(a['reference_answer'])+pre(a['key_points'])+'</details>']
        for arm in ARMS:
            r=by[(arm,tid)];adj=r['adjudication'];final=r['final_codex_metrics'];raw=r['raw_jev_metrics']
            parts+=['<section class="'+('changed' if adj['changes'] or raw is None else '')+'"><h3>'+e(LABELS[arm])+'</h3>',
                pre(r['candidate']['answer']),'<p>要点：Jev '+(f"{raw['point_mean']*100:.2f}%" if raw else '未能有效评分')+' → 最终 '+f"{final['point_mean']*100:.2f}%"+'；边界 '+str(final['boundary'])+'/2。</p>',
                '<p><strong>复核结论：</strong>'+e(adj['summary'])+'</p>']
            if adj['changes']:parts+=['<h4>调整明细及证据</h4>'+pre(adj['changes'])]
            parts+=['<details><summary>Jev原始五维评分与最终评分</summary>'+pre(r['raw_jev_review'])+pre(r['final_codex_review'])+'</details>',
                '<details><summary>实际引用与证据原文</summary>'+pre(r['candidate']['citations'])+'</details>',
                '<details><summary>原图交付及引用校验记录</summary>'+pre(r['sent_images'])+pre(r['citation_validation'])+'</details>',
                '<details><summary>完整复核依据与补评决定</summary>'+pre(adj)+'</details></section>']
        parts+=['</article>']
    parts+=['<section><h2>调用与费用记录</h2>'+pre({a:summary['summaries'][a] for a in ARMS})+'</section>',
        '<section><h2>适用范围</h2>'+pre(summary['limitations'])+'<p>原论文：Li等，Polymers 2020, 12, 2912，DOI: <a href="https://doi.org/10.3390/polym12122912">10.3390/polym12122912</a>。本报告源材料保持原样。</p></section></html>']
    (PUBLIC/'comparison.html').write_text(''.join(parts),encoding='utf-8',newline='\n')


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in {'packets','publish'},'Choose packets or publish')
    print(judge.encode(packets() if sys.argv[1]=='packets' else publish()))
