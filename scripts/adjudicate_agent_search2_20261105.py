"""Source-based calibration of the frozen compact-agent run; raw Jev remains unchanged."""
import judge_qa_eval as j
import qa_system_judge as g
import report_qa_system_benchmark as s
from grade_agent_search2_20261105 import RUN,OUTPUT
NOTES={
4:'63/57及非通用换算限制正确。方法足以支持限定条件，不要求附加一段不存在的通用换算原文。',
15:'长度差异与图1近似读数正确；低压力解释丢失might，且零距未降低不能排除削弱碎解；外部细纤维化与宏观指标并非同一变量。Jev三次未生成有效评分，由Codex补评。',
16:'三个必答点齐全；图3估读错误，针叶零距约140→167而非100→180–200；附加的零距/取向机理缺乏本篇依据。',
24:'核心机制和不能定量排名答出；但未降低不能排除单纤维增强，长度反向变化不能排除因果作用，唯一统计量说法遗漏两种CI的相关。',
25:'正确拒绝编造缺失BET数据；额外写同批、8000转自由OH局部高点、8000转对应63SR均无依据或有误（应40SR）。',
26:'正确拒绝提供不存在的逐次重复数字，也没有将未看图误写成原图没有误差棒。请求补充资料不是无依据事实。',
27:'正确区分报告的抗张类指标与未报告的撕裂/耐破；方法引用对范围判断有实质贡献。',
28:'正确说明只找到一篇而不能跨文献比较；额外把O2只在0→4000增加及相关分析n=5写确定，表2还存在12000→16000增加，n并未明示。',
29:'正确拒绝虚构预测模型，并区分拟合r²与预测验证；两次检索同一篇和未查看像素均与轨迹一致。',
30:'正确纠正湿纸幅变化前提；但把长度关键扩大为相对结合的主次排序，且等能量会产生更多细小纤维没有证据。',
31:'复核finish_reason=length，保留初稿不择优；开头正确纠正I→II前提，随后却扩展该文未研究的II型机理、峰位和测量判据，边界仅部分通过。'
}
O={}
def change(n,key,value,reason,basis):O.setdefault(n,[]).append((key,value,reason,basis))
def supported(n,c,reason,basis,group=True):
    change(n,'support_'+c,'supported',reason,basis)
    if group:change(n,'group_'+c,'complete',reason,basis)
def partial(n,c,reason,basis):
    change(n,'support_'+c,'partially_supported',reason,basis)
    change(n,'group_'+c,'partial',reason,basis)
for c in ['C2','C3']:change(4,'group_'+c,'complete','方法与转数/打浆度列表支持条件限定，未提出未经验证的换算。','actual [1]; E01/E03')
for key in ['citation_C1_2','citation_C1_3','citation_C3_2','citation_C3_3']:
    change(16,key,'supported','图3题名/实际图像支持测试对象或趋势；单引文不要求支持整段全部事实，错误估读仍记部分支持。','actual [3]/[6]; verified Figure3')
partial(24,'C2','未降低不等于没有增强，不能推出不是靠单纤维变强；更依赖长度也未比较贡献。','E14; actual [12]/[13]/[14]')
partial(24,'C3','反向共同变化不能排除长度对抗张的作用。','actual [1]/[4]/[12]; E12/E14')
partial(24,'C4','唯一统计量遗漏CI-XI与CI-XA的相关系数。','E10/E21')
partial(25,'C2','同供应商不等于同批次。','E01; actual [4]')
partial(25,'C3','8000转14.84%不是局部高点，下一档为15.25%。','E18; Table2')
partial(25,'C4','8000转应40SR；63SR对应12000转，不能错配。','E03; actual methods')
for key in ['citation_C1_2','citation_C1_3']:change(25,key,'supported','原文指向BET和TableS1，对未提供补充表的说明有实质贡献。','actual [5]/[9]; E23')
for key in ['citation_C1_3','citation_C1_6']:change(26,key,'supported','强度正文或表2对已报告指标及其所在图表有实质贡献。','actual [20]/[2]')
change(26,'group_C1','complete','方法、图3及表1/2共同覆盖所列已知结果，未把图形读数冒充重复数据。','actual attached references; E01/E03/E14')
for n,c in [(26,'C3'),(28,'C3'),(29,'C2'),(29,'C6')]:
    change(n,'support_'+c,'supported','这是可核实的检索/读图范围或请求补资料，不是声称缺失数据已经存在。','available_context; tool_calls')
    change(n,'basis_'+c,'CONTEXT','范围按实际工具轨迹核实。','tool_calls')
