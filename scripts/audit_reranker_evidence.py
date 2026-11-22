"""Summarize reviewed point-to-evidence mappings against immutable reranker pools.

Semantic judgments are supplied in annotations. This program validates identities,
tests whether the selected chunks contain the reviewed evidence, and aggregates
coverage; it does not replace semantic review with keyword/page matching.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import html
import json
from pathlib import Path
import statistics

MODELS = ('bge', 'qwen', 'jev')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def score_atom(atom, selected):
    if set(atom['candidates']) & selected:
        return 1
    if set(atom.get('partial_candidates',[])) & selected:
        return .5
    return 0


def score_point(point, selected):
    if point.get('not_applicable'):
        return None
    values = [score_atom(atom, selected) for atom in point['atoms']]
    if not values:
        raise ValueError('An applicable point must have at least one reviewed subfact')
    return 1 if all(v==1 for v in values) else .5 if any(v>0 for v in values) else 0


def validate_annotations(pools, gold, annotations, rankings, models=MODELS):
    if annotations.get('frozen_pool_sha256') != digest(pools):
        raise ValueError('Reviewed evidence belongs to a different frozen pool')
    expected={r['id'] for r in pools['rows']}
    if set(annotations['case_annotations']) != expected or set(rankings) != expected:
        raise ValueError('Incomplete annotation or ranking case set')
    for row in pools['rows']:
        cid=row['id'];points=annotations['case_annotations'][cid]
        if len(points)!=len(gold[cid]['key_points']):
            raise ValueError('Gold point count changed: '+cid)
        count=len(row['candidates'])
        ids={c['chunk_id'] for c in row['candidates']}
        if len(ids)!=count:
            raise ValueError('Candidate identities are not unique')
        for model in models:
            ranked=rankings[cid]['models'][model]
            if ranked['status']!='completed' or len(ranked['ranking'])!=count or set(ranked['ranking'])!=ids:
                raise ValueError('Not a complete ranking of the frozen pool: '+cid)
            if ranked.get('top_ids')!=ranked['ranking'][:8]:
                raise ValueError('Saved top-8 list disagrees with ranking: '+cid)
        for point in points:
            if point.get('not_applicable'):
                if point['atoms']:
                    raise ValueError('Not-applicable point contains evidence atoms')
                continue
            if not point['atoms']:
                raise ValueError('Unreviewed point')
            for atom in point['atoms']:
                if not atom.get('label'):
                    raise ValueError('Missing semantic subfact')
                for key in ['candidates','partial_candidates']:
                    values=atom.get(key,[])
                    if len(set(values))!=len(values) or any(type(i) is not int or not 0<=i<count for i in values):
                        raise ValueError('Invalid reviewed candidate index')
                if set(atom['candidates']) & set(atom.get('partial_candidates',[])):
                    raise ValueError('Same evidence graded both full and partial')


def failure_stage(score, pool_score):
    if score==1:
        return 'covered'
    if pool_score==1:
        return 'rerank_omitted_available_evidence'
    if pool_score==0:
        return 'missing_from_frozen_candidate_pool'
    if score<pool_score:
        return 'candidate_pool_incomplete_and_rerank_loss'
    return 'candidate_pool_only_partial_evidence'


def make_report(output, gold_path):
    pools=read(output/'pools.json')
    rankings={r['id']:r for r in read(output/'details.json')}
    annotations=read(output/'semantic-audit-annotations.json')
    # Keep the original three-model reports replayable; evaluate newly supplied
    # model rankings using the very same source-to-fact annotations.
    first=next(iter(rankings.values()))
    models=[*MODELS,*[m for m in first['models'] if m not in (*MODELS,'vector')]]
    gold={r['id']:r for r in map(json.loads,gold_path.read_text(encoding='utf-8').splitlines())}
    if annotations.get('gold_sha256') != sha256(gold_path.read_bytes()).hexdigest():
        raise ValueError('Reviewed key points changed')
    validate_annotations(pools,gold,annotations,rankings,models=models)
    cases=[]
    for row in pools['rows']:
        cid=row['id'];index_by_id={c['chunk_id']:i for i,c in enumerate(row['candidates'])}
        selected={m:{index_by_id[i] for i in rankings[cid]['models'][m]['ranking'][:8]} for m in models}
        case=dict(id=cid,group=row['group'],question=row['question'],reference_answer=gold[cid]['reference_answer'],points=[],models={})
        for n,point in enumerate(annotations['case_annotations'][cid],1):
            pool_score=score_point(point,set(range(len(row['candidates']))))
            checked=dict(point_id=f'P{n}',text=gold[cid]['key_points'][n-1],note=point.get('note',''),
                not_applicable=point.get('not_applicable'),pool_score=pool_score,atoms=[],models={})
            for atom in point['atoms']:
                evidence=[]
                for strength,key in [('full','candidates'),('partial','partial_candidates')]:
                    for index in atom.get(key,[]):
                        source=row['candidates'][index]
                        evidence.append(dict(candidate_index=index,strength=strength,**source,
                            text_sha256=sha256(source['text'].encode()).hexdigest(),
                            ranks={m:rankings[cid]['models'][m]['ranking'].index(source['chunk_id'])+1 for m in models}))
                checked['atoms'].append(dict(label=atom['label'],evidence=evidence))
            for model in models:
                score=score_point(point,selected[model])
                checked['models'][model]=dict(score=score,stage=failure_stage(score,pool_score) if score is not None else 'not_applicable',
                    atom_scores=[score_atom(atom,selected[model]) for atom in point['atoms']],
                    missing_subfacts=[atom['label'] for atom in point['atoms'] if score_atom(atom,selected[model])<1])
            case['points'].append(checked)
        for model in models:
            values=[p['models'][model]['score'] for p in case['points'] if p['models'][model]['score'] is not None]
            case['models'][model]=dict(applicable_points=len(values),weighted_coverage=statistics.mean(values),fully_covered_points=values.count(1),
                partial_points=values.count(.5),missing_points=values.count(0),all_points_covered=all(v==1 for v in values))
        cases.append(case)
    applicable=[p for c in cases for p in c['points'] if p['pool_score'] is not None]
    summary=dict(version='rerank-point-evidence-audit-v1',reviewer=annotations['reviewer'],additional_api_calls=0,
        frozen_pool_sha256=digest(pools),annotation_sha256=digest(annotations),gold_sha256=sha256(gold_path.read_bytes()).hexdigest(),
        ranking_sha256=digest(rankings),review_blinded=False,
        total_cases=len(cases),total_gold_points=sum(len(c['points']) for c in cases),applicable_points=len(applicable),
        not_applicable_points=[dict(case_id=c['id'],point=p['point_id'],reason=p['not_applicable']) for c in cases for p in c['points'] if p['pool_score'] is None],
        candidate_pool=dict(fully_supported_points=sum(p['pool_score']==1 for p in applicable),partial_points=sum(p['pool_score']==.5 for p in applicable),missing_points=sum(p['pool_score']==0 for p in applicable)),models={},policy=annotations['policy'])
    for model in models:
        values=[p['models'][model]['score'] for p in applicable]
        stages={p['models'][model]['stage'] for p in applicable}
        summary['models'][model]=dict(fully_covered_points=values.count(1),partial_points=values.count(.5),missing_points=values.count(0),
            complete_coverage=values.count(1)/len(values),weighted_coverage=statistics.mean(values),
            case_macro_weighted_coverage=statistics.mean(c['models'][model]['weighted_coverage'] for c in cases),
            fully_covered_cases=sum(c['models'][model]['all_points_covered'] for c in cases),
            stages={s:sum(p['models'][model]['stage']==s for p in applicable) for s in sorted(stages)},
            by_group={g:dict(cases=sum(c['group']==g for c in cases),weighted_coverage=statistics.mean(p['models'][model]['score'] for c in cases if c['group']==g for p in c['points'] if p['pool_score'] is not None)) for g in ['single','cross']})
    (output/'semantic-audit-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'semantic-audit-details.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape
    body='<h1>逐要点证据覆盖核对</h1><p>同一24题、同一50候选池、各模型前8条原文块。由Codex逐条进行语义核对，程序仅校验编号并汇总，不调用Jev或其他API作裁判。本报告检查证据是否已被选出，尚未计入章节补全或Agent补查。</p>'
    body+='<p>完整1、部分0.5、缺失0。允许同义表述、多块共同支持，以及由来源数据作出的合理推论。仅命中同一页、只出现关键词或引用其他研究，不能替代目标论文的实际事实。不适用的纯写作/计算/管理建议另列。</p>'
    body+='<table><tr><th>模型</th><th>完整要点</th><th>部分要点</th><th>缺失要点</th><th>完整覆盖率</th><th>加权覆盖率</th><th>整题证据齐全</th></tr>'
    for model,m in summary['models'].items():
        values=[model,str(m['fully_covered_points']),str(m['partial_points']),str(m['missing_points']),f"{m['complete_coverage']*100:.2f}%",f"{m['weighted_coverage']*100:.2f}%",f"{m['fully_covered_cases']}/{len(cases)}"]
        body+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>'
    body+='</table><p>完整覆盖率＝完整要点数/适用要点数；加权覆盖率＝(完整数＋0.5×部分数)/适用要点数。这些是要点所需证据的覆盖率，不是生成答案准确率；没有重跑回答模型。以下列出所有题目、所有要点、失分阶段与原文，便于复查本次Codex判断。</p>'
    body+='<details><summary>口径、共同候选池缺口与数据指纹</summary><pre>'+esc(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>'
    labels={1:'完整',.5:'部分',0:'缺失',None:'不适用'}
    for case in cases:
        body+=f"<h2 id='{case['id']}'>{esc(case['id']+' '+case['question'])}</h2><p>参考答案：{esc(case['reference_answer'])}</p>"
        body+='<table><tr><th>要点</th>'+''.join('<th>'+esc(m)+'</th>' for m in models)+'<th>50候选池</th></tr>'
        for point in case['points']:
            body+='<tr><td>'+esc(point['point_id']+' '+point['text'])+'</td>'+''.join('<td>'+labels[point['models'][m]['score']]+'</td>' for m in models)+'<td>'+labels[point['pool_score']]+'</td></tr>'
        body+='</table>'
        for point in case['points']:
            body+='<details><summary>'+esc(point['point_id']+' 原文依据与缺失项')+'</summary>'
            if point['not_applicable']:
                body+='<p>'+esc(point['not_applicable'])+'</p>'
            else:
                if point['note']:body+='<p>判定说明：'+esc(point['note'])+'</p>'
                for model in models:
                    item=point['models'][model]
                    body+='<p>'+esc(model+'：'+labels[item['score']]+'；阶段 '+item['stage']+'；不足：'+'；'.join(item['missing_subfacts']))+'</p>'
                for atom in point['atoms']:
                    body+='<h4>'+esc(atom['label'])+'</h4>'
                    if not atom['evidence']:
                        body+='<p>当前50条候选中没有找到能支持该具体事实的原文。</p>'
                    for source in atom['evidence']:
                        ranks=' / '.join(f'{m}:{source["ranks"][m]}' for m in models)
                        body+='<details><summary>'+esc(f"C{source['candidate_index']:02} {source['chunk_id']} | {source['document_id']} | PDF {source['page_start']}–{source['page_end']} | {source['strength']} | 排名 {ranks}")+'</summary><pre>'+esc(source['text'])+'</pre></details>'
            body+='</details>'
    (output/'semantic-audit.html').write_text('<!doctype html><meta charset="utf-8"><title>逐要点证据覆盖核对</title><style>body{max-width:1200px;margin:32px auto;font:15px/1.7 sans-serif;color:#203044}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{border:1px solid #cbd5e1;padding:9px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:14px}summary{cursor:pointer;padding:10px;background:#edf2f7;margin:8px 0}h2{margin-top:45px}h4{margin-bottom:6px}</style>'+body,encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gold',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(make_report(args.output,args.gold),ensure_ascii=False,indent=2))
