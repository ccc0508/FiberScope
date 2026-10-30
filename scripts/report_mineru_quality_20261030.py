"""Publish Jev-only, paired arithmetic for the 95-chunk parse-quality experiment."""
from argparse import ArgumentParser
from collections import Counter
from html import escape
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scores
from report_mineru_rag_20261029 import override
import report_qa_context_v1_20261029 as context
from validate_qa_eval import require

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.rag-data/evaluations'
STUDIES = {
    'quality': (PRIVATE/'mineru-quality-five-import-20261030-r1', PRIVATE/'mineru-quality-jev-20261030-r1'),
    'sections': (PRIVATE/'mineru-sections-v2-five-import-20261030-r1', PRIVATE/'mineru-sections-v2-five-judges-20261030-r1'),
    'pymupdf': (PRIVATE/'context-v1-five-import-20261029-r1', PRIVATE/'context-v1-five-judges-20261029-r1'),
    'native': (PRIVATE/'mineru-native-five-import-20261029-r1', PRIVATE/'mineru-native-five-judges-20261029-r1'),
}
RUNS = {s: PRIVATE/n for s,n in [
    ('quality','pfi-mineru-quality-v1-20261030-r1'), ('sections','pfi-mineru-sections-v2-20261030-r1'),
    ('pymupdf','pfi-context-v1-20261029-r1'), ('native','pfi-mineru-native-v1-20261029-r1')]}
LABELS = {'quality':'MinerU解析修复95块','sections':'MinerU章节107块','pymupdf':'PyMuPDF结构81块','native':'MinerU原生117块'}
OUTPUT = ROOT/'data/literature/qa-evaluation/reports/mineru-quality-jev-20261030'
DOC = ROOT/'docs/QA_MINERU_QUALITY_EVAL_20261030.md'


