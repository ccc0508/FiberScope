"""Source-calibrated paired review-only report; never alter drafts or Jev responses."""
import json,copy,difflib,re
from html import escape
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from report_answer_models_20261102 import final_review
from evaluate_fixed_review_20261105 import ROOT,RUN,BASE,IDS,verify
PUBLIC=ROOT/'data/literature/qa-evaluation/reports/fixed-review-20261105'
NOTES={
4:'两版均保留63/57和非通用限制；但都把稀疏端点进一步写成达到63必须超过12000及区间内确定，证据未给完整曲线。新版没有清除这一推断。',
15:'两版必答点齐全。新版删除了切断/碎解解释，但新增“图示误差范围内”，图1没有误差棒；旧版只说波动范围。不能把更短等同于全修复。',
24:'两版仍保留“未降低→不是纤维本身变强”及“长度不是驱动因素”。新版还将引用改成连续的2–9，与实际证据编号不符，如强度[6]实际是图1标题、氢键[8]实际是WRV段。',
25:'两版拒绝编造BET值正确。旧版不再确定写63，却仍称序列含混；新版继续把8000→63称作按顺序推断（实际40），并未删除无关指标。',
26:'两版保留没有逐次重复数字、未看图不报读数及测试标准；新版明显缩短。文中未说明图的误差棒定义与图本身有没有误差棒要区分。',
27:'两版保留抗张提高及没有耐破/撕裂数值，新版删除背景和重复内容，未发现必答信息误删。',
28:'两版仍把O2只在首段增加写入；新版又写先升后降再升，自相矛盾。旧版新增0转与16SR不一致的错误，新版去掉了这句。',
29:'旧版将CI-XI/CI-XA的0.919/0.925错配为氢键相关，并把T494带到零距；新版正确分开测试标准并去掉错配相关系数，必要拒答保留。',
31:'两版均完成复核并保留否定I→II前提，但都继续扩写无依据II型机制、峰位和测量推断。旧版把相对降幅与百分点比较而误称矛盾；新版仍称线性降幅。Jev两版均无有效评分，Codex补评。'
}
OV={}
def change(arm,n,key,value,reason,basis='actual attached evidence; full paper; fixed input'):
    OV.setdefault((arm,n),[]).append((key,value,reason,basis))
def partial(arm,n,c,reason):
    change(arm,n,'support_'+c,'partially_supported',reason)
    change(arm,n,'group_'+c,'partial',reason)
def full(arm,n,c,reason,group=True):
    change(arm,n,'support_'+c,'supported',reason)
    if group:change(arm,n,'group_'+c,'complete',reason)
def cite(arm,n,keys,reason):
    for key in keys:change(arm,n,key,'supported',reason)

for arm in ['old','new']:
    for c in ['C1','C2','C3']:partial(arm,24,c,'排除纤维长度作用、未降低推出没有增强、关系方向或主次均超出证据。')
    partial(arm,25,'C1','8000转按列表对应40，称顺序不明或63为合理推断不成立。')
    full(arm,29,'C3','条件性请求提供论文，没有断言任何新论文或模型存在。',False)
    change(arm,29,'basis_C3','CONTEXT','范围按实际输入判断。')
    cite(arm,27,['citation_C2_1','citation_C2_2'],'强度段和图3标题支持该文报告的三类力学指标。')
    change(arm,27,'group_C2','complete','三类力学指标及方法范围由合并引用支持，未臆造耐破/撕裂数值。')
