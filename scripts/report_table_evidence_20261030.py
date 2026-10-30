"""Audit table-row/source-link retrieval and publish paired Jev grades without changing them."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sqlite3

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import report_qa_context_v1_20261029 as runtime_report
from report_mineru_rag_20261029 import override
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.rag-data/evaluations'
RUNS={
    'tables':PRIVATE/'pfi-table-evidence-v1-20261030-r1',
    'quality':PRIVATE/'pfi-mineru-quality-v1-20261030-r1',
    'pymupdf':PRIVATE/'pfi-context-v1-20261029-r1',
}
STUDIES={
    'tables':(PRIVATE/'table-evidence-five-import-20261030-r1',PRIVATE/'table-evidence-jev-20261030-r1'),
    'quality':(PRIVATE/'mineru-quality-five-import-20261030-r1',PRIVATE/'mineru-quality-jev-20261030-r1'),
    'pymupdf':(PRIVATE/'context-v1-five-import-20261029-r1',PRIVATE/'context-v1-five-judges-20261029-r1'),
}
LABELS={'tables':'表格行检索＋关联补全','quality':'解析修复95块','pymupdf':'PyMuPDF结构81块'}
OUTPUT=ROOT/'data/literature/qa-evaluation/reports/table-evidence-jev-20261030'
DOC=ROOT/'docs/QA_TABLE_EVIDENCE_EVAL_20261030.md'
ALLOWED_SOURCE_CHANGES={'literature_rag/application/retrieve.py','literature_rag/application/table_evidence.py',
    'literature_rag/config.py','literature_rag/diagnostics.py','literature_worker.py'}


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def source_controls(new_dir,old_dir):
    new_dir,old_dir=Path(new_dir),Path(old_dir)
    a,b=judge.read_json(new_dir/'run.json'),judge.read_json(old_dir/'run.json')
    require(a['tasks']==b['tasks'],'Questions or capabilities changed')
    changes={'pipeline_version','prompt_pipeline_sha256','pipeline_source_files','table_retrieval'}
    left={k:v for k,v in a['configuration_probe'].items() if k not in changes}
    right={k:v for k,v in b['configuration_probe'].items() if k not in changes}
    require(left==right,'Model, prompt settings, thresholds or budgets changed')
    expected=a['configuration_probe'].get('table_retrieval',{})
    require(expected.get('enabled') and expected.get('version')=='table-evidence-v1','Table retrieval is not enabled')
    changed=[];unchanged=[]
    names={n for run in [a,b] for n in run['source_files'] if n.startswith('literature_rag/') or n=='literature_worker.py'}
    for name in sorted(names):
        paths=[directory/'backend'/name for directory in [new_dir,old_dir]]
        for path,run in zip(paths,[a,b],strict=True):
            if path.is_file():require(judge.digest(path)==run['source_files'][name],'Frozen runtime code changed')
        texts=[p.read_bytes().replace(b'\r\n',b'\n') if p.is_file() else None for p in paths]
        if texts[0]!=texts[1]:
            require(name in ALLOWED_SOURCE_CHANGES,'Unapproved runtime source change: '+name)
            changed.append(name)
        else:unchanged.append(name)
    for required in ['literature_rag/application/prompts.py','literature_rag/application/citations.py',
                     'literature_rag/application/answer_question.py','literature_rag/adapters/providers/deepseek.py',
                     'literature_rag/application/context.py']:
        require(required in unchanged,'Answer generation or existing context logic changed')
    return dict(configuration_equal_except_explicit_retrieval_feature=True,
        changed_source_files=changed,unchanged_source_files=unchanged,
        same_questions=True,same_answer_prompt_generator_and_citation_validator=True,
        source_comparison='Byte comparison after CRLF/LF normalization; original file fingerprints also verified.')


def paired(metrics,tids,control):
    selected=[t for t in tids if all((s,t) in metrics and not metrics[(s,t)]['reference_concern'] for s in [control,'tables'])]
    require(bool(selected),'No valid paired questions')
    summaries={s:scoring.summarize([metrics[(s,t)] for t in selected]) for s in [control,'tables']}
    return dict(task_ids=selected,tasks=len(selected),scores=summaries,
        point_delta=summaries['tables']['point_macro_average']-summaries[control]['point_macro_average'],
        point_wins=[t for t in selected if metrics[('tables',t)]['point_mean']>metrics[(control,t)]['point_mean']],
        point_losses=[t for t in selected if metrics[('tables',t)]['point_mean']<metrics[(control,t)]['point_mean']],
        all_five_wins=[t for t in selected if metrics[('tables',t)]['all_five_pass'] and not metrics[(control,t)]['all_five_pass']],
        all_five_losses=[t for t in selected if metrics[(control,t)]['all_five_pass'] and not metrics[('tables',t)]['all_five_pass']],
        exclusions=[dict(task_id=t,missing_or_flagged=[s for s in [control,'tables'] if (s,t) not in metrics or metrics[(s,t)]['reference_concern']]) for t in tids if t not in selected])


def score_cells(system,row):
    supports=row['support_counts'];n=sum(supports.values())
    return [LABELS[system],row['tasks'],scoring.percent(row['point_macro_average']),
        scoring.ratio(scoring.fraction(supports.get('supported',0),n)),scoring.ratio(row['citation_precision']),
        scoring.ratio(row['citation_coverage']),f"{row['boundary_mean']:.3f}",f"{row['all_five_pass']}/{row['tasks']}"]


HEADERS=['版本','题数','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项全部达标']


def html_report(path,result,rows):
    e=lambda value:escape(str(value),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>表格检索优化：32题Jev评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}p{overflow-wrap:anywhere}</style><main>',
        '<h1>表格行检索＋关联补全：32题Jev评测</h1>',
        '<p>保留95个原证据块，新增20条行检索表示及9条正文—表格关联。行表示不直接成为回答引文；命中后返回完整原表。</p>',
        '<p>本轮有效Jev评分：'+str(result['valid_grades'])+'/32。旧评分直接复用，未新增Luna评分。五项规则不变，缺失不记零分，不计算加权总分。</p>']
    for control,c in result['comparisons'].items():
        html+=['<section><h2>'+e(LABELS[control])+' → '+e(LABELS['tables'])+'</h2><div class="scroll"><table><tr>'+''.join('<th>'+e(h)+'</th>' for h in HEADERS)+'</tr>']
        for system,value in c['scores'].items():html.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in score_cells(system,value))+'</tr>')
        html+=['</table></div><p>要点变化：'+f"{c['point_delta']*100:+.2f}"+'个百分点。提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'。</p>',
            '<p>新增全部达标：'+e(c['all_five_wins'])+'；失去全部达标：'+e(c['all_five_losses'])+'。</p>',
            '<details><summary>共同题目与排除原因</summary><pre>'+e(json.dumps(dict(task_ids=c['task_ids'],exclusions=c['exclusions']),ensure_ascii=False,indent=2))+'</pre></details></section>']
    primary=result['comparisons'].get('quality')
    if primary:
        html+=['<section><h2>本轮结果解读</h2><p>相同'+str(primary['tasks'])+'题：必答要点变化'+f"{primary['point_delta']*100:+.2f}"+'个百分点，五项全部达标由'+str(primary['scores']['quality']['all_five_pass'])+'题变为'+str(primary['scores']['tables']['all_five_pass'])+'题。</p>',
            '<p>引用组完整率提高；事实完全支持率、单条引用有效率和边界均分略降。第11题仍未拿到结晶度关键表；第13题丢失原文机制解释的不确定性，第20题一条引用未通过Jev判断。</p>',
            '<p>相对PyMuPDF，全部达标题数略多，但必答要点和边界分仍较低。这是一次开发集结果，尚不能称为全面或稳定超过。</p></section>']
    html+=['<details><summary>耗时、费用、检索行为与控制变量</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>',
        '<h2>全部32题</h2><p>Jev输出结构化判断及证据定位，不生成自由文字理由；程序不补写裁判意见。</p><input id="search" placeholder="搜索题号或问题">']
    for row in rows:
        html+=['<article data-search="'+e(row['task_id']+' '+row['question'])+'"><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与评分要点</summary><p>'+e(row['reference_answer'])+'</p><pre>'+e(json.dumps(row['key_points'],ensure_ascii=False,indent=2))+'</pre></details>']
        for system,value in row['systems'].items():
            metric=value.get('metrics');review=value.get('review')
            label=(f"要点 {metric['required_point_sum']}/{metric['required_point_count']}；边界 {metric['boundary']}/2" if metric else '有效评分缺失')
            html+=['<details'+(' open' if system=='tables' else '')+'><summary>'+e(LABELS[system])+' · '+e(label)+'</summary><p>'+e(value['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev逐项评分、引用与来源判断</summary><pre>'+e(json.dumps(dict(metrics=metric,review=review),ensure_ascii=False,indent=2))+'</pre></details>',
                '<details><summary>回答的实际引文和可用上下文</summary><pre>'+e(json.dumps(value['candidate'],ensure_ascii=False,indent=2))+'</pre></details></details>']
        html+=['<details><summary>本题表格检索与关联补全记录</summary><pre>'+e(json.dumps(row['table_diagnostics'],ensure_ascii=False,indent=2))+'</pre></details></article>']
    html+=['<p>单轮开发集实验，尚未验证稳定性与新论文泛化；所有语义评分来自Jev，默认网站索引保持不变。</p>',
        '<script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(html),encoding='utf-8',newline='\n')


def report(refresh=False):
    if refresh:
        seal=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==h for n,h in seal['files'].items()),'Published report changed')
        require(judge.digest(DOC)==seal['document_sha256'],'Report document changed')
    else:require(not OUTPUT.exists() and not DOC.exists(),'Use new report destinations')
    audits={s:scoring.audit(*paths) for s,paths in STUDIES.items()}
    new=audits['tables'];study=new[2]
    require(set(study['requested_judges'])=={'jev'} and len(study['jobs'])==32,'Expected 32 Jev-only jobs')
    require(all(e['judge']=='jev' and e['system']=='rag' for e in study['jobs']),'Unexpected extra judge/system')
    require(all(status!='pending' for _,_,status in new[5]),'Wait for in-flight grading')
    controls={s:source_controls(RUNS['tables'],RUNS[s]) for s in ['quality','pymupdf']}
    settings=judge.read_json(ROOT/'.rag-data/configs/table-evidence-v1-20261030-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==settings['application_env_sha256'],'Default application configuration changed')
    jobs,reviews,metrics={},{},{}
    for system,a in audits.items():
        for job in a[1]:
            if job['system']!='rag':continue
            tid=job['task_id'];jobs[(system,tid)]=job
            review=a[3].get(('jev','rag',tid))
            if review is not None:
                reviews[(system,tid)]=review
                metrics[(system,tid)]=scoring.metrics(review,job['reference_case'],job['task']['capabilities'])
    tids=sorted(t for s,t in jobs if s=='tables');require(len(tids)==32,'Expected original 32 questions')
    for tid in tids:
        require(all(jobs[(s,tid)]['reference_case']==jobs[('tables',tid)]['reference_case'] for s in STUDIES),'Reference standard changed')
    # Full evidence chunks, not merely their counts, must remain exactly equal to the prior 95-chunk version.
    def chunk_rows(run):
        with sqlite3.connect((run/'library/metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as conn:
            return conn.execute('SELECT id,document_id,filename,page_start,page_end,chunk_index,text,kind,embedding_model FROM chunks ORDER BY id').fetchall()
    require(chunk_rows(RUNS['tables'])==chunk_rows(RUNS['quality']),'Parent source text, ID or locator changed')
    sidecar=judge.read_json(RUNS['tables']/'library/table-retrieval.json')
    structure=judge.read_json(RUNS['tables']/'library/structure.json')
    with override(runtime_report,RUN=RUNS['tables']):runtime=runtime_report.runtime()
    comparisons={s:paired(metrics,tids,s) for s in ['quality','pymupdf']}
    calls=new[4].get('jev',[])
    attempt_counts={entry['task_id']:len(list((STUDIES['tables'][1]/'records'/entry['name']).glob('*.json'))) for entry in study['jobs']}
    result=dict(version='table-evidence-jev-v1',published_on='2026-10-30',question_count=32,
        policy_sha256=grading.POLICY_SHA,valid_grades=sum(k=='jev' and s=='rag' for k,s,t in new[3]),
        grading_statuses={status:n for (kind,s,status),n in new[5].items() if kind=='jev' and s=='rag'},
        grading_accounting=scoring.accounting(calls,'jev'),new_luna_calls=0,new_control_grading_calls=0,
        grading_attempts_by_task=attempt_counts,
        all_grades_valid_on_first_attempt=all(n==1 for n in attempt_counts.values()) and len(new[3])==32,
        comparisons=comparisons,controls=controls,unchanged_parent_chunks=structure['chunks'],
        rows=len(sidecar['rows']),links=len(sidecar['links']),row_embedding_calls=sidecar['embedding_calls'],
        new_answer_runtime=runtime,default_configuration_unchanged=True,
        limitations=['One generation run and first-valid Jev grade, no holdout or stability claim.',
            'Row retrieval and explicit links were added together; their independent effects are not separated.',
            'Model aliases and settings are frozen but remote model weights are not.',
            'No extra scientific facts, row interpretations or reference grades authored by this report.'])
    diagnostics={};rows=[];added=Counter();omitted=Counter();row_seed_count=0
    for tid in tids:
        response=judge.read_json(RUNS['tables']/'results'/(tid+'.json'))['response']
        context=response.get('context_assembly',{})
        final=response.get('retrieved_evidence',[])
        seed_table_ids=[e['chunk_id'] for e in response.get('retrieval_seed_evidence',[]) if structure['mapping'][e['chunk_id']]['kind']=='table']
        row_seed_count+=len(seed_table_ids)
        additions=context.get('table_relationship_additions',[])
        added.update(x['kind'] for x in additions);omitted.update(x['reason'] for x in context.get('table_relationship_omissions',[]))
        text='\n'.join(e['text'] for e in final)
        diagnostics[tid]=dict(seed_table_chunk_ids=seed_table_ids,
            final_table_chunk_ids=sorted({s['chunk_id'] for e in final for s in e.get('source_chunks',[]) if s['kind']=='table'}),
            relationship_additions=additions,relationship_omissions=context.get('table_relationship_omissions',[]),
            row_retrieval=context.get('table_retrieval'),context_chars=context.get('context_chars'),
            source_value_markers={value:value in text for value in ['70.42','72.54','0.888','0.912','0.889']},
            literal_diagnostic_only=True)
        case=jobs[('tables',tid)]['reference_case']
        rows.append(dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],key_points=case['key_points'],
            systems={s:dict(candidate=jobs[(s,tid)]['candidate'],review=reviews.get((s,tid)),metrics=metrics.get((s,tid))) for s in LABELS},
            table_diagnostics=diagnostics[tid]))
    result['retrieval_summary']=dict(seed_tables=row_seed_count,relationship_additions=dict(added),relationship_omissions=dict(omitted),
        questions_with_table_evidence=sum(bool(v['final_table_chunk_ids']) for v in diagnostics.values()))
    result['new_valid_summary']=scoring.summarize([metrics[('tables',t)] for t in tids if ('tables',t) in metrics and not metrics[('tables',t)]['reference_concern']])
    with override(runtime_report,RUN=RUNS['quality']):previous_runtime=runtime_report.runtime()
    result['previous_answer_runtime']={k:v for k,v in previous_runtime.items() if k!='per_question'}
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result);save(OUTPUT/'retrieval-diagnostics.json',diagnostics)
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    save(OUTPUT/'audit.json',dict(controls=controls,policy_sha256=grading.POLICY_SHA,
        studies={s:dict(import_sha256=judge.digest(paths[0]/'import.json'),study_sha256=judge.digest(paths[1]/'study.json'),
            grade_proofs=[p for p in audits[s][6] if p['name'].startswith('jev-')]) for s,paths in STUDIES.items()},
        new_luna_calls=0,new_control_grading_calls=0,all_parent_chunks_equal=True))
    html_report(OUTPUT/'comparison.html',result,rows)
    lines=['# 表格行检索与关联补全：32题Jev评测','',
        '2026-10-30。保持已复核的95块正文/完整表格及原始位置不变，新增20条行检索表示和9条正文—表格关联。',
        '',f"原32题答题结果：{runtime['outcomes']}；有效Jev评分{result['valid_grades']}/32。仅对本轮新回答评分，旧Jev评分直接复用，Luna新调用0。",'',
        '五项规则、参考答案和题目不变。主比较与上一轮95块版使用共同有效题目；补充比较与PyMuPDF版另行配对。缺失不计零分，不计算加权总分。','']
    for s,c in comparisons.items():
        lines+=['## '+LABELS[s]+' → '+LABELS['tables'],'',
            '| '+' | '.join(HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |']
        for name,summary in c['scores'].items():lines.append('| '+' | '.join(map(str,score_cells(name,summary)))+' |')
        lines+=['',f"共同{c['tasks']}题，必答要点变化{c['point_delta']*100:+.2f}个百分点。",'',
            '要点提高：'+(', '.join(c['point_wins']) or '无')+'。','要点下降：'+(', '.join(c['point_losses']) or '无')+'。',
            '新增全部达标：'+(', '.join(c['all_five_wins']) or '无')+'。','失去全部达标：'+(', '.join(c['all_five_losses']) or '无')+'。','',
            '排除：'+json.dumps(c['exclusions'],ensure_ascii=False)+'。','']
    primary=comparisons['quality'];old_score=primary['scores']['quality'];new_score=primary['scores']['tables']
    lines += ['## 结果解读','',
        f"相同32题，必答要点{scoring.percent(old_score['point_macro_average'])}→{scoring.percent(new_score['point_macro_average'])}，变化{primary['point_delta']*100:+.2f}个百分点；五项全部达标{old_score['all_five_pass']}/32→{new_score['all_five_pass']}/32。新增7题达标、2题失去达标，净增5题。",'',
        '引用组完整率94.57%→97.32%；事实完全支持率98.45%→97.32%，单条引用有效率98.56%→98.36%，边界均分1.844→1.812。收益和退步同时存在。','',
        '- 第11题仍未获得Table 1结晶度数据，仅补入了正文提及的Table 2。Jev第一要点0→0.5，数值反例要点仍为0；不能声称关键表格检索问题已解决。',
        '- 第13题原文的“可能”机制被写成较确定的归因，Jev保留不确定性要点1→0，并把两条陈述判为部分支持。后续需要加强回答的限定条件保留。',
        '- 第20题必答要点仍满分，但Jev将一条单独引用判为0，失去全部达标；原始判断保留，报告不自行改分。',
        '- 第32题继续完整说明摘要0.888与正文0.912不一致，必答要点均满分，本轮引用也全部通过Jev判断。','',
        '与PyMuPDF共同31题比较，本轮全部达标23/31，PyMuPDF为22/31；但要点94.09%低于95.97%，边界1.839低于1.935。尚不能称为全面超过或稳定提升。','',
        '本轮39次生成、217,058已知生成Token；前一轮34次、163,252 Token。更多上下文及生成纠正尝试使Token用量上升，缓存命中量也不同，不能据Token比例直接推断货币费用。端到端中位数12.42→13.13秒。','']
    lines+=['## 检索行为与重点题','',
        '本轮检索诊断汇总：'+json.dumps(result['retrieval_summary'],ensure_ascii=False)+'。',
        '检索诊断记录源块、数值字符串和关联行为，不是额外的语义评分维度。','']
    for tid in ['PFI2-011','PFI2-032']:
        row=next(r for r in rows if r['task_id']==tid)
        lines += ['### '+tid,'',
            '原95块要点：'+json.dumps((row['systems']['quality']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'；本轮：'+json.dumps((row['systems']['tables']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'。','',
            '本轮完整表格源块：'+json.dumps(diagnostics[tid]['final_table_chunk_ids'],ensure_ascii=False)+'。',
            '数值字符串出现情况：'+json.dumps(diagnostics[tid]['source_value_markers'],ensure_ascii=False)+'。','']
    cost=result['grading_accounting']
    lines+=['## 用量、控制变量与限制','',
        f"新增行Embedding 1次、4,836 Token，原95块主向量未重建。答题生成{runtime['generation_calls']}次，已知生成Token {runtime['generation_known_tokens'].get('total_tokens','未知')}；问题Embedding {runtime['embedding_known_tokens']} Token；答题端到端中位数{runtime['median_end_to_end_seconds']:.2f}秒。",'',
        f"新增Jev请求{cost['calls']}次，API报告费用${cost['reported_cost_usd']}，费用未知请求{cost['cost_unknown_calls']}次；"+('32份评分均首次有效、无补评。' if result['all_grades_valid_on_first_attempt'] else '统计包含所有有效/无效尝试。')+'答题、Embedding实际货币费用未知。','',
        '对比源代码时只允许检索、功能开关、诊断和工作进程接线变化；答题提示词、DeepSeek生成器、引用校验、已有邻块补全代码按原字节内容核验（仅忽略Git的CRLF/LF差异）。检索新功能已写入新配置与源文件指纹，没有把变化伪装成同一旧流程。','',
        '每题独立请求，没有注入评测标准答案。表格行表示仅用于检索；回答引用的是原完整表及其原位置。8,000/24,000字符预算、0.35阈值与最多8个主命中不变；关联补充会产生额外证据编号并记录来源。','',
        '本轮同时增加行检索和关联补全，未拆分两者各自贡献。32题是开发集；一次生成和一次首个有效Jev评分不能证明稳定提升、新论文泛化或统计显著性。所有语义评分保持Jev原判定。','',
        '网站默认索引未切换。','',
        '[全部32题、三套回答、Jev逐项判断与检索记录](../data/literature/qa-evaluation/reports/table-evidence-jev-20261030/comparison.html)。',
        '[实现与范围](QA_TABLE_EVIDENCE_V1_20261030.md)。','']
    DOC.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    save(OUTPUT/'publication.json',dict(version=result['version'],document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),
        files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'}))
    return {k:result[k] for k in ['valid_grades','comparisons','retrieval_summary','grading_accounting']}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    print(json.dumps(report(args.refresh),ensure_ascii=False))
