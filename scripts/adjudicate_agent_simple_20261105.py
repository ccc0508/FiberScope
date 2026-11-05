"""Explicit source-based calibration; never changes answers or raw Jev records."""
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from grade_agent_simple_20261105 import RUN,OUTPUT

NOTES={
1:'必答原料、漂白及kraft正确。新增方法参数与E01一致；开头原料/刊物说明和末尾比较限制未就近标注引用。kraft的译名及方法未给额外工艺信息不应导致已有[2]失效。',
2:'Jev三次未形成有效评分，补评：10%、0.2 mm、3.33/1.77及1.9倍推算正确；共同方法引文明确统领连续列表。未把打浆度差异当作已证效率排名。',
3:'五个水平和两种浆正确，补充材料目录确实列S1–S3各五档；当前解析文字重复转数序列，答案已解释该解析歧义。方法[1]支持所述条件及未提供重复次数的局部范围说明。',
4:'63/57及作用力混杂条件齐全。额外段落将阔叶木四项列表称为对应五档；对图文初始值矛盾的推测不能替代勘误；由非线性直接推出不能内插也过强。明确标为工程建议的另行标定不当作论文实测结论扣分。',
5:'仪器和三指标正确。额外称不能确定two parameters所指，忽略紧邻前句的macro-fibrillation index和fiber length，属于过度保守解释。未查看像素属实，不能因正文/图注存在而将这一范围声明评为无依据。',
6:'WRV公式和m1/m2正确。宣称所列遗漏参数均由标准规定而未查标准，保留部分支持；数学解读未附引文。实际[4]支持WRV—横向柔顺—结合解释，但[3]只是图题，不能独立证明上升趋势。',
7:'CI-XI公式、CI-XA面积、Pearson VII、九点平滑及方法差异均有原文依据；没有将可能过拟合说成定论。',
8:'四组CI端点及所有新增差值/相对变化均核算正确；[1]含表1及三阶段机制，[2]含过拟合解释，可共同支持该段。没有把描述性高低改成因果。',
9:'47.16→42.35、4.81个百分点与10.2%正确。计算引用明确标为派生计算且操作数与表1相符，应认可算术支持；[6]本身仅提供总降幅等，不能单独支持三阶段解释。',
10:'(200)完整序列及末段回落已给出；没有下降在同段被明确限定为总体/端点，不能忽略后句的回落说明。原图确认尺寸列和计算0.2 nm/4.4%。末段异常文本解释的引用只有方法[2]，不能完整覆盖该诊断。',
11:'必答非单调及数值反例完整。已核对Figure4确有误差棒；计算引用支持6.26和15.47%。[9]提供材料条件，[8]提供晶面波动解释，均有实质贡献。引文[8]晶面符号损坏，正文限制本次转录的区分能力是合理的。',
12:'Jev三次未形成有效评分，补评：高低范围、0.919/0.925及p值正确；Figure4确为双轴且两类右轴范围不同。可能过拟合、相关非互换及无相关系数差异检验的限制合理。',
14:'必答WRV—横向柔顺—结合完整。但新增Figure2读数偏高：软木末端约190%，并非略高200%，硬木末端约180%；该段只部分支持。图像仍对上升趋势有实质支持。另一些分子关系的扩写也不能冒充直接验证。',
17:'Jev三次未形成有效评分，补评：软木湿纸幅增幅较大和长度解释正确。Figure3黑点约0.8→4.4、0.65→1.8，回答已标明粗读量级，未按精确误差要求扣分。但用零距未降低排除一切本征强度变化不成立，保留机制段部分支持。',
18:'必答拟合区间、Gaussian/Peakfit、相对面积非绝对数量完整。用Decimal复算Table2十行均为100.00，面积口径及r²范围正确；新引入吸光系数相同假设不由所引论文验证。图7及图题对软木五档与四峰有实质支持。',
19:'三峰位必答正确，图6确标3226/3228、3346、3452；图像引用有效。额外把图6称为4000–16000样品遗漏图内0 r，且表格引文不能完整覆盖标题中采集条件，保留部分支持/覆盖。',
21:'33.06→29.28、3.78个百分点、11.4%正确，计算证据有效；完整序列与8.8%为相对变化均正确。所获上下文确实未含该研究Materials，局部证据缺口声明不应因全文另有方法而误罚；但引用组未覆盖所有方法/缺失声明，保留部分覆盖。',
22:'四项跨表数值和测量口径正确。但把不同测试进一步说成并非同批数据无证据；又把O3形成解释写成确定结论，并断言相关基于五点而原文未明确n，新增断言只部分支持。表1原图仍支持该段中的CI定义/表头，不是无关引用。',
23:'正文0.912/摘要0.888冲突、阔叶0.889及不可判定正误均正确；附加相对面积和趋势也有来源。图8图题只列对象而无趋势数据，单独[6]不支持先降后升再降；其他[2]文本已提供趋势。',
32:'三项必答齐全。新增同一树种把softwood/hardwood浆类误写为树种，原文未给具体树种，保留部分支持。未读Materials和未看图片是本次轨迹范围声明。提出另行回归/验证属明确建议，不当作本文已完成预测而扣分。'
}

