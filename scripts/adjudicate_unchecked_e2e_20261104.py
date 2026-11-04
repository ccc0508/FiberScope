"""Explicit Codex source decisions for this run; no calls or answer modifications."""
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from grade_unchecked_e2e_20261104 import RUN,OUTPUT
NOTES={
1:'原料、商业漂白及kraft工艺与E01及实际[1]一致。',
2:'浆浓10%、间隙0.2mm及两类作用力均与方法E01一致。',
3:'两类浆五个转数水平正确，E02及实际[1]支持。',
4:'63/57数值正确且限定本研究针叶木，不照搬到阔叶木；仍未说明作用力不同，P3半分。另行实验确认是合理边界，不是未经证据的确定转数建议。',
5:'MORFI LB和三个形态指标与E04一致。',
6:'WRV公式、质量定义及0.5g/ISO23714均正确，实际公式和方法分别支持。',
7:'峰强度法、峰面积法、峰位范围、预处理及可能过拟合均有依据。',
8:'两类浆0/16000转四组CI-XI/CI-XA值逐项对应Table1。',
9:'47.16与42.35、4.81个百分点和10.20%正确，并保留相对指数测量边界。',
10:'(200)尺寸全序列正确，阔叶木末段4.8降至4.7未被遗漏；总体上升不是单调上升。',
11:'给出两类浆8000对4000转回升的数值反例，区分端点下降与非单调。',
12:'两指数范围和0.919/0.925相关系数正确，过拟合仍表述为可能。',
13:'三阶段解释保留可能/可解释措辞，符合E11。',
14:'WRV—横向柔顺—结合链条正确；新增游离OH解释已限定软木及相对含量。因果句只把柔顺性列为直接结果，无旧的主链断裂扩写。',
15:'明确针叶木显著、阔叶木不显著，保留作者推测，并给3.33/1.77作用力作为条件差异；整体已经表达该比较非纯浆种效应，不要求逐字复述参考答案。',
16:'明确纸页强度提高主要来自结合，同时用零距表征单纤维并仅称未降低；已经区分两层强度，未作同步提高推断。',
17:'软木湿纸幅增幅更显著及长度解释与E14一致。',
18:'相对峰面积而非绝对浓度已表达测量边界；不能因没有逐字写绝对数量再扣半分。实际[3]含面积比例和Table2支持。',
19:'正文3227/3346/3452和归属区间准确；实际[1]挂载图6，图上软木3226/硬木3228及另两峰明确可见，不应当成无依据或无效引用。',
20:'能量距离与比例变化区分正确。各表值与总变化百分比准确；实际[1]也含硬木总下降5.91%、O3增长8.8%段落，有实质引用贡献。',
21:'33.06→29.28、3.78个百分点、11.43%准确。',
22:'材料/转数/两表四个值对齐正确，FTIR相对面积边界明确。',
23:'正文0.912与摘要0.888冲突明确。C3比较两处数值，[1]提供正文这一侧，属于有效联合引用。',
24:'机制链、抗张与零距区分正确；柔顺性是直接结果，其他为相关因素；明确无法比较贡献排名。未沿用旧的最直接排名与三结果因果扩张。',
25:'准确指出外部TableS1缺失，不编造BET值；可选索取建议未写不影响必答分。',
26:'Jev无有效评分，依据图3及方法补评。正确拒绝逐次原始值，但C5把软木8000转红点读成80；图3a原图约66–67，80接近16000转。该句部分事实与引用组不充分；初答已有此错误，审校未修。',
27:'Jev无有效评分。抗张趋势及解释与图3/E14一致；方法未列耐破撕裂，C5明确限于提供摘录，不编造数值。',
28:'明确无第二篇，不冒充跨文献比较。额外Li2020结论受实际[3]支持；[6]的CI波动/微晶尺寸也贡献C4部分事实，不是全无关系引用。',
29:'正确区分FTIR拟合与预测验证；未提Pearson的可选项半分保留。C4限定本文证据，是对提供材料范围的总结，不要求将文库外全文当作引用支持。',
30:'软木湿纸幅增幅更明显及较低作用力可能解释均有依据，未接受题目错误前提。',
31:'晶型前提纠正正确，但C6仍把among molecular chains扩大成分子链断裂，给部分支持与部分引用组。C4的[3]表1确实贡献先降再升再降趋势；C7仅将柔顺性作直接结果，未扩大结果对象。',
32:'0.919/0.925对象纠正、0.912/0.888冲突及不能直接换算均完整。实际[6]明确FTIR面积比例，[4]仅支持趋势推测，联合支持C5测量边界。'
}
OVERRIDES={
4:[('group_C4','complete','限定本研究条件并要求另行确认，未声称通用换算或需要增加特定转数。','E01/E03; actual [1]')],
15:[('point_P3','complete','全文同时给出不同作用力并将其作为差别的可能原因，已经表达条件混杂。','E01/E12; C4/C5'),('boundary','appropriate','已保留可能性和不同作用力条件，不要求参考答案逐字出现。','E01/E12')],
16:[('point_P3','complete','纸页提高与单纤维未降低明确并列，已区分两个层面。','E14; C1/C3/C4/C5'),('boundary','appropriate','没有把未降低偷换成必然提高。','E14')],
18:[('point_P3','complete','明确面积占比而非绝对浓度，已表达相对测量不等于绝对量。','E16; C5'),('boundary','appropriate','必要测量限制已写在最终答案。','C5'),('group_C5','complete','实际[3]含按峰面积比例计算及Table2相对含量。','actual [3]; E16')],
19:[('support_C1','supported','正文与图6分别支持约3227和两类3226/3228，不能把原文区间与峰位边缘差别当回答编造。','E17; Figure6'),('group_C1','complete','[2]正文与[1]实际原图共同覆盖。','actual [1]/[2]'),*[(f'citation_C{i}_1','supported','实际[1]挂载的Figure6明确标注该峰位，有实质支持。','Figure6 original image') for i in (1,2,3)]],
20:[('citation_C5_1','supported','实际[1]文本提供硬木下降5.91%及O3增长8.8%，支持该句部分数值。','actual [1] section3.3')],
23:[('citation_C3_1','supported','比较冲突时正文0.912是另一侧必要数据，[1]有实质贡献。','actual [1] section3.4')],
28:[('citation_C4_2','supported','实际[6]给CI非单调变化及微晶尺寸解释，对该复合句部分内容有贡献。','actual [6] section3.2')],
29:[('kind_C4','scope','明确限定本文证据，陈述所提供材料未涉及模型验证，属于材料范围说明。','candidate.available_context')],
31:[('support_C6','partially_supported','数值和相对量正确，但among chains不等于主链断裂，结构层级扩大。','E27; actual [4] The decrease might be due to cleavage among cellulose molecular chains'),('group_C6','partial','[4]不能完整支持分子链断裂这一改写。','actual [4] full sentence'),('citation_C4_2','supported','Table1直接证明CI先降再升再降，支持句中趋势。','actual [3] Table1')],
32:[('support_C5','supported','面积比例与绝对数量区分及相关非换算是有界推断。','E16/E22'),('group_C5','complete','[6]定义相对峰面积，[4]仅允许趋势推测，共同支持限制。','actual [6]/[4]')]
}

