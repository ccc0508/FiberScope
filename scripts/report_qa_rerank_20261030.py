"""Publish controlled rerank diagnostics and first-valid Jev judgments without changing grades."""
from argparse import ArgumentParser
from collections import Counter
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import statistics

import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as scoring
import report_qa_context_v1_20261029 as runtime_report
import report_content_units_20261030 as content_report
from report_mineru_rag_20261029 import override
from qa_retrieval_alignment import locate_evidence,source_pages,span_coverage
from validate_qa_eval import require

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.rag-data/evaluations'
RUNS={'rerank':PRIVATE/'pfi-candidate-rerank-v1-20261030-r1',**content_report.RUNS}
DIRECT_STUDY=PRIVATE/'candidate-rerank-jev-20261030-r1'
STUDIES={'rerank':(PRIVATE/'candidate-rerank-five-import-20261030-r1',PRIVATE/'candidate-rerank-jev-20261031-proxy-recovery'),**content_report.STUDIES}
LABELS={'rerank':'85块＋候选重排','content':'85块纯向量排序','tables':'95块表格检索','pymupdf':'PyMuPDF结构81块'}
OUTPUT=ROOT/'data/literature/qa-evaluation/reports/candidate-rerank-jev-20261030'
DOC=ROOT/'docs/QA_CANDIDATE_RERANK_EVAL_20261030.md'
ALLOWED={'literature_rag/application/retrieve.py','literature_rag/application/rerank.py',
    'literature_rag/adapters/providers/rerank.py','literature_rag/config.py','literature_rag/diagnostics.py',
    'literature_rag/ports/protocols.py','literature_worker.py'}
HEADERS=content_report.HEADERS
save=content_report.save
ANALYST_NOTES=[
    '共同30题，要点93.06%→97.78%，五项全部达标20→23；单条引用有效率基本持平，事实支持率98.25%→98.21%、引用组完整率95.61%→95.54%略降，没有全面提高。',
    '第11题Table 1从本轮向量第15位升至重排第3位，关键数据进入模型。Jev将两项判为满分，但实际回答没有明确写出4000→8000转的数值反例；第二要点存在可能高估，需另行复核。本报告保留原判，不将其称为已完整满足要求。',
    '第18题明确区分相对峰面积与绝对含量；第13题的要点与限定条件判定改善。第32题正文相关系数进入上下文，但摘要0.888未进入，回答遗漏摘要与正文冲突，第二要点降为0.5。',
    '主命中的参考原文区间覆盖提高，但经过原有上下文补全后，两版总覆盖相同；第11题补足了关键表，同时其他题仍有未覆盖区间。位置覆盖不是语义充分性的证明。',
    '这是单轮开发集结果，生成表达、裁判边界和远端模型计算差异仍会影响得分；未证明稳定提升或新论文泛化。',
]


def source_controls(new_dir,old_dir):
    a,b=[judge.read_json(Path(d)/'run.json') for d in [new_dir,old_dir]]
    require(a['tasks']==b['tasks'] and a['dataset_manifest_sha256']==b['dataset_manifest_sha256'],'Question dataset changed')
    excluded={'pipeline_version','prompt_pipeline_sha256','pipeline_source_files','rerank'}
    require({k:v for k,v in a['configuration_probe'].items() if k not in excluded}==
        {k:v for k,v in b['configuration_probe'].items() if k not in excluded},'Answer, vector or context settings changed')
    settings=a['configuration_probe'].get('rerank',{})
    require(settings.get('enabled') and settings.get('version')=='candidate-rerank-v1','Rerank feature missing')
    require(not b['configuration_probe'].get('rerank',{}).get('enabled'),'Control already uses reranking')
    names={n for r in [a,b] for n in r['source_files'] if n.startswith('literature_rag/') or n=='literature_worker.py'}
    changed=[];unchanged=[]
    for n in sorted(names):
        texts=[]
        for d,r in zip([new_dir,old_dir],[a,b],strict=True):
            p=Path(d)/'backend'/n
            if p.is_file():require(judge.digest(p)==r['source_files'][n],'Frozen source changed')
            texts.append(p.read_bytes().replace(b'\r\n',b'\n') if p.is_file() else None)
        if texts[0]!=texts[1]:
            require(n in ALLOWED,'Unapproved runtime source change: '+n);changed.append(n)
        else:unchanged.append(n)
    for n in ['literature_rag/application/prompts.py','literature_rag/application/answer_question.py',
              'literature_rag/application/citations.py','literature_rag/application/context.py',
              'literature_rag/application/table_evidence.py','literature_rag/adapters/providers/deepseek.py',
              'literature_rag/adapters/providers/openai.py']:
        require(n in unchanged,'Answer or existing retrieval component changed')
    return dict(question_dataset_equal=True,configuration_equal_except_explicit_rerank=True,
        changed_runtime_files=changed,unchanged_runtime_files=unchanged,comparison='Original fingerprints verified; CRLF/LF normalized only for source comparison.')


