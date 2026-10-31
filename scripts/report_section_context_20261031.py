"""Offline audit and publication of fixed-primary-hit context expansion A/B."""
from collections import Counter
from html import escape
import json
from pathlib import Path

import judge_qa_eval as judge
import report_qa_system_benchmark as scoring
import report_answer_guidance_20261031 as shared
import report_qa_context_v1_20261029 as runtime_report
from report_mineru_rag_20261029 import override
from collect_rerank_stability_20261031 import verify_run,verify_import_binding,answer_timing,attempt_details,model_observations
from validate_qa_eval import require
from section_context_20261031 import canonical,save,ARMS,STRATEGIES,TAG

LABELS={'control':'同页前后邻块','guidance':'小节补全＋邻块回退'}
LIMITATIONS=[
    '这是固定主命中后的上下文补全实验，不是重新检索的完整系统比较；没有新增PDF解析、文档Embedding、查询Embedding或重排调用。',
    '使用原107块索引和当时保存的同一批前8主命中，两臂各新答32题。未使用历史答案作答题对照；原同页补全在32题上逐字段复现。',
    '小节归属来自程序规则推断；结构可信不等于科学内容相关。原解析中的错误、重复和表格HTML不在本轮修正。',
    '两臂长度上限相同，但实际证据长度、引用编号、证据分组和陈述数可以不同。新增原文不能自动当作新增有效证据。',
    '只用Jev首个有效评分；每份答案最多3次评分尝试。评分缺失不记零，主对照只用共同有效且无参考疑问的题目。',
    '仅单篇论文32道已见开发题的一轮实验，混合生成与裁判波动，不证明稳定提升、统计显著性或新论文泛化。',
    '五个评分维度分别报告，五项全部达标是联合条件，不是第六个评分维度，也不合成加权总分。',
    '按小节补全不能保证跨小节证据覆盖；摘要与正文冲突仍可能需要更全面的检索。',
    '进程耗时包含启动和生成，不等于网页HTTP耗时；离线补全时间另行记录。实际答题费用未知，Jev API报告费用不是核验账单。',
    '网站默认配置未切换。远端模型别名相同和High相同不能保证远端权重固定。']


def selected_jobs(import_jobs):
    # The import bundle also archives DSH; only RAG was selected for this study.
    jobs=sorted((j for j in import_jobs if j['system']=='rag'),key=lambda j:j['task_id'])
    require([j['task_id'] for j in jobs]==[f'PFI2-{i:03}' for i in range(1,33)],'Expected exactly 32 selected RAG jobs')
    return jobs