# Every override names an immutable actual citation or reference passage.
O={}
def change(n,key,value,reason,basis):O.setdefault(n,[]).append((key,value,reason,basis))
def supported(n,c,reason,basis,group=True):
    change(n,'support_'+c,'supported',reason,basis)
    if group:change(n,'group_'+c,'complete',reason,basis)
def partial(n,c,reason,basis):
    change(n,'support_'+c,'partially_supported',reason,basis);change(n,'group_'+c,'partial',reason,basis)

change(1,'group_C3','complete','方法给出bleached/kraft及供应商，其他条件缺失被明确限定为论文没有提供。','actual [2]; E01')
change(3,'group_C2','complete','实际方法文字本身含重复转数序列且未写重复性；答案明确解释转录并限定已获文本。','actual [1]')
partial(4,'C4','非线性与离散观测不能直接证明任何内插都不可用；应说未经验证而不是不能内插。','E01/E03; actual [1]/[13]')
supported(4,'C5','工程建议被明确标为推论，唯一实测方法陈述ISO5267-1已有支持。','actual [1]; E01')
partial(5,'C3','two parameters紧接宏观纤丝化与长度，断言不能确定所指过强；忠实转述正文的趋势部分保留。','E12; actual [1]')
change(5,'citation_C2_2','supported','[1]直接解释macro-fibrillation index表征external macro-fibrillation，贡献该列表的一项。','actual [1]')
change(5,'support_C4','supported','轨迹只有检索/读节，没有view_image；文本图注不等于已看像素。','run tool_calls; candidate.available_context')
change(5,'basis_C4','CONTEXT','这是本次工具可见范围声明。','run tool_calls')
change(6,'group_C5','complete','[4]给WRV上升、孔隙及横向柔顺到结合的解释；缺少直接因果实验证明是合理边界。','actual [4]; E13')
supported(8,'C3','核算两类CI差值/百分比/差距无误，[1]还含三阶段可能解释，[2]含可能过拟合。','actual [1]/[2]/[9]; Table1')
for c in ('C3','C4'):change(9,'group_'+c,'complete','计算证据保留47.16、42.35、差值与公式；操作数与本题表1一致。','actual [10]/[11]; Table1')
change(9,'citation_C3_1','supported','该引用明确标为派生算术，正确给出-4.81，不能按原文引句要求排除。','actual [10]')
change(10,'group_C1','complete','方法给仪器公式参数，Table1原图/文字给转数、材料、尺寸列。','actual [2]/[1]/[8]')
change(10,'group_C3','complete','计算证据证明端点0.2/4.4%，表1证明局部回落；同段明确区分总体与路径。','actual [9]/[1]/[8]')
change(10,'citation_C3_1','supported','计算工具正确换算4.5→4.7，且明确非原文引述。','actual [9]')
change(11,'group_C1','complete','方法材料、正文非单调与原图的形状互相支持。','actual [9]/[8]/[11]')
change(11,'citation_C1_1','supported','[9]贡献本段材料、工艺及五档条件，不要求独自支持整段全部内容。','actual [9]')
supported(11,'C3','图4确有误差棒，差值与百分比计算正确；没有将误差棒冒充显著性检验。','Figure4 actual [11]; calculation [12]; E26')
change(11,'citation_C3_2','supported','计算证据给出34.20-40.46=-6.26及-15.472%，有实质贡献。','actual [12]')
change(11,'citation_C3_3','supported','实际图4可见误差棒，支持该段关于误差棒的陈述。','actual [11] Figure4 image')
supported(11,'C5','(200)表值与回落正确；原始送入文本的另两列符号确有损坏，答案限定其转录可辨能力。','actual [6]/[8]; Table1')
change(11,'citation_C5_2','supported','[8]包含亲水晶面的波动解释，即使转录符号不全仍有实质贡献。','actual [8]')
change(14,'citation_C1_2','supported','原图明确WRV上升和双轴结构，有实质支持，但数值过高仍由支持/覆盖部分分反映。','actual [26] Figure2')
change(14,'citation_C1_6','supported','结论[11]明确PFI使纤维细纤维化且超分子结构改变小，支持本段部分结论。','actual [11] conclusion')
change(18,'group_C5','complete','Decimal复算十行均恰为100.00；[2]给面积口径，[4]给所有数值和r²，不把拟合优度当不确定度的限定合理。','Table2 original image; actual [2]/[4]; E16/E18/E19')
change(18,'citation_C2_2','supported','图7图题确实标为解卷积谱，贡献段落的图谱对象；坐标/峰数另由原图支持。','actual [5]')
for key,basis in [('citation_C6_3','actual [5] Figure7 caption'),('citation_C6_4','actual [9] Figure7 image'),('citation_C7_2','actual [2] section3.3'),('citation_C7_3','actual [4] Table2'),('citation_C7_4','actual [5] Figure7 caption'),('citation_C7_5','actual [9] Figure7 image')]:
    change(18,key,'supported','该来源支持复合段落中对应的部分内容，单条有效性不要求一个来源包办整段。',basis)
