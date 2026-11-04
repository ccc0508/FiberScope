"""Join only missing persisted results after an interrupted full32 run; no API calls."""
from pathlib import Path
import shutil
import judge_qa_eval as j
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.rag-data/evaluations/unified-full32-20261104'
RESUME=ROOT/'.rag-data/evaluations/unified-full32-20261104-resume'


def main():
    a,b=(j.read_json(p/'manifest.json') for p in [RUN,RESUME])
    require(a['source_files']==b['source_files'],'Runtime changed across interruption')
    require(a['replay_effective_limits']==b['replay_effective_limits'],'Budget changed')
    original={r['case_id']:r for r in j.read_json(RUN/'inputs.json')}
    resumed=j.read_json(RESUME/'inputs.json')
    require([r['case_id'] for r in resumed]==[f'PFI2-{i:03}' for i in range(24,33)],'Unexpected resumed set')
    require(all(original[r['case_id']]==r for r in resumed),'Inputs changed')
    summary=j.read_json(RESUME/'summary.json')
    require(len(summary)==9 and all(r['status']!='harness_failed' for r in summary),'Resume incomplete')
    origins={}
    for i in range(1,33):
        tid=f'PFI2-{i:03}';src=(RESUME if i>=24 else RUN)/(tid+'.json');dst=RUN/src.name
        require(src.exists(),'Result missing')
        if src!=dst:
            if dst.exists():require(j.digest(src)==j.digest(dst),'Never overwrite a different completed result')
            else:shutil.copyfile(src,dst)
        origins[tid]=dict(directory=src.parent.name,result_sha256=j.digest(src))
    j.write(RUN/'recovery.json',dict(reason='Process absent after interruption; 23 results persisted. No result for 24-32.',
        interrupted_inflight_usage='unknown; may have incurred upstream charges',
        original_manifest_sha256=j.digest(RUN/'manifest.json'),resume_manifest_sha256=j.digest(RESUME/'manifest.json'),origins=origins))
    rows=[]
    for tid in origins:
        r=j.read_json(RUN/(tid+'.json'));t=r['evidence_review']
        rows.append(dict(case_id=tid,status=r['review_summary']['status'],review_calls=t['api_calls'],supplement_rounds=t['supplement_rounds']))
    j.write(RUN/'summary.json',rows)
    print(j.encode(dict(results=len(rows),resumed=9,paid_calls=0)))


if __name__=='__main__':main()
