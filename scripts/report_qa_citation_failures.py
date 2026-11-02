"""Read saved worker/evaluation/history JSON and render citation diagnostics offline."""
from argparse import ArgumentParser
from hashlib import sha256
from html import escape
import json
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def read_records(source: Path) -> list[dict]:
    source=source.resolve()
    if source.is_dir():
        directory=source/'results' if (source/'results').is_dir() else source
        files=sorted(directory.glob('*.json'))
    else:files=[source]
    if not files:raise ValueError('No saved JSON results found')
    rows=[]
    for path in files:
        raw=path.read_bytes();checksum=sha256(raw).hexdigest()
        values=[json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()] if path.suffix=='.jsonl' else [json.loads(raw)]
        for index,value in enumerate(values,1):
            if not isinstance(value,dict):raise ValueError('Expected a saved result object')
            body=value.get('response') if 'response' in value else value.get('result') if 'result' in value else value
            if body is None:body={}
            if not isinstance(body,dict) or ('status' not in body and 'status' not in value):
                raise ValueError('Input is not a saved worker/evaluation/history result')
            trace=body.get('citation_validation')
            if trace is not None:
                if (not isinstance(trace,dict) or trace.get('version')!='citation-validation-trace-v1'
                        or not isinstance(trace.get('attempts'),list)):
                    raise ValueError('Unknown citation diagnostic schema')
                for attempt in trace['attempts']:
                    if (attempt.get('status') not in {'passed','failed'} or type(attempt.get('attempt')) is not int
                            or attempt['attempt']<1):
                        raise ValueError('Invalid citation validation attempt')
                    if attempt.get('status')=='failed':
                        draft=attempt.get('draft')
                        if not isinstance(draft,dict) or sha256(encode(draft).encode('utf-8')).hexdigest()!=attempt.get('draft_sha256'):
                            raise ValueError('Failed draft checksum mismatch')
            rows.append(dict(id=value.get('task_id') or value.get('id') or f'{path.stem}:{index}',
                question=value.get('question'),status=body.get('status',value.get('status')),
                reason_code=body.get('reason_code'),final_answer=body.get('answer'),
                diagnostic_available=trace is not None,citation_validation=trace,
                source=dict(filename=path.name,row=index,sha256=checksum)))
    return rows


def publish(source: Path, output: Path) -> dict:
    if output.exists():raise ValueError('Use a new output directory; do not overwrite a report')
    rows=read_records(source)
    total_attempts=sum(len((r['citation_validation'] or {}).get('attempts',[])) for r in rows)
    failed_attempts=sum(a['status']=='failed' for r in rows for a in (r['citation_validation'] or {}).get('attempts',[]))
    summary=dict(records=len(rows),diagnostic_available=sum(r['diagnostic_available'] for r in rows),
        unavailable_records=sum(not r['diagnostic_available'] for r in rows),
        validation_attempts=total_attempts,failed_validation_attempts=failed_attempts,
        model_calls=0,answers_or_scores_changed=False)
    e=lambda value:escape(str(value),quote=True)
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>引用校验失败诊断</title><style>body{background:#f4f7fb;color:#203247;font:15px/1.7 system-ui;margin:24px auto;padding:0 18px;max-width:1100px}article,details{background:white;border:1px solid #dbe3ed;border-radius:8px;padding:16px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px}summary{cursor:pointer}strong{color:#a34816}</style>',
        '<h1>引用校验失败诊断</h1><p>失败草稿未经校验，仅供诊断，不是最终回答。每次只记录首先触发的一条规则；历史缺失信息不推测补写。此报告不调用模型、不重新评分。</p>',
        '<article><pre>'+e(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></article>']
    for row in rows:
        trace=row['citation_validation']
        parts+=['<details><summary>'+e(row['id'])+' · '+e(row['status'])+' · '+e(row['question'] or '未提供问题正文')+'</summary>',
            '<h3>最终返回</h3><pre>'+e(row['final_answer'] or '')+'</pre>']
        if trace is None:
            parts+=['<p>此旧记录未保存具体校验规则及失败草稿，无法还原；未重跑或补写。</p>']
        elif not trace['attempts']:
            parts+=['<p>本次未进入引用结构校验；请结合reason_code及生成调用判断阶段。</p>']
        for attempt in (trace or {}).get('attempts',[]):
            parts+=['<article><h3>第'+e(attempt['attempt'])+'次生成 · '+e(attempt['status'])+'</h3>']
            if attempt['status']=='failed':
                parts+=['<p><strong>'+e(attempt['message'])+'</strong></p><pre>'+e(encode({k:attempt.get(k) for k in ['rule_code','field','claim_index','supplied_refs','draft_sha256']}))+'</pre>',
                    '<h4>失败草稿（未经校验）</h4><pre>'+e(json.dumps(attempt['draft'],ensure_ascii=False,indent=2))+'</pre>']
            else:parts+=['<p>引用结构校验通过；未重复保存成功草稿。</p>']
            parts+=['</article>']
        parts+=['<details><summary>原始诊断与来源指纹</summary><pre>'+e(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></details>']
    parts+=['</html>']
    output.mkdir(parents=True)
    (output/'report.html').write_text(''.join(parts),encoding='utf-8',newline='\n')
    (output/'records.jsonl').write_text(''.join(encode(row)+'\n' for row in rows),encoding='utf-8',newline='\n')
    manifest=dict(summary=summary,files={p.name:sha256(p.read_bytes()).hexdigest() for p in output.iterdir()})
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return summary


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='Frozen run directory, worker JSON, or history JSONL export')
    parser.add_argument('--output',type=Path,required=True,help='New local output directory')
    args=parser.parse_args()
    try:print(encode(publish(args.input,args.output)))
    except (OSError,ValueError,KeyError,TypeError):
        parser.exit(1,'Unable to export diagnostics; check input schema, draft checksum and output path.\n')
