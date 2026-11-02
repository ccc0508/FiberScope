"""Merge three new source-adjudicated grades with the 29 unchanged v3 grades."""
from copy import deepcopy
from html import escape
from pathlib import Path
import json

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
from evaluate_evidence_review_retries_20261102 import BASE, OUTPUT, RETRY, ROOT, SELECTED, verify
from report_answer_models_20261102 import final_review

PUBLIC = ROOT / 'data/literature/qa-evaluation/reports/evidence-review-merged-20261102'


def render(summary, records):
    def pct(v):
        return f'{v * 100:.2f}%'

    def supported(m):
        counts = m['support_counts']
        return pct(counts.get('supported', 0) / sum(counts.values()))

    measures = [
        ('要点得分（按题平均）', lambda m: pct(m['point_macro_average'])),
        ('事实充分支持率', supported),
        ('单条引用有效率', lambda m: pct(m['citation_precision']['value'])),
        ('引用组完整率', lambda m: pct(m['citation_coverage']['value'])),
        ('回答边界（满分2）', lambda m: f"{m['boundary_mean']:.5f}"),
        ('五项全部达标', lambda m: f"{m['all_five_pass']}/{m['tasks']}"),
    ]
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><title>审校失败题补跑合并结果</title>',
             '<style>body{font:16px/1.7 system-ui,sans-serif;margin:32px auto;padding:0 20px;max-width:1100px;color:#18324b;background:#f6f8fb}table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;border:1px solid #dae2ec;text-align:left}article{margin:22px 0;padding:22px;background:white;border:1px solid #dae2ec;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer;font-weight:600}a{color:#2463aa}</style>',
             '<h1>三题补跑合并后的32题评测</h1>',
             '<p>只替换第24、31、32题的答案和评分，另外29题沿用v3。三题新增Jev独立评分，再由Codex核对来源；无加权综合总分。原报告保留。</p>',
             '<p>这是失败题补跑后的合并统计，不是32题重新运行，也不能用于证明稳定性或将收益单独归因于提高输出上限。</p>',
             '<table><thead><tr><th>指标</th><th>审校前原稿</th><th>上次v3</th><th>三题合并后</th></tr></thead><tbody>']
    for name, value in measures:
        parts.append('<tr><td>' + escape(name) + '</td>' + ''.join('<td>' + escape(value(summary['final'][arm])) + '</td>' for arm in ['control', 'previous_v3', 'merged']) + '</tr>')
    parts += ['</tbody></table>', '<p>仍未全部达标：第14、18、24、32题。要点总分没有变化，主要改善是事实支持、引用及第31题的科学边界。</p>',
              '<p><a href="comparison.json">汇总与用量</a> · <a href="questions-answers-reviews.jsonl">全部32题及评分</a> · <a href="adjudication.json">三题评分复核依据</a></p>']
    for row in records:
        tid, metrics = row['task_id'], row['final_codex_metrics']
        parts.append('<article><h2>' + escape(tid + ' ' + row['question']) + '</h2><p>' + ('本次替换并重新评分' if tid in SELECTED else '答案与最终评分原样沿用v3') + '</p>')
        parts.append('<p>要点：' + pct(metrics['point_mean']) + '；五项全部达标：' + ('是' if metrics['all_five_pass'] else '否') + '</p>')
        parts.append('<h3>模型答案</h3><pre>' + escape(row['candidate']['answer']) + '</pre>')
        for label, value in [('参考答案', row['reference_answer']), ('评分要点', row['key_points']), ('最终评分明细', row['final_codex_review']), ('Jev原评分', row['raw_jev_review']), ('来源复核', row['adjudication'])]:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            parts.append('<details><summary>' + escape(label) + '</summary><pre>' + escape(text) + '</pre></details>')
        parts.append('</article>')
    parts.append('</html>')
    return ''.join(parts)


