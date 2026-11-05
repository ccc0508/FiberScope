"""Source-based calibration of the frozen compact-agent run; raw Jev remains unchanged."""
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from grade_agent_compact_20261105 import RUN,OUTPUT
NOTES={int(k):v for k,v in j.read_json(RUN/'source-review-notes.json').items()}
O={}
def change(n,key,value,reason,basis):O.setdefault(n,[]).append((key,value,reason,basis))
def supported(n,c,reason,basis,group=True):
    change(n,'support_'+c,'supported',reason,basis)
    if group:change(n,'group_'+c,'complete',reason,basis)
def partial(n,c,reason,basis):
    change(n,'support_'+c,'partially_supported',reason,basis)
    change(n,'group_'+c,'partial',reason,basis)
# Overrides address actual attached evidence, not preferred answer style.
partial(1,'C2','每厘米齿刀长度与N/mm不一致；such as不足以断言非逐点标定。','E01/E03; actual [1]')
supported(2,'C2','区别仅在于作用力在本段列出的PFI参数范围内；1.88倍正确，末尾未作已证因果。','actual [1]; E01')
for n,c in [(3,'C6'),(12,'C7')]:
    change(n,'support_'+c,'supported','轨迹没有view_image，未查看像素的范围声明属实。','run tool_calls')
    change(n,'basis_'+c,'CONTEXT','按实际可见上下文与工具轨迹判定。','run tool_calls')
for key in ['citation_C1_2','citation_C2_2']:
    change(4,key,'supported','实际Figure2支持柱高趋势与约63/57，不要求单一图支持整个复合段。','actual [22]; verified Figure2 pixels')
change(4,'citation_C3_2','supported','方法文字明确首值0与57，贡献图文冲突的一方。','actual [1]; E03')
change(4,'group_C3','complete','已实看Figure2无误差棒且首值约15，与方法0冲突。','actual [22]/[1]')
for c in ['C1','C2']:change(5,'group_'+c,'complete','MORFI三指标及其他测试类别在方法中可核实。','actual [2]; E04')
partial(5,'C3','two parameters由紧邻前句宏观细纤维化与长度指明，称未明确过强。','actual [1]; E12')
change(9,'citation_C4_2','supported','派生计算给出-4.81与-10.1993%，操作数与表1一致。','actual [7]/[1]; E09')
change(9,'group_C5','complete','表1提供36.26到42.35回升且未列误差，本句仅限制所给表。','actual [1]')
change(11,'group_C2','complete','引用包含全序列及三阶段描述，端点与非单调解释有依据。','actual [1]; E08/E09/E11')
change(11,'group_C5','complete','两引用合并有表格值、无误差列、过拟合可能性；未说图中无误差棒。','actual [1]/[2]')
change(12,'citation_C6_2','supported','表1端点和中间回升支持计算口径与非单调。','actual [2]; E08/E09')
partial(13,'C4','把cleavage among chains写成分子链断裂，额外关系缺乏原文支持。','actual [4]; E27')
partial(13,'C5','把CI-XA无定形过拟合解释成CI-XA偏高，方向与原文相反。','actual [2]; E10')
partial(14,'C3','相对含量写总量，链间分离写主链断裂，并去掉该解释might的不确定性。','actual [4]; E16/E27')
supported(15,'C1','原图1的长度约2000→1650/硬约900且无误差棒；作用力和正文差异均支持，树种仅是否定归因限制。','actual [8]/[2]/[1]; verified Figure1')
for c in ['C2','C5','C7','C8']:supported(18,c,'已核对FTIR方法、表2面积和、式4实际缺常数及无view_image轨迹，相关描述正确。','actual [1]/[2]/[4]/[5]; E15/E16; tool trace')
change(18,'citation_C6_2','supported','方法明确五次记录平均，支持区分采谱平均与拟合面积不确定度。','actual [1]')
partial(20,'C5','原文链间cleavage不能写成纤维素分子主链断裂，可能措辞不能补足对象错误。','actual [1]/[4]; E27')
partial(22,'C2','未建立直接换算不等于CI-XI不能作为候选预测指标，末尾排除过强。','actual [1]; E22')
for key in ['citation_C1_3','citation_C2_5']:
    change(23,key,'supported','实际[5]含Figure4定义与完整Table1，分别支持强度法及五档CI数值。','actual [5]')
for c in ['C1','C2']:change(23,'group_'+c,'complete','全部实际引文覆盖定义、摘要正文冲突、各档数值及未明示样本量。','actual [1]/[2]/[3]/[4]/[5]; E20/E21')
partial(24,'C2','硬木较低作用力在原文为might，回答写成确定归因。','actual [1]; E12')
partial(24,'C3','把mobility/accessibility/WRV三个解释因素改成直接因果结果，并把相对含量写总量。','actual [2]; original section3.3')
partial(24,'C4','零距未降低不能排除纤维本征强度提高；而非纤维变强过强。','actual [10]; E14')
partial(24,'C6','显著相关不只CI-XI与CI-XA，氢键—CI也报告p<.05；无贡献排名部分仍正确。','E20/E21; actual [12]')
change(25,'citation_C1_1','supported','方法直接支持复合段中的商业漂白针叶kraft、浓度与转数。','actual [4]; E01/E02')
change(25,'group_C2','complete','方法的有序列表与BET缺表限制由[4]/[10]及实际范围支持。','actual [4]/[10]; E03/E23')
for key in ['citation_C1_3','citation_C1_4','citation_C1_6','citation_C1_7']:
    change(26,key,'supported','对应片段分别支持随转数的抗张描述、图3题名、表2对象或T494方法，有实质贡献。','actual [20]/[24]/[2]/[6]')
