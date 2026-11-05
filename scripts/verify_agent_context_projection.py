"""Replay stored tool results without APIs; verify lossless text reuse and sizes."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.agent_context import EvidenceProjection


def evidence_rows(r):
    yield from r.get('evidence',[])
    yield from r.get('sources',[])
    if 'table' in r:yield r['table']


def verify(directory):
    rows=[]
    for path in sorted(directory.glob('PFI2-*.json')):
        state=json.loads(path.read_text(encoding='utf-8'))
        projection=EvidenceProjection();parts={};refs={};raw_chars=compact_chars=0
        for event in state['tool_calls']:
            raw=event['result'];compact=projection.project(raw)
            raw_chars+=len(json.dumps(raw,ensure_ascii=False))
            compact_chars+=len(json.dumps(compact,ensure_ascii=False))
            original=list(evidence_rows(raw.get('result',{})))
            supplied=list(evidence_rows(compact.get('result',{})))
            assert len(original)==len(supplied)
            for old,new in zip(original,supplied):
                key=(new.get('document_id'),new['ref'])
                if new.get('already_provided'):text=refs[key]
                else:
                    pieces=[]
                    for part in new['text_parts']:
                        if 'text_id' in part:parts[part['text_id']]=part['text']
                        pieces.append(parts[part['reuse_text_id']] if 'reuse_text_id' in part else part['text'])
                    text=''.join(pieces);refs[key]=text
                assert text==old['text'],f'{path.stem}: changed text for {key}'
                assert old['ref']==new['ref']
        rows.append(dict(task_id=path.stem,raw_chars=raw_chars,compact_chars=compact_chars))
    assert rows,'No stored cases found'
    return dict(cases=len(rows),raw_chars=sum(r['raw_chars'] for r in rows),
        compact_chars=sum(r['compact_chars'] for r in rows),text_reconstruction='exact',
        api_calls=0,scope='Stored result replay only; not an answer-quality evaluation or budgeted live run.',rows=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();result=verify(a.directory)
    if a.output:a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))