partial('old',15,'C4','标题“而非切断为主”缺乏与切断贡献的独立比较；正文承认某机制未验证也未删除扩写。')
partial('old',15,'C5','零距未降低不能替代切断/分丝而非削弱碎解机制的证据，称并不矛盾仍为无根据补充。')
full('old',15,'C2','核对原图1：约2000→1650、硬木约900小幅波动、宏观指数上升可见，均明确估读。',False)
full('old',15,'C6','混杂条件、没有长度数值表、未报告该机理均与原文及图1一致。',False)
change('old',15,'group_C1','complete','正文和图1共同支持长度趋势与比较。')
cite('old',15,['citation_C1_2','citation_C2_1','citation_C3_1','citation_C4_2'],'图1支持趋势，正文[1]明确作者might较低压力解释；图像由Codex核验。')
cite('old',26,['citation_C1_5','citation_C1_6','citation_C1_7'],'表1/2支持其内容类别，形态段支持BET补充表范围，均对复合单元有实质贡献。')
change('old',26,'group_C1','complete','方法和所附表格/强度文字覆盖该单元，未声称已看图或没有误差棒。')
full('old',26,'C2','没有逐次数据、未查看像素和补充目录均属实；图注没有交代重复次数。',False)
change('old',26,'group_C2','complete','补充目录支持排除力学逐次表，其余为实际证据范围限制。')
cite('old',27,['citation_C1_7','citation_C1_8','citation_C2_4'],'图3标题和表1支持实验对象、处理水平和表格范围。')
partial('old',28,'C2','0转是处理量，16SR是初始打浆度，二者不同量并非不一致。')
partial('old',28,'C3','O2在12000→16000也上升，不能说仅首段增加。')
cite('old',29,['citation_C2_4','citation_C2_6','citation_C2_9'],'同篇引用支持文献身份、实验指标或结构分析范围；错配系数仍部分支持。')
# The current metric scores the supplied compound unit, not atomic sentence-reference pairs.
cite('old',24,['citation_C2_3'],'该段涉及宏观形态，[4]支持这部分；不支持后面因果外推。')
cite('new',24,['citation_C2_3','citation_C2_4','citation_C2_7','citation_C2_8','citation_C3_2'],
     '在现行整列表核查口径下，分别支持氢键、形态、WRV或柔顺性等部分事实；逐句错配另行在诊断中明确记录，不能据此称引用正确。')
change('new',24,'citation_C2_1','unsupported','[2]为打浆方法，本单元将它挂到形态变化结果，没有相应结果。')
cite('new',25,['citation_C1_5'],'表1支持8000转CI值；错误SR对应仍扣事实支持。')
full('new',26,'C2','8000=40、测试标准、图表类别和补充目录均有依据；表格不是力学结果表。')
cite('new',26,['citation_C2_6'],'表2内容是相对氢键含量，支持表格内容范围。')
full('new',26,'C3','未查看像素并拒绝给读数属实，未把正文未说明误差棒改成原图无误差棒。',False)
full('new',26,'C4','条件性请求其他资料不构成虚构事实。',False)
full('new',28,'C1','确实两次检索只获得同篇，未取得另一篇。',False)
full('new',28,'C6','请求PDF是条件性建议，没有断言其他数据已取得。',False)
partial('new',28,'C4','仅首段增加与先升后降再升相互矛盾，表2明确最后一段也增加。')
full('new',29,'C2','方法标准已区分，FTIR拟合不是预测验证，结构相关不等于因果且无错配数值。')
cite('new',29,['citation_C2_3'],'[7]属于同篇图1/机械性质段，对文献身份和实验内容有贡献。')

def supplement(arm,n,saved):
    assert n==31 or (arm=='new' and n==15)
    decisions={};reasons={};claims={c['id']:c for c in saved['state']['candidate']['claims']}
    for key,t in saved['targets'].items():
        k=t['kind'];cid=t.get('claim_id')
        if k=='point':v='complete'
        elif k=='boundary':v='partial' if n==31 else 'appropriate'
        elif k=='reference':v='sound'
        elif k=='claim_type':v='scope' if (n==31 and cid=='C9') or (n==15 and cid=='C5') else 'fact'
        elif k=='support':
            if n==31:v='supported' if cid=='C1' else 'unsupported' if cid=='C2' or (cid=='C7' and arm=='new') else 'partially_supported'
            else:v='partially_supported' if cid in {'C2','C6'} else 'supported'
        elif k=='basis':v='CONTEXT' if n==15 and cid=='C5' else 'E12' if n==15 else 'E24' if cid=='C1' else 'NONE'
        elif k=='group':
            if not claims[cid]['citation_refs']:v='missing'
            elif n==31:v='complete' if cid=='C1' else 'partial'
            else:v='partial' if cid in {'C2','C6'} else 'complete'
        elif k=='citation':v='supported'
        else:raise ValueError(k)
        decisions[key]=v
        reasons[key]=NOTES[n]+(' 新版C2虚构误差范围；C6两个不同SR序列不证明不宜按SR对齐，保留部分支持。' if n==15 else ' C1有据；C2的II峰位无来源；C3/C5/C6/C8混合正确原文与无依据机制；C4混淆相对降幅/线性降幅；C7仍有II科学断言。引用按复合单元部分贡献计，不能等于整句充分支持。')
    return decisions,reasons

