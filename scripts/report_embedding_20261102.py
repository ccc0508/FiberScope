"""Publish frozen shared-query BGE/Qwen answers, evidence coverage and Jev scores."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_embedding_20261102 import ROOT,OUTPUT,ARMS,CACHE,plan,check_pair
from report_mineru_current_20261101 import audit_one,paired_ids,usage_summary,quality_cells,pct
from report_query_rewrite_20261102 import source_ids,score_label
from qa_retrieval_sources import load_library
from qa_retrieval_alignment import span_coverage
from validate_qa_eval import require

PUBLIC=ROOT/'data/literature/qa-evaluation/reports/embedding-20261102'
DOC=ROOT/'docs/QA_EMBEDDING_EVAL_20261102.md'
LABELS={'bge':'BGE-M3 · 1024维','qwen':'Qwen3-VL · 2560维（文字输入）'}


def retrieval_diff(bge,qwen):
    def stages(r):
        return dict(candidates={c['chunk_id'] for c in r['context_assembly']['rerank']['candidates']},
            primary={e['chunk_id'] for e in r['retrieval_seed_evidence']},final=source_ids(r))
    before,after=stages(bge),stages(qwen)
    query_rows={a:r['context_assembly']['query_rewrite'] for a,r in [('bge',bge),('qwen',qwen)]}
    queries={a:{b['branch']:b['query'] for b in d['branches']} for a,d in query_rows.items()}
    require(queries['bge']==queries['qwen'],'Different queries would confound embedding comparison')
    fields=('ref','filename','page_start','page_end','chunk_id','text')
    prompt=lambda r:[{k:e[k] for k in fields} for e in r['retrieved_evidence']]
    return dict(queries=queries['bge'],queries_equal=True,
        query_statuses={a:d['status'] for a,d in query_rows.items()},
        stages={stage:dict(bge_ids=sorted(before[stage]),qwen_ids=sorted(after[stage]),
            added_in_qwen=sorted(after[stage]-before[stage]),removed_in_qwen=sorted(before[stage]-after[stage]),
            same_set=before[stage]==after[stage]) for stage in before},
        same_primary_order=[e['chunk_id'] for e in bge['retrieval_seed_evidence']]==[e['chunk_id'] for e in qwen['retrieval_seed_evidence']],
        same_initial_generation_input=prompt(bge)==prompt(qwen),
        context_chars={a:sum(len(e['text']) for e in r['retrieved_evidence']) for a,r in [('bge',bge),('qwen',qwen)]})


def reference_coverage(case,capabilities,response,library):
    wanted=sorted({eid for point in case['key_points'] if not point['optional'] and point['capability'] in capabilities
                   for eid in point['evidence_ids']})
    stage_ids=dict(candidates=[c['chunk_id'] for c in response['context_assembly']['rerank']['candidates']],
        primary=[e['chunk_id'] for e in response['retrieval_seed_evidence']],final=sorted(source_ids(response)))
    checks=[]
    for eid in wanted:
        target=library['alignment'][eid]
        checks.append(dict(evidence_id=eid,alignment_status=target['status'],
            eligible_for_summary=target['status']=='located',
            stages={stage:span_coverage(target,ids,library['chunk_spans']) for stage,ids in stage_ids.items()}))
    return checks


def summarize_coverage(rows):
    checks=[c for row in rows for c in row if c['eligible_for_summary']]
    return dict(exact_reference_occurrences=len(checks),
        stages={stage:scoring.fraction(sum(c['stages'][stage]['status']=='complete' for c in checks),len(checks))
                for stage in ['candidates','primary','final']},
        excluded_occurrences=sum(not c['eligible_for_summary'] for row in rows for c in row),
        scope='Exact aligned reference source-interval coverage, not semantic evidence sufficiency or whole-benchmark recall.')


def runtime(rows):
    embedding=[c for row in rows for c in row['response']['query_embedding_calls']]
    replay=[c for row in rows for c in row['response']['query_rewrite_calls']]
    require(all(c['api_calls']==0 and c['status']=='replayed_for_controlled_evaluation' for c in replay),'Rewrite was not replayed')
    timing=[sum(c['latency_ms'] for c in row['response']['query_embedding_calls']) for row in rows]
    return dict(questions=len(rows),outcomes=dict(Counter(row['status'] for row in rows)),
        median_end_to_end_seconds=statistics.median(row['end_to_end_ms']/1000 for row in rows),
        median_question_embedding_seconds=statistics.median(timing)/1000,
        question_embedding=usage_summary(embedding),
        image_tokens=sum((c.get('usage') or {}).get('image_tokens',0) for c in embedding),
        generation=usage_summary([c for row in rows for c in row['response']['generation_calls']]),
        rerank=usage_summary([c for row in rows for c in row['response']['rerank_calls']]),
        cached_rewrite_replays=len(replay),rewrite_api_calls_during_answers=0,
        monetary_costs=dict(embedding=None,generation=None,rerank=None),
        timing_note='End-to-end excludes offline shared-query preparation; not comparable to live-rewrite historical timing.')


def failed_grades(arm,audit):
    root=plan(arm)['study_dir'];rows=[];study=judge.read_json(root/'study.json')
    for entry in study['jobs']:
        if entry['task_id'] in audit['metrics']:continue
        saved=judge.read_json(root/'inputs'/(entry['name']+'.json'));attempts=[]
        for p in sorted((root/'records'/entry['name']).glob('*.json')):
            record=judge.read_json(p);reason=None
            if record.get('raw_response') is not None:
                try:grading.decode('jev',record['raw_response'],saved['request'],saved['questions'],saved['targets'],saved['state'])
                except (ValueError,KeyError,TypeError,IndexError) as error:reason=str(error)
            attempts.append(dict(attempt=record['attempt'],status=record['status'],validation_message=reason,
                record_sha256=judge.digest(p),usage=record.get('usage')))
        require(len(attempts)==3 and all(a['status'] not in {'pending','completed'} for a in attempts),'Wait for invalid grading attempts')
        rows.append(dict(arm=arm,task_id=entry['task_id'],attempts=attempts,score=None))
    return rows


def interpret(rows,common,summary):
    """Describe this frozen run; these observations never change Jev's decisions."""
    selected=[r for r in rows if r['task_id'] in common]
    refusal_cases=[r for r in selected if r['bge']['answer_runtime']['reason_code']=='citation_validation_failed']
    contribution=sum(r['qwen']['metrics']['point_mean']-r['bge']['metrics']['point_mean'] for r in refusal_cases)/len(common)
    delta=summary['qwen']['point_macro_average']-summary['bge']['point_macro_average']
    observations={
        'PFI2-004':'首次输入完全相同。两版均给63/57 °SR并列作用力条件；Jev把Qwen的条件限制要点评为部分覆盖。属于措辞/裁判敏感性，不能归因于新检索。',
        'PFI2-015':'两版都找到纤维长度变化及较低作用力的解释，但都未明确说不能全部归因于浆种；Jev对这项限制分别判缺失/部分。没有证明补到了新的关键事实。',
        'PFI2-020':'首次输入完全相同，要点均全覆盖。Qwen回答的陈述及引用组获全支持；BGE多写的一项free OH解释被判部分支持。',
        'PFI2-024':'首次输入完全相同，要点均全覆盖。BGE有一条额外机制陈述被判部分支持；Qwen的表达全部获支持，属于生成表述差异。',
        'PFI2-025':'两版都拿到补充表线索。Qwen列了Table S1与定性趋势，却没有明确说明当前证据缺少8000转的精确BET值，必答点从1降为0；并非提供了错误数值。',
        'PFI2-026':'两版均无逐次重复实验数据。Qwen明确限定为所给证据未提供，获得完整要点；BGE措辞与引用组获部分支持。未证明原始数据召回增加。',
        'PFI2-027':'首次输入完全相同。BGE两次生成后引用校验失败并返回统一拒答；Qwen回答可答部分并声明耐破/撕裂数据缺失。不能把此增分算作召回收益。',
        'PFI2-032':'BGE两次生成后引用校验失败；Qwen纠正0.919/0.925的对象并给正文0.912/0.889，但仍漏摘要0.888及冲突，只获部分要点。不能视为已解决冲突检索。'}
    return dict(source='Report interpretation of saved answers/runtime and original Jev labels; not Jev-generated rationale.',
        mainline=f'共同{len(common)}题，要点提高{delta*100:.2f}个百分点；五项全达标BGE为{summary["bge"]["all_five_pass"]}题，Qwen为{summary["qwen"]["all_five_pass"]}题。本轮略好，但未证明文字检索稳定领先。',
        baseline_citation_failure_task_ids=[r['task_id'] for r in refusal_cases],
        point_delta_decomposition=dict(total_percentage_points=delta*100,
            baseline_citation_failure_questions_percentage_points=contribution*100,
            other_questions_percentage_points=(delta-contribution)*100,
            note='Arithmetic decomposition, not causal attribution; keep all these questions in the primary paired result.'),
        cases=[dict(task_id=r['task_id'],note=observations[r['task_id']]) for r in selected if r['task_id'] in observations],
        next_step='保留候选，不据此替换网站默认版本。先补图像题单独核验多模态收益；文字部分优先定位引用校验拒答、缺数据声明及摘要/正文冲突漏检。')


