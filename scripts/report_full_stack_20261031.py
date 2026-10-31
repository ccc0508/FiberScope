"""Offline full-stack comparison: original Jev labels, live retrieval traces and all usage."""
from collections import Counter
from hashlib import sha256
from html import escape
from pathlib import Path
import json

import judge_qa_eval as judge
import report_qa_system_benchmark as scoring
import report_answer_guidance_20261031 as shared
import report_qa_context_v1_20261029 as runtime_report
from report_mineru_rag_20261029 import override
from collect_rerank_stability_20261031 import verify_run,verify_import_binding,attempt_details,answer_timing,model_observations
from validate_qa_eval import require

ARMS=('control','guidance')
LABELS={'control':'PyMuPDF结构81块基线','guidance':'MinerU85块＋全部既有优化'}
LIMITATIONS=[
    '这是从查询向量化到生成的完整问答进程比较，不是固定证据回放；解析和文档索引使用已验证缓存。',
    '两版各新答32题，旧评分不混入主对照。多项组件同时变化，只能比较整个系统组合，不能单独归因。',
    '共同有效题以外的评分保留缺失，不计零；共同子集不等于全部32题，缺失不一定随机。',
    '各维度独立报告，无加权总分。事实支持率只统计科学事实；联合达标还检查范围声明。',
    '仅一次运行、单篇论文的已见开发题，不证明稳定性、统计显著性或新论文泛化；生成和裁判波动未分开识别。',
    '保留Jev原判，包括可能的范围、单位和复合引用误判。分析者说明不改原分，也不是裁判自由文字理由。',
    '耗时包括工作进程启动和库加载，不是网页HTTP延迟。并发时间不能相加当实际墙钟耗时。',
    '答题和重排实际货币费用未知，未知不记零；Jev的API报告费用不是已核验账单。推理Token已含在生成总Token中。',
    '同一模型别名/High及端点设置不保证远端权重不变。图片仍只使用既有图注，不代表新增完整图像理解。',
]


def trace(response,arm,status):
    require('fixed_evidence_diagnostics' not in response,'Fixed evidence replay is not an end-to-end run')
    config=response['configuration'];context=response.get('context_assembly') or {}
    require(config['context_expansion']['context_expansion_enabled'],'Context assembly disabled')
    rr=response.get('rerank_calls',[])
    if arm=='guidance':
        for feature in ('table_retrieval','rerank','answer_guidance'):
            require(config.get(feature,{}).get('enabled'),'Full stack feature disabled: '+feature)
        if status=='answered':
            require(response.get('embedding_usage') is not None,'Query embedding usage unavailable; inspect the live trace')
            require(rr and all(c['status']=='completed' for c in rr),'No successful rerank API call')
            rank=context.get('rerank') or {}
            require(rank.get('status')=='completed' and rank.get('enabled'),'Rerank selection diagnostics missing')
            require(rank['selected_chunk_ids']==[e['chunk_id'] for e in response['retrieval_seed_evidence']],'Ranked source selection differs')
            require(bool(context.get('table_retrieval')),'Table retrieval diagnostics missing')
    else:
        require(not rr and not config.get('rerank',{}).get('enabled'),'Baseline unexpectedly reranked')
        require(not config.get('answer_guidance',{}).get('enabled') and not config.get('table_retrieval',{}).get('enabled'),'Baseline enables experimental features')
    return dict(status=status,query_embedding_usage_observed=response.get('embedding_usage') is not None,
        rerank_calls=len(rr),rerank_statuses=dict(Counter(c['status'] for c in rr)),
        table_retrieval_observed=bool(context.get('table_retrieval')),context=context,
        seed_chunks=[e['chunk_id'] for e in response.get('retrieval_seed_evidence',[])],
        final_evidence_chars=sum(len(e['text']) for e in response.get('retrieved_evidence',[])),
        final_evidence_count=len(response.get('retrieved_evidence',[])))


