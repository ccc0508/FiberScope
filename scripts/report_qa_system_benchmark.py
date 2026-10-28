"""Audit frozen two-system/two-judge responses and publish arithmetic only; no API calls."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from decimal import Decimal
import html
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import judge_qa_jev as jev
import qa_system_judge as grading
from validate_qa_eval import require


def fraction(n,d):return dict(numerator=n,denominator=d,value=n/d if d else None)


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def metrics(review,case,capabilities):
    values=[review['key_point_scores'][p['id']] for p in case['key_points'] if not p['optional'] and p['capability'] in capabilities]
    facts=[c for c in review['claim_assessments'] if c['claim_type']=='fact']
    citations=[p for p in review['citation_assessments'] if p['score'] is not None]
    groups=[g for g in review['citation_group_assessments'] if g['coverage'] is not None]
    return dict(point_mean=statistics.mean(values),required_point_count=len(values),
                required_point_sum=sum(values),support_counts=dict(Counter(c['support'] for c in facts)),
                factual_claims=len(facts),factual_citations=len(citations),
                supported_citations=sum(c['score'] for c in citations),complete_groups=sum(g['coverage']=='complete' for g in groups),
                boundary=review['answerability_score'],reference_concern=review['reference_concern'],
                all_five_pass=all(v==1 for v in values) and all(c['support']=='supported' for c in review['claim_assessments'])
                  and all(p['score']==1 for p in citations) and all(g['coverage']=='complete' for g in groups)
                  and review['answerability_score']==2)


def summarize(rows):
    require(rows,'Cannot summarize empty matched subset')
    support=Counter()
    for row in rows:support.update(row['support_counts'])
    return dict(tasks=len(rows),point_macro_average=statistics.mean(r['point_mean'] for r in rows),
                support_counts=dict(support),citation_precision=fraction(sum(r['supported_citations'] for r in rows),sum(r['factual_citations'] for r in rows)),
                citation_coverage=fraction(sum(r['complete_groups'] for r in rows),sum(r['factual_claims'] for r in rows)),
                boundary_mean=statistics.mean(r['boundary'] for r in rows),all_five_pass=sum(r['all_five_pass'] for r in rows))


def accounting(rows,kind):
    calls=[r for r in rows if r.get('api_calls')]
    costs=[];tokens=Counter()
    for r in calls:
        cost=(r.get('usage') or {}).get('reported_cost_usd') if kind=='jev' else ((r.get('raw_response') or {}).get('usage') or {}).get('cost')
        costs.append(cost if type(cost) in {int,float} and cost>=0 else None)
        for key in ['input_tokens','output_tokens','total_tokens']:
            value=(r.get('usage') or {}).get(key)
            if type(value) is int:tokens[key]+=value
    return dict(calls=len(calls),known_tokens=dict(tokens),
                usage_unknown_calls=sum((r.get('usage') or {}).get('total_tokens') is None for r in calls),
                reported_cost_usd=str(sum((Decimal(str(c)) for c in costs if c is not None),Decimal(0))),
                cost_unknown_calls=sum(c is None for c in costs),invoice_cost_usd=None,
                request_time_ms=sum(r.get('duration_ms') or 0 for r in calls))


def config_from_public(kind,row):
    if kind=='jev':return jev.Config(row['base_url'],row['requested_model'],'',row['timeout_seconds'])
    return judge.Config(row['base_url'],row['requested_model'],'',row['api'],row['timeout_seconds'],row['max_output_tokens'])


def audit(import_dir,study_dir):
    import_dir,study_dir=Path(import_dir),Path(study_dir)
    meta,jobs,sources,pages=grading.load_import(import_dir)
    study=judge.read_json(study_dir/'study.json')
    require(study['import_sha256']==judge.digest(import_dir/'import.json'),'Imported answers changed')
    require(study['policy_sha256']==grading.POLICY_SHA,'Common scoring policy changed')
    require(all(judge.digest(study_dir/'harness'/n)==h for n,h in study['harness_files'].items()),'Archived grading code changed')
    lookup={j['blind_id']:j for j in jobs};reviews={};records=defaultdict(list);statuses=Counter();proofs=[]
    for entry in study['jobs']:
        job=lookup[entry['blind_id']];kind=entry['judge'];config=config_from_public(kind,study['requested_judges'][kind])
        path=study_dir/'inputs'/(entry['name']+'.json');saved=judge.read_json(path)
        require(judge.digest(path)==entry['input_sha256'],'Sealed judge input changed')
        state,questions,targets=grading.packet(job,meta,sources,pages)
        request=grading.request_for(kind,config,state,questions)
        require(saved==dict(state=state,questions=questions,targets=targets,request=request),'Original scientific input differs')
        require(judge.sha(request)==entry['request_sha256'],'Pre-call request seal differs')
        attempts=sorted((study_dir/'records'/entry['name']).glob('*.json'),key=lambda p:int(p.stem))
        previous=None;accepted=None
        for index,path in enumerate(attempts,1):
            r=judge.read_json(path);records[kind].append(r)
            require(int(path.stem)==index and r['attempt']==index,'Attempt sequence has gaps')
            require(accepted is None,'A valid grade was unnecessarily replayed')
            if previous and kind=='luna':request=grading.request_for(kind,config,state,questions,previous.get('validation_error'))
            require(r['request_sha256']==judge.sha(request),'Repair request does not reproduce')
            if index>1:require(r['prior_record_sha256']==judge.digest(attempts[index-2]),'Repair predecessor changed')
            if r.get('raw_response') is not None:require(judge.sha(r['raw_response'])==r['response_sha256'],'Provider raw response changed')
            if r['status']=='completed':
                rechecked=grading.decode(kind,r['raw_response'],request,questions,targets,state)
                require(rechecked==r['review'],'Saved model judgments changed')
                accepted=r['review'];proofs.append(dict(name=entry['name'],record_sha256=judge.digest(path),request_sha256=r['request_sha256']))
            previous=r
        status=previous['status'] if previous else 'missing';statuses[(kind,job['system'],status)]+=1
        if accepted is not None:reviews[(kind,job['system'],job['task_id'])]=accepted
    return meta,jobs,study,reviews,records,statuses,proofs


def publish(import_dir,study_dir,output,document,allow_incomplete=False):
    import_dir,study_dir,output,document=map(lambda p:Path(p).resolve(),(import_dir,study_dir,output,document))
    require(not output.exists() and not document.exists(),'Use new report destinations')
    meta,jobs,study,reviews,records,statuses,proofs=audit(import_dir,study_dir)
    by_task={j['task_id']:j for j in jobs};task_ids=sorted(by_task)
    require(all(s!='pending' for _,_,s in statuses),'Wait for in-flight grading requests before publication')
    if not allow_incomplete:require(len(reviews)==128,'Incomplete grading; explicitly disclose partial publication')
    rows={key:metrics(r,by_task[key[2]]['reference_case'],by_task[key[2]]['task']['capabilities']) for key,r in reviews.items()}
    common=[tid for tid in task_ids if all((kind,system,tid) in rows and not rows[(kind,system,tid)]['reference_concern']
                                          for kind in ['luna','jev'] for system in ['rag','dsh'])]
    require(common,'No fully matched, unflagged comparison subset')
    summaries={kind:{system:summarize([rows[(kind,system,tid)] for tid in common]) for system in ['rag','dsh']} for kind in ['luna','jev']}
    within_judge={}
    for kind in ['luna','jev']:
        selected=[tid for tid in task_ids if all((kind,system,tid) in rows and not rows[(kind,system,tid)]['reference_concern']
                                               for system in ['rag','dsh'])]
        within_judge[kind]=dict(task_ids=selected,tasks=len(selected),
                               scores={system:summarize([rows[(kind,system,tid)] for tid in selected]) for system in ['rag','dsh']})
    independent={}
    for kind in ['luna','jev']:
        for system in ['rag','dsh']:
            own=[r for (k,s,_),r in rows.items() if k==kind and s==system and not r['reference_concern']]
            independent[kind+'_'+system]=summarize(own) if own else None
    exclusions=[]
    for tid in task_ids:
        if tid in common:continue
        exclusions.append(dict(task_id=tid,missing=[kind+'_'+system for kind in ['luna','jev'] for system in ['rag','dsh'] if (kind,system,tid) not in reviews],
                               reference_flags=[kind+'_'+system for kind in ['luna','jev'] for system in ['rag','dsh']
                                                if (kind,system,tid) in reviews and reviews[(kind,system,tid)]['reference_concern']]))
    costs={kind:accounting(records[kind],kind) for kind in ['luna','jev']}
    runtime_path=import_dir/'runtime-confirmation.json'
    runtime=judge.read_json(runtime_path) if runtime_path.exists() else meta['metadata']
    text_counts={system:dict(claims=sum(len(j['candidate']['claims']) for j in jobs if j['system']==system),
                             citations=sum(len(j['candidate']['citations']) for j in jobs if j['system']==system),
                             mean_answer_characters=statistics.mean(len(j['candidate']['answer']) for j in jobs if j['system']==system))
                 for system in ['rag','dsh']}
    win_loss={kind:dict(dsh_higher=sum(rows[(kind,'dsh',tid)]['point_mean']>rows[(kind,'rag',tid)]['point_mean'] for tid in common),
                             tie=sum(rows[(kind,'dsh',tid)]['point_mean']==rows[(kind,'rag',tid)]['point_mean'] for tid in common),
                             rag_higher=sum(rows[(kind,'dsh',tid)]['point_mean']<rows[(kind,'rag',tid)]['point_mean'] for tid in common))
              for kind in ['luna','jev']}
    result=dict(version=grading.VERSION,policy_sha256=grading.POLICY_SHA,study_sha256=judge.digest(study_dir/'study.json'),
                import_sha256=judge.digest(import_dir/'import.json'),question_count=32,planned_grades=128,valid_grades=len(reviews),
                matched_tasks=len(common),matched_task_ids=common,excluded_tasks=exclusions,
                all_grades_valid=len(reviews)==128,scores=summaries,individual_unflagged_scores=independent,
                paired_within_each_judge=within_judge,
                point_win_tie_loss=win_loss,accounting=costs,dsh_runtime=runtime,text_counts=text_counts,
                user_declared_execution=meta['metadata'],quote_verification=meta['quote_verification'],
                runtime_confirmation_supersedes_import_metadata=runtime_path.exists(),
                grading_coverage={kind:{system:{status:count for (k,s,status),count in statuses.items() if k==kind and s==system}
                                        for system in ['rag','dsh']} for kind in ['luna','jev']},
                initial_attempt_statuses={kind:dict(Counter(r['status'] for r in records[kind] if r['attempt']==1)) for kind in ['luna','jev']},
                raw_input_sha256=meta['raw_input_sha256'],new_answer_generation_calls=0,new_analysis_model_calls=0,
                rounds_per_judge=1,expert_gold_accuracy_measured=False,
                caveat='Single paper, 32 development questions, one generation set and one valid grade per judge/system; '
                       'model/platform internals differ. No causal architecture attribution, significance or new-paper generalization claim.')
    output.mkdir(parents=True)
    save(output/'comparison.json',result)
    public_rows=[]
    for tid in task_ids:
        sample=dict(task_id=tid,question=by_task[tid]['reference_case']['question'],category=by_task[tid]['reference_case']['category'],
                    reference_answer=by_task[tid]['reference_case']['reference_answer'],key_points=by_task[tid]['reference_case']['key_points'],systems={})
        for system in ['rag','dsh']:
            job=next(j for j in jobs if j['task_id']==tid and j['system']==system)
            candidate={k:v for k,v in job['candidate'].items() if k!='available_context'}
            sample['systems'][system]=dict(candidate=candidate,judges={kind:dict(review=reviews.get((kind,system,tid)),metrics=rows.get((kind,system,tid)))
                                                                      for kind in ['luna','jev']})
        public_rows.append(sample)
    (output/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in public_rows),encoding='utf-8',newline='\n')
    save(output/'audit.json',dict(valid_records=proofs,source_import_sha256=judge.digest(import_dir/'import.json'),
        runtime_confirmation_sha256=judge.digest(runtime_path) if runtime_path.exists() else None,
        grading_harness=study['harness_files'],original_inputs_unchanged=True,no_grades_assigned_by_exporter=True))
    render_html(output/'comparison.html',result,public_rows)
    write_document(document,result,output)
    save(output/'publication.json',dict(files={p.name:judge.digest(p) for p in output.iterdir() if p.is_file()},
                                      exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    return result


def percent(value):return f'{value*100:.2f}%'


def ratio(value):return f"{value['numerator']}/{value['denominator']} ({percent(value['value'])})" if value['value'] is not None else '不适用'


def summary_table(result):
    rows=['| 裁判 / 系统 | 要点均分 | 事实完全支持 | 单条引用有效 | 引用组完整 | 边界均分 / 2 | 五项全部达标 |',
          '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for kind in ['luna','jev']:
        for system in ['rag','dsh']:
            s=result['scores'][kind][system];support=s['support_counts'];total=sum(support.values())
            rows.append(f"| {kind} / {system.upper()} | {percent(s['point_macro_average'])} | {support.get('supported',0)}/{total} | "
                        f"{ratio(s['citation_precision'])} | {ratio(s['citation_coverage'])} | {s['boundary_mean']:.3f} | {s['all_five_pass']}/{s['tasks']} |")
    return rows


def write_document(path,result,output):
    relative='../'+output.relative_to(judge.ROOT).as_posix()
    lines=['# DSH与FiberScope：同论文、同32题、同五项规则的系统对照','',
        f"32题的DSH与已冻结RAG回答均已提交Luna和Jev独立评分；有效评分{result['valid_grades']}/128，共同可用题目{result['matched_tasks']}/32。",'',
        '双方均要求DeepSeek V4.1-Flash-1017 / High。DSH实际返回版本由用户选择确认，未取得平台API原始版本记录；RAG请求deepseek-flash并显式开启High。此次比较包含读取全文、检索和工具的整套系统差异，不是单独控制架构的模型实验。','',
        '## 同一共同可用题目上的结果','',*summary_table(result),'',
        '这些百分比属于不同维度，不相加为“答案总分”或“正确率”。要点按每题必答点先求均值再作宏平均；事实支持只统计事实陈述；纯范围声明的事实引用不适用。额外补充的事实仍须核验。','',
        '## 每位裁判各自最大可用配对集合','',
        *[f"{k}：{v['tasks']}/32题。该裁判的DSH和RAG使用完全相同的题目；不同裁判的集合可能不同，不混合求均分。" for k,v in result['paired_within_each_judge'].items()], '',
        *summary_table(dict(scores={k:v['scores'] for k,v in result['paired_within_each_judge'].items()})), '',
        '## 控制变量与变更','',
        '同一原始PDF、同32道问题、同冻结参考答案与要点、同一共同五项语义标准；两个裁判逐份答案独立请求，不接收另一裁判分数、旧评分、作答模型名或平台名。实际可用文档/片段只用于核验范围声明，不能作为第六项检索评分。',
        '重新评分双方已冻结答案，不再调用答题模型。旧六维评分不混入本报告。新协议让两个裁判选择同一组原子标签；Luna另外给出文字理由，Jev保留原生选择和概率。来源依据从固定原文ID选择，程序不替模型判断支持标签。',
        '第13题从原回答文本明确引用的本地JSON文件读取；其余31题来自answer.txt。仅去掉外部代码围栏，统一整数、数字字符串与方括号引用编号。回答、陈述和引文内容未改写，正文与claims一致性已核验。',
        '引用单位为各系统实际附带的片段/短引；不把整个页码中的未引用内容补入引用组。引文不能直接文本匹配时，提供对应PDF页的原始抽取供定位检查，不自动判零，也不修改原文。该差异及回答长度需与引用率一并解释。','',
        '## 未进入共同汇总的题目','',
        '| 裁判 / 系统 | 有效评分 |', '| --- | ---: |',
        *[f"| {k} / {s.upper()} | {result['grading_coverage'][k][s].get('completed',0)}/32 |" for k in ['luna','jev'] for s in ['rag','dsh']], '',
        *([judge.encode(r) for r in result['excluded_tasks']] or ['无。']),
        '接口失败、格式无效和参考标准疑点均不记为答案零分；无效或未结束评分不填充。原始请求、全部尝试、费用与来源指纹保留在本地忽略目录。先取得有效评分即停止该份答案，不择优重评。','',
        '若存在排除题，共同子集不等于完整32题结果；评分异常可能集中在复杂或较长回答上，不能假定缺失随机，也不能据此直接宣称系统整体胜出。','',
        '## 用量、耗时与费用','',
        f"DSH本轮32题合计Token：{result['dsh_runtime'].get('total_tokens','未知'):,}（用户确认，未核验平台日志）。输入/输出分项、总耗时、实际费用未知。不能由Token数量直接虚构实际费用。",
        'RAG答题用量沿用上轮归档：成功记录已知160,637 Token，另4次原90秒超时用量未知；成功回答端到端中位65.375秒，混合串行/并发调度。DSH缺少对应时间记录，当前不能作严格速度或完整成本对比。','',
        '| 裁判 | 本轮评分请求数（含失败/补评） | API报告费用 | 费用未知请求 |',
        '| --- | ---: | ---: | ---: |',
        *[f"| {k} | {a['calls']} | ${a['reported_cost_usd']} | {a['cost_unknown_calls']} |" for k,a in result['accounting'].items()],
        '', '上表是裁判评分成本，与DSH/RAG的答题成本分开；API报告费用也不等于已核验账单。','',
        '## 逐题材料与适用范围','',
        f'[可展开逐题报告]({relative}/comparison.html)、[32题答案、标准与两个裁判的全部标签和理由]({relative}/questions-answers-reviews.jsonl)、[机器可读汇总]({relative}/comparison.json)。',
        '一次运行不能衡量稳定性。本评测只覆盖一篇论文的32道已见开发题，不能作为独立holdout、跨论文泛化或专家准确率结论。两个裁判之间的一致不证明正确；参考疑点需进一步核对。','']
    lines.extend(['论文：Li、Zhao、He（2020），Polymers 12, 2912，'
                  '[DOI: 10.3390/polym12122912](https://doi.org/10.3390/polym12122912)，原论文CC BY 4.0。',''])
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines),encoding='utf-8',newline='\n')


def render_html(path,result,rows):
    e=html.escape
    pieces=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DSH 与 FiberScope 对照评测</title>',
        '<style>body{font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif;background:#f4f7fb;color:#203047;margin:0}main{max-width:1250px;margin:40px auto;padding:0 24px}h1{font-size:28px}details,article{background:white;border:1px solid #dde5ee;border-radius:10px;padding:18px;margin:14px 0}summary{cursor:pointer;font-weight:650}.systems{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f6f8fb;padding:14px}small{color:#5b6d83}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #dde5ee;text-align:left;padding:8px;vertical-align:top}h3{color:#356fbe}@media(max-width:850px){.systems{display:block}}</style><main>',
        '<h1>DSH 与 FiberScope：五项共同质量评测</h1>',
        f"<p>32题 · 有效评分 {result['valid_grades']}/128 · 共同可用 {result['matched_tasks']}/32。只比较同一共同子集；不合成总分。</p>",
        '<article><h2>配对汇总</h2><table><tr><th>裁判 / 系统</th><th>要点</th><th>事实完全支持</th><th>引用有效</th><th>引用组完整</th><th>边界 / 2</th></tr>']
    for kind in ['luna','jev']:
        for system,s in result['scores'][kind].items():
            support=s['support_counts'];fact_ratio=f"{support.get('supported',0)}/{sum(support.values())}"
            pieces.append(f"<tr><td>{e(kind)} / {e(system.upper())}</td><td>{percent(s['point_macro_average'])}</td><td>{fact_ratio}</td><td>{ratio(s['citation_precision'])}</td><td>{ratio(s['citation_coverage'])}</td><td>{s['boundary_mean']:.3f}</td></tr>")
    pieces.append('</table><p>裁判之间独立；参考论文相同。一次单篇开发集运行，不能证明统计显著性或跨论文泛化。</p></article>')
    for row in rows:
        pieces.append(f"<details><summary>{e(row['task_id'])} · {e(row['question'])}</summary><h3>参考答案与评分要点</h3><pre>{e(row['reference_answer'])}</pre><ul>")
        for p in row['key_points']:pieces.append(f"<li>{e(p['id'])} {'（可选）' if p['optional'] else '（必答）'}：{e(p['text'])}</li>")
        pieces.append('</ul><div class="systems">')
        for system,cell in row['systems'].items():
            pieces.append(f"<section><h2>{e(system.upper())}</h2><pre>{e(cell['candidate']['answer'])}</pre>")
            pieces.append('<details><summary>逐条陈述与对应引用</summary><ol>')
            for claim in cell['candidate']['claims']:
                pieces.append(f"<li>{e(claim['id'])}：{e(claim['text'])} {e(' '.join(claim['citation_refs']))}</li>")
            pieces.append('</ol></details>')
            for kind,card in cell['judges'].items():
                if card['review'] is None:pieces.append(f'<p>{e(kind)}：无有效评分。</p>');continue
                s=card['metrics'];pieces.append(f"<details><summary>{e(kind)} · 要点 {percent(s['point_mean'])} · 边界 {s['boundary']}/2</summary>")
                if s['reference_concern']:pieces.append('<p>本裁判标记参考标准疑点，未纳入共同汇总。</p>')
                pieces.append('<p><small>point为要点，support为事实支持，citation为单条引用，group为联合引用，boundary为边界。basis与reference_check为辅助定位及诊断；纯范围陈述的引用原生选择不纳入事实引用统计。</small></p><table><tr><th>评判项</th><th>模型选择</th><th>理由</th></tr>')
                for key,value in card['review']['decisions'].items():pieces.append(f"<tr><td>{e(key)}</td><td>{e(value)}</td><td>{e(card['review']['reasons'].get(key,'Jev原生选择；未生成文字理由'))}</td></tr>")
                pieces.append('</table></details>')
            pieces.append('<details><summary>实际引用与定位核验</summary>')
            for c in cell['candidate']['citations']:pieces.append(f"<p>{e(c['ref'])} · PDF {c['page_start']}–{c['page_end']} 页 · {e(c['verification']['status'])}</p><pre>{e(c['text'])}</pre>")
            pieces.append('</details></section>')
        pieces.append('</div></details>')
    pieces.append('<p><small>论文：Li、Zhao、He（2020），Polymers 12, 2912。<a href="https://doi.org/10.3390/polym12122912">DOI:10.3390/polym12122912</a> · 原论文 CC BY 4.0。</small></p></main></html>')
    path.write_text(''.join(pieces),encoding='utf-8',newline='\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['import-dir','study-dir','output','document']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--allow-incomplete',action='store_true');args=parser.parse_args()
    r=publish(args.import_dir,args.study_dir,args.output,args.document,args.allow_incomplete)
    print(judge.encode(dict(valid=r['valid_grades'],matched=r['matched_tasks'],scores=r['scores'],accounting=r['accounting'])))


if __name__=='__main__':main()
