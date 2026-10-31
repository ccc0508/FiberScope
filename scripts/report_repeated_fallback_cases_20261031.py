"""Count original Jev target-point completeness over five fresh answers per condition."""
from collections import Counter
from html import escape
from pathlib import Path
import json
import statistics

import judge_qa_eval as judge
from validate_qa_eval import require
from section_context_20261031 import save

TAG='fallback-two-cases-five-20261031'
TASKS=('PFI2-016','PFI2-028')
ARMS=('control','guidance')
LABELS={'control':'保留邻块','guidance':'删除邻块'}
TARGETS={'PFI2-016':'P3','PFI2-028':'P1'}
CRITERIA={'PFI2-016':'明确区分纸页与纤维层面的强度，说明纸页变强不能推断单根纤维必然变强。',
    'PFI2-028':'明确说明缺少第二篇论文或其证据，无法完成所要求的跨文献比较。'}
LIMITATIONS=[
    '每题每种输入各5份全新独立回答，旧单轮不计入；相同材料、模型别名、High、提示词和原引用纠正机制。',
    '主观察项事先指定为第16题P3、第28题P1。Jev原判1=完整、0.5=部分、0=缺失；未完整回答率统计0或0.5，完全缺失率只统计0。其他要点和边界另列。',
    '无效评分记未知，不算漏答或答全。频率分母明确为有效评分数，同时保留计划5次和未知数；不补第6份答案填补评分缺失。',
    '只用原Jev协议与首个有效评分，最多3次评分尝试；每份评分独立组装上下文，不提供其他回答或旧分。裁判标签不是专家定论。',
    '每组仅5次，是描述性小样本，不证明统计显著性或因果关系。生成波动与裁判波动未分开识别。',
    '没有新增检索、Embedding或重排；网站默认配置未改变。Token包括推理Token，答题实际费用未知，Jev API报告费用不是核验账单。']


def analyze(p):
    rows=p['records'];expected={(t,a,r) for t in TASKS for a in ARMS for r in range(1,6)}
    keys=[(r['task_id'],r['arm'],r['round']) for r in rows]
    require(len(keys)==20 and set(keys)==expected,'Require exactly 20 unique fresh answers')
    require(p['controls']['old_answers_included'] is False and p['controls']['fresh_answers']==20,'Prior answers cannot enter these five repeats')
    summaries=[]
    for tid in TASKS:
        for a in ARMS:
            own=sorted([r for r in rows if r['task_id']==tid and r['arm']==a],key=lambda r:r['round'])
            require(len({r['evidence_sha256'] for r in own})==1,'Repeated evidence differs')
            counts=Counter();labels=[]
            for r in own:
                if r['review'] is None:label='unknown'
                else:
                    v=r['review']['key_point_scores'][TARGETS[tid]]
                    require(v in [0,.5,1],'Unexpected target-point score')
                    label={0:'missing',.5:'partial',1:'complete'}[v]
                labels.append(label);counts[label]+=1
            valid=5-counts['unknown'];incomplete=counts['missing']+counts['partial']
            summaries.append(dict(task_id=tid,arm=a,target_point=TARGETS[tid],criterion=CRITERIA[tid],planned_answers=5,
                valid_grades=valid,complete=counts['complete'],partial=counts['partial'],missing=counts['missing'],unknown=counts['unknown'],
                incomplete_count=incomplete,incomplete_rate=incomplete/valid if valid else None,
                strict_missing_rate=counts['missing']/valid if valid else None,round_labels=labels))
    calls={a:[c for r in rows if r['arm']==a for c in r['generation_calls']] for a in ARMS}
    runtime={a:dict(answers=10,generation_calls=len(calls[a]),known_tokens=dict(sum((Counter(c.get('usage') or {}) for c in calls[a]),Counter())),
        usage_unknown_calls=sum(c.get('usage') is None for c in calls[a]),median_seconds=statistics.median(r['latency_ms'] for r in rows if r['arm']==a)/1000)
        for a in ARMS}
    return dict(version=p['version'],summaries=summaries,runtimes=runtime,accounting=p['accounting'],controls=p['controls'],
        provenance=p['provenance'],analyst_notes=p.get('analyst_notes',[]),limitations=LIMITATIONS,reporter_model_calls=0)


def table(result):
    e=lambda v:escape(str(v),quote=True)
    labels={'complete':'完整','partial':'部分','missing':'缺失','unknown':'未知'}
    rows=[]
    for s in result['summaries']:
        rows.append([s['task_id'],LABELS[s['arm']],'/'.join(labels[x] for x in s['round_labels']),s['complete'],s['partial'],s['missing'],s['unknown'],
            f"{s['incomplete_count']}/{s['valid_grades']}" if s['valid_grades'] else '未知'])
    heads=['题目','输入','第1–5次目标要点','完整','部分','缺失','未知','未完整／有效评分']
    return '<table><tr>'+''.join('<th>'+e(h)+'</th>' for h in heads)+'</tr>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in r)+'</tr>' for r in rows)+'</table>'


