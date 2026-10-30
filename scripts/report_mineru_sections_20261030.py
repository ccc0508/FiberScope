"""Audit the section-organized experiment and report matched scores without API calls."""
from argparse import ArgumentParser
from collections import Counter
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scores
import report_qa_context_v1_20261029 as context
from report_mineru_rag_20261029 import override,score_cells
from validate_qa_eval import require

PRIVATE=ROOT/'.rag-data/evaluations'
STUDIES={
    'native':(PRIVATE/'mineru-native-five-import-20261029-r1',PRIVATE/'mineru-native-five-judges-20261029-r1'),
    'pymupdf':(PRIVATE/'context-v1-five-import-20261029-r1',PRIVATE/'context-v1-five-judges-20261029-r1'),
    'sections':(PRIVATE/'mineru-sections-v2-five-import-20261030-r1',PRIVATE/'mineru-sections-v2-five-judges-20261030-r1')}
RUN=PRIVATE/'pfi-mineru-sections-v2-20261030-r1'
OUTPUT=ROOT/'data/literature/qa-evaluation/reports/mineru-sections-v2-20261030'
DOC=ROOT/'docs/QA_MINERU_SECTIONS_V2_REPORT_20261030.md'
LABELS={'native':'MinerU原生117块','sections':'MinerU章节107块','pymupdf':'PyMuPDF结构81块'}


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def reuse():
    with override(context,NEW_IMPORT=STUDIES['sections'][0],NEW_STUDY=STUDIES['sections'][1]):
        context.reuse()


def paired(metrics,task_ids,control):
    output={}
    for kind in ['luna','jev']:
        chosen=[t for t in task_ids if all((kind,s,t) in metrics and not metrics[(kind,s,t)]['reference_concern'] for s in [control,'sections'])]
        require(chosen,'No valid matched comparison')
        output[kind]=dict(task_ids=chosen,tasks=len(chosen),
            scores={s:scores.summarize([metrics[(kind,s,t)] for t in chosen]) for s in [control,'sections']},
            point_wins=[t for t in chosen if metrics[(kind,'sections',t)]['point_mean']>metrics[(kind,control,t)]['point_mean']],
            point_losses=[t for t in chosen if metrics[(kind,'sections',t)]['point_mean']<metrics[(kind,control,t)]['point_mean']],
            exclusions=[dict(task_id=t,unavailable=[s for s in [control,'sections'] if (kind,s,t) not in metrics or metrics[(kind,s,t)]['reference_concern']]) for t in task_ids if t not in chosen])
    return output


def retrieval_diagnostics(run_dir):
    contract=judge.read_json(run_dir/'run.json')
    require(judge.digest(run_dir/'library/structure.json')==contract['initial_library_files']['structure.json'],'Frozen index mapping changed')
    mapping=judge.read_json(run_dir/'library/structure.json')['mapping']
    counts=Counter()
    with override(context,RUN=run_dir):
        runtime=context.runtime()
    for task in contract['tasks']:
        response=judge.read_json(run_dir/'results'/(task['id']+'.json')).get('response') or {}
        counts.update(mapping[e['chunk_id']]['kind'] for e in response.get('retrieval_seed_evidence',[]))
    return dict(seed_kind_counts=dict(counts),seed_total=sum(counts.values()),
        runtime={k:v for k,v in runtime.items() if k!='per_question'})


