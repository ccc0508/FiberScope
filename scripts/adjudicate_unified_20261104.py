"""Record Codex's explicit source-reviewed decisions. No model calls or inferred score optimization."""
from pathlib import Path
import judge_qa_eval as j
import qa_system_judge as g
from report_unified_20261104 import load,OUTPUT,RUN

NOTES={
1:'原料两类、商业漂白及kraft工艺均与E01和实际[1]一致。',
2:'浆浓10%、间隙0.2mm、作用力3.33/1.77 N/mm逐项对应E01。',
3:'两类各五个相同转数水平，与E02一致。',
4:'63/57 °SR及本文条件范围正确；未明确两类浆作用力不同，P3保留半分；“需要提高转数”比离散数据能确认的范围更强，C3保留部分支持。',
5:'MORFI LB及三个指标与E04一致。',
6:'E05及实际[1]公式、[2]质量定义共同支持质量差和绝干质量分母；公式对C5有实质贡献。',
7:'强度法、面积法、公式及变量定义正确，过拟合保留可能性；审校记录不完整不等于答案错误。',
8:'Table1两类浆0/16000转四组值全部准确。',
9:'47.16→42.35，4.81个百分点、10.20%准确；新增[5]明确CI-XA面积百分比，支持C2的测量口径限定。',
10:'逐行核对Table1：(200)软木4.5→4.7、硬木4.5→4.7，硬木末段4.8→4.7也正确。',
11:'CI-XA的数值回升同样构成有效反例，不限参考答案列举的CI-XI例子；总体下降与非单调区分正确。',
12:'CI-XI更高、0.919/0.925及p<0.05正确，过拟合解释保留可能。',
13:'阶段解释保留可能性；实际[4]完整Table1直接证明先降再升再降，不是无关引用。',
14:'前两项要点完整；C4把原文among molecular chains改成分子链断裂，结构层级扩大。C5[4]确实贡献较低CI这一事实。',
15:'Jev无有效记录，依据E01/E12与实际Figure1补评。图像显示约2000→1600μm及硬木约900μm；可能原因与3.33/1.77 N/mm同时给出。',
16:'提高纸页强度不等于提高单纤维强度，零距表征及未降低结论明确，来源E14/E04齐全。',
17:'针叶木增幅更明显及长度解释与E14一致。',
18:'P3仍未表达相对比例不等于绝对数量，保留0分及边界1；但C6所述四分峰、百分比和r²有实际Figure7/Table2支持，不能把漏答P3再当C6事实错误。',
19:'方法分配区间和结果峰位均为原文报告；3227与区间端点不完全重合属于论文表述本身，不按新造数字扣分。',
20:'稳定能量/距离与变化含量已区分。正文与表2支持软木/硬木分别16.54%/5.91%总降幅，满足可选P4两类各一例。',
21:'33.06→29.28，下降3.78个百分点、相对11.43%准确。',
22:'材料/16000转与Table1(a)、Table2(a)正确对齐，69.82/34.20/23.56/34.92均准确，限定相对面积分数。',
23:'摘要0.888与正文0.912均明确定位并指出不一致；审校格式失败未破坏原本正确的回答。',
24:'机制及抗张/零距要点正确，按既有要点规则P3保留满分（明确没有定量排序），额外“联系最直接”在事实及引用组另扣。图1确实上升，回答明确按图描述。C7相对量和收窄因果有正文及摘要共同支持。',
25:'未编造BET具体值，准确指向外部TableS1；可选的导入建议未写，保持可选要点0，不影响必答平均。',
26:'Jev无有效记录，方法E04、实际图3及全文未给逐次数据；图中仅汇总点和误差棒。保留无法恢复原始重复值的边界，未给可选索取建议。',
27:'Jev无有效记录。E14及图3支持干纸抗张趋势；方法和图示没有耐破/撕裂数据，明确拒绝编造其精确值。',
28:'两句均是所给证据/能力范围陈述；没有声称比较了第二篇，引用对及组不纳入事实分母。可选导入建议未写。',
29:'不挪用拟合r²为验证指标，正确限定缺少预测模型；可选P2未明确展开Pearson区别，保留半分。',
30:'纠正湿纸幅前提，长度解释、可能压力原因和3.33/1.77条件均有据。',
31:'晶型前提已纠正，相对量限定改善；但C7仍把活动性解释扩成柔顺性、可及性、WRV三个直接结果，Jev满支持不合理，应保留部分支持及部分引用组。',
32:'未报告摘要0.888冲突，P2半分、边界1保留；C4实际[2]贡献相关分析，[4]贡献趋势推测，联合支持相关不等于换算。缺少测量边界仍是改进项，不能冒充已补齐。'
}
# Each override follows inspection of actual attached evidence; never change point weights.
OVERRIDES={
6:[('citation_C5_1','supported','公式直接给出质量差除绝干质量，和[2]定义共同解释C5。','actual [1] WRV equation; E05')],
9:[('citation_C2_2','supported','[5]明确CI-XA是晶峰面积占总衍射面积百分比，支持相对指数限定。','actual [5] XRD methods; E07')],
13:[('citation_C1_2','supported','[4]含完整Table1，两类CI均在4000→8000回升，直接支持波动描述。','actual [4] Table1; E08/E09')],
14:[('support_C4','partially_supported','原文是分子链之间的cleavage；回答变成分子链断裂，扩大到链本体层级。','actual [1] full sentence: cleavage among cellulose molecular chains'),
    ('group_C4','partial','引文支持氢键变化及细纤维化，但不支持主张的分子链本体断裂。','actual [1] section3.3'),
    ('citation_C5_2','supported','[4]给出CI降低事实，是C5较低结晶指数部分的实质依据。','actual [4] CI reduction; E26')],
18:[('support_C6','supported','Figure7呈现四分峰；Table2各行约100%、r²约0.999。图文支持该句。','actual [3] Figure7/Table2; E16/E18/E19'),
    ('group_C6','complete','同一[3]实际挂载Figure7和Table2，足以共同支持C6。','actual [3] verified image assets')],
20:[('point_P4','complete','已给软木16.54%、硬木5.91%的准确含量变化例子，符合可选项；不强制端点数值。','E27; actual [1] section3.3')],
24:[('citation_C7_2','supported','摘要明确可及性、润胀、细纤维化与超分子结构相关，支持C7相关性质的表述。','actual [4] abstract'),
    ('group_C7','complete','[3]方法/表格/讨论与[4]摘要联合覆盖相对量、降幅及相关性质边界。','actual [3]/[4]'),
    ('citation_C9_2','supported','[2]介绍明确打浆改善润胀、柔顺性和结合能力，有关系依据贡献；不因此认可最直接排名。','actual [2] introduction')],
31:[('support_C7','partially_supported','原文直接结果是柔顺性，活动性、可及性、WRV出现在解释部分；回答重排成三个结果。','actual [4] Both the fewer ... will further improve the flexibility ... due to ...'),
    ('group_C7','partial','[4]有关系依据，但不完整支持被扩大后的结果对象。','actual [4] full causal sentence')],
32:[('citation_C4_1','supported','[2]直接提供相关分析证据，对相关不能直接换算的判断有实质贡献。','actual [2] section3.4; E21'),
    ('group_C4','complete','[2]相关分析与[4]仅作趋势推测联合支持有界解释；全文也未给定量换算模型。','actual [2]/[4]; E21/E22')]
}


