"""Publish a fixed-input corrective regression check, explicitly not a new 32-task score."""
from argparse import ArgumentParser
from hashlib import sha256
from html import escape
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text('utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def publish(before, after, notes, output):
    if output.exists():
        raise ValueError('Preserve existing reports')
    old_inputs={r['case_id']:r for r in read(before/'inputs.json')}
    new_inputs={r['case_id']:r for r in read(after/'inputs.json')}
    findings=read(notes)
    assert set(new_inputs)==set(findings)
    assert all(row['status']!='harness_failed' for row in read(after/'summary.json'))
    rows=[]
    for tid in sorted(new_inputs):
        assert new_inputs[tid]==old_inputs[tid], 'Initial input changed'
        old,new=read(before/(tid+'.json')),read(after/(tid+'.json'))
        assert old['evidence_review']['initial_evidence']==new['evidence_review']['initial_evidence']
        assert old['evidence_review']['original_draft']==new['evidence_review']['original_draft']
        rows.append(dict(task_id=tid,question=new['question'],before_answer=old['answer'],
            after_answer=new['answer'],before_summary=old['review_summary'],after_summary=new['review_summary'],
            source_review=findings[tid],before_sha256=digest(before/(tid+'.json')),
            after_sha256=digest(after/(tid+'.json')),trace=new['evidence_review']))
    summary=dict(version='corrective-recovery-check-v1',evaluated_version=read(after/'manifest.json')['mode'],
        selected_tasks=list(new_inputs),first_attempt_only=True,initial_inputs_identical=True,
        primary_generation_calls=0,judge_calls=0,aggregate_32_score=None,reviewer='Codex source inspection',
        limitations=['Four selected regression questions, one attempt each; not full quality evaluation.',
            'Source inspection is not an independent model judge or a human expert score.'],
        findings=findings,after_manifest_sha256=digest(after/'manifest.json'))
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>有限纠正v2.1修复验证</title><style>body{max-width:1050px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui;background:#f5f7fa;color:#18324b}article{background:white;padding:22px;margin:20px 0;border:1px solid #dde4ed;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer}</style>',
        '<h1>有限纠正v2.1修复验证</h1><p>四道选定回归题，各运行一次。原问题、原始草稿和首次证据相同；只运行修复后的审校及有限补查。没有调用Jev/Luna，不计算或更新32题总分。</p>',
        '<p>以下判断为Codex按实际来源和运行记录检查，不能代替独立评测。原有32题报告保持不变。</p>']
    for r in rows:
        html+=['<article><h2>'+escape(r['task_id']+' '+r['question'])+'</h2><p>'+escape(r['source_review']['conclusion'])+'</p>',
            '<h3>修复前</h3><pre>'+escape(r['before_answer'])+'</pre><h3>修复后</h3><pre>'+escape(r['after_answer'])+'</pre>']
        for label,key in [('来源检查与限制','source_review'),('流程状态','after_summary'),('完整修订及补查记录','trace')]:
            html+=['<details><summary>'+label+'</summary><pre>'+escape(json.dumps(r[key],ensure_ascii=False,indent=2))+'</pre></details>']
        html+=['</article>']
    html+=['</html>']
    files={'comparison.html':''.join(html),'summary.json':json.dumps(summary,ensure_ascii=False,indent=2),
        'cases.jsonl':''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)}
    from dotenv import dotenv_values
    for env in Path('backend').glob('.env*'):
        for key,value in dotenv_values(env).items():
            if value and len(value)>=12 and key.upper().endswith(('API_KEY','PASSWORD','TOKEN','BEARER_TOKEN')):
                assert all(value not in text for text in files.values()), 'Private value in output'
    output.mkdir(parents=True)
    for name,text in files.items():(output/name).write_text(text,encoding='utf-8',newline='\n')
    (output/'publication.json').write_text(json.dumps({n:digest(output/n) for n in files},indent=2),encoding='utf-8')
    return dict(questions=len(rows),judge_calls=0,output=str(output))


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    for flag in ['before','after','notes','output']:parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(publish(args.before,args.after,args.notes,args.output),ensure_ascii=False))
