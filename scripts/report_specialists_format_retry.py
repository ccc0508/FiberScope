"""Summarize format retry completion, not answer-quality scores."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'
OUT=ROOT/'data/agent-evaluation/reports/specialists-three-suites-20261107'
def main():
 rows=[]
 for p in sorted((BASE/'format-retry-1').glob('*.json')):
  x=json.loads(p.read_text('utf8'))
  if 'case_id' not in x:continue
  rows.append(dict(id=x['case_id'],suite=x['suite'],status=x['status'],reason=x.get('stop_reason'),
   model_calls=len(x.get('model_calls',[])),tool_calls=len(x.get('tool_calls',[])),
   duration_ms=x.get('end_to_end_ms'),formats=[{k:f.get(k) for k in ('stage','status','wrapper_removed','repair_attempted','initial_error','repair_error')} for f in x.get('format_checks',[])],
   answer=x.get('answer',''),child_failures=[dict(role=c['role'],reason=c.get('trace',{}).get('stop_reason')) for c in x.get('children',[]) if c.get('status')=='failed'],failed_calls=[dict(stage=m['stage'],error=m.get('error_type')) for m in x.get('model_calls',[]) if m.get('status')=='failed']))
 assert len(rows)==14
 summary=dict(total=14,completed=sum(r['status']=='completed' for r in rows),
  model_repairs=sum(f.get('repair_attempted',False) for r in rows for f in r['formats']),
  successful_repairs=sum(f['status']=='repaired' for r in rows for f in r['formats']),
  wrappers_removed=sum(bool(f.get('wrapper_removed')) for r in rows for f in r['formats']),
  integrity=json.loads((BASE/'format-retry-1/integrity.json').read_text('utf8')),
  scope='Fresh independent end-to-end attempts; completion only, no new answer-quality grading.',results=rows)
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'format-retry-1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
 lines=['# 14道格式失败题重跑','',f"完成：{summary['completed']}/14。模型格式纠正：{summary['model_repairs']}次，其中{summary['successful_repairs']}次通过。直接去掉围栏：{summary['wrappers_removed']}次。",'', '这是流程完成率，不是答案准确率；未重新进行Jev评分。原基线及失败输出保留。每题独立新上下文，12次模型调用、8次工具调用、240秒。','', '| 题号 | 状态 | 模型调用 | 工具调用 | 格式处理 |','|---|---|---:|---:|---|']
 for r in rows:
  detail='；'.join(f['stage']+': '+f['status']+(' (去掉围栏)' if f.get('wrapper_removed') else '') for f in r['formats'])
  lines.append(f"| {r['id']} | {r['status']} {r['reason'] or ''} | {r['model_calls']} | {r['tool_calls']} | {detail} |")
 lines += ['', '## 两题失败原因', '', '- FS8-008：子Agent引用校验未通过。回答保留论文内部参考文献号 [45–47]，不属于本次证据编号；一次引用纠正后仍保留。', '- MIX14：SQL子Agent将目录说明和失败查询标为 [1]、[2]、[3]，但本次没有成功查询产生的可引用记录。另有查询使用了明细视图不存在的 replicate_count 字段。', '', '两题均在子Agent完成交接之前失败，没有进入新格式纠正步骤。12题完成不等于12题内容全部正确；其余11题原生返回合法格式，不能把整轮改善全部归因于本次修复。']
 (OUT/'format-retry-1.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
 print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False))
if __name__=='__main__':main()
