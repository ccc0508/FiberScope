"""Private one-paper MinerU API experiment; no changes to the active QA library."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sys
import time
import zipfile

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.rag-data/parsing-comparisons/mineru-vs-pymupdf-20261029'
PDF=ROOT/'.rag-data/index-versions/structure-v1-20261029/papers/0fcf2a50cfa02d214b53a8c2d40ed3f660a41b1c81b3fbea04120a81dc09d4d4.pdf'
FILENAME='Li-2020-PFI-refining-aggregation-structure-cellulose.pdf'


def now():return datetime.now(timezone.utc).isoformat()
def sha(data):return hashlib.sha256(data).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    temp.replace(path)


def extract_archive(path,target):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        if len(members)>10000 or sum(m.file_size for m in members)>500_000_000:raise ValueError('Archive expansion limit exceeded')
        for member in members:
            destination=(target/member.filename.replace('\\','/')).resolve()
            if not destination.is_relative_to(target.resolve()) or ((member.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('Unsafe archive entry')
        archive.extractall(target)


def main(action):
    values=dotenv_values(ROOT/'backend/.env.mineru',interpolate=False)
    key=(values.get('MINERU_API_TOKEN') or '').strip().strip('"\'')
    if not key:raise ValueError('MinerU API token is not configured')
    if values.get('MINERU_API_BASE_URL')!='https://mineru.net':raise ValueError('Only the official endpoint is allowed in this comparison')
    OUT.mkdir(parents=True,exist_ok=True)
    state_file=OUT/'api-state.json'
    state=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
    if action=='poll' and state.get('status')=='completed':
        print(json.dumps(dict(status='completed',cached=True,new_api_calls=0)),flush=True)
        return 0
    headers={'Authorization':'Bearer '+key}
    with httpx.Client(timeout=httpx.Timeout(120,connect=15),trust_env=False,follow_redirects=False) as client:
        if action=='submit':
            if state.get('batch_id') or state.get('status')=='request_pending':raise ValueError('Existing submission requires inspection; do not submit it again')
            request=dict(files=[dict(name=FILENAME,data_id='fiberscope-'+sha(PDF.read_bytes())[:24],is_ocr=False)],
                         model_version=values.get('MINERU_MODEL_VERSION','vlm'),enable_table=True,enable_formula=True,language='en')
            state=dict(status='request_pending',started_at=now(),source_pdf_sha256=sha(PDF.read_bytes()),source_pdf_bytes=PDF.stat().st_size,
                       request=request,request_sha256=sha(json.dumps(request,sort_keys=True).encode()),service='https://mineru.net',api_calls=1)
            save(state_file,state)
            response=client.post('https://mineru.net/api/v4/file-urls/batch',json=request,headers=headers)
            try:body=response.json()
            except ValueError:body={}
            safe=json.loads(json.dumps(body).replace(key,'[REDACTED]'))
            save(OUT/'upload-response.private.json',safe)
            if response.status_code!=200 or body.get('code')!=0:
                state.update(status='submission_rejected',http_status=response.status_code,service_code=body.get('code'),finished_at=now())
                save(state_file,state)
                print(json.dumps({k:state[k] for k in ['status','http_status','service_code']}),flush=True)
                return 2
            state.update(batch_id=body['data']['batch_id'],status='upload_pending')
            save(state_file,state)
            url=body['data']['file_urls'][0]
            if not url.startswith('https://'):raise ValueError('Upload URL must use HTTPS')
            with PDF.open('rb') as stream:
                upload=client.put(url,content=stream)
            if upload.status_code not in {200,201,204}:raise ValueError('Signed file upload did not succeed')
            state.update(status='uploaded',uploaded_at=now())
            save(state_file,state)
            print(json.dumps(dict(status='uploaded',pdf_pages=14,pdf_bytes=PDF.stat().st_size,model=request['model_version'])),flush=True)
            return 0
        if not state.get('batch_id'):raise ValueError('No submitted MinerU task')
        for _ in range(180):
            response=client.get('https://mineru.net/api/v4/extract-results/batch/'+state['batch_id'],headers=headers)
            body=response.json()
            save(OUT/'last-status.private.json',json.loads(json.dumps(body).replace(key,'[REDACTED]')))
            if response.status_code!=200 or body.get('code')!=0:raise ValueError('Task status request failed')
            items=body['data']['extract_result']
            if not items:time.sleep(5);continue
            item=items[0];status=item['state']
            state.update(status=status,updated_at=now(),progress=item.get('extract_progress'))
            save(state_file,state)
            print(json.dumps(dict(status=status,progress=state.get('progress'))),flush=True)
            if status=='failed':return 3
            if status=='done':
                url=item['full_zip_url']
                if not url.startswith('https://'):raise ValueError('Result URL must use HTTPS')
                result=client.get(url,follow_redirects=True)
                result.raise_for_status()
                payload=result.content
                if len(payload)>100_000_000:raise ValueError('Result archive too large')
                path=OUT/'mineru-result.zip';path.write_bytes(payload)
                target=OUT/'mineru';target.mkdir(exist_ok=True)
                extract_archive(path,target)
                state.update(status='completed',completed_at=now(),archive_sha256=sha(payload),
                             artifacts={p.relative_to(target).as_posix():sha(p.read_bytes()) for p in sorted(target.rglob('*')) if p.is_file()})
                save(state_file,state)
                print(json.dumps(dict(status='completed',archive_bytes=len(payload),files=len(state['artifacts']))),flush=True)
                return 0
            time.sleep(5)
        print(json.dumps(dict(status='still_running',resume='poll')),flush=True)
        return 4


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['submit','poll'])
    args=parser.parse_args()
    try:sys.exit(main(args.action))
    except Exception as error:
        print(json.dumps(dict(status='client_error',type=type(error).__name__)),flush=True)
        sys.exit(1)
