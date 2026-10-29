"""One-run analysis: reuse identical DSH grades and compare frozen RAG revisions."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import html
import json
from pathlib import Path
import shutil
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as reporting
from validate_qa_eval import require

PRIVATE = ROOT / '.rag-data/evaluations'
OLD_IMPORT = PRIVATE / 'dsh-rag-five-import-20261028-r1'
OLD_STUDY = PRIVATE / 'dsh-rag-five-judges-20261028-r1'
NEW_IMPORT = PRIVATE / 'context-v1-five-import-20261029-r1'
NEW_STUDY = PRIVATE / 'context-v1-five-judges-20261029-r1'
RUN = PRIVATE / 'pfi-context-v1-20261029-r1'
OUTPUT = ROOT / 'data/literature/qa-evaluation/reports/context-v1-full-20261029'
DOC = ROOT / 'docs/QA_CONTEXT_V1_REPORT_20261029.md'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def reuse():
    # Audit the old responses before copying any of them. Every attempt, not only
    # valid results, is retained. This is archival reuse, not a new provider call.
    old = reporting.audit(OLD_IMPORT, OLD_STUDY)
    old_study = old[2]
    new_study = judge.read_json(NEW_STUDY / 'study.json')
    require(new_study['policy_sha256'] == old_study['policy_sha256'], 'Scoring policy changed')
    require(new_study['requested_judges'] == old_study['requested_judges'], 'Judge configuration changed')
    source_entries = {(e['judge'], e['task_id']): e for e in old_study['jobs'] if e['system'] == 'dsh'}
    planned = []
    for entry in new_study['jobs']:
        if entry['system'] != 'dsh':
            continue
        source = source_entries[(entry['judge'], entry['task_id'])]
        a = OLD_STUDY / 'inputs' / (source['name'] + '.json')
        b = NEW_STUDY / 'inputs' / (entry['name'] + '.json')
        require(a.read_bytes() == b.read_bytes(), 'DSH scientific input is not byte-identical')
        require(source['request_sha256'] == entry['request_sha256'], 'DSH request changed')
        target = NEW_STUDY / 'records' / entry['name']
        require(not target.exists(), 'Reuse destination already exists')
        files = sorted((OLD_STUDY / 'records' / source['name']).glob('*.json'), key=lambda p: int(p.stem))
        require(files, 'Original DSH grading records missing')
        planned.append((entry, files, target))
    require(len(planned) == 64, 'Expected exactly 64 reused DSH judge jobs')
    manifest = dict(source_study_sha256=judge.digest(OLD_STUDY / 'study.json'),
                    target_study_sha256=judge.digest(NEW_STUDY / 'study.json'),
                    identical_inputs_verified=True, new_provider_calls=0, records=[])
    for entry, files, target in planned:
        target.mkdir()
        for source in files:
            destination = target / source.name
            shutil.copyfile(source, destination)
            manifest['records'].append(dict(job=entry['name'], judge=entry['judge'], task_id=entry['task_id'],
                relative_path=destination.relative_to(NEW_STUDY).as_posix(), sha256=judge.digest(destination),
                source_relative_path=source.relative_to(OLD_STUDY).as_posix()))
    save(NEW_STUDY / 'reused-dsh-records.json', manifest)
    print(json.dumps(dict(reused_jobs=64, reused_attempts=len(manifest['records']), new_provider_calls=0)))


def runtime():
    run = judge.read_json(RUN / 'run.json')
    rows = []
    for task in run['tasks']:
        path = RUN / 'results' / (task['id'] + '.json')
        row = judge.read_json(path)
        require(judge.digest(path) == judge.read_json(RUN / 'attempts' / (task['id'] + '.json'))['result_sha256'], 'Answer changed')
        response = row.get('response') or {}
        rows.append(dict(task_id=task['id'], status=row['status'], elapsed_ms=row['end_to_end_ms'],
            core_ms=response.get('latency_ms'), generation_calls=response.get('generation_calls', []),
            embedding_usage=response.get('embedding_usage'), context=response.get('context_assembly', {}),
            result_sha256=judge.digest(path)))
    calls = [c for row in rows for c in row['generation_calls']]
    tokens = Counter()
    for call in calls:
        for key, value in (call.get('usage') or {}).items():
            if type(value) is int:
                tokens[key] += value
    return dict(questions=len(rows), outcomes=dict(Counter(r['status'] for r in rows)),
        generation_calls=len(calls), generation_known_tokens=dict(tokens),
        generation_usage_unknown_calls=sum(c.get('usage') is None for c in calls),
        embedding_known_tokens=sum((r['embedding_usage'] or {}).get('total_tokens', 0) for r in rows),
        embedding_usage_unknown_questions=sum(r['embedding_usage'] is None for r in rows),
        median_end_to_end_seconds=statistics.median(r['elapsed_ms'] for r in rows) / 1000,
        total_sequential_seconds=sum(r['elapsed_ms'] for r in rows) / 1000,
        median_context_chars=statistics.median(r['context'].get('context_chars', 0) for r in rows),
        budget_limited_questions=[r['task_id'] for r in rows if r['context'].get('budget_limited')],
        actual_billing_usd=None, notes='Reasoning tokens are a subset of completion tokens, not additional tokens.',
        per_question=rows)


def report(refresh=False):
    if refresh:
        publication=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/name)==checksum for name,checksum in publication['files'].items()
                    if name!='publication.json'), 'Published report bytes changed')
        require(judge.digest(DOC)==publication['document_sha256'], 'Published document changed')
    else:
        require(not OUTPUT.exists() and not DOC.exists(), 'Report destination exists')
    old = reporting.audit(OLD_IMPORT, OLD_STUDY)
    new = reporting.audit(NEW_IMPORT, NEW_STUDY)
    reuse_manifest = judge.read_json(NEW_STUDY / 'reused-dsh-records.json')
    require(reuse_manifest['target_study_sha256'] == judge.digest(NEW_STUDY / 'study.json'), 'Reuse target changed')
    for row in reuse_manifest['records']:
        require(judge.digest(NEW_STUDY / row['relative_path']) == row['sha256'] == judge.digest(OLD_STUDY / row['source_relative_path']), 'Reused attempt changed')
    old_meta, old_jobs, _, old_reviews, _, _, old_proofs = old
    new_meta, new_jobs, new_study, new_reviews, new_records, statuses, new_proofs = new
    require(all(s != 'pending' for _, _, s in statuses), 'Wait for pending judge calls')
    require(old_meta['pdf_sha256'] == new_meta['pdf_sha256'], 'Original PDF changed')
    require(old_meta['dataset_manifest_sha256'] == new_meta['dataset_manifest_sha256'], 'Frozen dataset changed')
    old_by = {(j['system'], j['task_id']): j for j in old_jobs}
    new_by = {(j['system'], j['task_id']): j for j in new_jobs}
    tids = sorted({j['task_id'] for j in new_jobs})
    metrics, reviews, jobs = {}, {}, {}
    for tid in tids:
        require(old_by[('rag', tid)]['reference_case'] == new_by[('rag', tid)]['reference_case'], 'Reference standard changed')
        require(old_by[('dsh', tid)] == new_by[('dsh', tid)], 'Archived DSH answer changed')
        for system, source_jobs, source_reviews, source_system in [
            ('old_rag', old_by, old_reviews, 'rag'), ('context_rag', new_by, new_reviews, 'rag'),
            ('dsh', old_by, old_reviews, 'dsh')]:
            job = source_jobs[(source_system, tid)]
            jobs[(system, tid)] = job
            for kind in ['luna', 'jev']:
                review = source_reviews.get((kind, source_system, tid))
                if review is not None:
                    reviews[(kind, system, tid)] = review
                    metrics[(kind, system, tid)] = reporting.metrics(review, job['reference_case'], job['task']['capabilities'])
    systems = ['old_rag', 'context_rag', 'dsh']
    usable = lambda kind, names, tid: all((kind, s, tid) in metrics and not metrics[(kind, s, tid)]['reference_concern'] for s in names)
    common = [tid for tid in tids if all(usable(k, systems, tid) for k in ['luna', 'jev'])]
    require(common, 'No common fully matched cases')
    summary = {k: {s: reporting.summarize([metrics[(k, s, t)] for t in common]) for s in systems} for k in ['luna', 'jev']}
    paired = {}
    for kind in ['luna', 'jev']:
        chosen = [t for t in tids if usable(kind, ['old_rag', 'context_rag'], t)]
        paired[kind] = dict(task_ids=chosen, scores={s: reporting.summarize([metrics[(kind, s, t)] for t in chosen]) for s in ['old_rag', 'context_rag']},
            point_wins=[t for t in chosen if metrics[(kind, 'context_rag', t)]['point_mean'] > metrics[(kind, 'old_rag', t)]['point_mean']],
            point_losses=[t for t in chosen if metrics[(kind, 'context_rag', t)]['point_mean'] < metrics[(kind, 'old_rag', t)]['point_mean']])
    record_names = {e['name'] for e in new_study['jobs'] if e['system'] == 'rag'}
    current_calls = {kind: [judge.read_json(p) for name in record_names if name.startswith(kind + '-')
        for p in sorted((NEW_STUDY / 'records' / name).glob('*.json'), key=lambda p: int(p.stem))] for kind in ['luna', 'jev']}
    grading_cost = {kind: reporting.accounting(current_calls[kind], kind) for kind in ['luna', 'jev']}
    _, billing = reporting.runtime_metadata(OLD_IMPORT, old_meta['metadata'])
    old_run = judge.read_json(PRIVATE/'pfi-v41flash1017-high-20261028-r1/run.json')
    new_run = judge.read_json(RUN/'run.json')
    retained = ['embedding_model','embedding_dimensions','llm_model','llm_provider','llm_thinking_enabled',
                'llm_reasoning_effort','top_k','min_score','provider_endpoint_fingerprints']
    require(all(old_run['configuration_probe'].get(k)==new_run['configuration_probe'].get(k) for k in retained),
            'Answering model, retrieval settings or provider endpoint changed')
    gaps=[]
    for kind in ['luna','jev']:
        for tid in tids:
            review=reviews.get((kind,'context_rag',tid))
            if review is None:continue
            case=jobs[('context_rag',tid)]['reference_case']
            for point in case['key_points']:
                if point['optional'] or point['capability']!='text':continue
                value=review['key_point_scores'][point['id']]
                if value<1:
                    gaps.append(dict(judge=kind,task_id=tid,point_id=point['id'],score=value,
                        criterion=point['text'],reason=review['reasons'].get('point_'+point['id'])))
    result = dict(version='context-v1-comparison-20261029', policy_sha256=grading.POLICY_SHA,
        question_count=32, common_task_ids=common, common_tasks=len(common), scores=summary,
        paired_old_vs_new=paired, new_rag_valid_grades=sum(s == 'rag' for k, s, t in new_reviews),
        new_rag_grading_coverage={kind: {status: count for (k, s, status), count in statuses.items() if k == kind and s == 'rag'} for kind in ['luna', 'jev']},
        exclusions=[dict(task_id=t, unavailable=[k + '_' + s for k in ['luna','jev'] for s in systems
            if (k, s, t) not in metrics or metrics[(k,s,t)]['reference_concern']]) for t in tids if t not in common],
        retained_configuration={k:new_run['configuration_probe'].get(k) for k in retained},
        runtime_baselines=dict(old=old_run['baseline_id'],new=new_run['baseline_id'],
            reference=new_run.get('reference_baseline_id'),old_chunks=44,new_chunks=81),
        remaining_key_point_gaps=gaps,
        grade_review_cautions=[
            dict(task_id='PFI2-004',note='新版已列出两类浆作用力条件；P3由Luna评1、Jev评0.5，存在判断分歧。'),
            dict(task_id='PFI2-015',note='Jev将P3从旧版0.5改为新版0；两版均列出作用力数值，需复核边界表达是否充分。'),
            dict(task_id='PFI2-024',note='新版指出未提供定量贡献排序；因果边界要点由Luna评0.5、Jev评1。'),
            dict(task_id='PFI2-032',note='两版均列出摘要与正文的不同系数；Luna对P2从0.5改为1，该增分需复核评分波动。')],
        new_grading_accounting=grading_cost, reused_dsh_grading_jobs=64, new_dsh_provider_calls=0,
        dsh_runtime=billing, new_answer_runtime=runtime(),
        comparison_scope='Same frozen paper, questions, gold standard and five-dimension scoring. Both chunking and context assembly changed together; answering randomness remains.',
        limitations=['Single-paper development set; no held-out generalization or statistical significance claim.',
            'One new answer per question and one first-valid judgment per judge; this is not a stability experiment.',
            'Citation text length and number of factual claims differ between systems.',
            'Prior RAG and DSH judgments are reused; judge service drift cannot be excluded.',
            'No new scores are assigned by this exporter. No weighted overall score.',
            'This run does not add reranking, query rewriting, OCR or cross-page table joining.'])
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT / 'comparison.json', result)
    public_rows = []
    for tid in tids:
        job = jobs[('context_rag', tid)]
        row = dict(task_id=tid, question=job['reference_case']['question'], reference_answer=job['reference_case']['reference_answer'],
            key_points=job['reference_case']['key_points'], systems={})
        for system in systems:
            candidate = {k: deepcopy(v) for k, v in jobs[(system,tid)]['candidate'].items() if k != 'available_context'}
            row['systems'][system] = dict(candidate=candidate, judges={kind: dict(review=reviews.get((kind,system,tid)),metrics=metrics.get((kind,system,tid))) for kind in ['luna','jev']})
        public_rows.append(row)
    (OUTPUT / 'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in public_rows), encoding='utf-8', newline='\n')
    save(OUTPUT / 'audit.json', dict(old_import_sha256=judge.digest(OLD_IMPORT/'import.json'),new_import_sha256=judge.digest(NEW_IMPORT/'import.json'),
        old_study_sha256=judge.digest(OLD_STUDY/'study.json'),new_study_sha256=judge.digest(NEW_STUDY/'study.json'),
        reuse_manifest_sha256=judge.digest(NEW_STUDY/'reused-dsh-records.json'),run_sha256=judge.digest(RUN/'run.json'),
        original_grade_proofs=old_proofs,new_study_grade_proofs=new_proofs,grader_input_identity_checked=True,
        exporter_assigns_no_scientific_grades=True))
    render(result, public_rows)
    save(OUTPUT/'publication.json', dict(files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    print(json.dumps({k:result[k] for k in ['common_tasks','new_rag_valid_grades','new_rag_grading_coverage','new_grading_accounting','paired_old_vs_new']},ensure_ascii=False))


def render(result, rows):
    labels = dict(old_rag='旧版RAG', context_rag='新版RAG', dsh='DSH')
    p = reporting.percent
    frac = reporting.ratio
    def cells(s):
        support=s['support_counts']; total=sum(support.values())
        return [p(s['point_macro_average']), f"{support.get('supported',0)}/{total}" + (f" ({p(support.get('supported',0)/total)})" if total else ''),
            frac(s['citation_precision']),frac(s['citation_coverage']),f"{s['boundary_mean']:.3f}",f"{s['all_five_pass']}/{s['tasks']}"]
    header=['裁判','系统','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项全部达标']
    table=[]
    for kind in ['luna','jev']:
        for system in labels:
            table.append([kind,labels[system],*cells(result['scores'][kind][system])])
    md=['# 文献问答第一轮优化完整复评','', '2026-10-29。新版32题重新答题，由Luna和Jev按原有共同五项规则独立评分；旧版RAG及DSH复用既有归档。', '',
        f"六组评分均有效且无参考疑点的共同题目：{result['common_tasks']}/32。新版有效评分：{result['new_rag_valid_grades']}/64。",'',
        '| '+' | '.join(header)+' |','| '+' | '.join(['---']*len(header))+' |']
    md += ['| '+' | '.join(row)+' |' for row in table]
    md += ['', '两位裁判均观察到新版的要点覆盖提高，数值比较题的证据缺口有所减少。同28题上，DSH的必答要点仍为100%，新版尚未完全追平；新版实际引用的支持与完整性指标较高，但受到引文长度和陈述粒度影响，不能据此宣布整体胜出。', '',
        '各维度独立解释，不相加为总分。事实与引用指标按各系统实际陈述/引用统计，披露分母，粒度可能不同。', '', '## 每位裁判的旧版与新版配对', '']
    for kind, paired in result['paired_old_vs_new'].items():
        md += [f"- {kind}：{len(paired['task_ids'])}道相同题目；要点均分 {p(paired['scores']['old_rag']['point_macro_average'])} → {p(paired['scores']['context_rag']['point_macro_average'])}；提高{len(paired['point_wins'])}题，下降{len(paired['point_losses'])}题，其余持平。",
               f"  提高：{', '.join(paired['point_wins']) or '无'}；下降：{', '.join(paired['point_losses']) or '无'}。"]
    md += ['', '## 剩余缺口与评分分歧', '',
        '新版Jev第23题的3次返回均未通过评分一致性校验，保留为缺失，不补零分，不继续挑选评分。', '',
        '尚未获得满分的必答要点涉及：'+', '.join(sorted({g['task_id'] for g in result['remaining_key_point_gaps']}))+'。具体要点和评委理由见HTML。', '']
    md += ['- '+item['task_id']+'：'+item['note'] for item in result['grade_review_cautions']]
    md += ['', '上述分歧只列为复核事项，保留原模型评分，不由报告程序改分；不能把每一项增分直接归因于系统改善。']
    md += ['', '下一步优先完善回答中的不确定性、测量口径和因果边界表达，例如保留“可能”、说明相对比例不等于绝对数量、避免将组间差异全部归因于浆种。先复核评分分歧，再将重排作为独立变更验证。']
    runtime=result['new_answer_runtime']
    md += ['', '## 用量与时间', '', f"新版答题：{runtime['questions']}题，{runtime['generation_calls']}次生成调用；已知生成Token {runtime['generation_known_tokens'].get('total_tokens',0):,}，问题Embedding Token {runtime['embedding_known_tokens']:,}。",
        f"评测程序记录的答题端到端耗时中位数{runtime['median_end_to_end_seconds']:.2f}秒，顺序执行累计{runtime['total_sequential_seconds']:.2f}秒；含独立工作进程启动，不是网页HTTP延迟实测。生成未知用量调用{runtime['generation_usage_unknown_calls']}次。实际货币费用未知。", '']
    for kind, cost in result['new_grading_accounting'].items():
        md += [f"- {kind}：新增{cost['calls']}次评分请求，API已报告费用${cost['reported_cost_usd']}，另有{cost['cost_unknown_calls']}次费用未知。"]
    md += ['', 'DSH复用64份原评分任务及其全部尝试，先核验输入字节与请求指纹完全一致，没有新增DSH调用；旧评分费用不计入本轮新增费用。', '', *reporting.runtime_cost_lines(result['dsh_runtime']), '',
        '## 实验范围与限制', '', '- 同一PDF、32题、参考答案、评分规则与裁判配置；新版独立请求不接收参考答案或旧分数。',
        '- 本轮同时改变结构切块和上下文补全，不能单独归因；模型生成随机性和裁判服务变化也可能影响差值。',
        '- 单篇开发题集，一轮生成与评分，未证明新论文泛化或稳定性；引用长度及陈述数量不同会影响比例。',
        '- 未加入重排、混合检索、query改写、OCR或跨页连接；本轮未更新服务器。', '',
        '完整32题、三套回答、两位裁判结果与理由：[HTML报告](../data/literature/qa-evaluation/reports/context-v1-full-20261029/comparison.html)。', '',
        '## 核验与重建', '',
        '评分复用与报告相关的20项离线测试通过；浏览器核对32题均包含三套回答，窄屏无横向溢出。', '',
        '保留本机忽略目录内的新旧答题、输入与原始评分档案后，可使用[报告脚本](../scripts/report_qa_context_v1_20261029.py)离线核验并刷新报告，不调用模型：', '',
        '```powershell', '.\\.venv\\Scripts\\python.exe scripts\\report_qa_context_v1_20261029.py refresh', '```', '',
        '刷新会先核对现有报告指纹，拒绝覆盖已被手工修改的文档；不会修改原始回答、参考答案或模型评分。']
    DOC.write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
    e=lambda x:html.escape(str(x),quote=True)
    pieces=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>文献问答优化复评</title>',
        '<style>body{margin:0;background:#f4f7fb;color:#203047;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1500px;margin:32px auto;padding:0 24px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:10px;border-bottom:1px solid #dde5ee;text-align:left;vertical-align:top}details,article{background:white;border:1px solid #dde5ee;border-radius:10px;padding:16px;margin:16px 0}summary{cursor:pointer;font-weight:650}.answers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f6f8fb;padding:12px}small{color:#60748a}h2{font-size:20px}h3{font-size:17px}@media(max-width:1000px){.answers{display:block}}.scroll{overflow:auto}</style><main>',
        '<h1>文献问答第一轮优化：旧版RAG / 新版RAG / DSH</h1>',
        f"<p>新版32题重新作答并独立双评；有效评分{result['new_rag_valid_grades']}/64，三套系统、两位裁判共同可用{result['common_tasks']}/32题。旧版及DSH评分复用归档。</p>",
        '<p>只比较结构切块与同页上下文补全这一组变更；未接入重排。五项独立报告，不计算综合总分。单篇开发集的一轮实验不能证明泛化、稳定性或因果效果。</p>',
        '<div class="scroll"><table><tr>'+''.join('<th>'+e(h)+'</th>' for h in header)+'</tr>']
    for row in table:pieces.append('<tr>'+''.join('<td>'+e(c)+'</td>' for c in row)+'</tr>')
    pieces += ['</table></div><h2>旧版与新版：各裁判最大可用配对集合</h2>']
    for kind, paired in result['paired_old_vs_new'].items():
        pieces.append(f"<p>{e(kind)}：{len(paired['task_ids'])}题，要点均分{p(paired['scores']['old_rag']['point_macro_average'])} → {p(paired['scores']['context_rag']['point_macro_average'])}；提高{len(paired['point_wins'])}题，下降{len(paired['point_losses'])}题。</p>")
    pieces += ['<details><summary>耗时、Token与本轮新增评分费用</summary><pre>'+e(json.dumps(dict(runtime={k:v for k,v in runtime.items() if k!='per_question'},grading=result['new_grading_accounting'],dsh=result['dsh_runtime']),ensure_ascii=False,indent=2))+'</pre></details>',
        '<details><summary>缺失评分与参考疑点</summary><pre>'+e(json.dumps(result['exclusions'],ensure_ascii=False,indent=2))+'</pre></details>',
        '<details><summary>剩余要点缺口与需复核的评分分歧（原评分保持不变）</summary><pre>'+e(json.dumps(dict(gaps=result['remaining_key_point_gaps'],cautions=result['grade_review_cautions']),ensure_ascii=False,indent=2))+'</pre></details>', '<h2>全部32题</h2>']
    for row in rows:
        pieces += ['<article><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与评分要点</summary><pre>'+e(row['reference_answer'])+'</pre><pre>'+e(json.dumps(row['key_points'],ensure_ascii=False,indent=2))+'</pre></details><div class="answers">']
        for system,label in labels.items():
            cell=row['systems'][system]
            pieces += ['<section><h3>'+e(label)+'</h3><pre>'+e(cell['candidate']['answer'])+'</pre>']
            for kind in ['luna','jev']:
                item=cell['judges'][kind]
                if item['metrics'] is None:pieces.append('<p>'+e(kind)+'：无有效评分</p>');continue
                metric=item['metrics']; support=metric['support_counts'];count=sum(support.values())
                pieces.append('<p>'+e(kind)+f"：要点{p(metric['point_mean'])}；事实{support.get('supported',0)}/{count}；引用{metric['supported_citations']}/{metric['factual_citations']}；引用组{metric['complete_groups']}/{metric['factual_claims']}；边界{metric['boundary']}/2。</p>")
                detail_label=kind+'逐条评分与原文依据'+('、文字理由' if kind=='luna' else '')
                pieces.append('<details><summary>'+e(detail_label)+'</summary><pre>'+e(json.dumps(item['review'],ensure_ascii=False,indent=2))+'</pre></details>')
            pieces.append('<details><summary>实际引用原文</summary><pre>'+e(json.dumps(cell['candidate']['citations'],ensure_ascii=False,indent=2))+'</pre></details></section>')
        pieces.append('</div></article>')
    pieces.append('</main></html>')
    (OUTPUT/'comparison.html').write_text('\n'.join(pieces),encoding='utf-8',newline='\n')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['reuse','report','refresh'])
    args=parser.parse_args()
    reuse() if args.action=='reuse' else report(refresh=args.action=='refresh')
