"""Offline role/context A/B audit; original Jev labels only, no new grading."""
from collections import Counter
import json
from pathlib import Path

import judge_qa_eval as judge
import report_section_context_20261031 as legacy
import report_answer_guidance_20261031 as shared
from report_mineru_rag_20261029 import override
from section_context_20261031 import save
from validate_qa_eval import require

TAG='role-context-20261031'
ARMS=('control','guidance')
LABELS={'control':'原小节补全（107块）','guidance':'内容分类与受限补全（113块）'}
LIMITATIONS=[
    '两版各新答32题，沿用原Jev五项评分和最多3次首个有效规则；缺失不记零，不合成加权总分。',
    '保留同一原始前8主命中的全部来源跨度，新版将跨类别的原块拆为子块，所以实际证据块编号和数量可变化。原文不删减，分数沿用原主命中。',
    '本轮检验分类后的组块与补全，不重新做向量化或查询。尚未建立113块向量索引，不能据此推断重新检索后的排名或端到端质量。',
    '分类是规则推断，包含已识别、不确定和混合状态；测试样例通过不等于不同真实论文分类准确率。未给出分类正确概率。',
    '不确定、参考文献、作者机构等内容只保留主命中；摘要只关联同一摘要；正文邻块回退要求明确的句子连续迹象。没有调用额外分类模型。',
    '单篇论文已见开发题的一轮结果，生成与裁判波动未分离，不证明稳定提升、统计显著性或新论文泛化。',
    '回答Token包含推理Token；缓存、网络和并发影响代价。答题实际费用未知；Jev API报告费用不是已核验账单。',
    '网站默认配置未改变，旧解析、旧组块、旧答案与旧评分均保留。']


def collect(root,out):
    root,out=Path(root),Path(out)
    legacy.collect(root,out)
    p=judge.read_json(out/'analysis-input.json');c=judge.read_json(out/'experiment.json')
    p['version']='role-aware-fixed-primary-spans-v1'
    p['controls']={**{k:v for k,v in p['controls'].items() if k!='same_107_block_index'},
        'same_original_primary_spans':True,'same_vector_index_claimed':False,'old_chunks':c['old_chunks'],'new_chunks':c['new_chunks'],
        'primary_projections':c['primary_projections'],'generation_input_policy':c['policy']}
    p['limitations']=LIMITATIONS
    p['provenance'].update(role_structure_sha256=c['role_structure_sha256'],engine_sha256=c['engine_sha256'],context_sha256=c['context_sha256'])
    save(out/'analysis-input.json',p)
    return dict(records=len(p['records']),provider_calls=0)


def analyze(p):
    require(p['controls']['same_original_primary_spans'] and not p['controls']['same_vector_index_claimed'],'Incorrect primary-span comparison')
    records,tids,_=shared.checked_records(p)
    require(len(tids)==32,'All 32 tasks including missing grades must remain visible')
    require(p['controls']['generation_settings']['control']==p['controls']['generation_settings']['guidance'],'Generation parameters differ')
    common,excluded=shared.select_common(records,tids);comparison=shared.paired(records,common);comparison['exclusions']=excluded
    diagnostics={}
    for a in ARMS:
        values=p['traces'][a].values();modes=Counter(d['mode'] for v in values for d in v['context']['decisions'])
        diagnostics[a]=dict(total_context_chars=sum(v['context']['context_chars'] for v in p['traces'][a].values()),
            decision_modes=dict(modes),budget_limited_questions=[t for t,v in p['traces'][a].items() if v['context']['budget_limited']])
    return dict(version=p['version'],question_count=32,comparison=comparison,context_diagnostics=diagnostics,
        risks=shared.risk_summary(records,common),output_diagnostics=shared.output_diagnostics(records,tids),
        runtimes=p['runtimes'],runtime_by_arm=shared.runtime_by_arm(p),accounting=p['accounting'],controls=p['controls'],
        traces=p['traces'],provenance=p['provenance'],analyst_notes=p['analyst_notes'],limitations=LIMITATIONS,
        missing_not_zero=True,no_weighted_total_score=True,reporter_model_calls=0)


def render(path,result,payload):
    with override(legacy,LABELS=LABELS):legacy.render(path,result,payload)
    text=path.read_text('utf-8')
    intro='2026-10-31。同一107块索引、相同前8主命中、相同8000/24000字符上限；两版各重新回答32题，仅改变上下文补全方式。没有重新检索，未开启重排或新回答指引。'
    require(text.count(intro)==1,'Unexpected shared report template')
    text=text.replace(intro,'2026-10-31。原107块小节补全与分类后113块受限补全各新答32题；保留同一原始前8主命中的全部原文跨度。没有建立新向量索引，没有重新检索、重排或更改回答指引。')
    text=text.replace('MinerU：同页邻块与小节补全对照','MinerU内容分类、组块与受限补全对照').replace('MinerU上下文补全对照','MinerU内容分类对照')
    path.write_text(text,encoding='utf-8',newline='\n')


def publish(root,out):
    root,out=Path(root),Path(out);dest=root/'data/literature/qa-evaluation/reports'/TAG;doc=root/'docs/QA_ROLE_CONTEXT_REPORT_20261031.md'
    require(not dest.exists() and not doc.exists(),'Never overwrite a published study')
    p=judge.read_json(out/'analysis-input.json');r=analyze(p);dest.mkdir(parents=True)
    save(dest/'comparison.json',r);render(dest/'comparison.html',r,p)
    records,tids,standards=shared.checked_records(p)
    (dest/'questions-answers-reviews.jsonl').write_text(''.join(json.dumps(dict(task_id=t,reference_case=standards[t],
        records=[records[(a,t)] for a in ARMS]),ensure_ascii=False)+'\n' for t in tids),encoding='utf-8',newline='\n')
    with override(legacy,LABELS=LABELS):rows=legacy.score_rows(r)
    lines=['# MinerU内容分类、组块与受限补全对照','','2026-10-31。原小节补全对比内容分类后的受限补全；原8个主命中的原文跨度全部保留。','',
        *sum(([s,''] for s in r['analyst_notes']),[]),'| '+' | '.join(shared.HEADERS)+' |','| '+' | '.join(['---']+['---:']*7)+' |',
        *['| '+' | '.join(map(str,row))+' |' for row in rows],'',f"共同有效{r['comparison']['tasks']}题；排除："+json.dumps(r['comparison']['exclusions'],ensure_ascii=False),'',
        '必答要点提高：'+str(r['comparison']['point_wins'])+'；下降：'+str(r['comparison']['point_losses']),'',*LIMITATIONS,'',
        '[32题新回答、引用、原文与Jev原判](../data/literature/qa-evaluation/reports/'+TAG+'/comparison.html)。','',
        '[分类与组块检查](../data/literature/parsing-comparisons/content-roles-v1-20261031/comparison.html)。']
    doc.write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    save(dest/'publication.json',dict(files={v.name:judge.digest(v) for v in dest.iterdir() if v.is_file()},document_sha256=judge.digest(doc),
        analysis_input_sha256=judge.digest(out/'analysis-input.json'),reporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    return dict(common_tasks=r['comparison']['tasks'],deltas=r['comparison']['deltas'],provider_calls=0)
