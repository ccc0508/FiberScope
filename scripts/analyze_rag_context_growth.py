"""Offline measurement of frozen full-v5 traces; no model calls or runtime edits."""
import csv,json,math,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-full-v5-20261109'
OUT=ROOT/'data/literature/qa-evaluation/reports/rag-context-growth-20261109'
def size(x):return len(json.dumps(x,ensure_ascii=False))
def read(p):return json.loads(p.read_text('utf8'))
def output_message(call):
    m=dict(call['raw_message']);m.pop('reasoning_content',None)
    return m
def describe(values):
    v=sorted(values)
    return dict(n=len(v),min=min(v),mean=statistics.mean(v),median=statistics.median(v),p95_nearest_rank=v[math.ceil(.95*len(v))-1],max=max(v)) if v else None
def main():
    rows=[]
    for p in sorted(RUN.glob('FS8-*.json')):
        x=read(p);b=x['budget'];children=x['children']
        row=dict(id=x['case_id'],applicable=bool(children),route=x['plan']['route'],context_limit=b['max_context_chars'])
        if not children:
            row.update(note='Direct/clarify route; no collection, no child reserve usage, no synthesis review.')
            rows.append(row);continue
        assert len(children)==1
        child=children[0];t=child['trace'];last=t['model_calls'][-1]
        assert t['review_status']=='delegated_to_parent' and last['stage'] in ('decide','finalize')
        calls=[c for c in x['model_calls'] if c['stage']==child['role']]
        final=calls[-1]
        assert final['input_messages']==last['input_messages'] and final['text']==last['text']
        # Last no-tool decide call uses collected context directly. Forced
        # finalize appends exactly one closing instruction, excluded at boundary.
        messages=last['input_messages']
        if last['stage']=='finalize':
            assert messages[-1]['content'].startswith('Evidence collection has ended.')
            boundary=messages[:-1]
        else:boundary=messages
        before=size(boundary);terminal=size(messages+[output_message(final)])
        parent=next(c for c in x['model_calls'] if c['stage']=='synthesis_review')
        pin=size(parent['input_messages']);pterminal=size(parent['input_messages']+[output_message(parent)])
        repairs=[c for c in x['model_calls'] if c['stage']==child['role']+'_format_repair']
        row.update(collection_end_chars=before,collection_limit=t['collection_context_limit'],early_stop_threshold=t['collection_stop_threshold'],reserved_chars=b['max_context_chars']-t['collection_context_limit'],stop_reason=t['stop_reason'],finalize_stage=last['stage'],finalize_input_chars=size(messages),closing_instruction_chars=size(messages)-before,child_output_text_chars=len(final['text']),child_terminal_history_chars=terminal,child_growth_chars=terminal-before,child_reserve_band_used_chars=max(0,terminal-t['collection_context_limit']),child_actual_max_input_chars=max(size(c['input_messages']) for c in calls),parent_review_input_chars=pin,parent_answer_text_chars=len(parent['text']),parent_input_plus_answer_chars=pterminal,parent_reassembly_delta_chars=pin-terminal,format_repair_input_chars=max([size(c['input_messages']) for c in repairs],default=0),max_actual_request_input_chars=max(size(c['input_messages']) for c in x['model_calls']),trace_url=(x.get('langfuse') or {}).get('url'))
        rows.append(row)
    eligible=[r for r in rows if r['applicable']]
    keys=['collection_end_chars','closing_instruction_chars','child_growth_chars','child_terminal_history_chars','child_reserve_band_used_chars','parent_review_input_chars','parent_answer_text_chars','parent_input_plus_answer_chars','max_actual_request_input_chars']
    summary=dict(total=len(rows),applicable=len(eligible),direct_or_clarify=len(rows)-len(eligible),metrics={k:describe([r[k] for r in eligible]) for k in keys},context_stop_cases=[r['id'] for r in eligible if r['stop_reason']=='context_budget'],reserve_band_entered_cases=[r['id'] for r in eligible if r['child_reserve_band_used_chars']>0],method='len(json.dumps(trace input_messages, ensure_ascii=False)), matching runtime; image base64 omitted by trace_messages; tool schemas not counted by runtime. Output appended from saved raw_message with reasoning_content removed. Parent review has a separate rebuilt context, not cumulative child growth. Terminal history includes observed output, is not a subsequent API input. P95 uses nearest-rank. Direct cases excluded, not zero-imputed.',limits='Offline observed-path measurement only. Increasing collection budget can lead to more tools, larger child output and larger parent input; these results do not prove safety of a new budget. No new model calls or runtime changes.')
    OUT.mkdir(parents=True,exist_ok=True)
    for name,obj in [('summary.json',summary),('cases.json',rows)]:
        (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (OUT/'cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    m=summary['metrics'];q=next(r for r in rows if r['id']=='FS8-020')
    lines=['# 收集结束后的上下文增长实测','',
      '对2026-11-09全量30题的冻结trace做离线统计；不调用模型、不修改运行时预算。24题有文献子Agent，6题直接回答/澄清，后6题不适用，未按0纳入平均。','',
      '## 结论','',
      f'当前65,536字符预留明显高于本轮实际子Agent收尾增长：平均{m["child_growth_chars"]["mean"]:,.2f}，中位数{m["child_growth_chars"]["median"]:,.1f}，P95 {m["child_growth_chars"]["p95_nearest_rank"]:,}，最大{m["child_growth_chars"]["max"]:,}字符。平均相当于预留的{m["child_growth_chars"]["mean"]/65536:.2%}，最大{m["child_growth_chars"]["max"]/65536:.2%}。',
      '', '但增长量不等于真正进入预留区的占用：多数题在94,464字符收集上限以下很早就结束。只有第20题在把子Agent输出追加到历史后超过94,464，超出156字符；这不是下一次API请求，子Agent此后没有在该历史上复核。','',
      '## 当前架构与统计口径','',
      '- 子Agent使用review_enabled=False，结束状态delegated_to_parent。父Agent用新的system/user消息重新组装证据、子Agent结果、任务覆盖报告，再合成复核；它不是把整份子Agent历史继续追加。',
      '- 自然结束：最后一次无工具调用的decide输入即收集结束上下文；强制结束：从finalize输入移除最后一条收尾指令，得到边界。',
      '- 增长量：边界之后的收尾指令，加实际输出消息在JSON序列化中的增量。使用保存的raw_message，移除reasoning_content，匹配程序字符统计；不是仅len(answer)。',
      '- 字符度量为len(json.dumps(messages, ensure_ascii=False))。图片base64在trace里已换成摘要；工具schema不在现有程序的这个字符预算内。因此不能把这些数字当作供应商真实token窗口占用。',
      '- 子Agent格式纠正如有发生，是独立请求，其大小单独列在cases.json/CSV，不与原历史累加。',
      '- 父Agent输入与答案合计是展示实际生成内容后的大小，不是有过后续请求的证明。P95使用nearest-rank。','',
      '## 汇总（24题）','', '| 指标 | 平均字符 | P95 | 最大字符 |','|---|---:|---:|---:|']
    for k,label in [('collection_end_chars','收集结束'),('child_growth_chars','子Agent收尾增长'),('child_terminal_history_chars','子Agent结束历史'),('parent_review_input_chars','父Agent复核输入（独立上下文）'),('parent_input_plus_answer_chars','父Agent输入＋实际答案'),('max_actual_request_input_chars','每题最大实际请求输入')]:
        v=m[k];lines.append(f'| {label} | {v["mean"]:,.2f} | {v["p95_nearest_rank"]:,} | {v["max"]:,} |')
    lines+=['','## 第20题','',
      f'- 收集结束：{q["collection_end_chars"]:,}字符。',
      '- 收集硬上限94,464，但还有提前停止阈值86,464（再提前8,000）。第20题是在一次工具返回后达到89,926，在下一轮触发提前收尾，并非已达到94,464或160,000。',
      f'- 收尾指令后输入：{q["finalize_input_chars"]:,}；加实际子Agent输出后的历史：{q["child_terminal_history_chars"]:,}；增长{q["child_growth_chars"]:,}字符。',
      f'- 父Agent重新组装后输入：{q["parent_review_input_chars"]:,}；输入加最终答案：{q["parent_input_plus_answer_chars"]:,}。它们不能再加到94,620上。',
      '', '## 决策建议及限制','',
      '这批数据支持“预留偏保守”，可以后续试验降低预留，而不是直接认定改完必然安全。可先试32,768预留，对应收集硬上限127,232、提前阈值119,232；本次尚未修改。放宽后会多读内容、可能产生更长结构化结果，必须重新观察实际请求与输出。',
      '另有父Agent证据转交的80,000字符独立上限（总上限一半）；单独放宽子Agent收集，不能保证新增证据最终进入父Agent。跨论文应先均衡取得每篇核心证据。',
      '', '## 全部题目','', '| 题号 | 收集结束 | 收尾增长 | 子Agent结束历史 | 父Agent输入 | 停止原因 |','|---|---:|---:|---:|---:|---|']
    for r in rows:
        if not r['applicable']:lines.append(f'| {r["id"]} | N/A | N/A | N/A | N/A | {r["route"]} |')
        else:lines.append(f'| {r["id"]} | {r["collection_end_chars"]:,} | {r["child_growth_chars"]:,} | {r["child_terminal_history_chars"]:,} | {r["parent_review_input_chars"]:,} | {r["stop_reason"] or "自然完成"} |')
    lines+=['','原始数据：`.rag-data/evaluations/specialists-three-suites-20261107/rag-full-v5-20261109/FS8-xxx.json`。脚本：`scripts/analyze_rag_context_growth.py`。逐题全部数值与trace链接见cases.json/cases.csv。']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('CASE20',json.dumps(next(r for r in rows if r['id']=='FS8-020'),ensure_ascii=False))
if __name__=='__main__':main()