def publish():
    verify()
    if PUBLIC.exists():
        raise ValueError('Publication already exists; do not overwrite')
    meta, jobs, study, reviews, api_records, statuses, proofs = scoring.audit(OUTPUT / 'import', OUTPUT / 'judges')
    if any(value != 'completed' for (_, _, value) in statuses):
        raise ValueError('Finish the three grades before publication')
    previous = [json.loads(line) for line in (BASE / 'questions-answers-reviews.jsonl').read_text(encoding='utf-8').splitlines()]
    prior_summary = judge.read_json(BASE / 'comparison.json')
    adj = judge.read_json(OUTPUT / 'codex-adjudication.json')
    if adj['policy_sha256'] != grading.POLICY_SHA or adj['reviewer'] != 'Codex':
        raise ValueError('Final source adjudication changed')
    adjudications = {r['task_id']: r for r in adj['items']}
    if set(adjudications) != SELECTED:
        raise ValueError('Only the three retry grades can be replaced')
    job_lookup = {j['task_id']: j for j in jobs if j['system'] == 'rag'}
    entries = {j['task_id']: j for j in study['jobs']}
    records = []
    changed = []
    for old in previous:
        if old['arm'] != 'review':
            continue
        tid = old['task_id']
        row = deepcopy(old)
        if tid in SELECTED:
            entry, job = entries[tid], job_lookup[tid]
            raw = reviews[('jev', 'rag', tid)]
            saved = judge.read_json(OUTPUT / 'judges/inputs' / (entry['name'] + '.json'))
            data = dict(result_sha256=judge.digest(RETRY / 'results' / (tid + '.json')),
                        grader_input_sha256=entry['input_sha256'], raw_review=raw, saved=saved)
            final = final_review(data, adjudications[tid])
            result = judge.read_json(RETRY / 'results' / (tid + '.json'))['response']
            metrics = scoring.metrics(final, job['reference_case'], job['task']['capabilities'])
            row.update(candidate=job['candidate'], raw_jev_review=raw,
                       raw_jev_metrics=scoring.metrics(raw, job['reference_case'], job['task']['capabilities']),
                       final_codex_review=final, final_codex_metrics=metrics,
                       adjudication=adjudications[tid], evidence_review=result['evidence_review'])
            changed.append(dict(task_id=tid, before=old['final_codex_metrics'], after=metrics, analysis=adjudications[tid]['summary']))
        else:
            if row != old:
                raise ValueError('An unchanged question was modified')
        row['grade_origin'] = 'new_jev_plus_codex_source_adjudication' if tid in SELECTED else 'unchanged_v3_grade'
        row['prior_record_sha256'] = judge.sha(old)
        records.append(row)
    if len(records) != 32 or len(changed) != 3:
        raise ValueError('Expected 32 total and exactly three replacements')
    before = scoring.summarize([r['final_codex_metrics'] for r in previous if r['arm'] == 'review'])
    if before != prior_summary['summaries']['review']['final_codex']:
        raise ValueError('Previous summary does not reproduce')
    after = scoring.summarize([r['final_codex_metrics'] for r in records])
    raw_rows = [r['raw_jev_metrics'] for r in records if r['raw_jev_metrics'] is not None]
    summary = dict(version='evidence-review-failed-retries-merged-v1', questions=32, replaced_question_ids=sorted(SELECTED), retained_questions=29,
                   scoring_policy_sha256=grading.POLICY_SHA, weighted_grand_score=None,
                   final=dict(control=prior_summary['summaries']['control']['final_codex'], previous_v3=before, merged=after),
                   raw_jev=dict(previous_v3=prior_summary['summaries']['review']['raw_jev'], merged=scoring.summarize(raw_rows), valid_tasks=len(raw_rows)),
                   per_question_changes=changed, remaining_not_all_pass=[r['task_id'] for r in records if not r['final_codex_metrics']['all_five_pass']],
                   incremental_judge_accounting=scoring.accounting(api_records['jev'], 'jev'),
                   calls_this_merge=dict(answer=0, retrieval=0, evidence_review=0, jev=len(api_records['jev'])),
                   retry_review_accounting=judge.read_json(ROOT / 'data/literature/qa-evaluation/reports/evidence-review-32768-retry-20261102/retry.json')['usage'],
                   prior_v3_files_sha256={p.name: judge.digest(p) for p in BASE.iterdir() if p.is_file()},
                   contract=judge.read_json(OUTPUT / 'contract.json'), adjudication_sha256=judge.digest(OUTPUT / 'codex-adjudication.json'),
                   limitations=['Retried failures only, not a new full 32-question run or stability estimate.',
                                'Final grades combine Jev with Codex source adjudication; not an independent human gold.',
                                'The 29 unchanged answers and grades are reused; the previous report is preserved.',
                                'All three successful retries used fewer output tokens than the old 16384 cap.'])
    files = {'comparison.json': judge.encode(summary) + '\n', 'adjudication.json': judge.encode(adj) + '\n',
             'questions-answers-reviews.jsonl': ''.join(judge.encode(r) + '\n' for r in records),
             'comparison.html': render(summary, records)}
    from dotenv import dotenv_values
    for name in ['.env.literature', '.env.aliyun', '.env.jev', '.env.judge', '.env.luna', '.env.astra']:
        for key, value in dotenv_values(ROOT / 'backend' / name).items():
            if value and len(value) >= 12 and key.upper().endswith(('API_KEY', 'PASSWORD', 'TOKEN', 'BEARER_TOKEN')):
                if any(value in text for text in files.values()):
                    raise ValueError('Private value in publication')
    PUBLIC.mkdir(parents=True)
    for name, text in files.items():
        (PUBLIC / name).write_text(text, encoding='utf-8', newline='\n')
    judge.write(PUBLIC / 'publication.json', dict(version='merged-evidence-review-publication-v1', files={n: judge.digest(PUBLIC / n) for n in files}))
    return dict(final=after, changed_question_ids=sorted(SELECTED), public=str(PUBLIC), new_jev_calls=len(api_records['jev']))


if __name__ == '__main__':
    print(judge.encode(publish()), flush=True)