def report(refresh=False):
    if refresh:
        seal=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==h for n,h in seal['files'].items()),'Existing report changed')
        require(judge.digest(DOC)==seal['document_sha256'],'Existing report document changed')
    else:
        require(not OUTPUT.exists() and not DOC.exists(),'Use new report destinations')
    audited={name:scores.audit(*paths) for name,paths in STUDIES.items()}
    for a in audited.values():
        require(all(status!='pending' for _,_,status in a[5]),'Grading is still pending')
    old_dsh=context.OLD_STUDY;new_study=STUDIES['sections'][1]
    reused=judge.read_json(new_study/'reused-dsh-records.json')
    require(reused['source_study_sha256']==judge.digest(old_dsh/'study.json'),'Reused DSH source study changed')
    require(reused['target_study_sha256']==judge.digest(new_study/'study.json'),'Reuse target changed')
    for entry in reused['records']:
        require(judge.digest(new_study/entry['relative_path'])==entry['sha256']==judge.digest(old_dsh/entry['source_relative_path']),'Reused DSH attempt changed')
    jobs={};reviews={};metrics={}
    for system,a in audited.items():
        for job in a[1]:
            if job['system']!='rag':
                continue
            tid=job['task_id'];jobs[(system,tid)]=job
            for kind in ['luna','jev']:
                review=a[3].get((kind,'rag',tid))
                if review is not None:
                    reviews[(kind,system,tid)]=review
                    metrics[(kind,system,tid)]=scores.metrics(review,job['reference_case'],job['task']['capabilities'])
    tids=sorted(t for s,t in jobs if s=='sections');require(len(tids)==32,'Expected 32 questions')
    for tid in tids:
        require(all(jobs[(s,tid)]['reference_case']==jobs[('sections',tid)]['reference_case'] for s in STUDIES),'Reference standard changed')
    run=judge.read_json(RUN/'run.json')
    for other in ['pfi-mineru-native-v1-20261029-r1','pfi-context-v1-20261029-r1']:
        old=judge.read_json(PRIVATE/other/'run.json')
        require(run['configuration_probe']==old['configuration_probe'],'Controlled runtime configuration changed')
        require(run['tasks']==old['tasks'],'Questions, tasks or capabilities changed')
    config=judge.read_json(ROOT/'.rag-data/configs/mineru-sections-v2-20261030-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==config['application_env_sha256'],'Application default configuration changed')
    new=audited['sections'];study=new[2]
    new_calls={kind:[judge.read_json(p) for job in study['jobs'] if job['system']=='rag' and job['judge']==kind
        for p in sorted((new_study/'records'/job['name']).glob('*.json'),key=lambda p:int(p.stem))] for kind in ['luna','jev']}
    costs={k:scores.accounting(v,k) for k,v in new_calls.items()}
    with override(context,RUN=RUN):
        runtime=context.runtime()
    build=judge.read_json(ROOT/'.rag-data/index-versions/mineru-sections-v2-20261030/structure.json')
    comparisons={control:paired(metrics,tids,control) for control in ['native','pymupdf']}
    diagnostics={s:retrieval_diagnostics(PRIVATE/name) for s,name in [
        ('native','pfi-mineru-native-v1-20261029-r1'),('sections','pfi-mineru-sections-v2-20261030-r1'),('pymupdf','pfi-context-v1-20261029-r1')]}
    common=[t for t in tids if all((k,s,t) in metrics and not metrics[(k,s,t)]['reference_concern'] for k in ['luna','jev'] for s in STUDIES)]
    result=dict(version='mineru-sections-v2-evaluation',published_on='2026-10-30',question_count=32,
        policy_sha256=grading.POLICY_SHA,comparisons=comparisons,common_task_ids=common,
        common_scores={k:{s:scores.summarize([metrics[(k,s,t)] for t in common]) for s in STUDIES} for k in ['luna','jev']} if common else {},
        new_valid_grades=sum(s=='rag' for k,s,t in new[3]),
        grading_coverage={name:{k:{status:n for (kind,s,status),n in a[5].items() if kind==k and s=='rag'} for k in ['luna','jev']} for name,a in audited.items()},
        new_grading_accounting=costs,total_reported_grading_usd=str(sum((Decimal(c['reported_cost_usd']) for c in costs.values()),Decimal(0))),
        new_answer_runtime=runtime,retrieval_diagnostics=diagnostics,controlled_configuration=run['configuration_probe'],
        index_summary=dict(chunks=build['chunks'],sections=len(build['sections']),chunk_kinds=build['chunk_kinds'],
            source_coverage=build['source_coverage'],anomalies=dict(Counter(a['code'] for a in build['anomalies'])),
            embedding_calls=build['embedding_calls'],embedding_known_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in build['embedding_calls'])),
        rag_quote_verification=new[0].get('rag_quote_verification'),reused_dsh_jobs=64,new_dsh_provider_calls=0,
        active_application_configuration_unchanged=True,
        limitations=['One paper, 32 development questions, one generation per question, first valid grade per judge; no expert-gold, stability or generalization claim.',
          'Changes include inferred section labels in embedding/evidence plus paragraph split/merge and removal of standalone heading hits; not a single-factor parser comparison.',
          'The same neighbor algorithm sees different units after regrouping; parent-section expansion is not implemented.',
          'Reference availability, raw HTML tables, body duplicates, image-caption-only policy, prompt, models, providers and judge standards are unchanged.',
          'Old answers and valid grades are reused; provider randomness and judge variability remain.',
          'Program-generated chapter labels are marked metadata; exact native spans and original PDF pages support quotation review.',
          'Five metrics have separate denominators; no total accuracy or weighted overall score is assigned.'])
    rows=[]
    for tid in tids:
        gold=jobs[('sections',tid)]['reference_case']
        row=dict(task_id=tid,question=gold['question'],reference_answer=gold['reference_answer'],key_points=gold['key_points'],
                 capabilities=jobs[('sections',tid)]['task']['capabilities'],systems={})
        for system in LABELS:
            row['systems'][system]=dict(candidate={k:v for k,v in jobs[(system,tid)]['candidate'].items() if k!='available_context'},
                judges={kind:dict(review=reviews.get((kind,system,tid)),metrics=metrics.get((kind,system,tid))) for kind in ['luna','jev']})
        rows.append(row)
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result)
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    save(OUTPUT/'audit.json',dict(import_sha256={s:judge.digest(p[0]/'import.json') for s,p in STUDIES.items()},
        study_sha256={s:judge.digest(p[1]/'study.json') for s,p in STUDIES.items()},grade_proofs={s:a[6] for s,a in audited.items()},
        run_sha256=judge.digest(RUN/'run.json'),preview_publication_sha256=build['preview_publication_sha256'],
        reused_dsh_manifest_sha256=judge.digest(new_study/'reused-dsh-records.json'),exporter_assigns_no_scientific_scores=True))
    render(result,rows)
    save(OUTPUT/'publication.json',dict(files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    print(json.dumps({k:result[k] for k in ['new_valid_grades','comparisons','total_reported_grading_usd']},ensure_ascii=False))


def render(result,rows):
    e=lambda v:escape(str(v),quote=True)
    header=['评委','流程','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项同时达标']
    q10=next(r for r in rows if r['task_id']=='PFI2-010')
    old_q10=q10['systems']['native']['judges']['luna']['metrics']['point_mean']
    new_q10=q10['systems']['sections']['judges']['luna']['metrics']['point_mean']
    pair=result['comparisons']['native']['luna']
    q10_contribution=(new_q10-old_q10)*100/pair['tasks']
    hypothetical=(pair['scores']['sections']['point_macro_average']-(new_q10-old_q10)/pair['tasks'])*100
    notes=[
        '章节识别与组块已完成，但本轮没有得到两位裁判一致的质量提升。相对原117块，Luna的要点均分下降，Jev在30题配对集合上上升；事实和引用维度也存在裁判差异。',
        '对比当前PyMuPDF结构版时，新版在两位裁判各自相同题目上的要点得分、边界分和五项同时达标数均较低，默认索引继续保留PyMuPDF。',
        '第4、24、25题的要点评分在两位裁判下均比原117块版提高：分别补充了打浆作用力差异、贡献排名限制、补充表数值不可得的说明。',
        '第11题的新上下文没有包含70.42%到72.54%的数值反例；原117块上下文有这些数据。因此仍需改善关键表格召回，章节标签尚未保证找到对应结果小节。',
        '第28题新版只总结了PFI论文，没有说明第二篇论文未入库、无法比较，两位裁判均给该题必答要点0分。它因旧Jev评分缺失被排除在原117块的Jev主配对表外，不能忽略此退步。',
        '第32题新版遗漏摘要与正文相关系数不一致的说明，两位裁判都降低该项要点分；需要覆盖不同章节中的相关证据。',
        '复查确认第10题的裁判理由与原答案矛盾：新版两条数值陈述末尾均明确写有nm，Luna却以“未注明nm单位”为由给两个要点各0.5分；Jev两版均给满分。这项应标记为裁判误判，原始评分记录仍保留，不由报告程序改分。',
        f'评分敏感性核查：第10题的Luna题均分由{old_q10:g}变为{new_q10:g}，对32题宏平均贡献{q10_contribution:+.4f}个百分点。若仅假设该题保持旧版满分，新版Luna要点均分将为{hypothetical:.2f}%，与原117块版相同；这是反事实算术，不是新的正式评分，也不能消除其他题目的真实退步。',
        '下一轮优先诊断表格/跨章节证据覆盖与回答是否完成全部子问题；本轮未继续叠加优化，未根据评分改写已保存答案。']
    md=['# MinerU章节组块：32题双评对照','',
        '2026-10-30。本轮完成标题校验、章节归属、正文分组；使用已有MinerU解析，无新增PDF解析。答题模型、提示词、检索参数、上下文补全算法和评分标准与对照一致。','',
        f"新版32题生成，有效评分{result['new_valid_grades']}/64。每项对照、每位裁判使用各自最大相同有效题目集合，评分缺失不记为零分。",'',
        '## 结果解读与具体案例','',*['- '+n for n in notes],'']
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MinerU章节组块评测</title>',
       '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1560px;margin:32px auto;padding:0 24px}article,details{background:white;border:1px solid #dce5ef;border-radius:8px;padding:16px;margin:14px 0}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.7 monospace}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:white}td,th{padding:8px;border:1px solid #dce5ef;text-align:left;vertical-align:top}.answers{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-width:0}.answers>section{min-width:0}@media(max-width:1000px){.answers{display:block}}</style><main><h1>MinerU章节组块：32题双评对照</h1>',
       f"<p>107块章节版重新答题32题，有效评分{result['new_valid_grades']}/64。原117块版、PyMuPDF 81块版的回答与评分保留归档对照。</p>",
       '<p>仅改变入库前的章节标签与分组；单篇论文、单轮回答。章节标签是程序推断元数据，原文保留。不同指标不相加为整体正确率，缺失评分不记零分。</p>']
    h.append('<h2>结果解读与具体案例</h2><ul>'+''.join('<li>'+e(n)+'</li>' for n in notes)+'</ul>')
    for control,judges in result['comparisons'].items():
        title='主对照：原117块 → 章节107块' if control=='native' else '补充对照：当前PyMuPDF 81块 → 章节107块'
        md += ['## '+title,'','| '+' | '.join(header)+' |','| '+' | '.join(['---']*len(header))+' |']
        h.append('<h2>'+e(title)+'</h2><div class="scroll"><table><tr>'+''.join('<th>'+e(x)+'</th>' for x in header)+'</tr>')
        for kind,pair in judges.items():
            for system in [control,'sections']:
                cells=[kind,LABELS[system],*score_cells(pair['scores'][system])]
                md.append('| '+' | '.join(cells)+' |');h.append('<tr>'+''.join('<td>'+e(x)+'</td>' for x in cells)+'</tr>')
        h.append('</table></div>')
        for kind,pair in judges.items():
            delta=100*(pair['scores']['sections']['point_macro_average']-pair['scores'][control]['point_macro_average'])
            line=f"{kind}：{pair['tasks']}题，必答要点{delta:+.2f}个百分点，提高{len(pair['point_wins'])}题、下降{len(pair['point_losses'])}题。"
            md += ['',line,'','提高：'+(', '.join(pair['point_wins']) or '无')+'；下降：'+(', '.join(pair['point_losses']) or '无')+'。',
                   '配对排除：'+json.dumps(pair['exclusions'],ensure_ascii=False)+'。']
            h.append('<p>'+e(line)+'</p>')
    md += ['', '## 检索行为','',
        '以下为32题合计的主命中类型，标签分类只用于描述取证行为，不代表这些命中都相关或都无关。PyMuPDF的参考文献可能包含在普通段落内，其类型不可直接与MinerU细分类等同。','',
        *[f"- {LABELS[s]}：{json.dumps(d['seed_kind_counts'],ensure_ascii=False)}，总主命中{d['seed_total']}。" for s,d in result['retrieval_diagnostics'].items()],
        '', '## 用量与局限','',
        f"索引107块、14个章节节点，一次性Embedding {result['index_summary']['embedding_known_tokens']:,} Token。原始117单位字符在正文或标题来源中逐字完整覆盖。",'',
        f"答题已知生成Token {result['new_answer_runtime']['generation_known_tokens'].get('total_tokens',0):,}，生成{result['new_answer_runtime']['generation_calls']}次；问题Embedding {result['new_answer_runtime']['embedding_known_tokens']:,} Token。端到端中位数{result['new_answer_runtime']['median_end_to_end_seconds']:.2f}秒。",'',
        f"新增双评API报告费用${result['total_reported_grading_usd']}，包括无效评分尝试；答题和Embedding实际货币费用未知。DSH 64个评分任务复用原封存记录，没有新增DSH调用。",'',
        '- 原参考答案与五项评分协议不变。每位裁判每份答案最多3次评分尝试，接受首个有效结果，不择优。',
        '- 新增章节标签参与向量化和答题证据，已明确标记为程序元数据，引用核验仍使用原PDF及原始文字定位。',
        '- 没有修改科学数值、正文重复、表格HTML、参考文献可用性或图像理解；章节树不是对所有格式都可靠。',
        '- 尚未按父小节扩展上下文，仍是原同页邻块算法；重组后其实际相邻内容会变化。',
        '- 当前32题属于开发评测；单轮差异可能含生成与评委波动，不代表稳定性、统计显著性或新论文泛化。','',
        '[全部32题、三套回答与逐项双评理由](../data/literature/qa-evaluation/reports/mineru-sections-v2-20261030/comparison.html)。',
        '[章节目录、新旧块对照与来源映射](../data/literature/parsing-comparisons/mineru-sections-v2-20261030/comparison.html)。',
        '[实现与范围](QA_MINERU_SECTIONS_V2_20261030.md)。','',
        '网站默认配置未切换。离线重建：`python scripts/report_mineru_sections_20261030.py refresh`，需要本机封存的私有实验记录。']
    DOC.write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
    h.append('<details><summary>用量、评分覆盖、共同子集和完整审计摘要</summary><pre>'+e(json.dumps({k:v for k,v in result.items() if k!='new_answer_runtime'},ensure_ascii=False,indent=2))+'</pre></details><h2>全部32题</h2>')
    for row in rows:
        h.append('<article><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2><details><summary>参考答案与必答要点</summary><pre>'+e(row['reference_answer'])+'</pre><pre>'+e(json.dumps(row['key_points'],ensure_ascii=False,indent=2))+'</pre></details><div class="answers">')
        for system in LABELS:
            item=row['systems'][system];s='<section><h3>'+e(LABELS[system])+'</h3><pre>'+e(item['candidate']['answer'])+'</pre>'
            for kind,r in item['judges'].items():
                m=r['metrics']
                if m is None:
                    s+='<p>'+e(kind)+'：无有效评分</p>';continue
                s+='<p>'+e(kind)+f"：要点{scores.percent(m['point_mean'])}；事实{m['support_counts'].get('supported',0)}/{m['factual_claims']}；引用{m['supported_citations']}/{m['factual_citations']}；引用组{m['complete_groups']}/{m['factual_claims']}；边界{m['boundary']}/2。</p>"
                s+='<details><summary>'+e(kind)+'逐项评分与依据</summary><pre>'+e(json.dumps(r['review'],ensure_ascii=False,indent=2))+'</pre></details>'
            s+='<details><summary>原始引用与定位核验</summary><pre>'+e(json.dumps(item['candidate']['citations'],ensure_ascii=False,indent=2))+'</pre></details></section>'
            h.append('<details><summary>PyMuPDF 81块归档对照</summary>'+s+'</details>' if system=='pymupdf' else s)
        h.append('</div></article>')
    h.append('</main></html>');(OUTPUT/'comparison.html').write_text('\n'.join(h),encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('action',choices=['reuse','report','refresh']);args=parser.parse_args()
    reuse() if args.action=='reuse' else report(refresh=args.action=='refresh')
