"""Publish paired original/rewritten-query answers, retrieval traces and unchanged Jev grades."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_rewrite_only_20261102 import ROOT, OUTPUT, ARMS, plan, check_pair
from report_mineru_current_20261101 import audit_one, paired_ids, usage_summary, quality_cells, pct
from validate_qa_eval import require

PUBLIC = ROOT/'data/literature/qa-evaluation/reports/rewrite-only-20261102'
DOC = ROOT/'docs/QA_REWRITE_ONLY_EVAL_20261102.md'
LABELS = {'original': '原问题检索与重排', 'rewrite': '仅改写检索与重排'}


def source_ids(response):
    return {s['chunk_id'] for e in response['retrieved_evidence']
            for s in (e.get('source_chunks') or [e])}


def score_label(metrics):
    return pct(metrics['point_mean']) if metrics is not None else '评分缺失（不记零）'


def failed_grade_diagnostics(arm, audit):
    root=plan(arm)['study_dir']; study=judge.read_json(root/'study.json'); rows=[]
    for entry in study['jobs']:
        if entry['task_id'] in audit['metrics']:
            continue
        saved=judge.read_json(root/'inputs'/(entry['name']+'.json'))
        attempts=[]
        for path in sorted((root/'records'/entry['name']).glob('*.json')):
            record=judge.read_json(path); error=None
            if record.get('raw_response') is not None:
                try: grading.decode('jev',record['raw_response'],saved['request'],saved['questions'],saved['targets'],saved['state'])
                except (ValueError,KeyError,TypeError,IndexError) as exc: error=str(exc)
            attempts.append(dict(attempt=record['attempt'],status=record['status'],validation_message=error,
                request_sha256=record['request_sha256'],response_sha256=record.get('response_sha256'),
                record_sha256=judge.digest(path),usage=record.get('usage')))
        require(len(attempts)==3 and all(a['status'] not in {'pending','completed'} for a in attempts),
                'Wait for all three invalid/API-failed attempts; do not discard an unattempted score')
        rows.append(dict(arm=arm,task_id=entry['task_id'],attempts=attempts,score=None))
    return rows


def retrieval_diff(original, rewritten):
    diag = rewritten['context_assembly']['query_rewrite']
    require(diag.get('mode') == 'rewrite_only' and len(diag['branches']) == 1, 'Expected one rewritten search')
    require(diag['branches'][0]['branch'] == 'rewritten' and not diag['original_query_searched'], 'Original search is forbidden')
    rank = rewritten['context_assembly']['rerank']
    query = diag['branches'][0]['query']
    require(rank['query_source'] == 'rewritten' and rank['query_text'] == query, 'Rerank must use this exact rewrite')
    original_candidates = {c['chunk_id'] for c in original['context_assembly']['rerank']['candidates']}
    rewritten_candidates = {c['chunk_id'] for c in diag['branches'][0]['candidates']}
    before = source_ids(original); after = source_ids(rewritten)
    original_seeds = [e['chunk_id'] for e in original['retrieval_seed_evidence']]
    rewritten_seeds = [e['chunk_id'] for e in rewritten['retrieval_seed_evidence']]
    novel = rewritten_candidates - original_candidates
    prompt_fields = ('ref','filename','page_start','page_end','chunk_id','text')
    prompt_payload = lambda response: [{k:e[k] for k in prompt_fields} for e in response['retrieved_evidence']]
    return dict(status=diag['status'], queries={'rewritten':query},
        same_candidate_set=original_candidates == rewritten_candidates,
        original_candidate_count=len(original_candidates), rewritten_candidate_count=len(rewritten_candidates),
        shared_candidates=len(original_candidates & rewritten_candidates),
        candidate_union_across_arms=len(original_candidates | rewritten_candidates),
        candidate_count_after_budget=diag['candidate_count_after_budget'],
        rewrite_only_candidate_ids=sorted(novel),
        rewrite_only_selected_ids=sorted(novel & set(rewritten_seeds)),
        rewrite_only_final_source_ids=sorted(novel & after),
        novelty_policy='Compared with the independent original-query control, not a hidden original search in treatment.',
        added_rerank_candidate_ids=sorted(novel),
        removed_rerank_candidate_ids=sorted(original_candidates-rewritten_candidates),
        original_seed_ids=original_seeds, rewritten_seed_ids=rewritten_seeds,
        same_primary_order=original_seeds == rewritten_seeds,
        added_final_source_ids=sorted(after-before), removed_final_source_ids=sorted(before-after),
        same_final_sources=before == after,
        same_initial_generation_input=prompt_payload(original) == prompt_payload(rewritten),
        original_context_chars=sum(len(e['text']) for e in original['retrieved_evidence']),
        rewritten_context_chars=sum(len(e['text']) for e in rewritten['retrieved_evidence']),
        full_query_diagnostics=diag)


def runtime_summary(rows):
    generations=[]; reranks=[]; embeddings=[]; rewrites=[]; durations=[]
    for row in rows:
        r = row['response']
        generations.extend(r['generation_calls']); reranks.extend(r['rerank_calls'])
        embeddings.extend(r.get('query_embedding_calls', [dict(usage=r['embedding_usage'])]))
        rewrites.extend(r.get('query_rewrite_calls', [])); durations.append(row['end_to_end_ms']/1000)
    return dict(questions=len(rows), outcomes=dict(Counter(r['status'] for r in rows)),
        median_end_to_end_seconds=statistics.median(durations), sum_end_to_end_seconds=sum(durations),
        generation=usage_summary(generations), rerank=usage_summary(reranks),
        question_embedding=usage_summary(embeddings), query_rewrite=usage_summary(rewrites),
        currency_costs=dict(generation=None, rerank=None, question_embedding=None, query_rewrite=None),
        returned_generation_models=dict(Counter(c.get('model_info', {}).get('returned_model', 'unknown') for c in generations)),
        returned_rewrite_models=dict(Counter(c.get('returned_model', 'unknown') for c in rewrites)))


def publish():
    require(not PUBLIC.exists() and not DOC.exists(), 'Preserve existing publication')
    check_pair()
    data = {a:audit_one(plan(a)['import_dir'], plan(a)['study_dir']) for a in ARMS}
    for a in ARMS:
        require(bool(data[a]['metrics']), 'No valid Jev scorecards')
        require(data[a]['study']['policy_sha256'] == grading.POLICY_SHA, 'Policy changed')
        require(data[a]['study']['requested_judges']['jev'] == data['original']['study']['requested_judges']['jev'], 'Judge settings changed')
    old, new = data['original'], data['rewrite']
    require(set(old['jobs']) == set(new['jobs']) == {f'PFI2-{i:03}' for i in range(1, 33)}, 'Question set differs')
    for tid in old['jobs']:
        require(old['jobs'][tid]['reference_case'] == new['jobs'][tid]['reference_case'], 'Reference standard differs')
        require(old['jobs'][tid]['task'] == new['jobs'][tid]['task'], 'Task capabilities differ')
    common = paired_ids(new['metrics'], old['metrics']); require(common, 'No common unflagged grades')
    summaries = {a:scoring.summarize([data[a]['metrics'][t] for t in common]) for a in ARMS}
    all_summaries = {a:scoring.summarize([m for m in data[a]['metrics'].values() if not m['reference_concern']]) for a in ARMS}
    responses = {a:{t:judge.read_json(plan(a)['run_dir']/'results'/(t+'.json')) for t in old['jobs']} for a in ARMS}
    changes = {k:[] for k in ['point_wins','point_losses','joint_wins','joint_losses']}
    rows=[]
    for tid in sorted(old['jobs']):
        before=old['metrics'].get(tid); after=new['metrics'].get(tid)
        if tid in common:
            if after['point_mean'] > before['point_mean']: changes['point_wins'].append(tid)
            if after['point_mean'] < before['point_mean']: changes['point_losses'].append(tid)
            if after['all_five_pass'] and not before['all_five_pass']: changes['joint_wins'].append(tid)
            if before['all_five_pass'] and not after['all_five_pass']: changes['joint_losses'].append(tid)
        diff=retrieval_diff(responses['original'][tid]['response'], responses['rewrite'][tid]['response'])
        require(diff['candidate_count_after_budget'] <= 50, 'Merged budget exceeded')
        for a in ARMS:
            response=responses[a][tid]['response']; ctx=response['context_assembly']
            require('answer_guidance' not in response['configuration'], 'Unexpected answer guidance')
            require(ctx['assembly_passes'] == 1 and not ctx['post_context_expansion'], 'Context policy changed')
            require(all(len(e['text']) <= 8000 for e in response['retrieved_evidence']), 'Evidence budget exceeded')
            require(sum(len(e['text']) for e in response['retrieved_evidence']) <= 24000, 'Global budget exceeded')
            if a=='rewrite':
                require(len(response['query_embedding_calls'])==1 and
                    response['query_embedding_calls'][0]['branch']=='rewritten', 'Treatment embedded the original query')
                require(len(response['query_rewrite_calls'])==1, 'Expected one rewrite request')
        case=old['jobs'][tid]['reference_case']
        row=dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
            key_points=case['key_points'],critical_errors=case['critical_errors'],
            capabilities=old['jobs'][tid]['task']['capabilities'],retrieval=diff)
        for a in ARMS:
            row[a]=dict(candidate=data[a]['jobs'][tid]['candidate'],review=data[a]['reviews'].get(tid),metrics=data[a]['metrics'].get(tid))
        rows.append(row)
    retrieval=dict(rewrite_statuses=dict(Counter(r['retrieval']['status'] for r in rows)),
        same_candidate_set=sum(r['retrieval']['same_candidate_set'] for r in rows),
        same_primary_order=sum(r['retrieval']['same_primary_order'] for r in rows),
        same_final_sources=sum(r['retrieval']['same_final_sources'] for r in rows),
        same_initial_generation_input=sum(r['retrieval']['same_initial_generation_input'] for r in rows),
        shared_candidate_occurrences=sum(r['retrieval']['shared_candidates'] for r in rows),
        rewrite_only_candidate_occurrences=sum(len(r['retrieval']['rewrite_only_candidate_ids']) for r in rows),
        rewrite_only_primary_occurrences=sum(len(r['retrieval']['rewrite_only_selected_ids']) for r in rows),
        added_final_source_occurrences=sum(len(r['retrieval']['added_final_source_ids']) for r in rows),
        removed_final_source_occurrences=sum(len(r['retrieval']['removed_final_source_ids']) for r in rows),
        changed_final_source_questions=[r['task_id'] for r in rows if not r['retrieval']['same_final_sources']],
        note='Counts are question/source occurrences, not paper chunks deleted or proof that required evidence improved.')
    retrieval['point_changes_with_same_initial_generation_input'] = [r['task_id'] for r in rows
        if r['task_id'] in common and r['retrieval']['same_initial_generation_input']
        and r['original']['metrics']['point_mean'] != r['rewrite']['metrics']['point_mean']]
    runtime={a:runtime_summary(list(responses[a].values())) for a in ARMS}
    probes=[judge.read_json(p) for p in [OUTPUT/'probe.json', OUTPUT/'probe-utf8.json'] if p.exists()]
    result=dict(version='rewrite-only-paired-20261102',common_task_ids=common,comparison=summaries,
        all_valid_summaries=all_summaries,valid_grades={a:len(data[a]['metrics']) for a in ARMS},
        excluded_task_ids=sorted(set(old['jobs'])-set(common)),changes=changes,retrieval=retrieval,runtime=runtime,
        failed_grades=[row for a in ARMS for row in failed_grade_diagnostics(a,data[a])],
        judge_statuses={a:data[a]['statuses'] for a in ARMS},
        judge_accounting={a:scoring.accounting(data[a]['records'],'jev') for a in ARMS},
        judge=data['original']['study']['requested_judges']['jev'],scoring_policy_sha256=grading.POLICY_SHA,
        probe_accounting=usage_summary([p['call'] for p in probes]),
        probe_note='No extra interface probes in this experiment.',
        comparison_kind='fresh_same_commit_same_corpus_configuration_switch_only',
        source_commit=judge.read_json(plan('original')['run_dir']/'run.json')['source_commit'],
        generated_questions=64,new_luna_calls=0,new_dsh_calls=0,answer_guidance_enabled=False)
    PUBLIC.mkdir(parents=True)
    scoring.save(PUBLIC/'comparison.json',result)
    (PUBLIC/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'audit.json',dict(proofs={a:data[a]['proofs'] for a in ARMS},
        runs={a:judge.digest(plan(a)['run_dir']/'run.json') for a in ARMS},
        studies={a:judge.digest(plan(a)['study_dir']/'study.json') for a in ARMS},
        imports={a:judge.digest(plan(a)['import_dir']/'import.json') for a in ARMS},
        contract_sha256=judge.digest(OUTPUT/'contract.json'),scores_changed_by_exporter=False,report_model_calls=0))
    render(result,rows)
    headers=['版本','共同题','必答要点','事实完全支持','单引有效','引用组完整','边界/2','五项全达标']
    lines=['# MinerU仅改写检索与重排：同期对照评测','', '2026-11-02。两组各32次新答题：对照用原问题检索和重排，试验只用改写检索和重排。最终均回答原问题。只由Jev沿用原五维协议评分，回答指引关闭。','',
        '| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']
    lines += ['| '+LABELS[a]+' | '+' | '.join(quality_cells(summaries[a]))+' |' for a in ARMS]
    lines += ['',f"有效评分：{result['valid_grades']}；共同题排除：{result['excluded_task_ids']}。无效不记零，不计算加权总分。",'',
        f"32题中有{retrieval['same_initial_generation_input']}题首次生成输入完全一致；改写新增独有候选累计{retrieval['rewrite_only_candidate_occurrences']}题次/块，但进入主命中的独有块仅{retrieval['rewrite_only_primary_occurrences']}题次/块。输入一致题的要点变化为{retrieval['point_changes_with_same_initial_generation_input']}，这些变化不能归因于改写补到新证据。",'',
        '## 逐题变化','',*[f"- {k}：{', '.join(v) or '无'}" for k,v in changes.items()],
        '', '## 无效评分','', '```json',json.dumps(result['failed_grades'],ensure_ascii=False,indent=2),'```',
        '评分格式、一致性校验或API失败均不代表回答得零分；原因与尝试见上。每份缺失评分已尝试3次并封存，不改裁判原判；这些题的两组回答仍完整列出。',
        '', '## 检索实际变化','', '```json',json.dumps(retrieval,ensure_ascii=False,indent=2),'```','',
        '候选、主命中和最终原文是三个阶段；新增候选不等于补到必需证据。不同原文块的数量按题累计，同一块在多题出现会重复计数。新增/独有块由独立对照组候选与试验组候选比较计算，试验内部没有隐藏的原问题检索。完整改写、候选预算、增减块和逐题回答在HTML与JSONL。','',
        '## 耗时和用量','']
    for a in ARMS:
        lines += [f"- {LABELS[a]}：端到端中位{runtime[a]['median_end_to_end_seconds']:.2f}秒/题。",
            f"  - 各环节：{judge.encode(runtime[a])}",f"  - Jev：{judge.encode(result['judge_accounting'][a])}"]
    lines += ['- 本轮无额外付费接口探测。推理Token已包含在生成Token内；每组每题各一次问题Embedding。未返回的供应商货币费用为未知，不能当成免费。','',
        '## 控制变量与限制','',f"答题源提交{result['source_commit']}，两组同代码、同113块索引及原PDF，唯一配置策略差异为是否启用仅改写检索和重排。两组新答题，不复用历史答案。本轮同时改变检索和重排输入，不能区分两项各自贡献。每题独立进程，仅输入问题与论文库，不包含标准答案；每个Jev请求独立组装，不包含另一组答案或旧评分。",'',
        '两组并行启动、各自按题序执行；网络和远端模型随机性无法冻结。一轮开发集结果不能证明稳定性或新论文泛化。单题变化还需结合候选/最终证据和重复实验判断，不能只看得分归因。原DSH答案仅为兼容旧导入格式而复制，本轮没有新DSH/Luna调用。网站默认配置与服务器未切换。','',
        '[方法](QA_REWRITE_ONLY_METHOD_20261102.md)',
        '[32题两组答案、Jev原判与检索变化](../data/literature/qa-evaluation/reports/rewrite-only-20261102/comparison.html)']
    DOC.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    scoring.save(PUBLIC/'publication.json',dict(files={p.name:judge.digest(p) for p in PUBLIC.iterdir() if p.is_file()},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),report_model_calls=0))
    return {k:result[k] for k in ['comparison','changes','retrieval','runtime','judge_accounting']}


def render(result,rows):
    esc=lambda v:escape(str(v),quote=True)
    table='<table><tr>'+''.join('<th>'+s+'</th>' for s in ['版本','题数','要点','事实支持','单引','引用组','边界/2','全达标'])+'</tr>'
    table+=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [LABELS[a],*quality_cells(result['comparison'][a])])+'</tr>' for a in ARMS)+'</table>'
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MinerU仅改写检索与重排同期对照</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui}main{max-width:1300px;margin:30px auto;padding:0 20px}article,details{background:white;border:1px solid #dce5ef;border-radius:10px;padding:18px;margin:15px 0}table{width:100%;border-collapse:collapse}td,th{padding:9px;text-align:left;border-bottom:1px solid #e6edf4}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px}summary{cursor:pointer;font-weight:600}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-width:0}.pair section{min-width:0}@media(max-width:800px){.pair{display:block}table{font-size:12px}td,th{padding:4px}}</style><main>',
        '<h1>MinerU仅改写检索与重排：同期对照</h1><p>2026-11-02 · 两组各32次独立新答题 · Jev原五维 · 回答指引关闭</p><article>'+table+
        '<p>试验只用改写进行一次检索和重排，最终回答原问题。无原问题检索或RRF，不计算加权总分。一轮结果仍包含回答和裁判的随机波动。</p></article>',
        '<details><summary>检索变化、用量与费用</summary><pre>'+esc(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>']
    for row in rows:
        html += ['<details id="'+esc(row['task_id'])+'"><summary>'+esc(row['task_id']+' · '+row['question'])+'</summary>',
            '<h3>参考答案与评分准则</h3><pre>'+esc(json.dumps({k:row[k] for k in ['reference_answer','key_points','critical_errors','capabilities']},ensure_ascii=False,indent=2))+'</pre>',
            '<h3>改写与检索变化</h3><pre>'+esc(json.dumps({k:v for k,v in row['retrieval'].items() if k!='full_query_diagnostics'},ensure_ascii=False,indent=2))+'</pre><div class="pair">']
        for a in ARMS:
            d=row[a]
            html += ['<section><h3>'+LABELS[a]+' · 要点'+score_label(d['metrics'])+'</h3><pre>'+esc(d['candidate']['answer'])+'</pre>',
                '<details><summary>Jev原判、五维指标与引用原文</summary><pre>'+esc(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details></section>']
        html += ['</div><details><summary>改写单路候选与重排输入完整记录</summary><pre>'+esc(json.dumps(row['retrieval']['full_query_diagnostics'],ensure_ascii=False,indent=2))+'</pre></details></details>']
    html += ['</main></html>']
    (PUBLIC/'comparison.html').write_text(''.join(html),encoding='utf-8',newline='\n')


if __name__ == '__main__': print(json.dumps(publish(),ensure_ascii=False))
