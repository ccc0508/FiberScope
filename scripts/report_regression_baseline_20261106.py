"""Publish frozen answers, independent Jev scores and explicit Codex calibration."""
import copy,html,json,statistics
from pathlib import Path
import judge_qa_eval as j
from run_regression_baseline_20261106 import ROOT,RUN

PACK=RUN/'pack'
REPORT=ROOT/'data/literature/qa-evaluation/reports/agent-regression-baseline-20261106'

def apply(review,change):
    parts=change['path'].split('.')
    obj=review
    for key in parts[:-1]:
        if isinstance(obj,list):
            obj=next(x for x in obj if x.get('id')==key or x.get('claim_id')==key or x.get('ref')==key)
        else:obj=obj[key]
    obj[parts[-1]]=change['value']

def calibrate(raw,notes):
    v=copy.deepcopy(raw)
    for c in notes['changes']:
        # Citation pair keys address both the claim and its attached ref.
        parts=c['path'].split('.')
        if parts[0]=='citation_assessments':
            p=next(p for p in v['citation_assessments'] if p['claim_id']==parts[1] and p['ref']==parts[2]);p[parts[3]]=c['value']
        else:apply(v,c)
    return v

def metrics(case,v,result):
    points=[p for p in v['key_point_scores'].values() if p is not None]
    facts=[c for c in v['claim_assessments'] if c['claim_type']=='fact']
    ids={c['id'] for c in facts}
    pairs=[p for p in v['citation_assessments'] if p['claim_id'] in ids and p['score'] is not None] if case['citation_applicable'] else []
    groups=[p for p in v['citation_group_assessments'] if p['claim_id'] in ids] if case['citation_applicable'] else []
    out=dict(point_score=100*statistics.mean(points) if points else None,point_count=len(points),fact_count=len(facts),supported_facts=sum(c['support']=='supported' for c in facts),
        pair_count=len(pairs),supported_pairs=sum(p['score'] for p in pairs),group_count=len(groups),covered_groups=sum(p['coverage']=='complete' for p in groups),boundary=v['answerability_score'])
    for name,n,d in [('fact_support','supported_facts','fact_count'),('citation_precision','supported_pairs','pair_count'),('citation_coverage','covered_groups','group_count')]:out[name]=100*out[n]/out[d] if out[d] else None
    completed=result.get('status')=='completed' and bool(result.get('answer','').strip())
    format_ok=True
    if case['id']=='FS8-030':
        try:format_ok=isinstance(json.loads(result.get('answer','')),list)
        except ValueError:format_ok=False
    out['strict_pass']=completed and bool(points) and all(p==1 for p in points) and v['answerability_score']==2 and all(c['support']=='supported' for c in v['claim_assessments']) and all(p['score']==1 for p in pairs) and all(p['coverage']=='complete' for p in groups) and format_ok
    out['format_ok']=format_ok
    return out

def summary(rows,arm):
    out={'count':len(rows),'point_score':statistics.mean(r[arm]['point_score'] for r in rows),'strict_pass_count':sum(r[arm]['strict_pass'] for r in rows),'boundary_mean':statistics.mean(r[arm]['boundary'] for r in rows)}
    for name,n,d in [('fact_support','supported_facts','fact_count'),('citation_precision','supported_pairs','pair_count'),('citation_coverage','covered_groups','group_count')]:
        den=sum(r[arm][d] for r in rows);num=sum(r[arm][n] for r in rows);out[name]=dict(percent=100*num/den if den else None,numerator=num,denominator=den)
    return out