def collect(root,out):
    root,out=Path(root),Path(out);c=judge.read_json(out/'experiment.json');gc=judge.read_json(out/'grading-contract.json')
    records=[];runtimes=[];proofs={};traces={};judging=[];all_results=[]
    require(c['version']=='context-expansion-fixed-seeds-v1','Unexpected experiment')
    for arm in ARMS:
        directory=out/'runs'/arm
        bundle=verify_run(directory,c['arms'][arm]['run_sha256'],judge.digest(root/'scripts/section_context_20261031.py'))
        audit=scoring.audit(out/'imports'/arm,out/'studies'/arm)
        require(audit[2]['requested_judges']==gc['requested_judges'] and audit[2]['selected_systems']==['rag'],'Wrong grading settings')
        require(all(s!='pending' for _,_,s in audit[5]),'Wait for pending grading requests')
        verify_import_binding(audit,bundle);attempts,statuses=attempt_details(out/'studies'/arm,max_attempts=3)
        traces[arm]={}
        for job in selected_jobs(audit[1]):
            tid=job['task_id'];row=bundle['results'][tid];r=row['response'];f=judge.read_json(out/'fixtures'/arm/(tid+'.json'))
            d=r['fixed_seed_diagnostics'];expected=c['fixtures'][tid][arm]
            require(judge.digest(out/'fixtures'/arm/(tid+'.json'))==expected['fixture_sha256'],'Fixture changed')
            require(r['retrieval_seed_evidence']==f['seeds'] and canonical(f['seeds'])==expected['seeds_sha256']==d['seeds_sha256'],
                    'Primary hit identity or order differs')
            require(r['retrieved_evidence']==f['evidences'] and canonical(f['evidences'])==expected['evidences_sha256']==d['generation_input_evidence_sha256'],
                    'Actual generation context differs')
            require(r['configuration']=={**c['arms'][arm]['configuration_probe'],'documents':f['documents']} or
                all(r['configuration'].get(k)==v for k,v in c['arms'][arm]['configuration_probe'].items() if k!='provider_endpoint_fingerprints'),
                'Actual generation settings differ')
            require(d['embedding_calls']==d['rerank_calls']==0 and not r['rerank_calls'] and r['embedding_usage'] is None,'Unexpected retrieval cost')
            require(len(r['generation_calls'])<=2,'More generation repairs than original pipeline')
            review=audit[3].get(('jev','rag',tid))
            records.append(dict(arm=arm,task_id=tid,reference_case=job['reference_case'],candidate=job['candidate'],review=review,
                metrics=scoring.metrics(review,job['reference_case'],job['task']['capabilities']) if review else None,
                capabilities=job['task']['capabilities'],grading_status='completed' if review else statuses[tid],
                answer_status=row['status'],reason_code=row.get('reason_code')))
            traces[arm][tid]=dict(seeds_sha256=d['seeds_sha256'],evidence_sha256=d['generation_input_evidence_sha256'],
                source_chunks=[s['chunk_id'] for e in f['evidences'] for s in e['source_chunks']],
                context=f['assembly'],assembly_ms=f['assembly_ms'],strategy=f['strategy'])
            all_results.append(row)
        with override(runtime_report,RUN=directory):runtime=runtime_report.runtime()
        runtime.update(embedding_calls=0,embedding_usage_unknown_questions=0,rerank_calls=0,
            assembly_ms=sum(t['assembly_ms'] for t in traces[arm].values()))
        runtimes.append(dict(arm=arm,**{k:v for k,v in runtime.items() if k!='per_question'}))
        judging.extend(audit[4].get('jev',[]))
        proofs[arm]=dict(run_sha256=bundle['run_sha256'],result_sha256=bundle['result_sha256'],grade_proofs=audit[6],
            attempts=attempts,observed_models=model_observations(list(bundle['results'].values())))
    for tid in c['task_ids']:
        require(traces['control'][tid]['seeds_sha256']==traces['guidance'][tid]['seeds_sha256'],'A/B primary hits differ')
    require(len(records)==64,'Expected exactly two records for each of the 32 questions')
    notes_path=out/'analysis-notes.json'
    notes=judge.read_json(notes_path) if notes_path.exists() else []
    require(isinstance(notes,list) and all(isinstance(n,str) for n in notes),'Analyst notes must be text')
    payload=dict(version=c['version'],records=records,runtimes=runtimes,traces=traces,
        controls=dict(same_primary_hits=True,same_107_block_index=True,old_context_exactly_reproduced=32,
            generation_settings={a:c['arms'][a]['configuration_probe'] for a in ARMS},
            new_embedding_calls=0,new_rerank_calls=0,default_configuration_changed=False,strategies=STRATEGIES),
        accounting=dict(jev=scoring.accounting(judging,'jev'),answer_timing=answer_timing(all_results),actual_generation_cost=None),
        provenance=dict(experiment_sha256=judge.digest(out/'experiment.json'),grading_contract_sha256=judge.digest(out/'grading-contract.json'),
            source_run_sha256=c['source_run_sha256'],source_results_sha256=c['source_results_sha256'],runs=proofs,
            reporting_amendments=c.get('reporting_amendments',[])),
        analyst_notes=notes,limitations=LIMITATIONS,provider_calls_by_collector=0)
    save(out/'analysis-input.json',payload)
    return dict(records=len(records),provider_calls=0)


def analyze(payload):
    require(payload['controls']['same_primary_hits'] and payload['controls']['same_107_block_index'],'Uncontrolled experiment')
    records,tids,_=shared.checked_records(payload)
    require(tids==[f'PFI2-{i:03}' for i in range(1,33)],'Expected all 32 task pairs')
    require(payload['controls']['generation_settings']['control']==payload['controls']['generation_settings']['guidance'],'Generation controls differ')
    common,excluded=shared.select_common(records,tids);comparison=shared.paired(records,common);comparison['exclusions']=excluded
    diagnostics={}
    for arm in ARMS:
        values=list(payload['traces'][arm].values())
        diagnostics[arm]=dict(total_context_chars=sum(v['context']['context_chars'] for v in values),
            mean_context_chars=sum(v['context']['context_chars'] for v in values)/32,
            budget_limited_questions=[t for t,v in payload['traces'][arm].items() if v['context']['budget_limited']],
            different_sources_from_other_arm=sum(set(v['source_chunks'])!=set(payload['traces'][ARMS[1-ARMS.index(arm)]][t]['source_chunks'])
                for t,v in payload['traces'][arm].items()))
    return dict(version=payload['version'],question_count=32,comparison=comparison,context_diagnostics=diagnostics,
        risks=shared.risk_summary(records,common),output_diagnostics=shared.output_diagnostics(records,tids),
        runtimes=payload['runtimes'],runtime_by_arm=shared.runtime_by_arm(payload),accounting=payload['accounting'],
        controls=payload['controls'],traces=payload['traces'],provenance=payload['provenance'],analyst_notes=payload['analyst_notes'],
        limitations=payload['limitations'],missing_not_zero=True,no_weighted_total_score=True,reporter_model_calls=0)


def score_rows(result):
    rows=[]
    for a in ARMS:
        row=shared.cells(a,result['comparison']['scores'][a]);row[0]=LABELS[a];rows.append(row)
    return rows


