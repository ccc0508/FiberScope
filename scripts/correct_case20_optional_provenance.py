"""Apply the user-confirmed optional-provenance correction; preserve raw Jev and answers."""
import json,html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/literature/qa-evaluation/reports'
REASON='来源追溯是可选建议，不是题目明确要求或论文原文必答内容；已回答条件、单位、目标区别，K4恢复1分。其他事实和引用缺陷不变。'
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 gold=next(json.loads(l) for l in (ROOT/'fiberscope-eval-8papers-v1/gold.jsonl').read_text('utf-8').splitlines() if json.loads(l)['id']=='FS8-020')
 for folder,name in [('agent-scoped-case19-20-20261106','grading.json'),('agent-case19-20-audit-20261106','audit.json')]:
  out=BASE/folder;rows=json.loads((out/name).read_text('utf-8'));r=next(r for r in rows if r['case']['id']=='FS8-020')
  r['case']=gold;r['calibrated']['key_point_scores']['K4']=1
  if 'final_metrics' in r:
   r['final_metrics']['point_score']=100
   r['changes']=[c for c in r['changes'] if not c.startswith('K4')]+[REASON]
   r['reason']='主要预测链条、条件、单位及目标区别答全，要点100；仍保留没有序列结构的证据不足断言。'
  else:
   r['latest_audit']['metrics']['point_score']=100
   r['latest_audit']['changes'].append(REASON)
   r['summary']['final']['point_score']=100
   r['summary']['changes']=[c for c in r['summary']['changes'] if c['path']!='key_point_scores.K4']
   r['summary']['reason']=REASON
  r['scoring_correction']=dict(reason=REASON,answer_regenerated=False,judge_rerun=False,old_point_score=87.5,new_point_score=100)
  save(out/name,rows)
  if (out/'README.md').exists():
   s=(out/'README.md').read_text('utf-8').replace('87.5 → 87.5','100 → 100').replace('20题Jev要点100；校准仍为87.5，原因与旧答案一致：数据建议未明确保留来源追溯。','20题Jev与校准要点均为100；来源追溯改为可选建议，不再扣分。')
   s+='\n\n## 评分修正\n\n'+REASON+' 原始Jev及回答不变。\n';(out/'README.md').write_text(s,encoding='utf-8')
  if (out/'FS8-020.md').exists():
   s=(out/'FS8-020.md').read_text('utf-8').replace('"point_score": 87.5','"point_score": 100');s+='\n\n评分修正：'+REASON+'\n';(out/'FS8-020.md').write_text(s,encoding='utf-8')
  page='<meta charset="utf-8"><title>第19、20题评分</title><style>body{max-width:1100px;margin:40px auto;font:16px/1.8 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><p>'+html.escape(REASON)+'</p>'
  for d in rows:
   m=d.get('final_metrics',d.get('latest_audit',{}).get('metrics'))
   page+='<h2>'+d['case']['id']+'</h2><pre>'+html.escape(d['case']['question']+'\n\n参考答案：'+d['case']['reference_answer']+'\n\n当前评分：'+json.dumps(m,ensure_ascii=False,indent=2))+'</pre><h3>模型完整回答</h3><pre>'+html.escape(d['answer'])+'</pre><details><summary>评分与修正详情</summary><pre>'+html.escape(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details>'
  (out/'report.html').write_text(page,encoding='utf-8')
  assert r['calibrated']['key_point_scores']['K4']==1
if __name__=='__main__':main()