def main():
    cases=j.read_jsonl(PACK/'gold.jsonl');notes=j.read_json(RUN/'calibration-notes.json');assert len(notes)==30
    REPORT.mkdir(parents=True,exist_ok=True);rows=[];details=[];usage={'answer_input_tokens':0,'answer_output_tokens':0,'answer_total_tokens':0,'answer_usage_missing_calls':0,'jev_cost_usd':0,'jev_cost_missing_attempts':0}
    for case in cases:
        tid=case['id'];x=j.read_json(RUN/(tid+'.json'));v=j.read_json(RUN/'jev'/tid/'review.json');final=calibrate(v,notes[tid])
        tools=[t['request']['tool'] for t in x.get('tool_calls',[])];paper_tools=[t for t in tools if t not in {'calculate','calculate_change'}]
        if case['group']=='no_paper':routing=not paper_tools
        else:
            expected={s['document_id'] for s in j.read_json(PACK/'sources.json') if s['id'] in {e['document'] for e in case['evidence']}}
            seen={e['content'].get('document_id') or e['content'].get('asset',{}).get('document_id') for e in x.get('evidence',[])};routing=expected<=seen
        row=dict(id=tid,group=case['group'],status=x['status'],review_status=x.get('review_status'),stop_reason=x.get('stop_reason'),jev=metrics(case,v,x),final=metrics(case,final,x),tools=tools,routing_ok=routing,elapsed_ms=x['end_to_end_ms'],changes=notes[tid]['changes'],reason=notes[tid]['reason'])
        rows.append(row);details.append(dict(case=case,answer=x.get('answer',''),draft=x.get('draft',''),raw_jev=v,calibrated=final,summary=row,result_sha256=j.digest(RUN/(tid+'.json')),judge_input_sha256=j.digest(RUN/'jev'/tid/'input.json')))
        for call in x['model_calls']:
            u=call.get('usage')
            if not u:usage['answer_usage_missing_calls']+=1;continue
            for target,source in [('answer_input_tokens','prompt_tokens'),('answer_output_tokens','completion_tokens'),('answer_total_tokens','total_tokens')]:usage[target]+=u.get(source,0) or 0
        for p in (RUN/'jev'/tid).glob('attempt-*.json'):
            a=j.read_json(p);u=a.get('usage') or {};cost=u.get('reported_cost_usd')
            if cost is None:usage['jev_cost_missing_attempts']+=1
            else:usage['jev_cost_usd']+=float(cost)
    meta=dict(suite='FS8-v1',runtime='frozen latest Agentic RAG, 2026-11-06',answer_model='deepseek-flash',thinking=False,judge='typesafe/jev-1.14',final_authority='Codex source-based calibration, not independent human expert review',
        completed=sum(r['status']=='completed' for r in rows),review_completed=sum(r['review_status']=='completed' for r in rows),count=len(rows),
        raw_jev=summary(rows,'jev'),calibrated=summary(rows,'final'),groups={group:summary([r for r in rows if r['group']==group],'final') for group in ['single','cross','no_paper']},usage=usage,
        elapsed_seconds=sum(r['elapsed_ms'] for r in rows)/1000,routing_ok=sum(r['routing_ok'] for r in rows),
        limitations=['one run per question, no stability estimate','new suite: not directly comparable to old 32-question scores','claims are frozen Markdown semantic blocks, not atomic sentences; compound blocks can contain multiple facts','Jev receives original source text pages and image metadata, not pixels','FS8-002 K4 excluded after reference-standard review because question does not request generic transferability','routing document-coverage proxy is separate from correctness and actual evidence utilization'])
    meta['baseline_manifest']=j.read_json(RUN/'manifest.json')
    meta['regression_policy']='Original 30 cases only; extension3 excluded; one independent first attempt; never mixed with old answers'
    j.write(REPORT/'summary.json',meta);j.write(REPORT/'results.json',details);j.write(REPORT/'calibration.json',notes)
    esc=html.escape
    def fmt(x):return 'N/A' if x is None else f'{x:.2f}'
    def measure(m):return ' / '.join([fmt(m['point_score']),fmt(m['fact_support']),fmt(m['citation_precision']),fmt(m['citation_coverage']),str(m['boundary']), '通过' if m['strict_pass'] else '未通过'])
    body=[]
    for d in details:
        c=d['case'];r=d['summary']
        changes=''.join('<li>'+esc(ch['path'])+' → '+esc(str(ch['value']))+'：'+esc(ch['reason'])+'</li>' for ch in r['changes']) or '<li>维持Jev评分，理由见下。</li>'
        evidence='；'.join(f"{e['document']} PDF第{','.join(map(str,e['pages']))}页 {e['locator']}" for e in c['evidence']) or '用户输入/计算，无论文要求'
        body.append(f'''<article><h2>{c['id']} · {esc(c['question'])}</h2><p><b>Jev：</b>{measure(r['jev'])}<br><b>校准：</b>{measure(r['final'])}</p><p>指标顺序：要点% / 事实充分支持% / 单引有效% / 引用组覆盖% / 边界0–2 / 严格通过</p><p><b>校准说明：</b>{esc(r['reason'])}</p><ul>{changes}</ul><p>状态：{r['status']} · 复核：{r['review_status']} · 工具：{esc(', '.join(r['tools']) or '无')} · {r['elapsed_ms']/1000:.1f}秒</p><details><summary>完整回答</summary><pre>{esc(d['answer'])}</pre></details><details><summary>参考答案、必答要点与证据</summary><p>{esc(c['reference_answer'])}</p><ol>{''.join('<li>'+esc(p)+'</li>' for p in c['key_points'])}</ol><p>{esc(evidence)}</p></details><details><summary>Jev原始决定与最终核查记录</summary><pre>{esc(json.dumps({'Jev':d['raw_jev'],'校准后':d['calibrated']},ensure_ascii=False,indent=2))}</pre></details></article>''')
    m=meta['calibrated'];intro=f"完成{meta['completed']}/30；完整复核{meta['review_completed']}/30。校准后要点分{m['point_score']:.2f}，严格通过{m['strict_pass_count']}/30。"
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>30题回归基线</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei";background:#f3f6fa;color:#22334a;margin:0}main{max-width:1100px;margin:auto;padding:28px}article{background:white;border:1px solid #d8e1ec;border-radius:10px;padding:22px;margin:20px 0}h2{font-size:19px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}summary{cursor:pointer;color:#25639a}details{margin:12px 0}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccd7e3}</style><main><h1>当前版本 · 30题回归基线</h1><p>''' + intro + '''</p><p>同一最新版运行时，每题独立上下文、首次作答，不挑最佳答案。Jev独立评分后由Codex逐题校准；这不是独立人类专家审核。没有重跑答得差的题。非论文题引用指标为N/A。</p><details><summary>总体分组指标、资源用量与限制</summary><pre>''' + esc(json.dumps(meta,ensure_ascii=False,indent=2)) + '</pre></details>'+''.join(body)+'</main></html>'
    (REPORT/'report.html').write_text(page,encoding='utf-8')
    print(j.encode({k:meta[k] for k in ['completed','review_completed','calibrated','usage','elapsed_seconds','routing_ok']}))

if __name__=='__main__':main()