def paired(metrics,tids,control):
    # Reuse the established maximum-pairing rules with the experiment key renamed.
    remapped={(('content' if s=='rerank' else 'control'),t):v for (s,t),v in metrics.items() if s in ['rerank',control]}
    p=content_report.paired(remapped,tids,'control')
    p['scores']={control:p['scores']['control'],'rerank':p['scores']['content']}
    for x in p['exclusions']:x['missing_or_flagged']=[control if s=='control' else 'rerank' for s in x['missing_or_flagged']]
    return p


def combine_grade_audits(direct,recovery):
    """First-valid judgments across a logged transport recovery; never rescore a valid grade."""
    require(direct[1]==recovery[1],'Recovery scientific jobs differ')
    require(direct[2]['requested_judges']==recovery[2]['requested_judges'],'Recovery judge configuration differs')
    for a,b in zip(direct[2]['jobs'],recovery[2]['jobs'],strict=True):
        require(a['request_sha256']==b['request_sha256'] and a['name']==b['name'],'Recovery request changed')
    require(not(set(direct[3])&set(recovery[3])),'A valid original judgment was rescored')
    require(all(status!='pending' for audit in [direct,recovery] for _,_,status in audit[5]),'Wait for pending grading')
    combined=list(recovery)
    combined[3]={**direct[3],**recovery[3]}
    combined[4]={k:direct[4].get(k,[])+recovery[4].get(k,[]) for k in set(direct[4])|set(recovery[4])}
    combined[5]=direct[5]+recovery[5]
    combined[6]=[dict(p,execution_phase=phase) for phase,a in [('direct',direct),('proxy_recovery',recovery)] for p in a[6]]
    return tuple(combined)


def corpus_proof():
    new,old=[RUNS[s]/'library' for s in ['rerank','content']]
    require(content_report.chunk_rows(new)==content_report.chunk_rows(old),'Evidence contents or locators changed')
    names=['structure.json','native-source.json','quality-ledger.json','chunk-organization.json',
        'table-retrieval.json','table-row-vectors.json']
    checks={n:judge.digest(new/n) for n in names}
    require(all(h==judge.digest(old/n) for n,h in checks.items()),'Parsing, table rows or source mapping changed')
    import chromadb
    vectors=[]
    for d in [new,old]:
        client=chromadb.PersistentClient(path=str(d/'chroma'));collections=client.list_collections()
        require(len(collections)==1,'Expected one collection')
        got=client.get_collection(collections[0].name).get(include=['embeddings'])
        vectors.append({cid:v.tolist() for cid,v in zip(got['ids'],got['embeddings'],strict=True)})
    require(vectors[0]==vectors[1] and len(vectors[0])==85,'Primary vectors changed')
    return dict(identical_evidence_chunks=85,identical_primary_vectors=85,identical_sidecars=checks,new_document_embedding_calls=0)