def collect(root,out,contract):
    root,out=Path(root),Path(out);records=[];runtimes=[];proofs={};traces={};judging=[];all_results=[];reranks=[]
    gc=judge.read_json(out/'grading-contract.json')
    for arm in ARMS:
        directory=out/'runs'/arm
        bundle=verify_run(directory,contract['arms'][arm]['run_sha256'],judge.digest(root/'scripts/run_qa_baseline.py'))
        run=bundle['run'];require(run['tasks'] and all(t['mode']=='retrieval' for t in run['tasks']),'Non-live retrieval task')
        imp,study=out/'imports'/arm,out/'studies'/arm;audit=scoring.audit(imp,study)
        require(audit[2]['requested_judges']==gc['requested_judges'] and audit[2]['selected_systems']==['rag'],'Wrong judge/system')
        require(all(s!='pending' for _,_,s in audit[5]),'Scoring still pending')
        verify_import_binding(audit,bundle);attempts,statuses=attempt_details(study,max_attempts=3)
        traces[arm]={}
        for job in sorted((j for j in audit[1] if j['system']=='rag'),key=lambda j:j['task_id']):
            tid=job['task_id'];result=bundle['results'][tid];response=result.get('response')
            require(isinstance(response,dict),'Preserve worker failure; no fabricated trace')
            for k in ('llm_model','llm_reasoning_effort','embedding_model','top_k','min_score','prompt_pipeline_sha256','rerank','answer_guidance','table_retrieval'):
                require(response['configuration'].get(k)==run['configuration_probe'].get(k),'Actual runtime configuration changed: '+k)
            traces[arm][tid]=trace(response,arm,result['status']);review=audit[3].get(('jev','rag',tid))
            records.append(dict(arm=arm,task_id=tid,reference_case=job['reference_case'],candidate=job['candidate'],
                review=review,metrics=scoring.metrics(review,job['reference_case'],job['task']['capabilities']) if review else None,
                capabilities=job['task']['capabilities'],grading_status='completed' if review else statuses[tid],
                answer_status=result['status'],reason_code=result.get('reason_code')))
            reranks.extend(response.get('rerank_calls',[]));all_results.append(result)
        with override(runtime_report,RUN=directory):runtime=runtime_report.runtime()
        runtimes.append(dict(arm=arm,**{k:v for k,v in runtime.items() if k!='per_question'}))
        judging.extend(audit[4].get('jev',[]))
        manifest=judge.read_json(root/'.rag-data/baselines'/run['baseline_id']/'manifest.json')
        proofs[arm]=dict(run_sha256=bundle['run_sha256'],result_sha256=bundle['result_sha256'],
            import_sha256=judge.digest(imp/'import.json'),study_sha256=judge.digest(study/'study.json'),
            grade_proofs=audit[6],attempts=attempts,observed_models=model_observations(list(bundle['results'].values())),
            chunks=manifest['chunk_count'],offline_index_validation=manifest['index_validation'])
    tokens=Counter()
    for c in reranks:tokens.update(c.get('usage') or {})
    return dict(version='full-stack-end-to-end-v1',records=records,runtimes=runtimes,
        controls=dict(execution_mode=contract['execution_mode'],fresh_answers=64,common_settings=contract['common_settings'],
            arms=contract['arms'],default_configuration_changed=False,all_existing_features_enabled=True,
            live_sources_expected_to_differ=True,no_gold_in_answer_input=True),
        traces=traces,accounting=dict(jev=scoring.accounting(judging,'jev'),
            rerank=dict(calls=len(reranks),statuses=dict(Counter(c['status'] for c in reranks)),known_tokens=dict(tokens),
                usage_unknown_calls=sum(c.get('usage') is None for c in reranks),actual_billing_usd=None,attempts=reranks),
            answer_timing=answer_timing(all_results),actual_generation_billing_usd=None),
        provenance=dict(experiment_sha256=judge.digest(out/'experiment.json'),grading_contract_sha256=judge.digest(out/'grading-contract.json'),
            collector_sha256=judge.digest(Path(__file__)),runs=proofs),limitations=LIMITATIONS,provider_calls_by_collector=0)