def render(path,result,payload):
    e=lambda v:escape(str(v),quote=True)
    dump=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    records,tids,standards=shared.checked_records(payload);c=result['comparison']
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MinerU上下文补全对照</title>',
       '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}section,article{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce5ef;padding:8px;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:12px}</style><main>',
       '<h1>MinerU：同页邻块与小节补全对照</h1><p>2026-10-31。同一107块索引、相同前8主命中、相同8000/24000字符上限；两版各重新回答32题，仅改变上下文补全方式。没有重新检索，未开启重排或新回答指引。</p>',
       '<section><h2>共同有效'+str(c['tasks'])+'题</h2>'+shared.table(shared.HEADERS,score_rows(result)),
       '<p>要点提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'</p><p>新增联合达标：'+e(c['all_five_wins'])+'；失去联合达标：'+e(c['all_five_losses'])+'</p>',
       ''.join('<p>'+e(n)+'</p>' for n in result['analyst_notes']),
       '<details><summary>题集与排除原因</summary>'+dump(dict(task_ids=c['task_ids'],exclusions=c['exclusions']))+'</details></section>',
       '<section><h2>证据变化、用量和控制变量</h2>'+dump(dict(context=result['context_diagnostics'],runtimes=result['runtimes'],accounting=result['accounting'],controls=result['controls']))+'</section>',
       '<section><h2>局限</h2>'+''.join('<p>'+e(n)+'</p>' for n in result['limitations'])+'</section>',
       '<h2>全部32题、两份新回答及Jev原始评分</h2><p>可展开查看实际补全原文、保留的主命中和引用。Jev没有自由文字理由，报告不代写理由或改分。</p><input id="search" placeholder="搜索题号或问题">']
    for tid in tids:
        h+=['<article data-search="'+e(tid+' '+standards[tid]['question'])+'"><h2>'+e(tid+' · '+standards[tid]['question'])+'</h2>',
            '<details><summary>参考答案与评分规则</summary>'+dump(standards[tid])+'</details>']
        for arm in ARMS:
            row=records[(arm,tid)];metric=row['metrics'];label='有效评分缺失' if metric is None else f"要点 {metric['required_point_sum']}/{metric['required_point_count']}；边界 {metric['boundary']}/2"
            h+=['<details open><summary>'+e(LABELS[arm]+' · '+label)+'</summary><p>'+e(row['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev原判与计算</summary>'+dump(dict(review=row['review'],metrics=metric,status=row['grading_status']))+'</details>',
                '<details><summary>回答、引用及可用上下文</summary>'+dump(row['candidate'])+'</details>',
                '<details><summary>上下文补全轨迹与原块编号</summary>'+dump(result['traces'][arm][tid])+'</details></details>']
        h+=['</article>']
    h+=['<script>document.getElementById("search").addEventListener("input",function(){let q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    path.write_text(''.join(h),encoding='utf-8',newline='\n')


def publish(root,out):
    root,out=Path(root),Path(out);dest=root/'data/literature/qa-evaluation/reports'/TAG
    doc=root/'docs/QA_SECTION_CONTEXT_REPORT_20261031.md'
    require(not dest.exists() and not doc.exists(),'Never overwrite a published experiment')
    payload=judge.read_json(out/'analysis-input.json');result=analyze(payload);dest.mkdir(parents=True)
    save(dest/'comparison.json',result);render(dest/'comparison.html',result,payload)
    records,tids,standards=shared.checked_records(payload)
    (dest/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(dict(task_id=t,reference_case=standards[t],
        records=[records[(a,t)] for a in ARMS]),ensure_ascii=False)+'\n' for t in tids),encoding='utf-8',newline='\n')
    lines=['# MinerU同页邻块与小节补全对照','','2026-10-31。同一107块索引，固定32题的原8个主命中，两版各新答一次，只使用Jev原评分。','',
        *sum(([n,''] for n in result['analyst_notes']),[]),'| '+' | '.join(shared.HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |',
        *['| '+' | '.join(map(str,r))+' |' for r in score_rows(result)],'',
        f"共同有效{result['comparison']['tasks']}题；排除："+json.dumps(result['comparison']['exclusions'],ensure_ascii=False),'',
        '要点提高：'+str(result['comparison']['point_wins'])+'；下降：'+str(result['comparison']['point_losses']),'',
        *result['limitations'],'','[全部32题与原始双臂评分](../data/literature/qa-evaluation/reports/'+TAG+'/comparison.html)。','',
        '[实验方案与运行方式](QA_SECTION_CONTEXT_METHOD_20261031.md)。']
    doc.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    save(dest/'publication.json',dict(files={p.name:judge.digest(p) for p in dest.iterdir() if p.is_file()},
        document_sha256=judge.digest(doc),analysis_input_sha256=judge.digest(out/'analysis-input.json'),
        reporter_sha256=judge.digest(Path(__file__)),reporter_model_calls=0))
    return dict(common_tasks=result['comparison']['tasks'],deltas=result['comparison']['deltas'],provider_calls=0)