def retrieve_diagnostics(cases):
    lib=RUNS['rerank']/'library';structure=judge.read_json(lib/'structure.json')
    native=judge.read_json(lib/'native-source.json');ledger=judge.read_json(lib/'quality-ledger.json')
    corrections={r['source_id']:r for r in ledger};units=deepcopy(native['units'])
    for u in units:
        if r:=corrections.get(u['source_id']):u.update(text=r['corrected_text'],kind=r['corrected_kind'])
    references=judge.read_json(RUNS['rerank']/'dataset/evidence.json');pages=source_pages(units)
    alignment={e['id']:locate_evidence(e,units,pages) for e in references}
    spans={cid:[{k:s[k] for k in ['source_id','start','end']} for s in m['source_spans']] for cid,m in structure['mapping'].items()}
    details={};coverage_counts={};full_pools_same=0;pool_sets_same=0;max_cosine_difference=0
    for tid,case in cases.items():
        new,old=[judge.read_json(RUNS[s]/'results'/(tid+'.json'))['response'] for s in ['rerank','content']]
        ranking=new['context_assembly']['rerank'];candidate_ids=[v['chunk_id'] for v in ranking['candidates']]
        require(len(candidate_ids)<=50 and len(set(candidate_ids))==len(candidate_ids),'Invalid rerank parent candidates')
        require(ranking['selected_chunk_ids']==[e['chunk_id'] for e in new['retrieval_seed_evidence']],'Ranked selections differ')
        rank_map={c['chunk_id']:c for c in ranking['candidates']}
        for e in new['retrieval_seed_evidence']:
            require(e['score']==rank_map[e['chunk_id']]['vector_score'],'Cosine was overwritten with rerank score')
        before=new['context_assembly']['table_retrieval']['candidates'];historical=old['context_assembly']['table_retrieval']['candidates']
        pool_same=[x['chunk_id'] for x in before]==[x['chunk_id'] for x in historical]
        full_pools_same+=pool_same
        a,b=[{x['chunk_id']:x['score'] for x in pool} for pool in [before,historical]]
        same_set=a.keys()==b.keys();pool_sets_same+=same_set
        difference=max((abs(a[k]-b[k]) for k in a.keys()&b.keys()),default=0)
        max_cosine_difference=max(max_cosine_difference,difference)
        targets=sorted({eid for p in case['key_points'] if not p['optional'] and p['capability']=='text' for eid in p['evidence_ids']})
        selected={}
        for s,response in [('rerank',new),('content',old)]:
            seeds=[e['chunk_id'] for e in response['retrieval_seed_evidence']]
            final=sorted({c['chunk_id'] for e in response['retrieved_evidence'] for c in e.get('source_chunks',[])})
            selected[s]={}
            for level,ids in [('top8',seeds),('context',final)]:
                coverage={eid:span_coverage(alignment[eid],ids,spans) for eid in targets}
                selected[s][level]=coverage
                counter=coverage_counts.setdefault(s,{}).setdefault(level,Counter())
                for eid,cov in coverage.items():
                    if alignment[eid]['status']!='located':counter['alignment_unknown_or_review_required']+=1
                    else:counter[cov['status']]+=1
        # Within the very same live candidate pool, isolate selection by cosine vs rerank.
        same_pool_ids=[c['chunk_id'] for c in sorted(ranking['candidates'],key=lambda c:c['vector_rank'])[:8]]
        coverage={eid:span_coverage(alignment[eid],same_pool_ids,spans) for eid in targets}
        selected['vector_same_pool']={'top8':coverage}
        counter=coverage_counts.setdefault('vector_same_pool',{}).setdefault('top8',Counter())
        for eid,cov in coverage.items():
            if alignment[eid]['status']!='located':counter['alignment_unknown_or_review_required']+=1
            else:counter[cov['status']]+=1
        text='\n'.join(e['text'] for e in new['retrieved_evidence'])
        details[tid]=dict(rerank=ranking,original_candidate_order_equal=pool_same,original_candidate_set_equal=same_set,
            maximum_shared_candidate_cosine_difference=difference,
            reference_span_coverage=selected,source_value_markers={v:v in text for v in ['70.42','72.54','0.888','0.912','0.889']},
            context_chars=new['context_assembly']['context_chars'],budget_limited=new['context_assembly']['budget_limited'],
            diagnostic_only='Raw source-position coverage, not semantic sufficiency, a sixth judge dimension or a replacement for Jev.')
    return details,dict(reference_span_counts=coverage_counts,questions_with_identical_original_candidate_order=full_pools_same,
        questions_with_identical_candidate_set=pool_sets_same,maximum_shared_candidate_cosine_difference=max_cosine_difference,
        alignment_statuses=dict(Counter(a['status'] for a in alignment.values()))),alignment