def main():
    jobs,entries,reviews,_,_,_=load();items=[]
    for tid,job in sorted(jobs.items()):
        n=int(tid[-3:]);raw=reviews.get(('jev','rag',tid));entry=entries[tid]
        saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        evidence=sorted({eid for p in job['reference_case']['key_points'] for eid in p['evidence_ids']})
        item=dict(task_id=tid,result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=entry['input_sha256'],
            raw_review_sha256=j.sha(raw) if raw else None,summary=NOTES[n],evidence_checked=evidence+['actual_attached_citations_and_scope'],changes=[])
        if raw:
            for key,to,reason,basis in OVERRIDES.get(n,[]):
                old=raw['decisions'][key]
                if old!=to:item['changes'].append(dict(decision_key=key,**{'from':old},to=to,reason=reason,basis=basis))
        else:
            assert n in {15,26,27}
            d={};reasons={}
            basis={15:{'C1':'E12','C2':'NONE','C3':'E12','C4':'E01'},26:{'C1':'E04','C2':'NONE','C3':'CONTEXT'},27:{'C1':'E14','C2':'E14','C3':'NONE','C4':'E04','C5':'CONTEXT'}}[n]
            scopes={15:set(),26:{'C3'},27:{'C5'}}[n]
            for key,t in saved['targets'].items():
                kind=t['kind'];cid=t.get('claim_id');scope=cid in scopes
                if kind=='point':value='missing' if n==26 and t['point_id']=='P3' else 'complete'
                elif kind=='boundary':value='appropriate'
                elif kind=='reference':value='sound'
                elif kind=='claim_type':value='scope' if scope else 'fact'
                elif kind=='support':value='supported'
                elif kind=='basis':value=basis[cid]
                elif kind=='group':value='missing' if scope else 'complete'
                elif kind=='citation':value='unsupported' if scope else 'supported'
                else:raise ValueError(kind)
                d[key]=value;reasons[key]=NOTES[n]
            item['supplemental_decisions']=d;item['supplemental_reasons']=reasons
        items.append(item)
    j.write(OUTPUT/'codex-adjudication.json',dict(reviewer='Codex',policy_sha256=g.POLICY_SHA,
        final_evidence_unit='actual_attached_text_and_verified_images',items=items))
    print(j.encode(dict(reviewed=32,supplemented=[15,26,27],changed=sum(bool(i['changes']) for i in items))))


if __name__=='__main__':main()