def publish():
    require(not PUBLIC.exists() and not DOC.exists(),'Preserve existing publication')
    runs=check_pair();data={a:audit_one(plan(a)['import_dir'],plan(a)['study_dir']) for a in ARMS}
    for a in ARMS:
        require(bool(data[a]['metrics']),'No valid scores')
        require(data[a]['study']['policy_sha256']==grading.POLICY_SHA,'Jev rules changed')
        require(data[a]['study']['requested_judges']['jev']==data['bge']['study']['requested_judges']['jev'],'Jev settings differ')
    common=paired_ids(data['bge']['metrics'],data['qwen']['metrics']);require(common,'No common unflagged scores')
    summary={a:scoring.summarize([data[a]['metrics'][t] for t in common]) for a in ARMS}
    all_summary={a:scoring.summarize([m for m in data[a]['metrics'].values() if not m['reference_concern']]) for a in ARMS}
    task_ids=sorted(data['bge']['jobs']);require(set(task_ids)==set(data['qwen']['jobs']) and len(task_ids)==32,'Wrong task set')
    responses={a:{tid:judge.read_json(plan(a)['run_dir']/'results'/(tid+'.json')) for tid in task_ids} for a in ARMS}
    evidence=judge.read_json(plan('bge')['run_dir']/'dataset/evidence.json')
    library=load_library(plan('bge')['run_dir']/'library',evidence)
    changes={k:[] for k in ['point_wins','point_losses','joint_wins','joint_losses']};rows=[]
    for tid in task_ids:
        jobs={a:data[a]['jobs'][tid] for a in ARMS}
        require(jobs['bge']['reference_case']==jobs['qwen']['reference_case'] and jobs['bge']['task']==jobs['qwen']['task'],'Reference case changed')
        case=jobs['bge']['reference_case'];caps=jobs['bge']['task']['capabilities']
        diff=retrieval_diff(responses['bge'][tid]['response'],responses['qwen'][tid]['response'])
        row=dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],key_points=case['key_points'],
            critical_errors=case['critical_errors'],capabilities=caps,retrieval=diff)
        for a in ARMS:
            r=responses[a][tid]['response'];cfg=r['configuration'];ctx=r['context_assembly']
            require('visual_retrieval' not in cfg and 'answer_guidance' not in cfg,'Images/guidance enabled')
            require(all(not e.get('visual_assets') for e in r['retrieved_evidence']),'Unexpected image payload')
            require(ctx['assembly_passes']==1 and not ctx['post_context_expansion'],'Context policy changed')
            require(len(ctx['rerank']['candidates'])<=50 and len(r['retrieval_seed_evidence'])<=8,'Retrieval budget changed')
            require(all(len(e['text'])<=8000 for e in r['retrieved_evidence']) and diff['context_chars'][a]<=24000,'Character budget exceeded')
            row[a]=dict(candidate=jobs[a]['candidate'],review=data[a]['reviews'].get(tid),metrics=data[a]['metrics'].get(tid),
                answer_runtime=dict(status=r['status'],reason_code=r.get('reason_code'),
                    generation_calls=len(r['generation_calls']),
                    generation_outcomes=[c.get('outcome') for c in r['generation_calls']]),
                reference_coverage=reference_coverage(case,caps,r,library))
        if tid in common:
            b,q=row['bge']['metrics'],row['qwen']['metrics']
            if q['point_mean']>b['point_mean']:changes['point_wins'].append(tid)
            if q['point_mean']<b['point_mean']:changes['point_losses'].append(tid)
            if q['all_five_pass'] and not b['all_five_pass']:changes['joint_wins'].append(tid)
            if b['all_five_pass'] and not q['all_five_pass']:changes['joint_losses'].append(tid)
        rows.append(row)
    retrieval=dict(shared_queries_identical=all(r['retrieval']['queries_equal'] for r in rows),
        same_primary_order=sum(r['retrieval']['same_primary_order'] for r in rows),
        same_initial_generation_input=sum(r['retrieval']['same_initial_generation_input'] for r in rows),
        stage_changes={stage:dict(same_set=sum(r['retrieval']['stages'][stage]['same_set'] for r in rows),
            added_occurrences=sum(len(r['retrieval']['stages'][stage]['added_in_qwen']) for r in rows),
            removed_occurrences=sum(len(r['retrieval']['stages'][stage]['removed_in_qwen']) for r in rows))
            for stage in ['candidates','primary','final']},
        point_changes_with_same_initial_input=[r['task_id'] for r in rows if r['task_id'] in common and
            r['retrieval']['same_initial_generation_input'] and r['bge']['metrics']['point_mean']!=r['qwen']['metrics']['point_mean']])
    prepared=judge.read_json(CACHE);calls=[r['provider_call'] for r in prepared['queries'].values()]
    result=dict(version='text-embedding-shared-query-eval-20261102',source_commit=runs[0]['source_commit'],
        comparison=summary,all_valid_summaries=all_summary,common_task_ids=common,
        valid_grades={a:len(data[a]['metrics']) for a in ARMS},excluded_task_ids=sorted(set(task_ids)-set(common)),
        failed_grades=[r for a in ARMS for r in failed_grades(a,data[a])],changes=changes,retrieval=retrieval,
        reference_coverage={a:summarize_coverage([r[a]['reference_coverage'] for r in rows]) for a in ARMS},
        alignment_statuses=dict(Counter(a['status'] for a in library['alignment'].values())),
        runtime={a:runtime(list(responses[a].values())) for a in ARMS},
        shared_rewrite_preparation=dict(usage=usage_summary(calls),sum_request_seconds=sum(c['latency_ms'] for c in calls)/1000,
            median_request_seconds=statistics.median(c['latency_ms'] for c in calls)/1000,currency_cost=None,
            statuses=dict(Counter(r['status'] for r in prepared['queries'].values())),cache_sha256=judge.digest(CACHE)),
        judge_accounting={a:scoring.accounting(data[a]['records'],'jev') for a in ARMS},
        judge=data['bge']['study']['requested_judges']['jev'],policy_sha256=grading.POLICY_SHA,
        images_enabled=False,generated_questions=64,new_luna_calls=0,new_dsh_calls=0,
        comparison_kind='fresh_answers_same_scientific_sources_shared_queries_different_embedding_route',
        caveats=['One paper and 32 development questions; one generation and one valid judge score per arm.',
            '0.35 is inherited and uncalibrated for Qwen; this compares current settings rather than tuned model ceilings.',
            'Exact reference-interval coverage excludes unresolved/review-required alignment and is not a semantic answer score.',
            'No image retrieval or image answering evaluated; production candidate configuration unchanged.'])
    result['interpretation']=interpret(rows,common,summary)
    PUBLIC.mkdir(parents=True)
    scoring.save(PUBLIC/'comparison.json',result)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'audit.json',dict(proofs={a:data[a]['proofs'] for a in ARMS},
        runs={a:judge.digest(plan(a)['run_dir']/'run.json') for a in ARMS},studies={a:judge.digest(plan(a)['study_dir']/'study.json') for a in ARMS},
        contract_sha256=judge.digest(OUTPUT/'contract.json'),shared_query_cache_sha256=judge.digest(CACHE),
        alignment=library['alignment'],scores_changed_by_exporter=False,report_model_calls=0))
    render(result,rows)
    headers=['版本','共同题','必答要点','事实支持','单引有效','引用组完整','边界/2','全达标']
    lines=['# 新Embedding模型：BGE与Qwen控制变量评测','',
        '2026-11-02。只比较文字Embedding，图片关闭；两组复用相同检索改写，各新答32题，Jev沿用原五维协议。','',
        '| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']
    lines+=['| '+LABELS[a]+' | '+' | '.join(quality_cells(summary[a]))+' |' for a in ARMS]
    lines+=['',f"有效评分：{result['valid_grades']}；共同题排除{result['excluded_task_ids']}。无效评分不记零，不算加权总分。",'',
        '## 结果解读','',result['interpretation']['mainline'],'',
        '以下为报告对保存的回答、运行诊断及Jev原判的解读，不是Jev生成的文字理由，也不更改模型分数。','',
        *[f"- {case['task_id']}：{case['note']}" for case in result['interpretation']['cases']],
        '',f"要点差异的算术分解：{judge.encode(result['interpretation']['point_delta_decomposition'])}",
        '第27/32题对总差异贡献较大，但含生成/校验失败，不能据此认定检索能力提高。主表仍保留这两题，没有事后删题抬分。','',
        result['interpretation']['next_step'],'',
        '## 逐题变化','',*[f"- {k}：{', '.join(v) or '无'}" for k,v in changes.items()],
        '',f"32题中{retrieval['same_initial_generation_input']}题首次生成输入完全相同，这类题的分数变化不能归因于Embedding补到了新材料。",'',
        '## 检索变化与参考原文覆盖','', '```json',json.dumps(dict(retrieval=retrieval,reference_coverage=result['reference_coverage'],alignment_statuses=result['alignment_statuses']),ensure_ascii=False,indent=2),'```','',
        '覆盖率只统计在MinerU源文本中精确对齐的参考原文区间，按每题所需参考片段计数。近似/待复核和未定位片段排除且不记零。这是原文位置覆盖诊断，不等于证据已足够回答，也不代表全部题目的语义召回率。新增/删除块按题累计，不是删改数据库原文。','',
        '## 用量与耗时','',f"共享改写准备：{judge.encode(result['shared_rewrite_preparation'])}"]
    for a in ARMS:
        rt=result['runtime'][a]
        lines += [f"- {LABELS[a]}：端到端中位{rt['median_end_to_end_seconds']:.2f}秒/题，问题Embedding合计中位{rt['median_question_embedding_seconds']:.3f}秒/题。",
            f"  - 运行用量：{judge.encode(rt)}",f"  - Jev评分：{judge.encode(result['judge_accounting'][a])}"]
    lines+=['','端到端不含预先生成改写的耗时；改写一次计费、两组回放不再计费。不要与之前实时改写的耗时直接比较。推理Token已含在生成Token内，未返回金额保持未知。','',
        '## 无效评分','', '```json',json.dumps(result['failed_grades'],ensure_ascii=False,indent=2),'```','',
        '本轮未重复入库Embedding；这里的Token仅统计新问题与本轮运行。此前索引重建的用量不混入本轮答题成本。','',
        '## 结论的适用范围','',
        '本轮比较同一113块、20条表格行、相同query和原BGE重排下的模型替换，不包含图片。仅一轮开发集结果，不证明稳定性或新论文泛化；0.35未针对Qwen校准，不代表两模型最佳能力。两组均新答、独立进程，裁判不看另一组答案、模型身份或旧分数。网站和启用图片的MinerU候选配置均未切换。','',
        '[方法](QA_EMBEDDING_METHOD_20261102.md)',
        '[32题逐题回答、Jev原判与检索对照](../data/literature/qa-evaluation/reports/embedding-20261102/comparison.html)']
    DOC.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir() if p.is_file()},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),report_model_calls=0))
    return {k:result[k] for k in ['comparison','changes','retrieval','reference_coverage','runtime','judge_accounting']}