supported(26,'C2','明确未看图，不能排除图内误差棒；附件目录仅有结构/孔隙数据，未声称原作者从未做重复。','actual [5]; run tool_calls')
change(27,'citation_C1_1','supported','方法支持首句原料商业漂白两类kraft，引用不必独自支持整段。','actual [9]; E01')
supported(27,'C3','未看图且未报告数字的限制针对retrieved text，未断言原图无误差棒。','actual [2]; tool_calls; available_context')
change(27,'group_C4','complete','明确没有耐破/撕裂方法并限制为检索范围，未声称从未实验。','actual [1]; available_context')
partial(28,'C2','五个处理水平不证明相关计算只有5个点，原文未说明n。','E02/E21; actual [6]/[3]')
change(29,'group_C2','complete','方法、正文和表2共同支持非预测研究及拟合r²的正确区分。','actual [1]/[2]/[3]/[4]')
change(29,'citation_C2_4','supported','[4]说明研究结晶结构相关而非抗张预测模型，对该段领域/范围声明有贡献。','actual [4]')
partial(30,'C1','文中未给误差范围的绝对表述忽略原图可见误差棒；应限制正文没有数值列。','actual [6]; verified Figure3')
supported(30,'C2','已核实Figure3黑点约0.8→4.4、0.65→1.8；近似值和方向合理且未当重复原始数据。','actual [6]; verified Figure3')
change(30,'citation_C5_1','supported','图3只有图形和误差棒，支持没有逐次数字或显著性标记的限定。','actual [6]; verified Figure3')
change(31,'group_C4','complete','端点计算和中间回升均能从表1核算。','actual [5]; E08/E09')
change(31,'kind_C10','fact','复合段包含通用I→II处理条件的科学断言，不能全当纯范围声明排除。','claim C10')
for key in ['citation_C10_1','citation_C10_2','citation_C10_3']:
    change(31,key,'supported','分别支持晶型未变、表1数值和相关趋势这一段的部分内容；通用处理断言仍保留部分覆盖。','actual [2]/[5]/[6]')
change(32,'citation_C1_2','supported','表1注脚明确强度法/面积法，实质支持该段定义。','actual [5]')
partial(32,'C3','每树种5点把浆类写成树种并肯定未经报告的n=5；后标推断不能替代原始样本量。','E01/E21; actual [5]/[6]')

supported(23,'C1','开头0.912在后文紧接明确披露摘要0.888冲突，不能拆开处罚为择正文；实际定义也正确。','actual [1]/[4]/[5]; E20/E21')
change(7,'group_C4','complete','表1、方法定义和可能过拟合/显著相关共同支持该段。','actual [1]/[3]; E06/E07/E10')
change(24,'citation_C3_3','supported','[9]给各类相对含量随转数变化，对复合段中含量变化有实质贡献；错误因果仍计部分支持。','actual [9]')

def supplement(n,saved):
    assert n in {16,19}
    claims={c['id']:c for c in saved['state']['candidate']['claims']}
    decisions={};reasons={}
    for key,t in saved['targets'].items():
        kind=t['kind'];cid=t.get('claim_id')
        if kind=='point':v='complete'
        elif kind=='boundary':v='appropriate'
        elif kind=='reference':v='sound'
        elif kind=='claim_type':v='fact'
        elif kind=='support':
            v=('supported' if cid=='C2' else 'contradicted' if cid=='C3' else 'partially_supported') if n==19 else 'partially_supported'
        elif kind=='basis':v='E17' if n==19 else 'E14'
        elif kind=='group':v='missing' if not claims[cid]['citation_refs'] else 'complete' if n==19 and cid=='C2' else 'partial'
        elif kind=='citation':v='supported'
        else:raise ValueError(kind)
        decisions[key]=v
        reasons[key]=NOTES[n]+' 单条引用按部分实质贡献判断；16题图3支持趋势/误差棒但不能支持错误估读，19题C2峰归属和稳定性有[2]/[3]支持。'
    return decisions,reasons

def main():
    _,jobs,study,reviews,_,_,_=s.audit(OUTPUT/'import',OUTPUT/'judges');entries={e['task_id']:e for e in study['jobs']};items=[]
    for job in jobs:
        if job['system']!='rag':continue
        tid=job['task_id'];n=int(tid[-3:]);raw=reviews.get(('jev','rag',tid));entry=entries[tid]
        result=j.read_json(RUN/(tid+'.json'));saved=j.read_json(OUTPUT/'judges/inputs'/(entry['name']+'.json'))
        note=NOTES.get(n)
        if not result.get('answer'):
            assert result['status']=='failed'
            note='运行失败未产生答案。空答案的必答要点与边界为0；不构造不存在的陈述/引用。已核对运行轨迹，未补跑或择优。'
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
    print(j.encode(dict(reviewed=32,supplemented=[x["task_id"] for x in items if "supplemental_decisions" in x],changed=sum(bool(x['changes']) for x in items))))
if __name__=='__main__':main()