change(19,'citation_C1_3','supported','图6原图明确三个标注峰位与双面板，即使回答漏写0r，该来源仍有实质支持。','actual [7] Figure6')
change(21,'group_C3','complete','计算证据提供-11.4337%，与33.06到29.28和回答11.4%一致。','actual [7]')
change(22,'citation_C2_3','supported','表1图像贡献Revolutions、材料、CI表头，不能因不支持FTIR部分就判整条无效。','actual [8] Table1')
partial(22,'C3','O3氢键生成在原文为might，回答直接写成断键少且新生，丢失解释的不确定性。','E19; actual [6] The increase might be because')
partial(22,'C4','五档不等于原文已经确认相关计算n=5；该句直接断言基于五点，证据不完整。','actual [2] section3.4; Table1/Table2')
change(23,'group_C2','complete','两处来源共同支持0.889和0.912/0.888冲突；不选择真值是正确限制。','actual [1]/[2]; E20/E21')
change(23,'group_C3','complete','[5]含相对谱带面积、[8]含CI定义、[2]含相关与趋势；合并证据已支持有界描述。','actual [5]/[8]/[2]; E16/E21/E22')
partial(32,'C4','论文只给两类商品浆，未给具体树种；同一浆类不应擅自写成同一树种。','E01; actual [3]/[5]/[9]')
change(32,'group_C5','complete','相关和冲突由三处引文支持，末尾另行回归验证明确是建议而非本文实测。','actual [3]/[7]/[2]; E20/E21/E22')
change(32,'support_C6','supported','本次可见内容未包含目标研究2.1方法，工具也没有看图；范围声明属实。','candidate.available_context; run tool_calls')
change(32,'basis_C6','CONTEXT','按实际可见范围而非全文是否存在方法判定。','candidate.available_context')

def supplement(n,saved):
    assert n in {2,12,17}
    claims={c['id']:c for c in saved['state']['candidate']['claims']}
    basis={2:{'C1':'E01','C2':'E01','C3':'E03','C4':'E01'},
           12:{'C1':'E10','C2':'NONE','C3':'E07','C4':'NONE','C5':'E10','C6':'E10','C7':'E26'},
           17:{'C1':'E14','C2':'NONE','C3':'NONE','C4':'E01','C5':'E14','C6':'CONTEXT'}}[n]
    decisions={};reasons={}
    for key,t in saved['targets'].items():
        kind=t['kind'];cid=t.get('claim_id');scope=n==17 and cid=='C6';bad=n==17 and cid=='C5'
        if kind=='point':v='complete'
        elif kind=='boundary':v='appropriate'
        elif kind=='reference':v='sound'
        elif kind=='claim_type':v='scope' if scope else 'fact'
        elif kind=='support':v='partially_supported' if bad else 'supported'
        elif kind=='basis':v=basis[cid]
        elif kind=='group':v='missing' if not claims[cid]['citation_refs'] else 'partial' if bad else 'complete'
        elif kind=='citation':v='supported'
        else:raise ValueError(kind)
        decisions[key]=v;reasons[key]=NOTES[n]
    return decisions,reasons

def main():
    _,jobs,study,reviews,_,_,_=s.audit(OUTPUT/'import',OUTPUT/'judges');entries={e['task_id']:e for e in study['jobs']};items=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];n=int(tid[-3:]);raw=reviews.get(('jev','rag',tid));entry=entries[tid]
        result=j.read_json(RUN/(tid+'.json'));saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        note=NOTES.get(n)
        if not result.get('answer'):
            assert result['stop_reason']=='OverflowError'
            note='上下文预算溢出，尚未产生初答即结束。空答案的必答要点与边界为0；不构造不存在的陈述/引用。已核对运行轨迹，未补跑或择优。'
            assert raw and all(v==0 for v in raw['key_point_scores'].values()) and raw['answerability_score']==0
        assert note
        item=dict(task_id=tid,result_sha256=j.digest(RUN/(tid+'.json')),grader_input_sha256=entry['input_sha256'],
            raw_review_sha256=j.sha(raw) if raw else None,summary=note,
            evidence_checked=sorted({e for p in job['reference_case']['key_points'] for e in p['evidence_ids']})+['actual_attached_text_and_verified_images','run_tool_trace'],changes=[])
        if raw:
            for key,to,reason,basis in O.get(n,[]):
                old=raw['decisions'][key]
                if old!=to:item['changes'].append(dict(decision_key=key,**{'from':old},to=to,reason=reason,basis=basis))
        else:
            d,r=supplement(n,saved);item.update(supplemental_decisions=d,supplemental_reasons=r)
        items.append(item)
    j.write(OUTPUT/'codex-adjudication.json',dict(reviewer='Codex',policy_sha256=g.POLICY_SHA,
        final_evidence_unit='actual_attached_text_and_verified_images',items=items))
    print(j.encode(dict(reviewed=32,supplemented=[2,12,17],changed=sum(bool(x['changes']) for x in items))))
if __name__=='__main__':main()