def rerank_accounting():
    calls=[c for path in sorted((RUNS['rerank']/'results').glob('*.json')) for c in judge.read_json(path)['response'].get('rerank_calls',[])]
    require(len(calls)==32 and all(c['status']=='completed' for c in calls),'Expected one completed rerank call per answer')
    tokens=Counter()
    for c in calls:tokens.update(c['usage'] or {})
    probe=judge.read_json(PRIVATE/'candidate-rerank-probe-20261030/PFI2-011.json')
    return dict(answering_calls=len(calls),known_tokens=dict(tokens),usage_unknown_calls=sum(c['usage'] is None for c in calls),
        median_call_seconds=statistics.median(c['latency_ms'] for c in calls)/1000,actual_billing=None,
        independent_probe_calls=1,probe=probe['provider_call'],probe_included_in_answer_runtime=False,total_new_rerank_calls=33),probe


def score_cells(system,value):
    with override(content_report.previous_report,LABELS=LABELS):return content_report.previous_report.score_cells(system,value)


def html_report(path,result,rows):
    e=lambda v:escape(str(v),quote=True)
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>候选重排：32题Jev评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1400px;margin:30px auto;padding:0 22px}article,section{background:white;border:1px solid #dce5ef;border-radius:9px;padding:18px;margin:15px 0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.6 monospace}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dce5ef;padding:8px;text-align:left;vertical-align:top}.scroll{overflow:auto}summary{cursor:pointer;font-weight:650}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #b6cce4;border-radius:7px}p{overflow-wrap:anywhere}</style><main>',
        '<h1>候选证据重排：32题Jev评测</h1><p>2026-10-31发布；实验于10月30日启动。固定85块及原向量、回答模型、提示词和上下文预算，仅新增BGE-reranker-v2-m3重排。</p>',
        '<p>五项：必答要点0/0.5/1、事实支持四类标签、单条引用0/1、引用组完整/部分/缺失、边界0/1/2。缺失不记零，不计算加权总分；原评分直接复用，只对新回答调用Jev。</p>']
    for control,c in result['comparisons'].items():
        parts+=['<section><h2>'+e(LABELS[control])+' → '+e(LABELS['rerank'])+'</h2><div class="scroll"><table><tr>'+''.join('<th>'+e(h)+'</th>' for h in HEADERS)+'</tr>']
        for s,value in c['scores'].items():parts.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in score_cells(s,value))+'</tr>')
        parts+=['</table></div><p>要点变化'+f"{c['point_delta']*100:+.2f}"+'个百分点；提高：'+e(c['point_wins'])+'；下降：'+e(c['point_losses'])+'。</p>',
            '<p>新增全部达标：'+e(c['all_five_wins'])+'；失去全部达标：'+e(c['all_five_losses'])+'。</p>',
            '<details><summary>共同题目与排除原因</summary><pre>'+e(json.dumps(dict(task_ids=c['task_ids'],exclusions=c['exclusions']),ensure_ascii=False,indent=2))+'</pre></details></section>']
    parts+=['<section><h2>结果解读与需复核之处</h2>'+''.join('<p>'+e(n)+'</p>' for n in result.get('analyst_notes',[]))+'</section>',
        '<details><summary>费用、耗时、检索诊断与控制变量</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>',
        '<h2>全部32题</h2><p>Jev提供结构化判定和来源定位，不生成自由文字理由。原文位置覆盖是检索诊断，不是新的语义评分。</p><input id="search" placeholder="搜索题号或问题">']
    for row in rows:
        parts+=['<article data-search="'+e(row['task_id']+' '+row['question'])+'"><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与评分准则</summary><pre>'+e(json.dumps(row['reference_case'],ensure_ascii=False,indent=2))+'</pre></details>']
        for s,v in row['systems'].items():
            m=v['metrics'];label=f"要点 {m['required_point_sum']}/{m['required_point_count']}；边界 {m['boundary']}/2" if m else '有效评分缺失'
            parts+=['<details'+(' open' if s=='rerank' else '')+'><summary>'+e(LABELS[s])+' · '+e(label)+'</summary><p>'+e(v['candidate']['answer']).replace('\n','<br>')+'</p>',
                '<details><summary>Jev五项逐条判断</summary><pre>'+e(json.dumps(dict(metrics=m,review=v['review']),ensure_ascii=False,indent=2))+'</pre></details>',
                '<details><summary>原回答、引用和实际可用上下文</summary><pre>'+e(json.dumps(v['candidate'],ensure_ascii=False,indent=2))+'</pre></details></details>']
        parts+=['<details><summary>候选重排名次及参考证据位置覆盖</summary><pre>'+e(json.dumps(row['retrieval_diagnostics'],ensure_ascii=False,indent=2))+'</pre></details></article>']
    parts+=['<p>单轮开发集实验，未证明稳定性或新论文泛化。默认网站索引和功能开关未切换。</p><script>document.getElementById("search").addEventListener("input",function(){const q=this.value.trim().toLowerCase();document.querySelectorAll("article[data-search]").forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(q));});</script></main></html>']
    Path(path).write_text(''.join(parts),encoding='utf-8',newline='\n')


