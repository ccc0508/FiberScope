"""Publish independent reruns with transparent Jev/source-based calibration."""
import copy, html, json
from pathlib import Path
import judge_qa_eval as j
from report_agent_eightpapers_20261105 import calibrate, metrics

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-scoped-case23-24-20261106'
OUT=ROOT/'data/literature/qa-evaluation/reports/agent-scoped-case23-24-20261106'

def change(path,value,reason):
    return dict(path=path,value=value,reason=reason)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cases={c['id']:c for c in j.read_jsonl(ROOT/'fiberscope-eval-8papers-v1/gold.jsonl')}
    notes={
      'FS8-023':dict(changes=[
        change('claim_assessments.C2.support','supported','0.88/0.978分别来自正文和表格，不判数值幻觉；高粱体系表述不强读为单一品种。'),
        change('citation_group_assessments.C2.coverage','complete','联合引文提供相关数值、原料与建模背景。'),
        change('citation_group_assessments.C1.coverage','complete','开头概括由后文明确引文承接，不要求重复引用。'),
        change('citation_assessments.C2.[2].score',1,'[2]实质支持高粱样本与处理能量背景；不能因未独立支持整段所有事实而记零。'),
        change('citation_assessments.C4.[7].score',1,'[7]提供包含kink的预测输入与ANN表现，联合[1][3]支持有限体系内预测特征的结论，不要求单条独立支撑整段。'),
        change('citation_group_assessments.C4.coverage','complete','[1][3][7]共同支持预测用途，[4]支持需要区分共变解释，实验验证建议不冒充已证实结果。'),
      ],reason='四个必答要点完整，100分。C2的0.88/0.978分别见正文和表格，不判数值幻觉；“同一高粱原料”按高粱体系理解，不强读为单一品种。建议解释原文数值差异，但不扣实质分。仅保留C3部分支持：称Uddin为“单一打浆序列”未获[7]支持。开头、结尾及联合引用不作过严扣分。'),
      'FS8-024':dict(changes=[
        change('citation_group_assessments.C1.coverage','complete','开头结论由后文三类差异与引用承接。'),
        change('citation_assessments.C2.[3].score',1,'[3]给出损伤D定义，实质支持该段损伤指标论述；T与T0公式由同组[1][2]支撑。'),
        change('claim_assessments.C3.support','supported','Uddin目标/单位未取回是本轮轨迹事实，不是断言论文没有这些信息。已取得的Li与Ayaliew部分有支持；未答全另在K2扣分。'),
        change('citation_group_assessments.C3.coverage','complete','[6][11]支持已回答的科学事实；工具失败说明不要求论文引用。'),
        change('citation_group_assessments.C4.coverage','partial','5折交叉验证出现在已检索的[14]，本段却仅挂[7][8][13][4][6]；另“合成数据所以不可外推”过强。'),
        change('answerability_score',2,'明确披露未查到Uddin及读取失败，未伪造其单位；K2漏答不重复算成不当边界。'),
      ],reason='沿用原四要点标准，K1/K3/K4齐全，K2只有MPa一侧，未回答Uddin的Nm/g，得87.5。维持C4部分支持：“合成数据所以不可外推”把应验证外推能力说成绝对禁止；“直接拼接会让模型把来源当信号”也把风险写成必然。其余实测/合成、10000/2000和原文性能数值有支持。不因如实承认证据不足惩罚事实正确性。')}
    rows=[]
    for tid in notes:
        x=j.read_json(RUN/(tid+'.json')); raw=j.read_json(RUN/'jev'/tid/'review.json')
        final=calibrate(raw,notes[tid]); c=cases[tid]
        row=dict(case=c,answer=x['answer'],draft=x['draft'],raw_jev=raw,calibrated=final,**notes[tid],
            raw_metrics=metrics(c,raw,x),final_metrics=metrics(c,final,x),run_id=x['run_id'],
            status=x['status'],review_status=x['review_status'],stop_reason=x['stop_reason'],
            elapsed_seconds=x['end_to_end_ms']/1000,
            tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']],
            result_sha256=j.digest(RUN/(tid+'.json')),judge_input_sha256=j.digest(RUN/'jev'/tid/'input.json'),
            evidence=[dict(ref=e['ref'],document_id=e['content'].get('document_id'),filename=e['content'].get('filename'),page_start=e['content'].get('page_start'),page_end=e['content'].get('page_end'),text=e['content'].get('text')) for e in x['evidence']])
        rows.append(row)
        (OUT/(tid+'-answer.md')).write_text('# '+tid+'\n\n'+c['question']+'\n\n'+x['answer']+'\n',encoding='utf-8')
    j.write(OUT/'grading.json',rows)
    failure=j.read_json(RUN/'FS8-024-first-worker-failed.json')
    provenance=dict(source_manifest=j.read_json(RUN/'manifest.json'),failed_attempt=dict(run_id=failure['run_id'],worker_returncode=failure['worker_returncode'],status=failure['status'],review_status=failure['review_status'],answer_present=bool(failure['answer']),sha256=j.digest(RUN/'FS8-024-first-worker-failed.json')),policy='FS8-023 first attempt; FS8-024 one independent supplementary run after worker failure. Failed attempt retained, not counted as completed. No selection among successful answers.',limitations=['single successful answer per question; not a stability estimate','Jev semantic blocks are compound paragraphs, not individual factual sentences; different answer denominators are not directly comparable','No global 30-question aggregate replaced','Codex calibration is not independent human expert review'])
    j.write(OUT/'provenance.json',provenance)
    def measure(m):
        return f"{m['point_score']:.2f} / {m['fact_support']:.2f} ({m['supported_facts']}/{m['fact_count']}) / {m['citation_precision']:.2f} ({m['supported_pairs']}/{m['pair_count']}) / {m['citation_coverage']:.2f} ({m['covered_groups']}/{m['group_count']}) / {m['boundary']}/2 / {'通过' if m['strict_pass'] else '未通过'}"
    md='# 第23、24题：最新版独立重跑及校准\n\n日期：2026-11-06。两份最终答案均完成复核；第24题首次工作进程失败，保留失败记录后独立补跑一次成功。不能记作首次2/2成功。\n\n顺序：要点分 / 事实充分支持率 / 单引有效率 / 引用组覆盖率 / 边界 / 严格通过。\n\n'
    for r in rows:
        md+=f"## {r['case']['id']}\n\nJev：{measure(r['raw_metrics'])}\n\n校准：{measure(r['final_metrics'])}\n\n{r['reason']}\n\n"
    md+='## 对比及限制\n\n第23题要点分仍为100；第24题从上次校准的50提高至87.5，补上损伤公式与合成数据，但仍漏Uddin单位。第24题沿用预设四要点口径，没有因其已列出三类差异就改为满分。\n\n事实/引用按本轮冻结的复合语义段计数，不代表逐句准确率；旧回答与新回答分段数不同，不能仅凭百分比断言整体质量升降。两题均还有实质缺陷，严格通过均为否。没有重算或覆盖30题总分。\n'
    (OUT/'README.md').write_text(md,encoding='utf-8')
    esc=html.escape
    body=''
    for r in rows:
        body+=f"<article><h2>{r['case']['id']}</h2><p>{esc(r['case']['question'])}</p><p>Jev：{measure(r['raw_metrics'])}<br>校准：{measure(r['final_metrics'])}</p><p>{esc(r['reason'])}</p><h3>完整回答</h3><pre>{esc(r['answer'])}</pre><details><summary>参考答案、评分及校准依据、调用轨迹、引用原文</summary><pre>{esc(json.dumps(r,ensure_ascii=False,indent=2))}</pre></details></article>"
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第23、24题最新重跑</title><style>body{background:#f4f7fa;color:#24364b;font:16px/1.8 system-ui;margin:0}main{max-width:1100px;margin:auto;padding:28px}article{background:white;padding:24px;margin:20px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.8 system-ui}summary{cursor:pointer}</style><main><h1>第23、24题最新重跑与评分</h1><pre>'+esc(md)+'</pre>'+body+'</main></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print(json.dumps([{r['case']['id']:r['final_metrics']} for r in rows],ensure_ascii=False))

if __name__=='__main__':main()