def publish(root,out):
    root,out=Path(root),Path(out);dest=root/'data/literature/qa-evaluation/reports'/TAG;doc=root/'docs/QA_FALLBACK_TWO_CASES_FIVE_REPORT_20261031.md'
    require(not dest.exists() and not doc.exists(),'Never overwrite published repeats')
    p=judge.read_json(out/'analysis-input.json');r=analyze(p);dest.mkdir(parents=True)
    e=lambda v:escape(str(v),quote=True);dump=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第16、28题五次独立回答</title>',
       '<style>body{font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif;background:#f3f6fa;color:#203247;margin:24px auto;padding:0 20px;max-width:1400px}section,article{background:white;padding:18px;margin:16px 0;border:1px solid #dce5ef;border-radius:9px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce5ef;padding:8px}summary{cursor:pointer;font-weight:650}.scroll{overflow:auto}</style>',
       '<h1>第16、28题：保留／删除邻块，各独立回答5次</h1><p>2026-10-31。20份全新回答，旧单轮不计入。使用原107块纯删除实验的固定输入，没有重新检索或改写提示词。</p>',
       '<section><h2>目标要点频率</h2><div class="scroll">'+table(r)+'</div>'+''.join('<p>'+e(n)+'</p>' for n in r['analyst_notes'])+'</section>',
       '<section><h2>判读口径</h2>'+''.join('<p>'+e(n)+'</p>' for n in LIMITATIONS)+'</section>',
       '<section><h2>用量与来源</h2>'+dump(dict(runtimes=r['runtimes'],accounting=r['accounting'],controls=r['controls'],provenance=r['provenance']))+'</section>']
    for tid in TASKS:
        first=next(x for x in p['records'] if x['task_id']==tid)
        h+=['<section><h2>'+e(tid+' · '+first['reference_case']['question'])+'</h2><p>主观察项：'+e(CRITERIA[tid])+'</p>',
            '<details><summary>完整参考答案与原评分要点</summary>'+dump(first['reference_case'])+'</details></section>']
        for round_no in range(1,6):
            h+=['<article><h3>'+e(tid+' · 第'+str(round_no)+'次')+'</h3>']
            for a in ARMS:
                row=next(x for x in p['records'] if (x['task_id'],x['round'],x['arm'])==(tid,round_no,a))
                target='未知' if row['review'] is None else row['review']['key_point_scores'][TARGETS[tid]]
                h+=['<details open><summary>'+e(LABELS[a]+' · 目标要点 '+str(target))+'</summary><p>'+e(row['candidate']['answer']).replace('\n','<br>')+'</p>',
                    '<details><summary>Jev原判与全部维度</summary>'+dump(dict(review=row['review'],metrics=row['metrics'],attempts=row['attempts']))+'</details>',
                    '<details><summary>回答、引用及实际证据</summary>'+dump(row['candidate'])+'</details></details>']
            h+=['</article>']
    h+=['</html>'];(dest/'comparison.html').write_text(''.join(h),encoding='utf-8',newline='\n')
    save(dest/'comparison.json',r)
    (dest/'answers-reviews.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in p['records']),encoding='utf-8',newline='\n')
    lines=['# 第16、28题：每种输入5次独立回答','','2026-10-31。20份全新回答；旧单轮不计入。','',*sum(([n,''] for n in r['analyst_notes']),[]),
        '| 题目 | 输入 | 完整 | 部分 | 缺失 | 未知 | 未完整／有效评分 |','| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for s in r['summaries']:lines+=['| '+' | '.join(map(str,[s['task_id'],LABELS[s['arm']],s['complete'],s['partial'],s['missing'],s['unknown'],str(s['incomplete_count'])+'/'+str(s['valid_grades'])]))+' |']
    lines+=['',*LIMITATIONS,'','[20份回答、引用和Jev原判](../data/literature/qa-evaluation/reports/'+TAG+'/comparison.html)。']
    doc.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    save(dest/'publication.json',dict(files={p.name:judge.digest(p) for p in dest.iterdir() if p.is_file()},document_sha256=judge.digest(doc),
        analysis_input_sha256=judge.digest(out/'analysis-input.json'),reporter_sha256=judge.digest(Path(__file__)),reporter_model_calls=0))
    return dict(published_answers=20,summaries=r['summaries'],provider_calls=0)