def analyze(payload):
    require(payload['controls']['execution_mode']=='live_retrieval_normal_worker','Not an end-to-end comparison')
    records,tids,_=shared.checked_records(payload)
    require(len(tids)==32,'Expected all 32 explicit question pairs')
    common,exclusions=shared.select_common(records,tids);comparison=shared.paired(records,common);comparison['exclusions']=exclusions
    return dict(version=payload['version'],question_count=32,comparison=comparison,
        risks=shared.risk_summary(records,common),output_diagnostics=shared.output_diagnostics(records,tids),
        runtimes=payload['runtimes'],runtime_by_arm=shared.runtime_by_arm(payload),controls=payload['controls'],
        traces=payload['traces'],accounting=payload['accounting'],provenance=payload['provenance'],
        analyst_notes=payload.get('analyst_notes',[]),limitations=payload['limitations'],
        no_weighted_total_score=True,missing_not_zero=True,reporter_model_calls=0)


def score_rows(result):
    rows=[]
    for arm in ARMS:
        row=shared.cells(arm,result['comparison']['scores'][arm]);row[0]=LABELS[arm];rows.append(row)
    return rows


def runtime_rows(result):
    rows=[]
    for arm in ARMS:
        r=result['runtime_by_arm'][arm];rr=[v for v in result['traces'][arm].values()]
        rows.append([LABELS[arm],r['median_end_to_end_seconds'],r['generation_calls'],r['generation_known_tokens'].get('total_tokens'),
            r['embedding_known_tokens'],sum(v['rerank_calls'] for v in rr),result['output_diagnostics'][arm]['mean_answer_characters']])
    return rows


