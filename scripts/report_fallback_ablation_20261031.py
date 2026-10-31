"""Offline matched-context deletion experiment; unchanged tasks diagnose stochastic variation."""
from pathlib import Path
import json

import judge_qa_eval as judge
import report_section_context_20261031 as legacy
import report_answer_guidance_20261031 as shared
from report_mineru_rag_20261029 import override
from section_context_20261031 import save
from validate_qa_eval import require

TAG='fallback-ablation-20261031'
ARMS=('control','guidance')
LABELS={'control':'原107块小节补全','guidance':'仅删回退额外邻块'}
LIMITATIONS=[
    '只删除原25次回退实际补入且并非主命中的邻块，不重新组块、分组、编号或补入替代片段，8000/24000字符上限及原科学证据保留。',
    '25次回退不是25道题，也不是25个不同邻块；涉及10道题，另22道题两臂完整输入相同。分别报告两类题目，不能将相同输入题的差异归功于删块。',
    '两臂均新答32题，使用同一模型别名/High/提示词/引用校验，最多两次生成；旧答案不混入主对照。',
    '只用Jev首个有效评分，最多3次尝试；缺失不记零，不改原判，无加权总分。五项同时达标是联合条件。',
    '只有单篇已见论文的一轮开发评测，生成和裁判波动未分开识别，不证明稳定性、统计显著性或泛化。',
    '没有新增解析、Embedding、检索或重排。相同输入题用于提示波动，不能作为已校正的效果估计。',
    'Token含推理用量，缓存与网络影响耗时和账单；答题实际货币费用未知，Jev API报告费用不是核验账单。',
    '网站默认配置不切换，既有107块和113块实验均保留。']


def collect(root,out):
    root,out=Path(root),Path(out);legacy.collect(root,out)
    p=judge.read_json(out/'analysis-input.json');c=judge.read_json(out/'experiment.json')
    p['version']='fallback-extras-deletion-v1'
    p['controls'].update(affected_tasks=c['affected_tasks'],unaffected_tasks=c['unaffected_tasks'],
        deletion_totals=c['deletion_totals'],deletion_proofs=c['deletion_proofs'],same_group_count_refs_and_primary=True,
        no_budget_redistribution=True)
    p['limitations']=LIMITATIONS;p['provenance'].update(engine_sha256=c['engine_sha256'],deletion_module_sha256=c['deletion_module_sha256'])
    save(out/'analysis-input.json',p);return dict(records=len(p['records']),provider_calls=0)


def analyze(p):
    require(p['controls']['no_budget_redistribution'] and p['controls']['same_group_count_refs_and_primary'],'Not a pure deletion study')
    r=legacy.analyze(p);records,tids,_=shared.checked_records(p);common=set(r['comparison']['task_ids'])
    affected=p['controls']['affected_tasks'];unaffected=p['controls']['unaffected_tasks']
    require(set(affected).isdisjoint(unaffected) and set(affected+unaffected)==set(tids),'Affected/unchanged task coverage differs')
    for tid in unaffected:
        require(records[('control',tid)]['candidate']['available_context']==records[('guidance',tid)]['candidate']['available_context'],
            'An unchanged-input task has different excerpts')
    r.update(version=p['version'],limitations=LIMITATIONS,
        affected_comparison=shared.paired(records,[t for t in affected if t in common]),
        unchanged_input_comparison=shared.paired(records,[t for t in unaffected if t in common]))
    return r


def render(path,r,p):
    with override(legacy,LABELS=LABELS):legacy.render(path,r,p)
    text=path.read_text('utf-8');intro='2026-10-31。同一107块索引、相同前8主命中、相同8000/24000字符上限；两版各重新回答32题，仅改变上下文补全方式。没有重新检索，未开启重排或新回答指引。'
    require(text.count(intro)==1,'Unexpected report template')
    text=text.replace(intro,'2026-10-31。两版各新答32题，仅删除原25次回退额外补入的邻块。原107块、主命中、证据分组和引用编号保留，删除后不补新片段。10题输入变化，22题输入完全相同。')
    text=text.replace('MinerU：同页邻块与小节补全对照','只删除回退额外邻块：对照评测').replace('MinerU上下文补全对照','删除回退邻块对照')
    sections=[]
    for key,label in [('affected_comparison','实际删块的题目'),('unchanged_input_comparison','输入完全相同的题目（波动观察）')]:
        c=r[key];rows=[]
        for a in ARMS:
            row=shared.cells(a,c['scores'][a]);row[0]=LABELS[a];rows.append(row)
        sections.append('<section><h2>'+label+'</h2>'+shared.table(shared.HEADERS,rows)+'</section>')
    text=text.replace('<h2>全部32题、两份新回答及Jev原始评分</h2>',''.join(sections)+'<h2>全部32题、两份新回答及Jev原始评分</h2>')
    path.write_text(text,encoding='utf-8',newline='\n')


def publish(root,out):
    root,out=Path(root),Path(out);dest=root/'data/literature/qa-evaluation/reports'/TAG;doc=root/'docs/QA_FALLBACK_ABLATION_REPORT_20261031.md'
    require(not dest.exists() and not doc.exists(),'Never overwrite a published experiment')
    p=judge.read_json(out/'analysis-input.json');r=analyze(p);dest.mkdir(parents=True)
    save(dest/'comparison.json',r);render(dest/'comparison.html',r,p)
    records,tids,standards=shared.checked_records(p)
    (dest/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(dict(task_id=t,reference_case=standards[t],
        records=[records[(a,t)] for a in ARMS]),ensure_ascii=False)+'\n' for t in tids),encoding='utf-8',newline='\n')
    lines=['# 仅删除回退额外邻块：对照评测','','2026-10-31。保留原107块和全部主命中，只移除25次回退实际额外补入的邻块，不重新分配预算。','',
        *sum(([n,''] for n in r['analyst_notes']),[])]
    for key,label in [('comparison','全部共同有效题'),('affected_comparison','实际删除邻块的题目'),('unchanged_input_comparison','输入完全相同的题目')]:
        c=r[key];lines+=['## '+label,'','| '+' | '.join(shared.HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |']
        for a in ARMS:
            row=shared.cells(a,c['scores'][a]);row[0]=LABELS[a];lines+=['| '+' | '.join(map(str,row))+' |']
        lines+=['','要点提高：'+str(c['point_wins'])+'；下降：'+str(c['point_losses']),'']
    lines+=['排除：'+json.dumps(r['comparison']['exclusions'],ensure_ascii=False),'',*LIMITATIONS,'',
        '[32题新回答、引用及Jev原判](../data/literature/qa-evaluation/reports/'+TAG+'/comparison.html)。','',
        '[实验方案](QA_FALLBACK_ABLATION_METHOD_20261031.md)。']
    doc.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    save(dest/'publication.json',dict(files={f.name:judge.digest(f) for f in dest.iterdir() if f.is_file()},document_sha256=judge.digest(doc),
        analysis_input_sha256=judge.digest(out/'analysis-input.json'),reporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    return dict(common_tasks=r['comparison']['tasks'],deltas=r['comparison']['deltas'],provider_calls=0)