def arm_rows(arm):
    output=ROOT/('.rag-data/evaluations/fixed-review-'+arm+'-grading-20261105')
    _,jobs,study,reviews,records,_,_=s.audit(output/'import',output/'judges')
    entries={e['task_id']:e for e in study['jobs']};assert set(entries)==set(IDS)
    rows=[];items=[]
    for job in jobs:
        tid=job['task_id']
        if job['system']!='rag' or tid not in entries:continue
        n=int(tid[-3:]);e=entries[tid];raw=reviews.get(('jev','rag',tid))
        saved=j.read_json(output/'judges/inputs'/(e['name']+'.json'))
        h=j.digest(RUN/arm/(tid+'.json'))
        item=dict(task_id=tid,result_sha256=h,grader_input_sha256=e['input_sha256'],raw_review_sha256=j.sha(raw) if raw else None,
                  summary=NOTES[n],evidence_checked=['full paper','actual attached text','verified Figure1','fixed tool trace'],changes=[])
        if raw:
            for key,to,reason,basis in OV.get((arm,n),[]):
                old=raw['decisions'][key]
                if old!=to:item['changes'].append(dict(decision_key=key,**{'from':old},to=to,reason=reason,basis=basis))
        else:item['supplemental_decisions'],item['supplemental_reasons']=supplement(arm,n,saved)
        final=final_review(dict(result_sha256=h,grader_input_sha256=e['input_sha256'],raw_review=raw,saved=saved),item)
        historical=j.read_json(BASE/(tid+'.json'))
        rows.append(dict(task_id=tid,arm=arm,fixed_draft=historical['draft'],historical_result_sha256=j.digest(BASE/(tid+'.json')),
            fixed_input_sha256=j.digest(RUN/(tid+'-input.json')),question=job['reference_case']['question'],reference=job['reference_case'],candidate=job['candidate'],raw_jev_review=raw,
            final_codex_review=final,adjudication=item,metrics=s.metrics(final,job['reference_case'],job['task']['capabilities'])))
        items.append(item)
    j.write(output/'codex-adjudication.json',dict(reviewer='Codex',policy_sha256=g.POLICY_SHA,items=items))
    return rows,s.accounting(records['jev'],'jev')

