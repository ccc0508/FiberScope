"""Separate two-case retry overlay; never mutate first-attempt results."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.rag-data/evaluations/specialists-three-suites-20261107/state-retry-20261108'
OUT = ROOT / 'data/mixed-agent-evaluation/reports/state-retry-20261108'
OLD = ROOT / 'data/mixed-agent-evaluation/reports/grounded-coverage-full-20261108'


def read(p):
    return json.loads(p.read_text('utf8'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    notes = read(ROOT / 'data/mixed-agent-evaluation/calibration-state-retry-20261108.json')
    rubric = read(BASE / 'rubric.json')
    originals = read(OLD / 'results.json')
    rows = []
    for k in ('MIX06', 'MIX15'):
        p = BASE / (k + '.json')
        x = read(p)
        judge = read(BASE / 'mixed-jev-v1' / k / 'review.json')
        for d, value in notes[k]['scores'].items():
            assert value in [rubric['dimensions'][d]['weight'] * v for v in rubric['levels'].values()]
        rows.append(dict(id=k, question=x['question'], answer=x['answer'], status=x['status'],
                         raw_jev=judge, final=notes[k], total=sum(notes[k]['scores'].values()),
                         result_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                         source=str(p.relative_to(ROOT)), budget=x.get('budget_usage'),
                         format_checks=x.get('format_checks'), task_contract=x.get('task_contract'),
                         coverage=[dict(role=c['role'], report=c.get('coverage_report')) for c in x.get('children', [])],
                         tools=[dict(request=t['request'],status=t['status']) for t in x['tool_calls']]))
    retry = {r['id']: r for r in rows}
    selected = [retry.get(r['id'], r) for r in originals]
    summary = dict(first_attempt_mean=read(OLD/'summary.json')['calibrated_mean'],
                   first_attempt_completed=18, retry_completed=sum(r['status']=='completed' for r in rows),
                   overlay_mean=sum(r['total'] for r in selected)/20,
                   overlay_jev_mean=sum(r['raw_jev']['total'] for r in selected)/20,
                   overlay_completed=sum(r['status']=='completed' for r in selected),
                   integrity=read(BASE/'integrity.json'),
                   policy='Original 20-case first attempt preserved. Replace ONLY MIX06/MIX15 with this single new attempt for a separately named overlay; other 18 answers and scores unchanged. Not a fresh 20-case run or stability proof.',
                   cases=[dict(id=r['id'],total=r['total'],source=r.get('source',r.get('selected_source'))) for r in selected])
    for name, data in [('summary',summary),('retry-results',rows),('rubric',rubric)]:
        (OUT/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    def pre(data):
        return '<pre>'+html.escape(data if isinstance(data,str) else json.dumps(data,ensure_ascii=False,indent=2))+'</pre>'
    page='<html lang="zh-CN"><meta charset="utf-8"><title>第6、15题补跑评分</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccc;padding:20px}</style><h1>状态保存修复：两题补跑</h1><p>保留首轮81.125分；补跑组合分：'+str(summary['overlay_mean'])+'。这不是重新完成整轮20题的首轮成绩。</p>'+pre(summary)
    for r in rows:
        page+='<article id="'+r['id']+'"><h2>'+r['id']+'：'+str(r['total'])+'分</h2>'+pre(r['question'])+'<h3>校准评分</h3>'+pre(r['final'])+'<h3>完整回答</h3>'+pre(r['answer'])+'<details><summary>Jev原始评分</summary>'+pre(r['raw_jev'])+'</details><details><summary>轨迹与校验</summary>'+pre({k:v for k,v in r.items() if k not in ('answer','final','raw_jev')})+'</details></article>'
    (OUT/'report.html').write_text(page+'</html>',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == '__main__':
    main()
