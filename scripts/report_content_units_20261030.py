"""Audit content organization and publish unchanged first-valid Jev judgments."""
from argparse import ArgumentParser
from collections import Counter
from html import escape
import json
from pathlib import Path
import sqlite3

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import report_qa_context_v1_20261029 as runtime_report
import report_table_evidence_20261030 as previous_report
from report_mineru_rag_20261029 import override
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.rag-data/evaluations'
RUNS={
    'content':PRIVATE/'pfi-content-units-v1-20261030-r1',
    'tables':PRIVATE/'pfi-table-evidence-v1-20261030-r1',
    'pymupdf':PRIVATE/'pfi-context-v1-20261029-r1',
}
STUDIES={
    'content':(PRIVATE/'content-units-five-import-20261030-r1',PRIVATE/'content-units-jev-20261030-r1'),
    'tables':previous_report.STUDIES['tables'],
    'pymupdf':previous_report.STUDIES['pymupdf'],
}
LABELS={'content':'内容组织85块','tables':'表格检索95块','pymupdf':'PyMuPDF结构81块'}
OUTPUT=ROOT/'data/literature/qa-evaluation/reports/content-units-jev-20261030'
DOC=ROOT/'docs/QA_CONTENT_UNITS_EVAL_20261030.md'
HEADERS=previous_report.HEADERS


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def source_controls(new_dir,old_dir):
    """This round permits no runtime code, question or configuration changes."""
    new_dir,old_dir=Path(new_dir),Path(old_dir)
    a,b=[judge.read_json(d/'run.json') for d in [new_dir,old_dir]]
    require(a['tasks']==b['tasks'],'Question tasks changed')
    require(a['dataset_manifest_sha256']==b['dataset_manifest_sha256'],'Frozen question dataset changed')
    require(a['configuration_probe']==b['configuration_probe'],'Runtime configuration changed')
    names={n for run in [a,b] for n in run['source_files'] if n.startswith('literature_rag/') or n=='literature_worker.py'}
    for name in names:
        fingerprints=[]
        for d,run in zip([new_dir,old_dir],[a,b],strict=True):
            checksum=judge.digest(d/'backend'/name)
            require(checksum==run['source_files'].get(name),'Frozen runtime code changed')
            fingerprints.append(checksum)
        require(fingerprints[0]==fingerprints[1],'Runtime source differs: '+name)
    require(bool(names),'Missing runtime fingerprints')
    return dict(same_questions=True,same_dataset=True,configuration_byte_values_equal=True,
        runtime_files_byte_identical=sorted(names),only_corpus_organization_changed=True)


def paired(metrics,tids,control):
    selected=[t for t in tids if all((s,t) in metrics and not metrics[(s,t)]['reference_concern'] for s in [control,'content'])]
    require(bool(selected),'No valid paired questions')
    summaries={s:scoring.summarize([metrics[(s,t)] for t in selected]) for s in [control,'content']}
    return dict(task_ids=selected,tasks=len(selected),scores=summaries,
        point_delta=summaries['content']['point_macro_average']-summaries[control]['point_macro_average'],
        point_wins=[t for t in selected if metrics[('content',t)]['point_mean']>metrics[(control,t)]['point_mean']],
        point_losses=[t for t in selected if metrics[('content',t)]['point_mean']<metrics[(control,t)]['point_mean']],
        all_five_wins=[t for t in selected if metrics[('content',t)]['all_five_pass'] and not metrics[(control,t)]['all_five_pass']],
        all_five_losses=[t for t in selected if metrics[(control,t)]['all_five_pass'] and not metrics[('content',t)]['all_five_pass']],
        exclusions=[dict(task_id=t,missing_or_flagged=[s for s in [control,'content'] if (s,t) not in metrics or metrics[(s,t)]['reference_concern']]) for t in tids if t not in selected])