def main():
    verify();rows={};account={}
    for arm in ['old','new']:rows[arm],account[arm]=arm_rows(arm)
    stats={arm:s.summarize([r['metrics'] for r in rs]) for arm,rs in rows.items()}
    runtime={}
    for arm in rows:
        results=[j.read_json(RUN/arm/(tid+'.json')) for tid in IDS]
        runtime[arm]=dict(review_calls=len(results),completed=sum(x['review_status']=='completed' for x in results),
            seconds=sum(x['review_call']['elapsed_ms'] for x in results)/1000,
            mean_answer_chars=sum(len(x['answer']) for x in results)/len(results),
            known_tokens=sum((x['review_call'].get('usage') or {}).get('total_tokens',0) for x in results),
            unknown_usage_calls=sum(not x['review_call'].get('usage') for x in results),
            usage=[x['review_call']['usage'] for x in results])
    summary=dict(design='9 paired frozen drafts, review-only, no retrieval or initial answer calls',policy_sha256=g.POLICY_SHA,
        model='deepseek-flash',thinking=False,selected=IDS,stats=stats,runtime=runtime,judge_accounting=account,
        review_instructions={arm:j.read_json(RUN/arm/(IDS[0]+'.json'))['review_call']['input_messages'][-1]['content'] for arm in ['old','new']},
        caveats=['One sample per arm; not a stability estimate.','Historical drafts were generated in thinking mode; both current review arms disable thinking.','Original system prompt, question, draft and delivered evidence are identical; only final user review instruction differs.','The newly changed initial-answer prompt is NOT tested here.','Historical acquisition model_calls are preserved solely for evidence provenance; costs count only review_call.','Compound Markdown units can mask sentence-level citation mismatches.','Controls were historically fully correct final answers; their pre-review drafts need not be error-free.'])
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>固定初稿复核对照</title><style>body{max-width:1200px;margin:auto;padding:24px;background:#f5f7fa;color:#173047;font:16px/1.7 system-ui}article{background:white;padding:20px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:10px;text-align:left}summary{cursor:pointer}</style><h1>固定初稿、固定证据：旧／新复核指令对照</h1><p>9题×2，DeepSeek Flash非推理模式，8192输出预算，双方逐题相同超时。没有重新检索或生成初稿；只替换最后复核指令。首次结果全部保留。Jev后由Codex按原文校准。</p><p>结论：精简部分有效，但第24题出现引用错配，第25题仍错配SR，第31题仍用“可能”保留无依据机制。未发现必答要点误删；不等于所有正确细节都无损。</p><table><tr><th>指标</th><th>旧复核</th><th>新复核</th></tr>']
    def values(x):return [x['point_macro_average'],x['support_counts'].get('supported',0)/sum(x['support_counts'].values()),x['citation_precision']['value'],x['citation_coverage']['value']]
    for name,a,b in zip(['必答要点','事实充分支持','单条引用有效','引用组完整覆盖'],values(stats['old']),values(stats['new'])):html.append(f'<tr><td>{name}</td><td>{a:.2%}</td><td>{b:.2%}</td></tr>')
    html.append('</table><details><summary>完整统计、资源与限制</summary><pre>'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>')
    maps={arm:{r['task_id']:r for r in rs} for arm,rs in rows.items()}
    for tid in IDS:
        original=j.read_json(BASE/(tid+'.json'))['draft'];a=maps['old'][tid];b=maps['new'][tid]
        html.append('<article><h2>'+escape(tid+' '+a['question'])+'</h2><p>'+escape(NOTES[int(tid[-3:])])+'</p>')
        for label,value in [('固定初稿',original),('旧复核',a['candidate']['answer']),('新复核',b['candidate']['answer'])]:html.append('<details open><summary>'+label+'</summary><pre>'+escape(value)+'</pre></details>')
        for arm,r in [('old',a),('new',b)]:
            diff='\n'.join(difflib.unified_diff(original.splitlines(),r['candidate']['answer'].splitlines(),fromfile='fixed draft',tofile=arm+' review',lineterm=''))
            html.append('<details><summary>'+arm+' 初稿变化与全部评分依据</summary><pre>'+escape(diff)+'\n'+escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>')
        html.append('</article>')
    rendered=re.sub(r'(?m)^ +$',lambda m:'&#32;'*len(m.group()),''.join(html)+'</html>')
    files={'comparison.html':rendered,'comparison.json':j.encode(summary),
           'answers-reviews.jsonl':''.join(j.encode(r)+'\n' for arm in ['old','new'] for r in rows[arm])}
    from dotenv import dotenv_values
    for p in (ROOT/'backend').glob('.env.*'):
        for k,v in dotenv_values(p).items():
            if v and len(v)>12 and k.upper().endswith(('API_KEY','TOKEN','PASSWORD')):assert all(v not in text for text in files.values())
    PUBLIC.mkdir(parents=True,exist_ok=True)
    for name,text in files.items():(PUBLIC/name).write_text(text,encoding='utf-8')
    print(j.encode(dict(stats=stats,runtime={a:{k:v for k,v in r.items() if k!='usage'} for a,r in runtime.items()},judge_accounting=account)))

if __name__=='__main__':main()
