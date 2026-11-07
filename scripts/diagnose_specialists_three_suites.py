"""Offline schema replay only: no model calls, repairs or changes to frozen answers."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.specialist_agent import Plan,SpecialistResult
RUN=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'
def main():
 rows=[]
 for path in sorted(RUN.glob('*.json')):
  x=json.loads(path.read_text('utf8'))
  if not isinstance(x,dict) or 'case_id' not in x or x.get('status')=='completed':continue
  row=dict(id=x['case_id'],status=x['status'],stop_reason=x.get('stop_reason'),stage='unknown',details=[])
  if not x.get('plan'):
   row['stage']='planner'
   for m in x.get('model_calls',[]):
    if m.get('stage')!='route':continue
    for c in m.get('calls',[]):
     try:Plan.model_validate(c['arguments'])
     except Exception as e:row['details'].append(str(e)[:1600])
  else:
   for c in x.get('children',[]):
    if c.get('result') is not None:continue
    row['stage']=c['role']+'_handoff'
    if c.get('trace',{}).get('status')=='failed':
     row['stage']=c['role']+'_execution'
     row['details'].append(c.get('trace',{}).get('stop_reason'))
     continue
    try:SpecialistResult.model_validate_json(c.get('trace',{}).get('answer',''))
    except Exception as e:row['details'].append(str(e)[:1600])
  rows.append(row)
 (RUN/'failure-diagnosis.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps([dict(id=r['id'],stage=r['stage']) for r in rows],ensure_ascii=False))
if __name__=='__main__':main()
