"""Pair fresh answers with immutable Jev decisions and explicit source calibration."""
import argparse
import copy
import html
import json
from pathlib import Path
import statistics
import sys


def read(path):return json.loads(path.read_text(encoding='utf8'))


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output=a.output.resolve();sys.path.insert(0,str(a.source/'scripts'))
    from report_regression_baseline_20261106 import metrics,calibrate,summary
    cases=read(a.output/'cases.json');notes_path=a.output/'calibration.json'
    notes=read(notes_path) if notes_path.exists() else {};rows=[];summaries={}
    for arm in ['qwen37','jev']:
        subset=[]
        usage=dict(answer_total_tokens=0,answer_calls_missing_usage=0,rerank_batches=0,rerank_api_calls=0,
            known_rerank_cost_usd=0,rerank_cost_unknown_calls=0,rerank_ms=0,
            known_judge_cost_usd=0,judge_cost_unknown_calls=0,search_questions=[],no_search_questions=[],
            rerank_provider_failures=[],rerank_usage={},rerank_batch_seconds=[])
        for case in cases:
            target=a.output/arm/(case['id']+'.json')
            if not target.exists():continue
            x=read(target);review_path=a.output/arm/'judge-jev'/case['id']/'review.json'
            raw=read(review_path) if review_path.exists() else None
            note=notes.get(arm,{}).get(case['id'])
            final=calibrate(raw,note) if raw and note else None
            def failed_metrics():
                return dict(point_score=0,point_count=len(case['key_points']),fact_count=0,supported_facts=0,pair_count=0,supported_pairs=0,
                    group_count=0,covered_groups=0,boundary=0,fact_support=None,citation_precision=None,citation_coverage=None,strict_pass=False,format_ok=False)
            row=dict(id=case['id'],arm=arm,case=case,answer=x.get('answer',''),draft=x.get('draft',''),status=x['status'],
                raw_jev=raw,calibrated=final,calibration=note,raw_metrics=metrics(case,raw,x) if raw else failed_metrics() if x['status']!='completed' else None,
                final_metrics=metrics(case,final,x) if final else failed_metrics() if x['status']!='completed' else None,
                seconds=x['end_to_end_ms']/1000,review_status=x.get('review_status'),stop_reason=x.get('stop_reason'),
                langfuse=x.get('langfuse'),tools=[t.get('input') for t in x.get('tool_trace',[])],result_path=str(target))
            row['evidence']=x.get('evidence',[])
            row['citation_validation']=x.get('citation_validation')
            subset.append(row);rows.append(row)
            for call in x.get('model_calls',[]):
                u=call.get('usage') or {};usage['answer_total_tokens']+=u.get('total_tokens',0) or 0;usage['answer_calls_missing_usage']+=not bool(u)
            searched=False
            for tool in x.get('tool_trace',[]):
                if tool.get('input',{}).get('tool')=='search_literature':searched=True
                r=tool.get('provider_calls',{}).get('rerank')
                if not r:continue
                usage['rerank_batches']+=1;usage['rerank_api_calls']+=r.get('api_calls',0)
                usage['known_rerank_cost_usd']+=r.get('known_cost_usd',0)
                usage['rerank_cost_unknown_calls']+=r.get('cost_unknown_calls',0)
                usage['rerank_ms']+=r.get('latency_ms',0)
                usage['rerank_batch_seconds'].append(r.get('latency_ms',0)/1000)
                for key,value in (r.get('usage') or {}).items():
                    if isinstance(value,(int,float)):
                        usage['rerank_usage'][key]=usage['rerank_usage'].get(key,0)+value
                if r.get('status')!='completed':usage['rerank_provider_failures'].append(dict(case=case['id'],reason=r.get('reason_code')))
            usage['search_questions' if searched else 'no_search_questions'].append(case['id'])
            for path in (a.output/arm/'judge-jev'/case['id']).glob('attempt-*.json'):
                u=read(path).get('usage') or {};cost=u.get('reported_cost_usd')
                if cost is None:usage['judge_cost_unknown_calls']+=1
                else:usage['known_judge_cost_usd']+=cost
        calibrated_rows=[r for r in subset if r['final_metrics'] is not None]
        raw_rows=[r for r in subset if r['raw_metrics'] is not None]
        summaries[arm]=dict(expected=24,recorded=len(subset),completed=sum(r['status']=='completed' for r in subset),
            judged=sum(r['raw_jev'] is not None for r in subset),calibrated=sum(r['calibrated'] is not None for r in subset),
            raw=summary(raw_rows,'raw_metrics') if raw_rows else None,
            final=summary(calibrated_rows,'final_metrics') if calibrated_rows else None,
            median_seconds=statistics.median(r['seconds'] for r in subset) if subset else None,
            total_seconds=sum(r['seconds'] for r in subset),
            usage=usage,by_group={g:summary([r for r in calibrated_rows if r['case']['group']==g],'final_metrics') for g in ['single','cross'] if any(r['case']['group']==g for r in calibrated_rows)})
    result=dict(arms=summaries,manifest=read(a.output/'manifest.json'),
        integrity=read(a.output/'integrity.json') if (a.output/'integrity.json').exists() else None,
        status='complete' if all(v['recorded']==24 and v['judged']==v['completed']==v['calibrated'] for v in summaries.values()) else 'in_progress',
        limitations=['One independent answer per arm/question; answer and routing randomness are not controlled by provider seeds.',
            'Agent may read sections/tables directly. A configured reranker does not imply it was invoked. Report search exposure separately.',
            'Jev is a candidate reranker and also the raw judge; correlated preference is possible. Codex source calibration is explicit and is not an independent human expert review.',
            'Judge receives PDF text and source image metadata, not pixels; visual claims require separate source inspection.',
            'Claims are frozen Markdown semantic blocks, not uniformly sized atomic facts; denominators differ between generated answers.',
            'No weighted grand accuracy. Point score, fact support, citation validity/coverage, boundaries and strict success are distinct.'])
    write(a.output/'summary.json',result);write(a.output/'results.json',rows)
    esc=html.escape
    def pre(x):return '<pre>'+esc(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2))+'</pre>'
    body='<h1>Qwen3.7 与 Jev：24题端到端文献问答对照</h1><p>同一冻结当前Agent代码、DeepSeek Flash非思考、八篇文献库及预算；每题独立新上下文生成一次。只切换重排器。Jev原始评测与Codex原文校准分别保留。'+esc(result['status'])+'</p>'
    body+='<table><tr><th>模型</th><th>完成</th><th>要点分</th><th>事实充分支持</th><th>单引有效</th><th>引用组覆盖</th><th>严格通过</th><th>调用过搜索的题目</th></tr>'
    for arm,s in summaries.items():
        m=s['final'];vals=[arm,f"{s['completed']}/24",f"{m['point_score']:.2f}" if m else '待校准']
        vals += [f"{m[k]['percent']:.2f}% ({m[k]['numerator']}/{m[k]['denominator']})" if m and m[k]['percent'] is not None else 'N/A' for k in ['fact_support','citation_precision','citation_coverage']]
        vals += [str(m['strict_pass_count']) if m else '待校准',str(len(s['usage']['search_questions']))+'/24']
        body+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>'
    body+='</table><p>要点分是逐题必答要点均分，不是整体准确率。事实与引用百分比按各自核查单元汇总，严格通过要求各项同时达标。每组仅运行一次，不能把回答随机波动视为重排器的因果效果。</p>'
    body+='<h2>时间与实际重排调用</h2><table><tr><th>配置</th><th>每题耗时中位数</th><th>重排批次 / API请求</th><th>重排批次耗时中位数</th><th>已知重排费用（美元）</th><th>费用未知请求</th></tr>'
    for arm,s in summaries.items():
        u=s['usage'];durations=u['rerank_batch_seconds']
        vals=[arm,f"{s['median_seconds']:.2f}秒" if s['median_seconds'] is not None else 'N/A',f"{u['rerank_batches']} / {u['rerank_api_calls']}",f"{statistics.median(durations):.2f}秒" if durations else 'N/A',f"{u['known_rerank_cost_usd']:.6f}",str(u['rerank_cost_unknown_calls'])]
        body+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>'
    body+='</table><p>费用未知不等于免费。两组端到端耗时包含不同工具路径，不能直接视为重排器速度对照。</p><details><summary>配置、执行、资源、限制和原始评分汇总</summary>'+pre(result)+'</details>'
    body+='<h2>逐题概览</h2><table><tr><th>题号</th><th>Qwen要点 / 事实支持 / 引用覆盖</th><th>Jev要点 / 事实支持 / 引用覆盖</th></tr>'
    for case in cases:
        cells=['<a href="#'+esc(case['id'])+'">'+esc(case['id'])+'</a>']
        for arm in ['qwen37','jev']:
            row=next((r for r in rows if r['id']==case['id'] and r['arm']==arm),None)
            m=row['final_metrics'] if row else None
            values=[f"{m['point_score']:.2f}"] if m else ['待完成']
            if m:
                values += [f"{m[key]:.2f}%" if m[key] is not None else 'N/A' for key in ['fact_support','citation_coverage']]
            cells.append(esc(' / '.join(values)))
        body+='<tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>'
    body+='</table>'
    for case in cases:
        body+='<h2 id="'+case['id']+'">'+esc(case['id']+' '+case['question'])+'</h2><details><summary>参考答案与评分准则</summary>'+pre(case)+'</details>'
        for arm in ['qwen37','jev']:
            row=next((r for r in rows if r['id']==case['id'] and r['arm']==arm),None)
            if row is None:continue
            body+='<article><h3>'+esc(arm+' '+row['status']+' '+str(row['seconds'])+'秒')+'</h3>'+pre(row['answer'])
            url=(row.get('langfuse') or {}).get('url')
            if url:body+='<a href="'+esc(url,quote=True)+'">Langfuse轨迹</a>'
            body+='<p><a href="'+esc(Path(row['result_path']).as_uri(),quote=True)+'">本地完整结果及原生请求记录</a></p><details><summary>工具顺序</summary>'+pre(row['tools'])+'</details><details><summary>原始证据账本与引用校验</summary>'+pre({k:row[k] for k in ['evidence','citation_validation']})+'</details><details><summary>Jev原始评分与校准差异</summary>'+pre({k:row[k] for k in ['raw_metrics','final_metrics','calibration','raw_jev','calibrated']})+'</details></article>'
    (a.output/'comparison.html').write_text('<!doctype html><meta charset="utf-8"><title>24题端到端重排器对照</title><style>body{max-width:1250px;margin:32px auto;padding:12px;font:15px/1.7 system-ui;color:#203044}table{width:100%;border-collapse:collapse}td,th{border:1px solid #cbd5e1;padding:8px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:14px}summary{cursor:pointer;color:#205da0;padding:8px}h2{margin-top:40px}article{border:1px solid #d6e0eb;margin:16px 0;padding:16px}</style>'+body,encoding='utf8')
    print(json.dumps({k:{f:v[f] for f in ['recorded','completed','judged','calibrated','final']} for k,v in summaries.items()},ensure_ascii=False))


if __name__=='__main__':main()
