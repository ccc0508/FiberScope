"""Matched five-dimension comparison of MinerU native text RAG and archived controls."""
from contextlib import contextmanager
from html import escape
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
import qa_system_judge as grading
import report_qa_system_benchmark as reporting
import report_qa_context_v1_20261029 as context_report
from validate_qa_eval import require

PRIVATE=ROOT/'.rag-data/evaluations'
ORIGINAL_IMPORT=PRIVATE/'dsh-rag-five-import-20261028-r1'
ORIGINAL_STUDY=PRIVATE/'dsh-rag-five-judges-20261028-r1'
CONTROL_IMPORT=PRIVATE/'context-v1-five-import-20261029-r1'
CONTROL_STUDY=PRIVATE/'context-v1-five-judges-20261029-r1'
NEW_IMPORT=PRIVATE/'mineru-native-five-import-20261029-r1'
NEW_STUDY=PRIVATE/'mineru-native-five-judges-20261029-r1'
RUN=PRIVATE/'pfi-mineru-native-v1-20261029-r1'
CONTROL_RUN=PRIVATE/'pfi-context-v1-20261029-r1'
OUTPUT=ROOT/'data/literature/qa-evaluation/reports/mineru-native-v1-20261029'
DOC=ROOT/'docs/QA_MINERU_RAG_REPORT_20261029.md'
LABELS={'pymupdf':'PyMuPDF结构版81块','mineru':'MinerU原生文本117块','original':'原固定44块','dsh':'DSH'}


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


@contextmanager
def override(module,**values):
    original={key:getattr(module,key) for key in values}
    try:
        for key,value in values.items():setattr(module,key,value)
        yield
    finally:
        for key,value in original.items():setattr(module,key,value)


def reuse():
    with override(context_report,NEW_IMPORT=NEW_IMPORT,NEW_STUDY=NEW_STUDY):context_report.reuse()


def aggregate_primary(metrics,task_ids):
    result={}
    for kind in ['luna','jev']:
        chosen=[tid for tid in task_ids if all((kind,s,tid) in metrics and not metrics[(kind,s,tid)]['reference_concern'] for s in ['pymupdf','mineru'])]
        require(chosen,'No valid primary matched comparison')
        result[kind]=dict(task_ids=chosen,scores={s:reporting.summarize([metrics[(kind,s,tid)] for tid in chosen]) for s in ['pymupdf','mineru']},
            point_wins=[t for t in chosen if metrics[(kind,'mineru',t)]['point_mean']>metrics[(kind,'pymupdf',t)]['point_mean']],
            point_losses=[t for t in chosen if metrics[(kind,'mineru',t)]['point_mean']<metrics[(kind,'pymupdf',t)]['point_mean']])
    return result


