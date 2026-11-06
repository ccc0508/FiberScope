"""Combine user-selected reruns and audit Q1–12 without changing the baseline."""
import copy
import hashlib
import html
import json
from pathlib import Path

from report_agent_eightpapers_20261105 import ROOT, calibrate, metrics, summary

BASE = ROOT / 'data/literature/qa-evaluation/reports'
ORIGINAL = BASE / 'agent-eightpapers-20261105'
OUT = BASE / 'agent-eightpapers-latest-20261106'
RERUNS = {
    2: 'agent-hash-refs-case2-20261105',
    4: 'agent-figure-discovery-case4-20261106',
    8: 'agent-current-case8-20261106',
    12: 'agent-current-case12-20261106',
    15: 'agent-current-case15-20261106',
}

# Each audit applies to the selected answer, never to another run's claim IDs.
AUDIT = {
    1: ('维持已确认满分；局部证据范围限定和总结不重复引用均已接受。', []),
    2: ('接受C3明确限定于本次检索材料的不确定性说明；仍保留C4把两位作者写成四位作者的实质错误。', [
        ('claim_assessments.C3.support', 'supported', '该段明确说现有收录材料、本次检索范围；不将未取得补充材料解释成断言论文没有该材料。其余实验输入与验证限制由[2][11][13]支持。'),
        ('citation_group_assessments.C3.coverage', 'complete', '允许来源共同支持段落及有界的检索不足说明，不要求每个来源单独证明整段。'),
        ('citation_assessments.C3.[1].score', 1, '[1]摘要说明建模数据来自实验设计，但未展示ANN划分；该引用用于限定已取得的信息，并非断言全文没有划分。'),
        ('citation_assessments.C3.[9].score', 1, '[9]明确将MLR分析明细指向补充表S2/S3，支持当前片段不足以核对完整训练清单的说明。'),
    ]),
    3: ('三值本身由[3]共同支持；总结承接前文，取消纯粹缺少重复引用的扣分。但50%条件缺损造成的过度保留、错引和把无量纲增幅称为量纲不可通约等问题仍保留。', [
        ('citation_group_assessments.C1.coverage', 'complete', '实际[3]同时列出56.8%、99.3%、108.1%，[1][2]支持抗张的50%条件；其他冗余错引仍在单引维度保留，不否认现有有效来源的联合覆盖。'),
        ('citation_group_assessments.C4.coverage', 'partial', '总结继承前文来源，不再判missing；但仍重复后两项50%配比待确认的实质缺陷，不能恢复complete。'),
    ]),
    4: ('采用指定的原图重跑，非高分辨率实验。开头趋势结论继承后文图像与正文引用；仍保留棉浆抗张峰位、耐破50%低于0%的读图错误。', [
        ('citation_group_assessments.C1.coverage', 'complete', '开头正确趋势总结由后文[7][9][10]支持，无需重复挂引。'),
    ]),
    5: ('维持原分，但澄清扣分理由：[6]确实写WRV回收五次，不应将这一忠实转述视为无依据。保留的是把解析后异常公式断言为原论文排版错误，尚不能排除解析失真；不因一般外推限制扣分。', []),
    6: ('接受末段对未提供误差区间及显著性的谨慎提醒，恢复C4；保留C3把训练集复用直接解释为曲线拟合优于LSTM的因果推断。两种方法都使用训练数据估计，不能据此单独解释优劣。', [
        ('claim_assessments.C4.support', 'supported', 'C4复述模型、RMSE及适用范围，不能从点估计确定统计显著性属于合理边界提醒，并未否认论文报告的精度差异。'),
        ('citation_group_assessments.C4.coverage', 'complete', '承接前文摘要、讨论和结论引用；合理不确定性提醒无需另找论文逐字表述。'),
    ]),
    7: ('保留把公开可获得与合成数据误称冲突的事实问题；末段未确定是否分层抽样是方法信息不足说明，承接已有方法引用，不单独罚漏引。', [
        ('citation_group_assessments.C5.coverage', 'complete', '训练/测试划分的方法说明承接前文来源；未能确定是否分层属于谨慎范围说明。'),
    ]),
    8: ('采用新回答，编号错配已消失；仍保留将原文列举的First/Second/Third进一步写成最关键的无依据因素排名，不因其余合理局限说明扣分。', []),
    9: ('[1]结论和[4]摘要共同支持分组结果及总体结果；合理区分评价层级、现有证据未提供样本明细不应扣覆盖分，恢复C4完整覆盖。', [
        ('citation_group_assessments.C4.coverage', 'complete', '原料分组及总体拟合结果有对应来源；未取得明细是局部证据范围声明，不要求原文主动声明缺失。'),
    ]),
    10: ('正文确实印R²=.34，答案明确标注原文为.34；不因未额外罗列结论中的.94而扣本题事实与引用分。保留原文内部数值冲突提示，但不是模型捏造，也不是题目要求的冲突辨析。', [
        ('claim_assessments.C3.support', 'supported', '实际[1]包含.34及混合样品预测不推荐的说明，忠实引用注明出处；小样本稳健性不确定是合理限定。'),
        ('citation_group_assessments.C3.coverage', 'complete', '来源支持该段报告值和训练划分，不强加题面未要求的全篇冲突汇总义务。'),
    ]),
    11: ('已接受总结和同表说明继承引用；仍保留把Table 5行说成列，以及将正文MLR数值误述为0.31范围的实质问题。实际正文给杨氏模量0.33，Table 5给0.31。', []),
    12: ('采用新回答且维持满分；Table 2支持Fibre_cont定义，原文100 and 10 mm的单位歧义属于来源问题，新答未擅自改为μm。', []),
    15: ('采用当前版本重跑及最新校准：开头结论承接[1]，[8]支持SR/CSF测量方法。保留末段仅凭表9引用作者差异不显著判断的支持不足；不是编号错配。', []),
    16: ('接受有界仪器差异及不能直接换算的谨慎说明；[6][7]直接支持两台仪器各自的测量均值，结合[1]检测限制共同覆盖末段，恢复满分。', [
        ('claim_assessments.C4.support', 'supported', '完整上下文明确有两仪器测量；非直接对比实测指形态解释及检测限制的推论，不能误读成否认实验。所引证据未显示校正关系是限定范围的说明。'),
        ('citation_assessments.C4.[6].score', 1, 'Table 3直接支持Kajaani测量均值，承担实质子事实。'),
        ('citation_assessments.C4.[7].score', 1, 'Table 4直接支持L&W测量均值，承担实质子事实。'),
        ('citation_group_assessments.C4.coverage', 'complete', '[1]方法与检测限制及[6][7]表格联合支持；不要求推论在论文中逐字重述。'),
    ]),
    17: ('单位换算正确；只检索一次且Morais命中参考文献条目，未确认mg/100m，保留K1半分和边界1。接受对现有材料缺口的如实说明及数据整合建议，不把答题不完整重复判成事实错误；换算不要求论文引用，总结承接前文。', [
        ('claim_assessments.C2.support', 'supported', '实际[2][3]支持Uddin单位及数值，Morais仅参考文献条目，局部证据不足说明准确。'),
        ('claim_assessments.C4.support', 'supported', '核对定义、仪器与统计基准并保留来源是合理整合建议，没有宣称论文给出了尚未取得的信息。'),
        ('citation_group_assessments.C1.coverage', 'complete', '用户给定数值的算术换算可直接核验，结论承接后文，不要求额外论文引用。'),
        ('citation_group_assessments.C2.coverage', 'complete', '已陈述的论文事实有[2][3]支持，检索范围限制不要求原文逐字声明。'),
        ('citation_group_assessments.C4.coverage', 'complete', '整合建议承接前文定义与单位证据，不因缺重复编号判漏引。'),
    ]),
    18: ('核心定义和检测限制齐全；开头、整合建议及总结可联合承接前文来源，恢复C1/C4/C5覆盖。保留C3将5µm长度检测下限与74µm筛孔直接比较后推出粒群更细的实质推断错误。', [
        ('citation_group_assessments.C1.coverage', 'complete', '开头概括由后文两篇定义和检测限制共同支持。'),
        ('citation_group_assessments.C4.coverage', 'complete', '不同定义及统计量不可直接换算由所附来源联合支持；可信度不同按后文理解为测量范围限制，而非论文质量排名。'),
        ('citation_group_assessments.C5.coverage', 'complete', '总结承接前文来源；没有现成校正关系时不直接拼接是合理有界结论。'),
    ]),
}


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    baseline = read(ORIGINAL / 'results.json')
    rows = copy.deepcopy(baseline)
    manifest = []
    before_rows = []
    audit_rows = []
    for number, row in enumerate(rows, 1):
        tid = row['case']['id']
        source = RERUNS.get(number, ORIGINAL.name)
        paths = [ORIGINAL / 'results.json']
        if number in RERUNS:
            folder = BASE / source
            grade = read(folder / 'grading.json')
            run_path = ROOT / '.rag-data/evaluations' / source / (tid + '.json')
            run = read(run_path)
            row['answer'], row['draft'] = run['answer'], run['draft']
            row['raw_jev'] = grade.get('raw_jev', grade.get('jev'))
            row['calibrated'] = grade['calibrated']
            row['source_calibration'] = grade.get('calibration', grade.get('calibration_notes', grade.get('changes')))
            row['result_sha256'] = sha(run_path)
            judge_path = run_path.parent / 'jev' / tid / 'input.json'
            row['judge_input_sha256'] = sha(judge_path) if judge_path.exists() else None
            row['summary'] = {
                'id': tid, 'group': row['case']['group'], 'status': run['status'],
                'review_status': run.get('review_status'),
                'tools': [t['request']['tool'] for t in run['tool_calls']],
                'reason': '使用指定重跑；来源校准详见source_calibration。',
            }
            paths = [folder / 'grading.json', folder / 'answer.md']
        source_calibrated = copy.deepcopy(row['calibrated'])
        row['source_calibrated'] = source_calibrated
        row['source_run'] = source
        row['baseline_metrics'] = baseline[number-1]['summary']['final']
        row['pre_audit_metrics'] = metrics(row['case'], source_calibrated, row['summary'] | {'answer': row['answer']})
        before_rows.append({'final': row['pre_audit_metrics']})
        reason, items = AUDIT.get(number, ('未列入本轮复查的题目沿用此前校准。', []))
        changes = [{'path': p, 'value': v, 'reason': why} for p, v, why in items]
        current = calibrate(source_calibrated, {'changes': changes})
        # Raw decision labels can conflict with later human-readable calibration fields.
        # Preserve them in raw_jev/source_calibrated, not in the authoritative current view.
        current.pop('decisions', None)
        row['calibrated'] = current
        row['latest_audit'] = {'reviewed': number in AUDIT, 'reason': reason, 'changes': changes}
        row['summary']['final'] = metrics(row['case'], current, row['summary'] | {'answer': row['answer']})
        row['summary']['jev'] = metrics(row['case'], row['raw_jev'], row['summary'] | {'answer': row['answer']})
        row['summary']['reason'] = reason if number in AUDIT else baseline[number-1]['summary']['reason']
        row['summary']['changes'] = changes if number in AUDIT else baseline[number-1]['summary']['changes']
        row['answer_sha256'] = hashlib.sha256(row['answer'].encode('utf-8')).hexdigest()
        manifest.append({'case_id': tid, 'source_run': source, 'answer_sha256': row['answer_sha256'], 'source_artifacts': [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)} for p in paths]})
        if number in AUDIT:
            audit_rows.append({'case_id': tid, 'source_run': source, **row['latest_audit'], 'before': row['pre_audit_metrics'], 'after': row['summary']['final']})
    final_rows = [r['summary'] for r in rows]
    totals = {
        'report_type': 'mixed-version selected-results snapshot, not a single-version end-to-end run',
        'answer_regenerated': False, 'judge_rerun': False,
        'scoring_policy': read(ROOT / 'fiberscope-eval-8papers-v1/rubric.json'),
        'baseline': summary([r['summary'] for r in baseline], 'final'),
        'selected_before_audit': summary(before_rows, 'final'),
        'latest': summary(final_rows, 'final'),
        'groups': {g: summary([r for r in final_rows if r['group'] == g], 'final') for g in ['single', 'cross', 'no_paper']},
        'strict_pass_cases': [r['id'] for r in final_rows if r['final']['strict_pass']],
        'limitations': ['前12题及第15—18题按本轮口径复查，其余保留此前校准。', '这不是同一版本的一次完整运行，不可将变化全部归因于算法优化。', '历史Jev评分未重跑；最终分为基于既有来源的Codex校准，不等同独立专家审核。', '第4题采用原图重跑，不采用后续分辨率实验或挑最高分答案。', '不混算不同批次Token、费用与时延。', '事实核查单位为冻结语义段落组，不是逐句正确率。'],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / 'results.json', rows)
    write(OUT / 'summary.json', totals)
    write(OUT / 'manifest.json', manifest)
    write(OUT / 'audit.json', audit_rows)
    def fmt(n):
        return 'N/A' if n is None else f'{n:.2f}'
    def score(m):
        return ' / '.join([fmt(m['point_score']), fmt(m['fact_support']), fmt(m['citation_precision']), fmt(m['citation_coverage']), str(m['boundary']), '通过' if m['strict_pass'] else '未通过'])
    esc = html.escape
    table = '<table><thead><tr><th>题目</th><th>答案来源</th><th>最新六维评分</th></tr></thead><tbody>' + ''.join(f'<tr><td><a href="#q{r["case"]["id"]}">{r["case"]["id"]}</a></td><td>{esc(r["source_run"])}</td><td>{score(r["summary"]["final"])}</td></tr>' for r in rows) + '</tbody></table>'
    overall = '<table><tr><th>阶段</th><th>要点</th><th>事实支持</th><th>单引有效</th><th>引用覆盖</th><th>边界</th><th>严格通过</th></tr>'
    for label, key in [('原30题最新校准', 'baseline'), ('替换四题后，口径复查前', 'selected_before_audit'), ('最新汇总（复查后）', 'latest')]:
        t = totals[key]
        overall += f'<tr><td>{label}</td><td>{t["point_score"]:.2f}</td><td>{t["fact_support"]["percent"]:.2f}%</td><td>{t["citation_precision"]["percent"]:.2f}%</td><td>{t["citation_coverage"]["percent"]:.2f}%</td><td>{t["boundary_mean"]:.2f}/2</td><td>{t["strict_pass_count"]}/30</td></tr>'
    overall += '</table>'
    articles = []
    for r in rows:
        c = r['case']; a = r['latest_audit']
        articles.append(f'<article id="q{c["id"]}"><h2>{c["id"]} · {esc(c["question"])}</h2><p>答案来源：{esc(r["source_run"])}</p><p>原30题对应分：{score(r["baseline_metrics"])}<br>选定回答复查前：{score(r["pre_audit_metrics"])}<br><b>最新校准：{score(r["summary"]["final"])}</b></p><p>{esc(r["summary"]["reason"])}</p><details open><summary>完整回答</summary><pre>{esc(r["answer"])}</pre></details><details><summary>题目参考答案与评分要点</summary><pre>{esc(json.dumps(c,ensure_ascii=False,indent=2))}</pre></details><details><summary>本轮调整、历史Jev及当前核查</summary><pre>{esc(json.dumps({"本轮复查":a,"历史Jev":r["raw_jev"],"选定版本校准":r["source_calibrated"],"当前校准":r["calibrated"]},ensure_ascii=False,indent=2))}</pre></details></article>')
    intro = '第2、4、8、12、15题使用指定重跑，其余保留原答案；前12题及15—18题按最新口径复查。原30题报告未修改。此为不同版本合并快照，不是一次新的端到端测试。'
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>八篇论文·最新结果汇总</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei";color:#24344a;background:#f3f6fa;margin:0}main{max-width:1200px;margin:auto;padding:28px}article{background:white;padding:24px;border:1px solid #d6e0ed;border-radius:12px;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #ccd7e3;padding:8px;text-align:left;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}summary{cursor:pointer;color:#25639a}details{margin:12px 0}</style><main><h1>八篇论文 · 最新结果汇总</h1><p>'+intro+'</p><p>六维顺序：要点% / 事实充分支持% / 单引有效% / 引用组覆盖% / 边界0–2 / 严格通过。</p>'+overall+'<details><summary>分组统计、分子分母与限制</summary><pre>'+esc(json.dumps(totals,ensure_ascii=False,indent=2))+'</pre></details>'+table+''.join(articles)+'</main></html>'
    (OUT / 'report.html').write_text(page, encoding='utf-8')
    md = '# 八篇论文：最新结果汇总\n\n' + intro + '\n\n## 汇总\n\n| 阶段 | 要点 | 事实充分支持 | 单引有效 | 引用组覆盖 | 严格通过 |\n|---|---:|---:|---:|---:|---:|\n'
    for label, key in [('原30题最新校准', 'baseline'), ('合并指定新回答，复查前', 'selected_before_audit'), ('合并并复查后', 'latest')]:
        t = totals[key]
        md += f'| {label} | {t["point_score"]:.2f} | {t["fact_support"]["percent"]:.2f}% | {t["citation_precision"]["percent"]:.2f}% | {t["citation_coverage"]["percent"]:.2f}% | {t["strict_pass_count"]}/30 |\n'
    md += '\n## 逐题复查\n\n' + '\n'.join(f'- {a["case_id"]}：{a["reason"]}' for a in audit_rows)
    md += '\n\n## 限制与文件\n\n' + '\n'.join('- '+s for s in totals['limitations']) + '\n\nreport.html包含完整题目、答案、参考标准及逐项核查；results.json保存全部30题；audit.json记录本轮复查变更；manifest.json标记来源及哈希；summary.json保存分子分母。\n'
    (OUT / 'README.md').write_text(md, encoding='utf-8')
    assert len(rows) == 30
    assert all(rows[i-1]['answer'] == baseline[i-1]['answer'] for i in range(1,31) if i not in RERUNS)
    assert all(rows[i]['summary']['final'] == baseline[i]['summary']['final'] for i in range(30) if i+1 not in AUDIT)
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