def main():
    _,jobs,study,reviews,_,_,_=s.audit(OUTPUT/'import',OUTPUT/'judges');entries={e['task_id']:e for e in study['jobs']};items=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];n=int(tid[-3:]);raw=reviews.get(('jev','rag',tid));entry=entries[tid]
        saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        item=dict(task_id=tid,result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=entry['input_sha256'],
            raw_review_sha256=j.sha(raw) if raw else None,summary=NOTES[n],
            evidence_checked=sorted({e for p in job['reference_case']['key_points'] for e in p['evidence_ids']})+['actual_attached_text_and_images'],changes=[])
        if raw:
            for key,to,reason,basis in OVERRIDES.get(n,[]):
                old=raw['decisions'][key]
                if old!=to:item['changes'].append(dict(decision_key=key,**{'from':old},to=to,reason=reason,basis=basis))
        else:
            assert n in {26,27}
            d={};reasons={};scopes={26:{'C1'},27:{'C5'}}[n]
            basis={26:{'C1':'CONTEXT','C2':'E08','C3':'E04','C4':'NONE','C5':'NONE'},27:{'C1':'E14','C2':'E14','C3':'NONE','C4':'E04','C5':'CONTEXT'}}[n]
            for key,t in saved['targets'].items():
                kind=t['kind'];cid=t.get('claim_id');scope=cid in scopes;bad=n==26 and cid=='C5'
                if kind=='point':value='missing' if n==26 and t['point_id']=='P3' else 'complete'
                elif kind=='boundary':value='appropriate'
                elif kind=='reference':value='sound'
                elif kind=='claim_type':value='scope' if scope else 'fact'
                elif kind=='support':value='partially_supported' if bad else 'supported'
                elif kind=='basis':value=basis[cid]
                elif kind=='group':value='missing' if scope else 'partial' if bad else 'complete'
                elif kind=='citation':value='unsupported' if scope else 'supported'
                else:raise ValueError(kind)
                d[key]=value;reasons[key]=NOTES[n]
            item.update(supplemental_decisions=d,supplemental_reasons=reasons)
        items.append(item)
    j.write(OUTPUT/'codex-adjudication.json',dict(reviewer='Codex',policy_sha256=g.POLICY_SHA,
        final_evidence_unit='actual_attached_text_and_verified_images',items=items))
    print(j.encode(dict(reviewed=32,changed=sum(bool(i['changes']) for i in items),supplemented=[26,27])))
if __name__=='__main__':main()