def report(refresh=False):
    if refresh:
        seal=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==h for n,h in seal['files'].items()),'Published report changed')
        require(judge.digest(DOC)==seal['document_sha256'],'Published document changed')
    else:require(not OUTPUT.exists() and not DOC.exists(),'Use new output destinations')
    audits={s:scoring.audit(*paths) for s,paths in STUDIES.items()}
    direct=scoring.audit(STUDIES['rerank'][0],DIRECT_STUDY)
    recovery=audits['rerank'];audits['rerank']=combine_grade_audits(direct,recovery)
    new=audits['rerank'];study=new[2]
    recovery_manifest=judge.read_json(STUDIES['rerank'][1]/'recovery-manifest.json')
    require(recovery_manifest['original_study_sha256']==judge.digest(DIRECT_STUDY/'study.json'),'Recovery original seal changed')
    require(recovery_manifest['recovery_study_sha256']==judge.digest(STUDIES['rerank'][1]/'study.json'),'Recovery seal changed')
    for e in study['jobs']:
        require((DIRECT_STUDY/'inputs'/(e['name']+'.json')).read_bytes()==(STUDIES['rerank'][1]/'inputs'/(e['name']+'.json')).read_bytes(),'Recovery judge input changed')
    require(set(study['requested_judges'])=={'jev'} and len(study['jobs'])==32,'Expected only 32 Jev jobs')
    require(all(e['judge']=='jev' and e['system']=='rag' for e in study['jobs']),'Unexpected judge or answer system')
    require(all(status!='pending' for _,_,status in new[5]),'Wait for in-flight scoring')
    controls=source_controls(RUNS['rerank'],RUNS['content']);proof=corpus_proof()
    config=judge.read_json(ROOT/'.rag-data/configs/candidate-rerank-v1-20261030-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==config['application_env_sha256'],'Default configuration changed')
    jobs,reviews,metrics={},{},{}
    for s,a in audits.items():
        for j in a[1]:
            if j['system']!='rag':continue
            tid=j['task_id'];jobs[(s,tid)]=j
            if r:=a[3].get(('jev','rag',tid)):
                reviews[(s,tid)]=r;metrics[(s,tid)]=scoring.metrics(r,j['reference_case'],j['task']['capabilities'])
    tids=sorted(t for s,t in jobs if s=='rerank')
    require(tids==[f'PFI2-{i:03}' for i in range(1,33)],'Original 32 questions required')
    for tid in tids:require(all(jobs[(s,tid)]['reference_case']==jobs[('rerank',tid)]['reference_case'] for s in STUDIES),'Reference answer changed')
    details,retrieval_summary,alignment=retrieve_diagnostics({t:jobs[('rerank',t)]['reference_case'] for t in tids})
    runtimes={}
    for s in RUNS:
        with override(runtime_report,RUN=RUNS[s]):runtimes[s]={k:v for k,v in runtime_report.runtime().items() if k!='per_question'}
    rerank_cost,probe=rerank_accounting()
    invalid=[]
    for phase,folder in [('direct',DIRECT_STUDY),('proxy_recovery',STUDIES['rerank'][1])]:
        with override(content_report,STUDIES={'content':(STUDIES['rerank'][0],folder)}):
            invalid.extend(dict(r,execution_phase=phase) for r in content_report.invalid_grading_records(study))
    attempts={e['task_id']:sum(len(list((folder/'records'/e['name']).glob('*.json'))) for folder in [DIRECT_STUDY,STUDIES['rerank'][1]]) for e in study['jobs']}
    result=dict(version='candidate-rerank-jev-v1',published_on='2026-10-31',experiment_started_on='2026-10-30',question_count=32,
        policy_sha256=grading.POLICY_SHA,valid_grades=sum(k=='jev' and s=='rag' for k,s,t in new[3]),
        grading_accounting=scoring.accounting(new[4].get('jev',[]),'jev'),grading_attempts_by_task=attempts,
        invalid_grading_records=invalid,new_luna_calls=0,new_control_grading_calls=0,
        transport_recovery=dict(manifest=recovery_manifest,direct_record_statuses=dict(Counter(r['status'] for r in direct[4].get('jev',[]))),
            original_valid_grades=len(direct[3]),new_recovery_valid_grades=len(recovery[3]),request_bytes_identical=True,
            interruption_sha256=judge.digest(DIRECT_STUDY/'transport-interruption.json')),
        comparisons={s:paired(metrics,tids,s) for s in ['content','tables','pymupdf']},
        controls=controls,corpus_proof=proof,rerank_accounting=rerank_cost,answer_runtime=runtimes,
        retrieval_summary=retrieval_summary,default_configuration_unchanged=True,analyst_notes=ANALYST_NOTES,
        limitations=['One generation run and first-valid Jev grades; development set, no stability or holdout claim.',
            'Raw source-span coverage does not prove semantic evidence sufficiency; uncertain alignments are excluded from confirmed coverage.',
            'Remote model aliases/settings do not guarantee identical provider weights.',
            'Money unknown for answer and rerank calls; judge API-reported costs are not invoices.'])
    rows=[dict(task_id=t,question=jobs[('rerank',t)]['reference_case']['question'],reference_case=jobs[('rerank',t)]['reference_case'],
        systems={s:dict(candidate=jobs[(s,t)]['candidate'],review=reviews.get((s,t)),metrics=metrics.get((s,t))) for s in LABELS},
        retrieval_diagnostics=details[t]) for t in tids]
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result);save(OUTPUT/'retrieval-diagnostics.json',details);save(OUTPUT/'reference-alignment.json',alignment)
    save(OUTPUT/'independent-probe.json',probe);save(OUTPUT/'invalid-grading-records.json',invalid)
    save(OUTPUT/'transport-interruption.json',judge.read_json(DIRECT_STUDY/'transport-interruption.json'))
    save(OUTPUT/'transport-recovery.json',recovery_manifest)
    save(OUTPUT/'audit.json',dict(controls=controls,corpus_proof=proof,policy_sha256=grading.POLICY_SHA,
        studies={s:dict(import_sha256=judge.digest(p[0]/'import.json'),study_sha256=judge.digest(p[1]/'study.json'),
            grade_proofs=[proof for proof in audits[s][6] if proof['name'].startswith('jev-')]) for s,p in STUDIES.items()},
        original_direct_study_sha256=judge.digest(DIRECT_STUDY/'study.json')))
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
    html_report(OUTPUT/'comparison.html',result,rows)
    lines=['# 候选证据重排：32题Jev评测','','2026-10-31发布，实验于2026-10-30启动。仅在内容组织85块版增加BGE-reranker-v2-m3候选重排。',
        '',f"32题答题状态：{runtimes['rerank']['outcomes']}；有效Jev评分{result['valid_grades']}/32。旧评分直接复用，不新增Luna评分。",'',
        '所有语义分数保留Jev原判定；五项规则与参考答案不变，缺失不记零，不计算加权总分。','']
    for control,c in result['comparisons'].items():
        lines+=['## '+LABELS[control]+' → '+LABELS['rerank'],'','| '+' | '.join(HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |']
        for s,v in c['scores'].items():lines.append('| '+' | '.join(map(str,score_cells(s,v)))+' |')
        lines+=['',f"共同{c['tasks']}题，要点变化{c['point_delta']*100:+.2f}个百分点。",'',
            '要点提高：'+(', '.join(c['point_wins']) or '无')+'。','要点下降：'+(', '.join(c['point_losses']) or '无')+'。',
            '新增全部达标：'+(', '.join(c['all_five_wins']) or '无')+'。','失去全部达标：'+(', '.join(c['all_five_losses']) or '无')+'。',
            '排除：'+json.dumps(c['exclusions'],ensure_ascii=False)+'。','']
    lines+=['## 结果解读与待复核','',*sum(([n,''] for n in ANALYST_NOTES),[]),
        '以上为对回答文本、检索记录和裁判标签的核对，属于报告诊断，不是Jev生成的自由文字理由，也不修改其分数。','',
        '## 检索与来源检查','',
        '85个证据块、全部85个主向量及解析修正、来源映射、20条表格行向量完全相同；新增文献Embedding为0。原问题、向量阈值0.35、最多50个候选、最多8个主命中、8000/24000字符预算不变。',
        '',f"32题中原候选ID顺序相同的题数为{retrieval_summary['questions_with_identical_original_candidate_order']}；实际重排名次与原向量分数分开保存。",'',
        f"32题的候选ID集合均相同，但6题的顺序不同，共有候选向量分数最大差异{retrieval_summary['maximum_shared_candidate_cosine_difference']:.6f}。模型接口及参数相同不保证远端计算逐位一致，因此另行统计同一次请求、同一候选池内的纯向量前8与重排前8，分离此次排序选择的影响。",'',
        '参考证据位置诊断：'+json.dumps(retrieval_summary,ensure_ascii=False)+'。',
        '', '按每题引用到的参考证据去重、跨题重复计数，共47个题目—参考证据配对，其中39个可确认定位，8个待核对。只对可确认定位的原文区间统计完整/部分/缺失覆盖；近似对齐和无法定位记为待核对，不当成检索失败。此为原文位置诊断，不是第六项语义评分。','']
    by_id={r['task_id']:r for r in rows}
    for tid in ['PFI2-004','PFI2-011','PFI2-013','PFI2-023','PFI2-027','PFI2-028','PFI2-029','PFI2-032']:
        r=by_id[tid]
        lines+=['### '+tid,'',r['question'],'',
            '原85块要点：'+json.dumps((r['systems']['content']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'。',
            '重排后要点：'+json.dumps((r['systems']['rerank']['review'] or {}).get('key_point_scores'),ensure_ascii=False)+'。',
            '数值字符串是否在实际上下文：'+json.dumps(details[tid]['source_value_markers'],ensure_ascii=False)+'。','']
    new_rt,old_rt=[runtimes[s] for s in ['rerank','content']];cost=result['grading_accounting']
    lines+=['## 用量、费用与限制','',
        f"正式32题重排请求{rerank_cost['answering_calls']}次，已知用量{json.dumps(rerank_cost['known_tokens'])}，重排调用中位数{rerank_cost['median_call_seconds']:.3f}秒；另有第11题独立探测1次，不混入正式运行。重排货币费用未知。",'',
        f"答题端到端中位数{old_rt['median_end_to_end_seconds']:.2f}→{new_rt['median_end_to_end_seconds']:.2f}秒；生成调用{old_rt['generation_calls']}→{new_rt['generation_calls']}次，生成Token {old_rt['generation_known_tokens']['total_tokens']:,}→{new_rt['generation_known_tokens']['total_tokens']:,}；查询Embedding仍32次、{new_rt['embedding_known_tokens']} Token。推理Token已包含在生成Token内。实际生成货币费用未知。",'',
        f"新增Jev请求{cost['calls']}次，API报告费用${cost['reported_cost_usd']}；费用未知{cost['cost_unknown_calls']}次。无效尝试同样计费统计，旧答案和旧评分不重跑。",'',
        f"评分直连阶段发生ReadError等传输故障，停止该进程后，保留{len(direct[3])}题有效评分；剩余{len(recovery[3])}题经电脑现有本地HTTP代理补齐。两阶段评分输入逐字节相同，模型和规则不变，已有效题不重评。失败/中断请求与恢复请求均计入上述总数；未收到响应的请求是否上游执行或计费未知。中断前后的状态和指纹另存，未改写任何收到的评分。",'',
        '重排能否送入关键证据与回答是否使用该证据分开检查。单轮开发集实验不能证明稳定性、新论文泛化或统计显著性；模型别名和参数固定，远端权重不可验证。网站默认索引和重排开关未切换。','',
        '[全部32题、四套回答与Jev逐项判定](../data/literature/qa-evaluation/reports/candidate-rerank-jev-20261030/comparison.html)。',
        '[实现范围、开关与首次探测](QA_CANDIDATE_RERANK_V1_20261030.md)。','']
    DOC.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    save(OUTPUT/'publication.json',dict(version=result['version'],document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),
        files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'}))
    return {k:result[k] for k in ['valid_grades','comparisons','grading_accounting','retrieval_summary']}


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    print(json.dumps(report(args.refresh),ensure_ascii=False))