def save(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def seal_publication(output, document, exporter):
    value=dict(version='mineru-quality-jev-v1',document_sha256=judge.digest(document),
        exporter_sha256=judge.digest(exporter),
        files={p.name:judge.digest(p) for p in sorted(Path(output).iterdir()) if p.is_file() and p.name!='publication.json'})
    save(Path(output)/'publication.json',value)
    return value


def paired(metrics, task_ids, control):
    selected = [t for t in task_ids if all((s,t) in metrics and not metrics[(s,t)]['reference_concern'] for s in [control,'quality'])]
    require(bool(selected),'No valid paired questions')
    left = scores.summarize([metrics[(control,t)] for t in selected])
    right = scores.summarize([metrics[('quality',t)] for t in selected])
    return dict(control=control,task_ids=selected,tasks=len(selected),scores={control:left,'quality':right},
        point_delta=right['point_macro_average']-left['point_macro_average'],
        point_wins=[t for t in selected if metrics[('quality',t)]['point_mean']>metrics[(control,t)]['point_mean']],
        point_losses=[t for t in selected if metrics[('quality',t)]['point_mean']<metrics[(control,t)]['point_mean']],
        exclusions=[dict(task_id=t,unavailable=[s for s in [control,'quality'] if (s,t) not in metrics or metrics[(s,t)]['reference_concern']]) for t in task_ids if t not in selected])


def table(comparison):
    lines=['| 版本 | 题数 | 必答要点 | 事实完全支持 | 单条引用有效 | 引用组完整 | 边界 / 2 | 五项同时达标 |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for system, row in comparison['scores'].items():
        support=row['support_counts']; facts=sum(support.values())
        lines.append('| '+ ' | '.join([LABELS[system],str(row['tasks']),scores.percent(row['point_macro_average']),
            scores.ratio(scores.fraction(support.get('supported',0),facts)),scores.ratio(row['citation_precision']),
            scores.ratio(row['citation_coverage']),f"{row['boundary_mean']:.3f}",f"{row['all_five_pass']}/{row['tasks']}"])+' |')
    return '\n'.join(lines)


def html_report(path, result, rows):
    e=lambda x:escape(str(x),quote=True)
    pieces=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>解析修复：32题Jev评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}a{color:#2869bd}p{overflow-wrap:anywhere}.muted{color:#63788e}</style><main>',
        '<h1>MinerU解析修复：32题Jev评测</h1>',
        '<p>本轮仅Jev评分；旧版回答与评分直接复用。每项比较使用最大相同有效题目集合；无效评分缺失不计为零。没有加权总分。</p>',
        '<p>五项：必答要点、陈述事实支持、单条引用有效性、引用组完整性、回答边界。检索是否充分不混入这五项。</p>',
        '<p>有效Jev评分'+str(result['new_valid_grades'])+'/32。新Luna调用0，旧版重新评分0。</p>']
    for control, comparison in result['comparisons'].items():
        pieces+=['<section><h2>'+e(LABELS[control])+' → '+e(LABELS['quality'])+'</h2><div class="scroll"><table><thead><tr>']
        for label in ['版本','题数','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项同时达标']:
            pieces.append('<th>'+label+'</th>')
        pieces.append('</tr></thead><tbody>')
        for system, row in comparison['scores'].items():
            support=row['support_counts']; facts=sum(support.values())
            cells=[LABELS[system],row['tasks'],scores.percent(row['point_macro_average']),
                scores.ratio(scores.fraction(support.get('supported',0),facts)),scores.ratio(row['citation_precision']),
                scores.ratio(row['citation_coverage']),f"{row['boundary_mean']:.3f}",f"{row['all_five_pass']}/{row['tasks']}"]
            pieces.append('<tr>'+''.join('<td>'+e(c)+'</td>' for c in cells)+'</tr>')
        pieces+=['</tbody></table></div><p>要点变化：'+f"{comparison['point_delta']*100:+.2f}"+'个百分点；提高：'+e(comparison['point_wins'])+'；下降：'+e(comparison['point_losses'])+'。</p>',
            '<details><summary>排除题目及原因</summary><pre>'+e(json.dumps(comparison['exclusions'],ensure_ascii=False,indent=2))+'</pre></details></section>']
    if result.get('new_32_summary'):
        pieces+=['<section><h2>结果解读</h2><p>新版本单独32题必答要点：'+scores.percent(result['new_32_summary']['point_macro_average'])+'。对照表按31题分别配对，不能把32题均分直接与旧版31题均分比较。</p>',
            '<p>相对章节版，要点与边界分提高，引用组完整率及五项同时达标数下降；尚未全面超过当前PyMuPDF版本。</p>',
            '<p>第11题最终上下文仍未包含关键表格，两项必答要点均未得分。第32题恢复了摘要与正文相关系数冲突的说明，三个必答要点均得满分。</p>',
            '<details><summary>重点题的原始上下文诊断（不是新增评分维度）</summary><pre>'+e(json.dumps(result.get('case_diagnostics',{}),ensure_ascii=False,indent=2))+'</pre></details></section>']
    pieces+=['<details><summary>耗时、Token、评分费用与控制变量</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>',
        '<h2>全部32题</h2><p>Jev提供结构化标签、概率与证据定位，不生成自由文字理由。下方展示原始判断及来源；程序不补写裁判理由。</p>',
        '<input id="search" placeholder="搜索题号或问题，例如 PFI2-011">']
    for row in rows:
        pieces+=['<article data-search="'+e(row['task_id']+' '+row['question'])+'"><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与必答要点评分标准</summary><p>'+e(row['reference_answer'])+'</p><pre>'+e(json.dumps(row['key_points'],ensure_ascii=False,indent=2))+'</pre></details>']
        for system, content in row['systems'].items():
            metric=content.get('metrics')
            pieces+=['<details'+(' open' if system=='quality' else '')+'><summary>'+e(LABELS[system])+' · '+
                (e(f"要点 {metric['required_point_sum']}/{metric['required_point_count']}；边界 {metric['boundary']}/2") if metric else '评分缺失')+'</summary>',
                '<p>'+e(content['candidate']['answer']).replace('\n','<br>')+'</p>']
            if metric:
                pieces+=['<p>Jev要点：'+e(content['review']['key_point_scores'])+'；事实支持：'+e(metric['support_counts'])+'；单条引用：'+str(metric['supported_citations'])+'/'+str(metric['factual_citations'])+'；引用组完整：'+str(metric['complete_groups'])+'/'+str(metric['factual_claims'])+'。</p>']
            pieces+=['<details><summary>陈述核查、逐条引用与Jev原始判定</summary><pre>'+e(json.dumps(dict(metrics=metric,review=content.get('review')),ensure_ascii=False,indent=2))+'</pre></details>',
                '<details><summary>回答引用的原文及实际可用上下文</summary><pre>'+e(json.dumps(content['candidate'],ensure_ascii=False,indent=2))+'</pre></details></details>']
        pieces+=['<p>相对章节107块版要点变化：'+e(row['point_change_from_sections'])+'；相对PyMuPDF版：'+e(row['point_change_from_pymupdf'])+'。</p></article>']
    pieces+=['<p class="muted">32题属于开发评测，参考标准尚非专家金标准；单轮差异包含生成与裁判波动。模型别名无法锁定远程服务的实际权重版本。网站默认索引尚未切换。</p>',
        '<script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(pieces),encoding='utf-8',newline='\n')


def report(refresh=False):
    if refresh:
        publication=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==checksum for n,checksum in publication['files'].items()),'Existing publication changed')
        require(judge.digest(DOC)==publication['document_sha256'],'Existing report document changed')
    else:
        require(not OUTPUT.exists() and not DOC.exists(),'Use new publication destinations')
    audits={name:scores.audit(*paths) for name,paths in STUDIES.items()}
    new=audits['quality']
    require(set(new[2]['requested_judges'])=={'jev'},'This experiment must only use Jev')
    require(len(new[2]['jobs'])==32 and all(j['system']=='rag' and j['judge']=='jev' for j in new[2]['jobs']),
            'Unexpected judge or extra paid system jobs')
    require(all(status!='pending' for _,_,status in new[5]),'Wait for in-flight judge calls')
    jobs, reviews, metrics={}, {}, {}
    for system,a in audits.items():
        for job in a[1]:
            if job['system']!='rag':continue
            tid=job['task_id'];jobs[(system,tid)]=job
            review=a[3].get(('jev','rag',tid))
            if review is not None:
                reviews[(system,tid)]=review
                metrics[(system,tid)]=scores.metrics(review,job['reference_case'],job['task']['capabilities'])
    tids=sorted(t for s,t in jobs if s=='quality')
    require(len(tids)==32,'Expected 32 original questions')
    run=judge.read_json(RUNS['quality']/'run.json')
    for control in ['sections','pymupdf','native']:
        old=judge.read_json(RUNS[control]/'run.json')
        require(run['configuration_probe']==old['configuration_probe'] and run['tasks']==old['tasks'],
                'Controlled answer configuration or task changed')
        for tid in tids:
            require(jobs[(control,tid)]['reference_case']==jobs[('quality',tid)]['reference_case'],'Reference standard changed')
    controls=judge.read_json(ROOT/'.rag-data/configs/mineru-quality-v1-20261030-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==controls['application_env_sha256'],'Application settings changed')
    comparisons={s:paired(metrics,tids,s) for s in ['sections','pymupdf','native']}
    common=[t for t in tids if all((s,t) in metrics and not metrics[(s,t)]['reference_concern'] for s in LABELS)]
    with override(context,RUN=RUNS['quality']):runtime=context.runtime()
    calls=new[4].get('jev',[])
    accounting=scores.accounting(calls,'jev')
    structure=judge.read_json(RUNS['quality']/'library/structure.json')
    seeds=Counter()
    for tid in tids:
        answer=judge.read_json(RUNS['quality']/'results'/(tid+'.json'))
        for evidence in (answer.get('response') or {}).get('retrieval_seed_evidence',[]):
            seeds.update([structure['mapping'][evidence['chunk_id']]['kind']])
    result=dict(version='mineru-quality-jev-v1',published_on='2026-10-30',question_count=32,
        policy_sha256=grading.POLICY_SHA,judges=['jev'],new_luna_calls=0,new_control_grading_calls=0,
        new_valid_grades=sum(kind=='jev' and system=='rag' for kind,system,tid in new[3]),
        new_grading_statuses={status:n for (kind,system,status),n in new[5].items() if kind=='jev' and system=='rag'},
        new_grading_accounting=accounting,comparisons=comparisons,common_task_ids=common,
        common_scores={s:scores.summarize([metrics[(s,t)] for t in common]) for s in LABELS} if common else {},
        new_answer_runtime=runtime,controlled_configuration=run['configuration_probe'],
        seed_kind_counts=dict(seeds),index_chunks=structure['chunks'],index_quality_summary=structure['quality_summary'],
        historical_index_embedding_calls=structure['embedding_calls'],
        preprocessing_cost_note='Parse review and index embedding are from the preceding completed stage, not repeated this round.',
        active_application_configuration_unchanged=True,
        limitations=['Single development-set answer generation and one first-valid Jev grade per answer; no stability or holdout claim.',
                    'Provider model aliases/settings are frozen, not remote weights.',
                    'Original source references and the scoring policy are unchanged. No human grades assigned by this report.'])
    result['new_grading_attempts_by_task']={entry['task_id']:len(list((STUDIES['quality'][1]/'records'/entry['name']).glob('*.json'))) for entry in new[2]['jobs']}
    result['all_new_grades_valid_on_first_attempt']=all(n==1 for n in result['new_grading_attempts_by_task'].values()) and result['new_valid_grades']==32
    result['new_32_summary']=scores.summarize([metrics[('quality',t)] for t in tids if ('quality',t) in metrics and not metrics[('quality',t)]['reference_concern']])
    result['all_five_changes_from_sections']={
        'wins':[t for t in comparisons['sections']['task_ids'] if metrics[('quality',t)]['all_five_pass'] and not metrics[('sections',t)]['all_five_pass']],
        'losses':[t for t in comparisons['sections']['task_ids'] if metrics[('sections',t)]['all_five_pass'] and not metrics[('quality',t)]['all_five_pass']]}
    diagnostics={}
    for tid in ['PFI2-011','PFI2-032']:
        response=judge.read_json(RUNS['quality']/'results'/(tid+'.json'))['response']
        evidence=response.get('retrieved_evidence',[])
        text='\n'.join(e['text'] for e in evidence)
        table_sources=[s for e in evidence for s in e.get('source_chunks',[]) if s.get('kind')=='table']
        diagnostics[tid]=dict(key_point_scores=reviews[('quality',tid)]['key_point_scores'],
            supplied_page_ranges=[[e['page_start'],e['page_end']] for e in evidence],
            table_source_chunk_ids=[s['chunk_id'] for s in table_sources],
            literal_source_markers={value:value in text for value in ['70.42','72.54','73.01','75.06','0.888','0.912','0.889']},
            limitation='Raw source-kind and literal-value checks only; not semantic sufficiency or a new grade.')
    result['case_diagnostics']=diagnostics
    rows=[]
    for tid in tids:
        reference=jobs[('quality',tid)]['reference_case']
        values={s:metrics.get((s,tid)) for s in LABELS}
        rows.append(dict(task_id=tid,question=reference['question'],reference_answer=reference['reference_answer'],
            key_points=reference['key_points'],critical_errors=reference['critical_errors'],
            systems={s:dict(candidate=jobs[(s,tid)]['candidate'],metrics=values[s],review=reviews.get((s,tid))) for s in LABELS},
            point_change_from_sections=values['quality']['point_mean']-values['sections']['point_mean'] if values['quality'] and values['sections'] else None,
            point_change_from_pymupdf=values['quality']['point_mean']-values['pymupdf']['point_mean'] if values['quality'] and values['pymupdf'] else None))
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result)
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    save(OUTPUT/'audit.json',dict(policy_sha256=grading.POLICY_SHA,
        studies={s:dict(study_sha256=judge.digest(paths[1]/'study.json'),import_sha256=judge.digest(paths[0]/'import.json'),
            completed_grade_proofs=[p for p in audits[s][6] if p['name'].startswith('jev-')]) for s,paths in STUDIES.items()},
        new_calls=accounting['calls'],new_luna_calls=0,controlled_configuration_identical=True,reference_cases_identical=True))
    html_report(OUTPUT/'comparison.html',result,rows)
    lines=['# MinerU解析修复：32题Jev评测','',
        '2026-10-30。使用修复后的95块索引重新回答原32题，仅Jev评分；旧117块、章节107块和PyMuPDF 81块的回答与评分直接复用。',
        '',f"新回答：{runtime['outcomes']}；新有效Jev评分：{result['new_valid_grades']}/32。评分缺失不记为零；每组比较使用自己的最大相同有效题目集合。",'',
        '评分仍为原五项协议：必答要点、陈述事实支持、单条引用有效、引用组完整、回答边界。不计算加权总分，也不把检索充分性另加进总分。','']
    for control,c in comparisons.items():
        lines += ['## '+LABELS[control]+' → '+LABELS['quality'],'',table(c),'',
            f"共同{c['tasks']}题，必答要点变化{c['point_delta']*100:+.2f}个百分点。",'',
            '提高：'+(', '.join(c['point_wins']) or '无')+'。','下降：'+(', '.join(c['point_losses']) or '无')+'。','',
            '排除：'+json.dumps(c['exclusions'],ensure_ascii=False)+'。','']
    lines += ['## 结果解读与重点题','',
        f"新版本单独32题的必答要点为{scores.percent(result['new_32_summary']['point_macro_average'])}，五项同时达标{result['new_32_summary']['all_five_pass']}/32。它与31题配对表使用不同分母，应分别阅读。",'',
        '相对章节107块版，要点均分、事实支持率、单条引用有效率及边界分提高；引用组完整率略降，五项同时达标数20/31降至18/31。尚未全面超过当前PyMuPDF版。','',
        '- 第16、20、28、32题要点提高；第4、11、15题要点下降。',
        '- 第11题新上下文没有表格源块，也没有70.42→72.54等反例值，Jev两项要点均给0分；说明解析修复仍未解决该题关键表格进入最终证据的问题。',
        '- 第32题新上下文同时包含0.888、0.912、0.889，回答明确区分摘要与正文，Jev三个必答要点均为1；原章节版该题第二要点为0.5。',
        '- 第4题缺少对不同作用力条件的充分说明，第三要点由1降为0.5；第15题未明确指出不能把差异全部归因于浆种，第三要点由0.5降为0。',
        '- 五项同时达标的变化：第20题新增达标；第4、25、27题由达标变为未达标。要点齐全仍可能在事实或引用、边界维度失分。','',
        '这些分数是Jev原始判定，未由报告程序纠正或重新裁判。源块类型与数值字符串出现情况仅作为诊断，不等同于语义充分性指标。','']
    lines += ['## 用量与范围','',
        f"答题生成{runtime['generation_calls']}次，已知生成Token {runtime['generation_known_tokens'].get('total_tokens','未知')}；问题Embedding {runtime['embedding_known_tokens']} Token。端到端中位数{runtime['median_end_to_end_seconds']:.2f}秒，顺序执行累计{runtime['total_sequential_seconds']:.2f}秒。",'',
        f"本轮新增Jev请求{accounting['calls']}次；"+('32份评分均首次有效，无补评。' if result['all_new_grades_valid_on_first_attempt'] else '统计包含所有无效评分尝试。')+f"API报告费用${accounting['reported_cost_usd']}，费用未知请求{accounting['cost_unknown_calls']}次。API报告金额不是正式账单。新Luna调用0，旧版重新评分0。",'',
        '前一阶段的局部图片复核和索引Embedding未重复运行，费用与Token单独记录在解析修复说明中。答题和问题Embedding的实际货币结算金额未知。','',
        '32题属于开发集，参考答案不是专家金标准；单轮结果包含生成和裁判波动。所有语义评分来自Jev；报告程序只校验记录并做算术，不补写或改动评分。模型别名及配置一致，不能保证远程底层权重在不同日期完全相同。','',
        '完整答题配置、提示词源文件指纹、问题和评分规则与旧运行一致。原始数据、旧答案、旧评分及网站默认索引未修改。','',
        '[全部32题、四套回答与Jev逐项判断](../data/literature/qa-evaluation/reports/mineru-quality-jev-20261030/comparison.html)。',
        '[解析修复及局部复核说明](QA_MINERU_QUALITY_20261030.md)。','']
    DOC.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    seal_publication(OUTPUT,DOC,Path(__file__))
    return {k:result[k] for k in ['question_count','new_valid_grades','new_grading_accounting','comparisons']}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true',help='Offline re-export after checking the prior publication seal.')
    args=parser.parse_args()
    print(json.dumps(report(args.refresh),ensure_ascii=False))