change(27,'citation_C2_1','supported','方法列出的测试指标对范围限定有贡献。','actual [1]; E04')
partial(28,'C5','O2并非只有0→4000上升，表2显示12000→16000也上升；下降趋势与无显著变化本身也不构成矛盾。','E18; actual Table2/E12')
change(28,'citation_C5_2','supported','补充材料目录支持孔隙/比表面积数据位于TableS1这一事实。','actual [6]; E23')
for key in ['citation_C2_1','citation_C2_2','citation_C2_3','citation_C3_3','citation_C3_5']:
    change(29,key,'supported','引用的同篇方法/结果支持文献身份和所研究的指标，而非预测模型。','actual [1]/[2]/[7]/[5]/[11]')
change(29,'group_C2','complete','两次命中同篇由工具轨迹及引用身份共同证实。','tool_calls; actual references')
change(29,'group_C3','complete','所列实验、结构及相对氢键指标在实际引用中均可核实。','actual attached references')
partial(30,'C3','长度关键不等于证明长度相对于结合占主因，跨指标趋势也不能排除氢键作用。','E14; actual references')
change(30,'citation_C4_2','supported','湿纸幅测试标准支持比较条件的一部分，不能支持等能量细小纤维假设。','actual [12]; E04')
change(31,'boundary','partial','先否定前提后把未研究I→II的论文用于支持I→II机制，未完全守住证据边界。','E24; C3-C8')
change(31,'group_C1','complete','晶型未变、I型晶面和前人不一致在三个引用中有支持。','actual [3]/[5]/[1]')
change(31,'kind_C6','fact','即使承认缺证，也仍明确断言II本征结晶度和尺寸通常更低，须纳入事实分母。','claim C6')
change(31,'citation_C3_3','supported','共结晶段对复合单元的一部分有支持，不支持其I→II外推。','actual [18]')

def supplement(n,saved):
    assert n==15
    decisions={};reasons={}
    for key,t in saved['targets'].items():
        kind=t['kind'];cid=t.get('claim_id')
        if kind=='point':v='partial' if key=='point_P2' else 'complete'
        elif kind=='boundary':v='appropriate'
        elif kind=='reference':v='sound'
        elif kind=='claim_type':v='fact'
        elif kind=='support':v='supported' if cid in {'C1','C2'} else 'partially_supported'
        elif kind=='basis':v='E12'
        elif kind=='group':v='complete' if cid in {'C1','C2'} else 'partial'
        elif kind=='citation':v='supported'
        else:raise ValueError(kind)
        decisions[key]=v
        reasons[key]=NOTES[n]+' C1/C2长度趋势及图1合理近似成立；C3确定归因和碎解排除过强；C4将外部细纤维化与宏观指标直接视作矛盾不成立。各引用仍对复合单元有部分实质贡献。'
    return decisions,reasons

def main():
    _,jobs,study,reviews,_,_,_=s.audit(OUTPUT/'import',OUTPUT/'judges');entries={e['task_id']:e for e in study['jobs']};items=[]
    for job in jobs:
        if job['system']!='rag' or job['task_id'] not in entries:continue
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
    print(j.encode(dict(reviewed=len(items),supplemented=[x["task_id"] for x in items if "supplemental_decisions" in x],changed=sum(bool(x['changes']) for x in items))))
if __name__=='__main__':main()