def chunk_rows(directory):
    with sqlite3.connect((Path(directory)/'metadata.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        return {r['id']:dict(r) for r in conn.execute('SELECT * FROM chunks')}


def corpus_proof():
    # Reproduce all chunks and source coverage without embedding or any model call.
    from index_mineru_content import prepare
    old,new=[RUNS[s]/'library' for s in ['tables','content']]
    _,_,organized,chunks,mapping,reused,info=prepare(old)
    structure=judge.read_json(new/'structure.json')
    organization=judge.read_json(new/'chunk-organization.json')
    require(judge.digest(new/'chunk-organization.json')==structure['organization_sha256'],'Organization seal changed')
    require(organization['source_mapping']==mapping==structure['mapping'],'Source mapping no longer reproduces')
    require(organization['source_coverage']==organized['source_coverage'],'Source conservation no longer reproduces')
    require(organization['events']==organized['events'],'Organization events changed')
    a,b=chunk_rows(new),chunk_rows(old)
    require(set(a)=={c.id for c in chunks},'Reproduced chunk IDs differ')
    for c in chunks:
        for field in ['document_id','text','kind','page_start','page_end','chunk_index','embedding_model']:
            require(a[c.id][field]==getattr(c,field),'Reproduced content or locator differs')
    for name in ['native-source.json','quality-ledger.json','table-row-vectors.json']:
        require(judge.digest(new/name)==judge.digest(old/name),'Prior source, corrections or row vectors changed')
    new_rows,old_rows=[judge.read_json(p/'table-retrieval.json') for p in [new,old]]
    require(new_rows['rows']==old_rows['rows'],'Table rows changed')
    require(new_rows['parent_text_sha256']==old_rows['parent_text_sha256'],'Original full table changed')
    cells=0
    for row in new_rows['rows']:
        parent=a[row['parent_chunk_id']]
        require(parent['text'][row['parent_text_start']:row['parent_text_end']]==row['parent_raw_row'],'Row offset changed')
        cells+=len(row['assignments'])
    for link in new_rows['links']:
        require(a[link['source_chunk_id']]['document_id']==a[link['target_chunk_id']]['document_id'],'Cross-document table link')
    # Verify actual retained vectors rather than relying on reuse counters alone.
    import chromadb
    vectors=[]
    for directory in [new,old]:
        client=chromadb.PersistentClient(path=str(directory/'chroma'))
        collections=client.list_collections()
        require(len(collections)==1,'Expected one vector collection')
        collection=client.get_collection(collections[0].name)
        require(collection.count()==len(chunk_rows(directory)),'Primary vector IDs diverged')
        data=collection.get(ids=reused,include=['embeddings'])
        vectors.append({cid:vector.tolist() for cid,vector in zip(data['ids'],data['embeddings'],strict=True)})
    require(vectors[0]==vectors[1] and len(vectors[0])==len(reused),'Reused vectors differ')
    require(structure['status']=='ready','Index is not ready')
    return dict(previous_chunks=len(b),chunks=len(a),chunk_kinds=dict(Counter(c['kind'] for c in a.values())),
        source_coverage=organized['source_coverage'],metadata_records=len(organized['document_metadata']),
        events=organized['events'],reused_vectors_verified=len(reused),new_vectors=info['new_vectors'],
        embedding_calls=structure['embedding_calls'],table_rows_reused=len(new_rows['rows']),
        table_cells_verified=cells,table_links=len(new_rows['links']),table_row_vectors_identical=True,
        source_pdf_sha256=structure['source_pdf_sha256'],source_organization_reproduced=True,
        historical_quality_summary='Prior parsing-review statistics, not the current chunk count.')


def diagnostics(run):
    structure=judge.read_json(run/'library/structure.json');result={}
    for path in sorted((run/'results').glob('*.json')):
        raw=judge.read_json(path)['response'];context=raw['context_assembly'];evidence=raw['retrieved_evidence']
        require(len(raw['retrieval_seed_evidence'])<=8,'Top-eight limit exceeded')
        require(sum(len(e['text']) for e in evidence)==context['context_chars']<=24000,'Context budget or count mismatch')
        require(all(len(e['text'])<=8000 for e in evidence),'Evidence budget exceeded')
        text='\n'.join(e['text'] for e in evidence)
        sources={s['chunk_id'] for e in evidence for s in e.get('source_chunks',[])}
        result[path.stem]=dict(seed_kinds=dict(Counter(structure['mapping'][e['chunk_id']]['kind'] for e in raw['retrieval_seed_evidence'])),
            final_kinds=dict(Counter(structure['mapping'][cid]['kind'] for cid in sources)),
            final_table_chunk_ids=sorted(cid for cid in sources if structure['mapping'][cid]['kind']=='table'),
            context_chars=context['context_chars'],budget_limited=context.get('budget_limited'),
            omitted_seed_chunk_ids=context.get('omitted_seed_chunk_ids'),
            relationship_additions=context.get('table_relationship_additions',[]),
            source_value_markers={v:v in text for v in ['70.42','72.54','0.888','0.912','0.889']},
            literal_diagnostic_only=True)
    return result


def invalid_grading_records(study):
    """Expose validation failures and original choices, without inventing grades."""
    folder=STUDIES['content'][1];result=[]
    for entry in study['jobs']:
        attempts=[]
        saved=judge.read_json(folder/'inputs'/(entry['name']+'.json'))
        for path in sorted((folder/'records'/entry['name']).glob('*.json'),key=lambda p:int(p.stem)):
            record=judge.read_json(path)
            if record['status']!='invalid_scorecard':continue
            error=None
            try:grading.decode('jev',record['raw_response'],saved['request'],saved['questions'],saved['targets'],saved['state'])
            except (ValueError,KeyError,TypeError,IndexError) as ex:error=type(ex).__name__+': '+str(ex)
            choices={k:v.get('choice') for k,v in record.get('raw_response',{}).get('answers',{}).items()}
            attempts.append(dict(attempt=record['attempt'],status=record['status'],validation_failure=error,
                request_sha256=record['request_sha256'],response_sha256=record.get('response_sha256'),
                record_sha256=judge.digest(path),duration_ms=record['duration_ms'],usage=record.get('usage'),original_choices=choices))
        if attempts:result.append(dict(task_id=entry['task_id'],attempts=attempts,missing_not_zero=True))
    return result


def score_cells(system,row):
    with override(previous_report,LABELS=LABELS):return previous_report.score_cells(system,row)


def html_report(path,result,rows):
    e=lambda v:escape(str(v),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>内容组织优化：32题Jev评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}p{overflow-wrap:anywhere}</style><main>',
        '<h1>内容组织优化：32题Jev评测</h1><p>元数据另存，公式绑定名称、条件和变量解释，图内标注归入图注，有依据的跨页句子合并。95块整理为85块。</p>',
        '<p>主比较严格保持答题模型、提示词、检索代码和全部运行参数相同。仅对本轮新回答调用Jev，旧评分直接复用；不新增Luna评分。</p>',
        '<p>五项维度：必答要点0/0.5/1；事实支持四类标签；单条引用0/1；引用组完整/部分/缺失；边界0/1/2。“全部达标”沿用原协议的联合条件，不是加权总分。缺失评分不记零。</p>']
    for control,c in result['comparisons'].items():
        html+=['<section><h2>'+e(LABELS[control])+' → '+e(LABELS['content'])+'</h2><div class="scroll"><table><tr>'+''.join('<th>'+e(h)+'</th>' for h in HEADERS)+'</tr>']
        for s,value in c['scores'].items():html.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in score_cells(s,value))+'</tr>')
        html+=['</table></div><p>必答要点变化：'+f"{c['point_delta']*100:+.2f}"+'个百分点。提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'。</p>',
            '<p>新增全部达标：'+e(c['all_five_wins'])+'；失去全部达标：'+e(c['all_five_losses'])+'。</p>',
            '<details><summary>共同题目与排除原因</summary><pre>'+e(json.dumps(dict(task_ids=c['task_ids'],exclusions=c['exclusions']),ensure_ascii=False,indent=2))+'</pre></details></section>']
    html+=['<section><h2>如何理解结果</h2><p>结构完整、原文保全和问答得分是不同的检查。本轮同时调整三类内容组织；单轮开发集结果不能分离各项贡献，也不能证明稳定提升或新论文泛化。所有语义评分保留Jev原判定，程序不补写裁判理由。</p></section>',
        '<details><summary>费用、耗时、来源保全、无效评分与控制变量</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>',
        '<h2>全部32题</h2><p>包括参考答案、必答要点与逐项判定。Jev输出结构化判断及证据定位，不生成自由文字理由。</p><input id="search" placeholder="搜索题号或问题">']
    for row in rows:
        html+=['<article data-search="'+e(row['task_id']+' '+row['question'])+'"><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与评分准则</summary><p>'+e(row['reference_answer'])+'</p><pre>'+e(json.dumps(row['reference_case'],ensure_ascii=False,indent=2))+'</pre></details>']
        for system,value in row['systems'].items():
            metric=value.get('metrics');review=value.get('review')
            label=f"要点 {metric['required_point_sum']}/{metric['required_point_count']}；边界 {metric['boundary']}/2" if metric else '有效评分缺失'
            html+=['<details'+(' open' if system=='content' else '')+'><summary>'+e(LABELS[system])+' · '+e(label)+'</summary><p>'+e(value['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev五项逐条判断与定位</summary><pre>'+e(json.dumps(dict(metrics=metric,review=review),ensure_ascii=False,indent=2))+'</pre></details>',
                '<details><summary>原回答、引文与实际可用上下文</summary><pre>'+e(json.dumps(value['candidate'],ensure_ascii=False,indent=2))+'</pre></details></details>']
        html+=['<details><summary>本题检索与上下文记录</summary><pre>'+e(json.dumps(row['diagnostics'],ensure_ascii=False,indent=2))+'</pre></details></article>']
    html+=['<p>默认网站索引未切换；本报告为独立实验。</p><script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(html),encoding='utf-8',newline='\n')


def report(refresh=False):
    if refresh:
        seal=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==h for n,h in seal['files'].items()),'Published report changed')
        require(judge.digest(DOC)==seal['document_sha256'],'Published document changed')
    else:require(not OUTPUT.exists() and not DOC.exists(),'Use new output destinations')
    audits={s:scoring.audit(*paths) for s,paths in STUDIES.items()}
    new=audits['content'];study=new[2]
    require(set(study['requested_judges'])=={'jev'} and len(study['jobs'])==32,'Expected 32 Jev jobs')
    require(all(e['judge']=='jev' and e['system']=='rag' for e in study['jobs']),'Unexpected judge/system')
    require(all(status!='pending' for _,_,status in new[5]),'Wait for in-flight scoring')
    controls=dict(tables=source_controls(RUNS['content'],RUNS['tables']),
        pymupdf=previous_report.source_controls(RUNS['content'],RUNS['pymupdf']))
    config=judge.read_json(ROOT/'.rag-data/configs/content-units-v1-20261030-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==config['application_env_sha256'],'Default application configuration changed')
    jobs,reviews,metrics={},{},{}
    for s,a in audits.items():
        for job in a[1]:
            if job['system']!='rag':continue
            tid=job['task_id'];jobs[(s,tid)]=job
            review=a[3].get(('jev','rag',tid))
            if review is not None:
                reviews[(s,tid)]=review
                metrics[(s,tid)]=scoring.metrics(review,job['reference_case'],job['task']['capabilities'])
    tids=sorted(t for s,t in jobs if s=='content')
    require(tids==[f'PFI2-{i:03}' for i in range(1,33)],'Expected original 32 questions')
    for tid in tids:
        require(all(jobs[(s,tid)]['reference_case']==jobs[('content',tid)]['reference_case'] for s in STUDIES),'Reference answer changed')
    proof=corpus_proof();details=diagnostics(RUNS['content'])
    runtimes={}
    for s in RUNS:
        with override(runtime_report,RUN=RUNS[s]):runtimes[s]=runtime_report.runtime()
    calls=new[4].get('jev',[])
    counts={e['task_id']:len(list((STUDIES['content'][1]/'records'/e['name']).glob('*.json'))) for e in study['jobs']}
    invalid=invalid_grading_records(study)
    result=dict(version='content-units-jev-v1',published_on='2026-10-30',question_count=32,
        policy_sha256=grading.POLICY_SHA,valid_grades=sum(k=='jev' and s=='rag' for k,s,t in new[3]),
        grading_statuses={status:n for (kind,s,status),n in new[5].items() if kind=='jev' and s=='rag'},
        grading_accounting=scoring.accounting(calls,'jev'),grading_attempts_by_task=counts,invalid_grading_records=invalid,
        all_grades_valid_on_first_attempt=all(n==1 for n in counts.values()) and len(new[3])==32,
        new_luna_calls=0,new_control_grading_calls=0,controls=controls,corpus_proof=proof,
        comparisons={s:paired(metrics,tids,s) for s in ['tables','pymupdf']},
        new_valid_summary=scoring.summarize([metrics[('content',t)] for t in tids if ('content',t) in metrics and not metrics[('content',t)]['reference_concern']]),
        answer_runtime={s:{k:v for k,v in rt.items() if k!='per_question'} for s,rt in runtimes.items()},
        default_configuration_unchanged=True,
        limitations=['One generation run and first-valid Jev grade; development set, no stability or holdout claim.',
            'Three organization changes together; individual causal effects are not separated.',
            'Same remote model aliases/settings do not guarantee unchanged provider weights.',
            'No new scientific facts or semantic grades authored by this report.'])
    rows=[]
    for tid in tids:
        case=jobs[('content',tid)]['reference_case']
        rows.append(dict(task_id=tid,question=case['question'],reference_answer=case['reference_answer'],
            key_points=case['key_points'],reference_case=case,
            systems={s:dict(candidate=jobs[(s,tid)]['candidate'],review=reviews.get((s,tid)),metrics=metrics.get((s,tid))) for s in LABELS},
            diagnostics=details[tid]))
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result);save(OUTPUT/'retrieval-diagnostics.json',details)
    save(OUTPUT/'invalid-grading-records.json',invalid)
    save(OUTPUT/'audit.json',dict(controls=controls,corpus_proof=proof,policy_sha256=grading.POLICY_SHA,
        studies={s:dict(import_sha256=judge.digest(paths[0]/'import.json'),study_sha256=judge.digest(paths[1]/'study.json'),
            grade_proofs=[p for p in audits[s][6] if p['name'].startswith('jev-')]) for s,paths in STUDIES.items()},
        new_luna_calls=0,new_control_grading_calls=0))
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    html_report(OUTPUT/'comparison.html',result,rows)
    lines=['# 内容组织优化：32题Jev评测','','2026-10-30。元数据分离、公式解释绑定和明确跨页句子衔接；95块重新组织为85块。',
        '',f"原32题答题状态：{runtimes['content']['outcomes']}；有效Jev评分{result['valid_grades']}/32。旧Jev评分直接复用，Luna新调用0。",'',
        '五项规则与参考答案不变，缺失不记零，不计算加权总分。主比较与上一轮表格检索95块版严格保持相同运行代码、模型、提示词和参数。','']
    for control,c in result['comparisons'].items():
        lines+=['## '+LABELS[control]+' → '+LABELS['content'],'','| '+' | '.join(HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |']
        for s,value in c['scores'].items():lines.append('| '+' | '.join(map(str,score_cells(s,value)))+' |')
        lines+=['',f"共同{c['tasks']}题，要点变化{c['point_delta']*100:+.2f}个百分点。",'',
            '要点提高：'+(', '.join(c['point_wins']) or '无')+'。','要点下降：'+(', '.join(c['point_losses']) or '无')+'。',
            '新增全部达标：'+(', '.join(c['all_five_wins']) or '无')+'。','失去全部达标：'+(', '.join(c['all_five_losses']) or '无')+'。',
            '排除：'+json.dumps(c['exclusions'],ensure_ascii=False)+'。','']
    primary=result['comparisons']['tables'];older=primary['scores']['tables'];current=primary['scores']['content']
    lines+=['## 结果解读','',
        f"本轮没有整体提升。共同31题，必答要点{scoring.percent(older['point_macro_average'])}→{scoring.percent(current['point_macro_average'])}，五项全部达标{older['all_five_pass']}/31→{current['all_five_pass']}/31。事实完全支持率与单条引用有效率略升，引用组完整率下降；不能把内容组织更规整解释成问答效果更好。",'',
        '- 第11题仍未拿到Table 1关键结晶度数据，只拿到Table 2及一般性讨论。回答这次还遗漏了直接否定单调下降的结论，要点0.5/2→0/2。这仍是关键证据召回与回答完整性问题。',
        '- 第23题明确指出正文0.912与摘要0.888不一致，要点与边界均通过Jev，新增全部达标。',
        '- 第27、29题必答要点仍满分，但Jev将一个混合陈述的引用组判为部分支持；第28题要点满分、边界从2降为1。原裁判标签保留，不能只看要点得分就称这些题完全通过。',
        '- 第13题已拿到相关解释，仍把原文“可能”写成确定机制；切块整理没有解决生成时丢失限定条件的问题。','',
        '上述是对实际回答、检索记录和Jev标签的诊断，不是替Jev生成文字理由；一次实验不能断言单项组织规则导致得分变化。','',
        '第24题三次评分内部矛盾：C6被判为事实，其两条引用均“不支持”，引用组却为“完整”。按照沿用协议全部无效；保留原始标签、响应指纹和费用，不人工修正、不无限补评。主比较排除24，和PyMuPDF比较另排除原本缺失评分的23，共30题。','',
        '## 来源保全与组织验证','',
        f"117个修正原生单位共{proof['source_coverage']['characters']:,}字符逐字符、无重复和遗漏覆盖；{proof['metadata_records']}项元数据另存，5个公式解释单元，1处新增跨页衔接。全部85块及来源映射可从冻结的原生源和修正账本重新生成。",'',
        f"实际核对{proof['reused_vectors_verified']}个保留向量完全相同；9块新增Embedding共1次、2,121 Token。20条表格行向量与原完整表保持相同，120个表格赋值及9条同文献关联通过验证。没有重新解析PDF、调用视觉模型或抽查正常区域。",'',
        '正文1200字符软目标、单条8000/总24000字符预算、0.35阈值和最多8个主命中不变。公式解释单元可超过1200字符。没有修改重排、回答提示词或引用校验。','',
        '## 重点题的原始判定与检索记录','']
    by_id={r['task_id']:r for r in rows}
    for tid in ['PFI2-004','PFI2-011','PFI2-013','PFI2-020','PFI2-032']:
        row=by_id[tid]
        lines+=['### '+tid,'',row['question'],'',
            '原95块要点：'+json.dumps((row['systems']['tables']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'。',
            '本轮85块要点：'+json.dumps((row['systems']['content']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'。',
            '本轮实际证据类型：'+json.dumps(details[tid]['final_kinds'],ensure_ascii=False)+'。',
            '数值字符串是否出现在上下文：'+json.dumps(details[tid]['source_value_markers'],ensure_ascii=False)+'。','']
    rt=runtimes['content'];cost=result['grading_accounting']
    old_rt=runtimes['tables']
    token_change=(rt['generation_known_tokens']['total_tokens']/old_rt['generation_known_tokens']['total_tokens']-1)*100
    lines+=['## 用量与限制','',
        f"本轮答题生成{rt['generation_calls']}次，已知生成Token {rt['generation_known_tokens'].get('total_tokens','未知'):,}；问题Embedding {rt['embedding_known_tokens']} Token；端到端中位数{rt['median_end_to_end_seconds']:.2f}秒。生成Token已包含推理Token，不重复相加。实际答题及Embedding货币费用未知。",'',
        f"上一轮39次生成、217,058 Token，本轮33次、187,825 Token，已知生成Token变化{token_change:+.2f}%；端到端中位数{old_rt['median_end_to_end_seconds']:.2f}→{rt['median_end_to_end_seconds']:.2f}秒。纠正尝试次数与缓存命中不同，不能据Token变化等比例推算费用。",'',
        f"Jev共{cost['calls']}次请求，API报告费用${cost['reported_cost_usd']}；费用未知{cost['cost_unknown_calls']}次。"+('32份评分均首次有效，无补评。' if result['all_grades_valid_on_first_attempt'] else '31题首次有效；第24题三次无效，全部尝试均计入费用。'),'',
        '来源完整不等于回答一定更好。重新组织会改变向量表示、候选排名和邻块组合；即使检索到正确材料，回答仍可能遗漏限定条件。所有语义评分保留Jev原判定，本报告不替裁判加分。','',
        '本轮同时调整几种组织规则，不能分离各自贡献。仅一次答题和首次有效Jev评分，32题仍是开发集，不能证明稳定提升、统计显著性或新论文泛化。模型别名与参数固定，远端权重不可验证。','',
        '网站默认索引未切换。','',
        '[全部32题、三套回答和Jev逐项判断](../data/literature/qa-evaluation/reports/content-units-jev-20261030/comparison.html)。',
        '[实现、范围与85块预览](QA_CONTENT_UNITS_V1_20261030.md)。','']
    DOC.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    save(OUTPUT/'publication.json',dict(version=result['version'],document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),
        files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'}))
    return {k:result[k] for k in ['valid_grades','comparisons','grading_accounting','all_grades_valid_on_first_attempt']}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    print(json.dumps(report(args.refresh),ensure_ascii=False))
