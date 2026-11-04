"""Apply saved review proposals without content validation; isolated offline experiment."""
import json
from pathlib import Path
from hashlib import sha256
from html import escape
from argparse import ArgumentParser
ROOT=Path(__file__).resolve().parents[1]

def apply_unchecked(claims,issues):
    changes={};appended=[];events=[]
    for i,x in enumerate(issues):
        # Structural executability only; no source, text-anchor, citation or semantic checks.
        ci=x.get('claim_index');replacements=x.get('replacement_claims')
        if ci is not None and (type(ci) is not int or not 0<=ci<len(claims)):
            events.append(dict(issue=i,status='unexecutable_index'));continue
        if not isinstance(replacements,list) or any(not isinstance(c,dict) or not isinstance(c.get('text'),str) or not isinstance(c.get('citation_refs'),list) or any(not isinstance(r,str) for r in c['citation_refs']) for c in replacements):
            events.append(dict(issue=i,status='unexecutable_structure'));continue
        if ci in changes:
            events.append(dict(issue=i,status='duplicate_target_last_wins',claim_index=ci))
        else:events.append(dict(issue=i,status='applied',claim_index=ci))
        if ci is None:appended.extend(replacements)
        else:changes[ci]=replacements
    result=[c for i,c in enumerate(claims) for c in changes.get(i,[c])]+appended
    return result,events

def main():
    cli=ArgumentParser();cli.add_argument('--output',type=Path,required=True);args=cli.parse_args()
    if args.output.exists():raise ValueError('Preserve existing experiments')
    run=ROOT/'.rag-data/evaluations/unified-v31-full32-20261104'
    rows=[]
    for n in range(1,33):
        p=run/f'PFI2-{n:03}.json';data=json.loads(p.read_text(encoding='utf-8'))
        for ri,r in enumerate(data['evidence_review']['rounds']):
            artifact=(r.get('model_info') or {}).get('failure_artifact') or {}
            source='saved_parsed_issues';body=None
            if artifact.get('artifact_id'):
                a=run/'private-diagnostics'/(artifact['artifact_id']+'.json')
                if a.exists():
                    raw=json.loads(a.read_text(encoding='utf-8'))['response']
                    body=json.loads(raw);source='archived_raw_response'
            if body is None:body=dict(issues=r.get('model_issues',r.get('issues',[])))
            issues=body.get('issues')
            if not isinstance(issues,list):raise ValueError('No executable issue array')
            draft=r['draft'];claims,events=apply_unchecked(draft['claims'],issues)
            answer='\n'.join(c['text']+' '+' '.join(c['citation_refs']) for c in claims)
            rows.append(dict(task_id=data['case_id'],round=ri+1,question=data['question'],
                input_sha256=sha256(p.read_bytes()).hexdigest(),evidence_sha256=r['evidence_sha256'],
                proposal_origin=source,issues=issues,events=events,before=draft['answer'],after=answer,
                claims=claims,old_status=r['status'],old_accepted=r.get('accepted_issue_indexes',[]),
                old_rejections=r.get('rejected_issues',[])))
    summary=dict(mode='saved-output unchecked execution, independent round replay',questions=32,rounds=len(rows),
        proposals=sum(len(r['issues']) for r in rows),applied=sum(e['status']=='applied' for r in rows for e in r['events']),
        changed_rounds=sum(r['before'].strip()!=r['after'].strip() for r in rows),provider_calls=0,
        limitations=['Not fresh generation or a full counterfactual multi-round run; later model outputs depend on historical inputs.',
        'No content gates and no citation cleanup. Structural execution failures are reported, not silently fixed.',
        'No new Jev scores; old grades must not be assigned to these answers.'])
    args.output.mkdir(parents=True)
    (args.output/'results.json').write_text(json.dumps(dict(summary=summary,rounds=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>关闭内容校验对照</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui;padding:20px}article{border:1px solid #ddd;padding:20px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><h1>关闭内容校验：固定输出对照</h1><p>逐轮独立执行保存的修订，未重新调用模型，也不是新的完整多轮运行或评分。</p><pre>'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>']
    for r in rows:
        html.append('<article><h2>'+escape(r['task_id']+' 第'+str(r['round'])+'轮')+'</h2><p>'+escape(r['question'])+'</p><h3>执行前</h3><pre>'+escape(r['before'])+'</pre><h3>全部修订直接执行后</h3><pre>'+escape(r['after'])+'</pre><details><summary>原始修改及执行记录</summary><pre>'+escape(json.dumps(dict(issues=r['issues'],events=r['events']),ensure_ascii=False,indent=2))+'</pre></details></article>')
    (args.output/'comparison.html').write_text(''.join(html)+'</html>',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