def render(result,rows):
    esc=lambda v:escape(str(v),quote=True)
    table='<table><tr>'+''.join('<th>'+s+'</th>' for s in ['版本','题数','要点','事实支持','单引','引用组','边界/2','全达标'])+'</tr>'
    table+=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [LABELS[a],*quality_cells(result['comparison'][a])])+'</tr>' for a in ARMS)+'</table>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BGE与Qwen Embedding评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui}main{max-width:1300px;margin:30px auto;padding:0 20px}article,details{background:white;border:1px solid #dce5ef;border-radius:10px;padding:18px;margin:15px 0}table{width:100%;border-collapse:collapse}td,th{padding:9px;text-align:left;border-bottom:1px solid #e6edf4}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px}summary{cursor:pointer;font-weight:600}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair section{min-width:0}@media(max-width:800px){.pair{display:block}table{font-size:12px}td,th{padding:4px}}</style><main>',
        '<h1>BGE-M3与Qwen3-VL-Embedding：文字检索对照</h1><p>2026-11-02 · 图片关闭 · 相同原问题与改写 · 原问题重排 · 各32次新答题 · Jev五维</p><article>'+table+
        '<p>不计算加权总分；共享改写只生成一次，不让改写随机性混入模型替换。0.35阈值未专门校准；本轮不评价图片能力或新论文泛化。</p></article>',
        '<article><h2>结果解读</h2><p>'+esc(result['interpretation']['mainline'])+'</p><p>以下是报告解读，不是Jev生成的文字理由，未改变原分数。</p><ul>'+''.join(
            '<li><a href="#'+esc(c['task_id'])+'">'+esc(c['task_id'])+'</a>：'+esc(c['note'])+'</li>' for c in result['interpretation']['cases'])+
        '</ul><p>'+esc(result['interpretation']['next_step'])+'</p></article>',
        '<details><summary>覆盖诊断、用量与排除说明</summary><pre>'+esc(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>']
    for row in rows:
        parts+=['<details id="'+esc(row['task_id'])+'"><summary>'+esc(row['task_id']+' · '+row['question'])+'</summary>',
            '<h3>参考答案与规则</h3><pre>'+esc(json.dumps({k:row[k] for k in ['reference_answer','key_points','critical_errors','capabilities']},ensure_ascii=False,indent=2))+'</pre>',
            '<details><summary>共享查询及候选、主命中、最终原文变化</summary><pre>'+esc(json.dumps(row['retrieval'],ensure_ascii=False,indent=2))+'</pre></details><div class="pair">']
        for a in ARMS:
            d=row[a];parts+=['<section><h3>'+LABELS[a]+' · 要点'+score_label(d['metrics'])+'</h3><pre>'+esc(d['candidate']['answer'])+'</pre>',
                '<details><summary>Jev原判、引用和参考覆盖</summary><pre>'+esc(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details></section>']
        parts+=['</div></details>']
    parts+=['</main></html>'];(PUBLIC/'comparison.html').write_text(''.join(parts),encoding='utf-8',newline='\n')


if __name__=='__main__':print(json.dumps(publish(),ensure_ascii=False))