def render(path,result,payload):
    e=lambda v:escape(str(v),quote=True);dump=lambda v:'<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    c=result['comparison'];records,tids,standards=shared.checked_records(payload)
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全部优化叠加：端到端评测</title>',
       '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}section,article{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce5ef;padding:8px;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:12px}p{overflow-wrap:anywhere}</style><main>',
       '<h1>全部既有优化叠加：端到端评测</h1><p>2026-10-31。PyMuPDF结构81块基线与MinerU85块全开版各新答32题；重新做查询向量化、检索、补全与生成。全开版另启用表格检索、重排和v3指引。解析成果复用，不使用固定证据回放。</p>',
       '<section><h2>结果与决定</h2>'+''.join('<p>'+e(n)+'</p>' for n in result['analyst_notes'])+'</section>',
       '<section><h2>共同有效'+str(c['tasks'])+'题</h2>'+shared.table(shared.HEADERS,score_rows(result))+'<p>要点提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'</p>',
       '<p>新增联合达标：'+e(c['all_five_wins'])+'；失去联合达标：'+e(c['all_five_losses'])+'</p>',
       '<details><summary>题集与排除原因</summary>'+dump(dict(tasks=c['task_ids'],exclusions=c['exclusions']))+'</details></section>',
       '<section><h2>实际调用与代价</h2>'+shared.table(['版本','进程端到端中位秒','生成请求','已知生成Token','已知查询Embedding Token','实际重排请求','平均答案字符'],runtime_rows(result)),
       '<details><summary>全部费用与用量</summary>'+dump(dict(runtimes=result['runtimes'],accounting=result['accounting']))+'</details>',
       '<details><summary>开关、索引、控制变量与来源</summary>'+dump(dict(controls=result['controls'],provenance=result['provenance']))+'</details>',
       '<details><summary>逐题真实检索、重排和补全轨迹</summary>'+dump(result['traces'])+'</details></section>',
       '<section><h2>事实依据、拒答及解释边界</h2>'+dump(result['risks'])+''.join('<p>'+e(n)+'</p>' for n in result['limitations'])+'</section>',
       '<h2>全部32题、两份新回答和Jev原判</h2><p>Jev只提供结构化标签和来源定位。以下不补写裁判文字理由，不修改原分。</p><input id="search" placeholder="搜索题号或问题">']
    for tid in tids:
        h+=['<article data-search="'+e(tid+' '+standards[tid]['question'])+'"><h2>'+e(tid+' · '+standards[tid]['question'])+'</h2>',
            '<details><summary>参考答案与评分标准</summary>'+dump(standards[tid])+'</details>']
        for arm in ARMS:
            row=records[(arm,tid)];m=row['metrics'];label='有效评分缺失' if m is None else f"要点 {m['required_point_sum']}/{m['required_point_count']}；边界 {m['boundary']}/2"
            h+=['<details open><summary>'+e(LABELS[arm]+' · '+label)+'</summary><p>'+e(row['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev原始标签与计算</summary>'+dump(dict(review=row['review'],metrics=m,status=row.get('grading_status')))+'</details>',
                '<details><summary>回答、引用和实际证据</summary>'+dump(row['candidate'])+'</details></details>']
        h+=['</article>']
    h+=['<script>document.getElementById("search").addEventListener("input",function(){let q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    path.write_text(''.join(h),encoding='utf-8',newline='\n')


def publish(root,out,refresh=False):
    root,out=Path(root),Path(out);dest=root/'data/literature/qa-evaluation/reports/full-stack-20261031';doc=root/'docs/QA_FULL_STACK_REPORT_20261031.md'
    if refresh:
        previous=judge.read_json(dest/'publication.json')
        require(all(judge.digest(dest/n)==h for n,h in previous['files'].items()) and judge.digest(doc)==previous['document_sha256'],'Existing report was changed')
    else:require(not dest.exists() and not doc.exists(),'Never overwrite a published study')
    source=out/'analysis-input.json';payload=judge.read_json(source);result=analyze(payload);dest.mkdir(parents=True,exist_ok=refresh)
    judge.write(dest/'comparison.json',result)
    records,tids,standards=shared.checked_records(payload)
    (dest/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(dict(task_id=t,reference_case=standards[t],records=[records[(a,t)] for a in ARMS]),ensure_ascii=False)+'\n' for t in tids),encoding='utf-8',newline='\n')
    render(dest/'comparison.html',result,payload)
    lines=['# 全部既有优化叠加：端到端评测','','2026-10-31。两版各新答32题。PyMuPDF结构81块基线对比MinerU85块＋解析修正/组块/表格检索/上下文补全/重排/v3指引。','',
        *sum(([n,''] for n in result['analyst_notes']),[]),'| '+' | '.join(shared.HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |',
        *['| '+' | '.join(map(str,row))+' |' for row in score_rows(result)],'',f"共同有效{result['comparison']['tasks']}题，排除："+json.dumps(result['comparison']['exclusions'],ensure_ascii=False),'',
        '## 代价','','| 版本 | 进程中位秒 | 生成请求 | 生成Token | 查询Embedding Token | 重排请求 | 平均答案字符 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
        *['| '+' | '.join(map(str,row))+' |' for row in runtime_rows(result)],'',
        'Jev API报告费用：$'+result['accounting']['jev']['reported_cost_usd']+'；请求数'+str(result['accounting']['jev']['calls'])+'（包括无效尝试）。','',
        *sum(([n,''] for n in result['limitations']),[]),
        '[完整32题与原始判定](../data/literature/qa-evaluation/reports/full-stack-20261031/comparison.html)。','']
    doc.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    judge.write(dest/'publication.json',dict(input_sha256=judge.digest(source),exporter_sha256=judge.digest(Path(__file__)),document_sha256=judge.digest(doc),
        files={p.name:judge.digest(p) for p in dest.iterdir() if p.is_file() and p.name!='publication.json'},model_calls=0))
    return dict(common_tasks=result['comparison']['tasks'],deltas=result['comparison']['deltas'],provider_calls=0)
