"""Publish case 24 section-directory validation, independent Jev and calibration."""
import html,json
from pathlib import Path
import judge_qa_eval as j
from report_agent_eightpapers_20261105 import calibrate,metrics
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/agent-section-recovery-case24-20261106'
OUT=ROOT/'data/literature/qa-evaluation/reports/agent-section-recovery-case24-20261106'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    x=j.read_json(RUN/'FS8-024.json');raw=j.read_json(RUN/'jev/FS8-024/review.json')
    case=next(c for c in j.read_jsonl(ROOT/'fiberscope-eval-8papers-v1/gold.jsonl') if c['id']=='FS8-024')
    changes=[
        dict(path='citation_group_assessments.C1.coverage',value='complete',reason='开头结论由后文明确证据承接，不要求重复引用。'),
        dict(path='citation_assessments.C3.[6].score',value=1,reason='[6]正文明确列出层数0.38、纤维体积分数0.20、孔隙率−0.28，不是仅图注。Jev此处误判。'),
        dict(path='citation_group_assessments.C4.coverage',value='partial',reason='来源支持测量值与输入特征，但不完整支持“受…支配”“将无法解释或外推”“会无差别拟合”等必然性扩写；与保留的事实部分支持一致。'),
        dict(path='claim_assessments.C5.support',value='supported',reason='这是明确的保守处理建议，要求再核对可比性，不声称单位相同就一定可合并；不强读为禁止一切可能的换算方法。'),
    ]
    final=calibrate(raw,dict(changes=changes))
    reason='四要点齐全，100分。C2把无来源混训的风险写成必然混合信号且“而非材料强度”，C4把合成数据的输入变量说成支配强度，并把缺条件的风险写成必然无法外推，保留部分支持。不惩罚开头无重复引用、正确的相关系数和保守合并建议。'
    row=dict(case=case,answer=x['answer'],draft=x['draft'],raw_jev=raw,calibrated=final,changes=changes,reason=reason,raw_metrics=metrics(case,raw,x),final_metrics=metrics(case,final,x),
        run_id=x['run_id'],status=x['status'],review_status=x['review_status'],budget=x['budget'],model=x['model'],model_calls=len(x['model_calls']),elapsed_seconds=x['end_to_end_ms']/1000,
        tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']],result_sha256=j.digest(RUN/'FS8-024.json'),judge_input_sha256=j.digest(RUN/'jev/FS8-024/input.json'),
        evidence=[dict(ref=e['ref'],**e['content']) for e in x['evidence']])
    j.write(OUT/'grading.json',row)
    j.write(OUT/'provenance.json',dict(manifest=j.read_json(RUN/'manifest.json'),policy='one independent first attempt; no answer selection; Jev then Codex source-based calibration',tests='30 passed: test_literature_tools.py, test_agent_loop.py, test_agent_context.py',limitations=['single rerun cannot establish stability or isolate directory vs budget effect','actual live directory use was for Ayaliew; Uddin unit already returned by search','invalid-ID recovery tested automatically; no invalid-ID failure occurred in this live run','compound semantic blocks are not individual factual sentences','not deployed to public server; no full 30-question aggregate replacement']))
    (OUT/'answer.md').write_text('# FS8-024\n\n'+case['question']+'\n\n'+x['answer'],encoding='utf8')
    def fmt(m):
        return f"要点 {m['point_score']:.1f}；事实充分支持 {m['supported_facts']}/{m['fact_count']} ({m['fact_support']:.1f}%)；单引有效 {m['supported_pairs']}/{m['pair_count']} ({m['citation_precision']:.1f}%)；引用组覆盖 {m['covered_groups']}/{m['group_count']} ({m['citation_coverage']:.1f}%)；边界 {m['boundary']}/2；严格通过：{m['strict_pass']}"
    text='# 章节发现与错误恢复修复：第24题重跑\n\n新增list_sections(document_id, offset)，以真实映射返回可读取的章节ID、路径、页码和块数；每页20个。无效章节返回unknown_section及首批真实章节，未知论文返回unknown_document及find_documents指引。错误保持failed并保存恢复信息，不冒充科学证据。\n\n默认模型调用上限6→10；检索仍最多2次、工具最多8次、240秒。\n\n实跑7次模型调用、5次工具调用：find_documents两次→search_literature→list_sections(Ayaliew)→read_section(Ayaliew数据准备小节)，全部成功，复核完成。章节读取使用目录返回的真实ID。本次未触发无效ID；自动化测试验证无效ID返回目录后可纠正并读取。\n\nJev：'+fmt(row['raw_metrics'])+'\n\n校准：'+fmt(row['final_metrics'])+'\n\n'+reason+'\n\n相比上次：要点87.5→100；事实充分支持75%→50%；单引100%→100%；引用组75%→50%；边界仍2/2。完成了缺失单位等必答内容，但额外扩写仍有过度断言。复合语义段长度与内容不同，百分比不等于逐句错误率，也不能据一次重跑判定稳定性。\n\n重要归因限制：本次Uddin证据在首次检索就已进入上下文，新目录工具实际补读的是Ayaliew；不能把Uddin漏答消失单独归因于章节工具。代码和预算同时变化，也不能独立量化二者贡献。\n'
    (OUT/'README.md').write_text(text,encoding='utf8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第24题章节恢复重跑</title><style>body{font:16px/1.8 system-ui;background:#f3f6fa;color:#20354a}main{max-width:1100px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.8 system-ui}details{padding:20px;background:white}</style><main><pre>'+html.escape(text)+'</pre><h2>完整回答</h2><pre>'+html.escape(x['answer'])+'</pre><details><summary>Jev、校准依据、工具参数与引用原文</summary><pre>'+html.escape(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></main></html>'
    (OUT/'report.html').write_text(page,encoding='utf8')
    print(fmt(row['final_metrics']))

if __name__=='__main__':main()
