"""Select all new-budget answers, replacing only documented infrastructure failures."""
import json,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/mixed-budget20-v1'
OUT=BASE/'selected'
def main():
 OUT.mkdir(exist_ok=True);selection={}
 for name in ('cases.json','rubric.json','manifest.json','integrity.json'):shutil.copy2(BASE/name,OUT/name)
 for c in json.loads((BASE/'cases.json').read_text('utf8')):
  k=c['id'];source=BASE/(k+'.json')
  if k in ('MIX08','MIX09'):
   first=json.loads(source.read_text('utf8'));assert first['status']=='failed'
   source=BASE/'infrastructure-retry-1'/(k+'.json')
  assert source.exists()
  dest=OUT/source.name
  if dest.exists():assert dest.read_bytes()==source.read_bytes()
  else:shutil.copy2(source,dest)
  selection[k]=str(source.relative_to(ROOT))
  jp=BASE/'mixed-jev-v1'/k
  if k not in ('MIX08','MIX09') and (jp/'review.json').exists():shutil.copytree(jp,OUT/'mixed-jev-v1'/k,dirs_exist_ok=True)
 (OUT/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
 print('Selected',len(selection),'answers; two infrastructure retries explicitly identified.')
if __name__=='__main__':main()
