"""Development overlay: final checks for 05/06/13, phase-one controls and other cases; keep both."""
import json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/grounded-coverage-v1'
OUT=BASE/'selected'
def main():
 OUT.mkdir(exist_ok=True);selection={}
 for name in ('cases.json','rubric.json','manifest.json'):shutil.copy2(BASE/name,OUT/name)
 integrity={phase:json.loads((p/'integrity.json').read_text('utf8')) for phase,p in [('initial',BASE),('final',BASE/'final-check')]}
 (OUT/'integrity.json').write_text(json.dumps(integrity),encoding='utf8')
 for c in json.loads((BASE/'cases.json').read_text('utf8')):
  k=c['id'];source=BASE/('final-check' if k in ('MIX05','MIX06','MIX13') else '')/(k+'.json')
  assert source.exists()
  dest=OUT/source.name
  if dest.exists():assert dest.read_bytes()==source.read_bytes()
  else:shutil.copy2(source,dest)
  selection[k]=str(source.relative_to(ROOT))
  jp=source.parent/'mixed-jev-v1'/k
  if (jp/'review.json').exists():shutil.copytree(jp,OUT/'mixed-jev-v1'/k,dirs_exist_ok=True)
 (OUT/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
