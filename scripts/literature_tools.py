"""Local tool entry point. No web endpoint and no autonomous agent loop."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.tools import SCHEMAS, ToolTraceStore

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['schemas','call','trace','evidence'])
    p.add_argument('--request',type=Path)
    p.add_argument('--library',type=Path)
    p.add_argument('--run-id')
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.action=='schemas':result=SCHEMAS
    elif a.action in ('trace','evidence'):
        if not a.run_id:p.error('--run-id required')
        store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
        result=store.read(a.run_id) if a.action=='trace' else store.evidence(a.run_id)
    else:
        if not all([a.request,a.library,a.run_id]):p.error('--request, --library and --run-id required')
        body=dict(tool_call=json.loads(a.request.read_text('utf-8')),data_dir=str(a.library.resolve()),run_id=a.run_id)
        r=subprocess.run([sys.executable,'-I','-X','utf8',str(ROOT/'backend/literature_worker.py')],
            input=json.dumps(body,ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',timeout=300,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if r.returncode:raise RuntimeError('Tool worker failed; inspect persisted trace. Provider details withheld.')
        result=json.loads(r.stdout)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
        print(json.dumps(dict(output=str(a.output)),ensure_ascii=False))
    else:print(text)

if __name__=='__main__':main()