def report(refresh=False):
    if refresh:
        publication=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/name)==checksum for name,checksum in publication['files'].items()),'Existing report changed')
        require(judge.digest(DOC)==publication['document_sha256'],'Existing report document changed')
    else:require(not OUTPUT.exists() and not DOC.exists(),'Use new report destinations')
    audits={name:reporting.audit(i,s) for name,i,s in [('original',ORIGINAL_IMPORT,ORIGINAL_STUDY),('pymupdf',CONTROL_IMPORT,CONTROL_STUDY),('mineru',NEW_IMPORT,NEW_STUDY)]}
    for data in audits.values():require(all(status!='pending' for _,_,status in data[5]),'Wait for pending judge calls')
    reused=judge.read_json(NEW_STUDY/'reused-dsh-records.json')
    require(reused['source_study_sha256']==judge.digest(ORIGINAL_STUDY/'study.json'),'Original reused study changed')
    require(reused['target_study_sha256']==judge.digest(NEW_STUDY/'study.json'),'Reuse target changed')
    for entry in reused['records']:
        require(judge.digest(NEW_STUDY/entry['relative_path'])==entry['sha256']==judge.digest(ORIGINAL_STUDY/entry['source_relative_path']),'Reused grading attempt changed')
    jobs={};reviews={};metrics={}
    by_audit={name:{(j['system'],j['task_id']):j for j in data[1]} for name,data in audits.items()}
    tids=sorted(t for s,t in by_audit['mineru'] if s=='rag')
    require(len(tids)==32,'Expected 32 questions')
    for tid in tids:
        reference=by_audit['original'][('rag',tid)]['reference_case']
        for name in ['pymupdf','mineru']:
            require(by_audit[name][('rag',tid)]['reference_case']==reference,'Reference standard changed')
            require(by_audit[name][('dsh',tid)]==by_audit['original'][('dsh',tid)],'Archived DSH content changed')
        for name in LABELS:
            audit_name='original' if name=='dsh' else name;source_system='dsh' if name=='dsh' else 'rag'
            job=by_audit[audit_name][(source_system,tid)];jobs[(name,tid)]=job
            for kind in ['luna','jev']:
                review=audits[audit_name][3].get((kind,source_system,tid))
                if review is not None:
                    reviews[(kind,name,tid)]=review
                    metrics[(kind,name,tid)]=reporting.metrics(review,job['reference_case'],job['task']['capabilities'])
    common=[tid for tid in tids if all((k,s,tid) in metrics and not metrics[(k,s,tid)]['reference_concern'] for k in ['luna','jev'] for s in LABELS)]
    require(common,'No common four-system comparison')
    primary=aggregate_primary(metrics,tids)
    new=audits['mineru'];study=new[2]
    names={e['name'] for e in study['jobs'] if e['system']=='rag'}
    new_calls={kind:[judge.read_json(p) for name in sorted(names) if name.startswith(kind+'-')
        for p in sorted((NEW_STUDY/'records'/name).glob('*.json'),key=lambda p:int(p.stem))] for kind in ['luna','jev']}
    costs={k:reporting.accounting(new_calls[k],k) for k in ['luna','jev']}
    old_run=judge.read_json(CONTROL_RUN/'run.json');new_run=judge.read_json(RUN/'run.json')
    kept=['embedding_provider','embedding_model','embedding_dimensions','llm_provider','llm_model','llm_thinking_enabled',
          'llm_reasoning_effort','top_k','min_score','context_expansion','prompt_pipeline_sha256','provider_endpoint_fingerprints']
    require(all(old_run['configuration_probe'].get(k)==new_run['configuration_probe'].get(k) for k in kept),'Controlled runtime setting changed')
    controls=judge.read_json(ROOT/'.rag-data/configs/mineru-rag-20261029-controls.json')
    require(judge.digest(ROOT/'backend/.env.literature')==controls['application_env_sha256'],'Application configuration changed')
    with override(context_report,RUN=RUN):runtime=context_report.runtime()
    build=judge.read_json(ROOT/'.rag-data/index-versions/mineru-native-v1-20261029/structure.json')
    _,billing=reporting.runtime_metadata(ORIGINAL_IMPORT,audits['original'][0]['metadata'])
    result=dict(version='mineru-native-text-rag-v1',published_on='2026-10-30',question_count=32,policy_sha256=grading.POLICY_SHA,
        primary_comparison=primary,common_task_ids=common,common_tasks=len(common),
        primary_exclusions={kind:[dict(task_id=t,unavailable=[s for s in ['pymupdf','mineru']
            if (kind,s,t) not in metrics or metrics[(kind,s,t)]['reference_concern']])
            for t in tids if t not in primary[kind]['task_ids']] for kind in ['luna','jev']},
        common_scores={k:{s:reporting.summarize([metrics[(k,s,t)] for t in common]) for s in LABELS} for k in ['luna','jev']},
        new_valid_grades=sum(s=='rag' for k,s,t in new[3]),
        new_grading_coverage={k:{status:n for (kind,s,status),n in new[5].items() if kind==k and s=='rag'} for k in ['luna','jev']},
        new_grading_accounting=costs,new_answer_runtime=runtime,
        one_time_index_embedding=dict(chunks=build['chunks'],calls=build['embedding_calls'],
            known_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in build['embedding_calls']),actual_billing_usd=None),
        controlled_configuration={k:new_run['configuration_probe'].get(k) for k in kept},
        native_index=dict(chunks=build['chunks'],chunk_kinds=build['chunk_kinds'],native_blocks=build['native_blocks'],
            policy=build['unit_policy'],visual_policy=build['visual_policy'],parser_version=build['reported_parser_version'],backend=build['reported_backend']),
        exclusions=[dict(task_id=t,unavailable=[k+'_'+s for k in ['luna','jev'] for s in LABELS
            if (k,s,t) not in metrics or metrics[(k,s,t)]['reference_concern']]) for t in tids if t not in common],
        dsh_runtime=billing,new_dsh_provider_calls=0,reused_dsh_jobs=64,
        rag_quote_validation=new[0].get('rag_quote_validation'),rag_quote_verification=new[0].get('rag_quote_verification'),
        active_application_configuration_unchanged=True,
        limitations=['MinerU native-block adaptation and PyMuPDF rule-based chunking differ; not a parser-only ablation.',
            'One paper, 32 development questions, one new generation set; no generalization, significance or stability claim.',
            'Old valid grades are reused. Generation randomness and evaluator service drift may affect differences.',
            'Scientific reference material and five-dimension policy are unchanged; nonmatching parser citations additionally include original-page locator review.',
            'Only captions are indexed; no image pixels or vision model are used. Known MinerU duplicates and heading errors are preserved.',
            'Metrics have different claim/citation denominators and are not summed into overall accuracy.'])
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'comparison.json',result)
    rows=[]
    for tid in tids:
        row=dict(task_id=tid,question=jobs[('mineru',tid)]['reference_case']['question'],
            reference_answer=jobs[('mineru',tid)]['reference_case']['reference_answer'],
            key_points=jobs[('mineru',tid)]['reference_case']['key_points'],systems={})
        for system in LABELS:
            row['systems'][system]=dict(candidate={k:v for k,v in jobs[(system,tid)]['candidate'].items() if k!='available_context'},
                judges={kind:dict(review=reviews.get((kind,system,tid)),metrics=metrics.get((kind,system,tid))) for kind in ['luna','jev']})
        rows.append(row)
    (OUTPUT/'questions-answers-reviews.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    save(OUTPUT/'audit.json',dict(import_sha256={s:judge.digest(i/'import.json') for s,i in [('original',ORIGINAL_IMPORT),('pymupdf',CONTROL_IMPORT),('mineru',NEW_IMPORT)]},
        study_sha256={s:judge.digest(i/'study.json') for s,i in [('original',ORIGINAL_STUDY),('pymupdf',CONTROL_STUDY),('mineru',NEW_STUDY)]},
        run_sha256=judge.digest(RUN/'run.json'),reused_dsh_manifest_sha256=judge.digest(NEW_STUDY/'reused-dsh-records.json'),
        grade_proofs={s:a[6] for s,a in audits.items()},exporter_assigns_no_scientific_scores=True))
    render(result,rows)
    save(OUTPUT/'publication.json',dict(files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    print(json.dumps(dict(new_valid_grades=result['new_valid_grades'],primary=primary,common_tasks=len(common),accounting=costs),ensure_ascii=False))


def score_cells(s):
    facts=s['support_counts'];total=sum(facts.values())
    return [reporting.percent(s['point_macro_average']),reporting.ratio(reporting.fraction(facts.get('supported',0),total)),reporting.ratio(s['citation_precision']),
        reporting.ratio(s['citation_coverage']),f"{s['boundary_mean']:.3f}",f"{s['all_five_pass']}/{s['tasks']}"]


def render(result,rows):
    header=['评委','流程','必答要点','事实完全支持','单条引用有效','引用组完整','边界 / 2','五项同时达标']
    table=[]
    for kind,paired in result['primary_comparison'].items():
        for system in ['pymupdf','mineru']:table.append([kind,LABELS[system],*score_cells(paired['scores'][system])])
    md=['# MinerU文本RAG与PyMuPDF结构版：32题对照','',
        '2026-10-30完成报告，实验批次20261029。MinerU原生文本117块版本重新答题并由Luna、Jev独立评分，主对照为前一轮PyMuPDF结构版81块；原44块和DSH归档仅作补充。','',
        f"32题答题完成，新版有效评分{result['new_valid_grades']}/64。主表内每位裁判的两套流程使用相同题目，各裁判集合可能不同。",'',
        '| '+' | '.join(header)+' |','| '+' | '.join(['---']*len(header))+' |']
    md += ['| '+' | '.join(row)+' |' for row in table]
    md += ['', '本轮两位裁判对PyMuPDF结构版的必答要点和五项同时达标数均给出更高结果；引用相关指标有升有降。尚无理由用这版MinerU原生块流程直接替换当前问答索引。结论仅适用于这篇论文、当前适配方式和本轮回答。','']
    md += ['', '## 每题变化与分母','']
    for kind,p in result['primary_comparison'].items():
        delta=(p['scores']['mineru']['point_macro_average']-p['scores']['pymupdf']['point_macro_average'])*100
        md += [f"- {kind}：{len(p['task_ids'])}题；必答要点变化{delta:+.2f}个百分点，提高{len(p['point_wins'])}题、下降{len(p['point_losses'])}题。",
               f"  提高：{', '.join(p['point_wins']) or '无'}；下降：{', '.join(p['point_losses']) or '无'}。"]
        if result['primary_exclusions'][kind]:
            md.append('  配对排除：'+json.dumps(result['primary_exclusions'][kind],ensure_ascii=False)+'。评分缺失不计为零分。')
    md += ['',f"四套流程、两位裁判全部有效的共同集合为{result['common_tasks']}/32题，另列于HTML与JSON；不替代上面的主对照分母。",'',
        '## 需要解释的具体变化','',
        '- PFI2-011：MinerU回答说结晶度并非单调下降，但未给出4000到8000转回升的数值反例；原回答列出了针叶木序列。两位裁判都降低了要点评分。',
        '- PFI2-024：机制链条仍有回答，但遗漏“论文没有给出独立贡献排名或控制其他因素后的效应量”这一限制；两位裁判对该要点都给0分。',
        '- PFI2-025：回答提到补充材料Table S1，却没有明确回答所求数值不可从现有正文获得、需要取得补充表；两位裁判均未给该题要点分。它没有编造比表面积数值，问题是没有完成回答。',
        '- PFI2-013：MinerU版本更一致地保留了“可能”“可解释为”的机制不确定性，Luna要点评分提高；Jev两版都满分。',
        '- 这些是已保存回答和裁判标签中可见的差异，不能证明所有退步都来自解析器。下一轮应先区分证据是否进入上下文、答案是否漏用，再设计适配改进。','',
        '## 控制变量与局限','',
        '- 同一PDF、原32题、参考答案和共同五项评分标准；BGE-M3/1024维、DeepSeek Flash/High、top_k=8、阈值0.35、同页邻块半径1、8,000/24,000字符预算、答题源代码指纹完全一致。',
        '- 改变的是解析结果及检索块组织：PyMuPDF规则81块，MinerU原生117块；不是只替换解析器的单因素实验。',
        '- MinerU重复正文、错误标题、原始HTML和科学符号原样保留；图片只索引图注，未增加视觉模型。',
        '- MinerU引用额外核对原PDF抽取，不匹配时给评委提供对应原页复核，不能只因抽取差异自动扣分；科学依据和评分规则没有改变。',
        f"- 本轮实际引用定位核验：{json.dumps(result['rag_quote_verification'],ensure_ascii=False)}。需原页复核不等于引用错误；HTML、公式及拼接窗口也会导致全文匹配失败。",
        '- 既有评分复用，保留首个有效结果；不代表评委稳定性或新论文泛化。各指标独立报告，不求综合正确率。','',
        '## 开销','',
        f"一次性索引：{result['one_time_index_embedding']['known_tokens']:,} Embedding Token，2次调用。复用先前MinerU解析结果，无新增PDF解析调用。"]
    rt=result['new_answer_runtime']
    md += [f"答题：{rt['generation_calls']}次生成；已知生成Token {rt['generation_known_tokens'].get('total_tokens',0):,}，问题Embedding Token {rt['embedding_known_tokens']:,}。",
        f"评测进程端到端中位数{rt['median_end_to_end_seconds']:.2f}秒，含独立进程启动；答题与Embedding实际货币费用未知。"]
    for kind,cost in result['new_grading_accounting'].items():
        md.append(f"- {kind}新增{cost['calls']}次评分请求，API报告${cost['reported_cost_usd']}，另有{cost['cost_unknown_calls']}次费用未知。")
    md += ['', 'DSH的64个评分任务先核验请求字节完全一致后复用，未新增DSH调用；不计入本轮新增费用。','',
        '[完整32题、四套回答和双评理由](../data/literature/qa-evaluation/reports/mineru-native-v1-20261029/comparison.html)。',
        '[实验方法与索引规则](QA_MINERU_RAG_EXPERIMENT_20261029.md)。', '',
        '应用默认配置和原索引未切换。离线重建：`python scripts/report_mineru_rag_20261029.py refresh`，需要保留本机私有运行和评分档案。']
    DOC.write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
    e=lambda text:escape(str(text),quote=True)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MinerU文本RAG对照评测</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1560px;margin:32px auto;padding:0 24px}table{width:100%;border-collapse:collapse;background:white}td,th{padding:9px;border:1px solid #dce5ef;text-align:left;vertical-align:top}.scroll{overflow:auto}article,details{background:white;border:1px solid #dce5ef;border-radius:9px;padding:16px;margin:16px 0}summary{cursor:pointer;font-weight:650}.answers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 ui-monospace,monospace;background:#f6f8fb;padding:12px}h2{font-size:20px}h3{font-size:17px}@media(max-width:1000px){.answers{display:block}}</style><main>',
        '<h1>MinerU文本RAG与PyMuPDF结构版：32题对照</h1>',
        f"<p>MinerU新答题32题，新版有效评分{result['new_valid_grades']}/64。主对照为PyMuPDF结构版81块；保留原44块与DSH作为补充。</p>",
        '<p><strong>本轮判断：</strong>当前PyMuPDF结构版的必答要点与五项同时达标数在两位裁判下均更高，暂不切换默认索引。实验批次20261029，2026-10-30完成报告。</p>',
        '<p>同一论文、题目、标准答案、评分规则、Embedding、答题模型及检索设置。原生块适配方式不同，不能将差异单独归因于解析器。只做文本问答，没有增加视觉模型或重排。</p>',
        '<h2>主对照：每位裁判的相同有效题目</h2><div class="scroll"><table><tr>'+''.join('<th>'+e(h)+'</th>' for h in header)+'</tr>']
    for row in table:html.append('<tr>'+''.join('<td>'+e(c)+'</td>' for c in row)+'</tr>')
    html.append('</table></div>')
    for kind,p in result['primary_comparison'].items():
        delta=(p['scores']['mineru']['point_macro_average']-p['scores']['pymupdf']['point_macro_average'])*100
        html.append(f"<p>{e(kind)}：{len(p['task_ids'])}题；必答要点变化{delta:+.2f}个百分点，提高{len(p['point_wins'])}题，下降{len(p['point_losses'])}题。</p>")
    html.append('<p>上述比率采用各自的事实、引用与题目分母，不相加为综合正确率。API失败或评分无效属于缺失，不计为答案零分。既有对照评分复用；单篇论文、单轮新回答不代表普遍性能或稳定性。</p>')
    html += ['<details><summary>四套流程共同集合与全部汇总</summary><pre>'+e(json.dumps({k:v for k,v in result.items() if k!='new_answer_runtime'},ensure_ascii=False,indent=2))+'</pre></details>',
        '<details><summary>本轮答题用量与耗时</summary><pre>'+e(json.dumps(result['new_answer_runtime'],ensure_ascii=False,indent=2))+'</pre></details>', '<h2>全部32题：每题优先展示两套主对照</h2>']
    for row in rows:
        html += ['<article><h2>'+e(row['task_id'])+' · '+e(row['question'])+'</h2>',
            '<details><summary>参考答案与评分要点</summary><pre>'+e(row['reference_answer'])+'</pre><pre>'+e(json.dumps(row['key_points'],ensure_ascii=False,indent=2))+'</pre></details><div class="answers">']
        for system in LABELS:
            cell=row['systems'][system]
            section='<section><h3>'+e(LABELS[system])+'</h3><pre>'+e(cell['candidate']['answer'])+'</pre>'
            for kind,item in cell['judges'].items():
                m=item['metrics']
                if m is None:section+='<p>'+e(kind)+'：无有效评分</p>';continue
                section+='<p>'+e(kind)+f"：要点{reporting.percent(m['point_mean'])}；事实{m['support_counts'].get('supported',0)}/{m['factual_claims']}；引用{m['supported_citations']}/{m['factual_citations']}；引用组{m['complete_groups']}/{m['factual_claims']}；边界{m['boundary']}/2。</p>"
                section+='<details><summary>'+e(kind)+'逐条评分与依据'+('、文字理由' if kind=='luna' else '')+'</summary><pre>'+e(json.dumps(item['review'],ensure_ascii=False,indent=2))+'</pre></details>'
            section+='<details><summary>实际引用原文及定位核验</summary><pre>'+e(json.dumps(cell['candidate']['citations'],ensure_ascii=False,indent=2))+'</pre></details></section>'
            html.append(section if system in {'pymupdf','mineru'} else '<details><summary>'+e(LABELS[system])+'归档对照</summary>'+section+'</details>')
        html.append('</div></article>')
    html.append('</main></html>')
    (OUTPUT/'comparison.html').write_text('\n'.join(html),encoding='utf-8',newline='\n')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['reuse','report','refresh'])
    args=parser.parse_args()
    reuse() if args.action=='reuse' else report(refresh=args.action=='refresh')
