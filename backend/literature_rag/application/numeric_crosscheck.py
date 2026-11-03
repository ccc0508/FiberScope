"""Question-triggered source-region checks; no expected values or evaluation identifiers."""
from copy import deepcopy
import re

VERSION='numeric-region-crosscheck-v1'


def numeric_verification_requested(question):
    numeric=bool(re.search(r'\d|数值|系数|数目|比例|百分比|coefficient|numeric|percentage',question,re.I))
    verification=bool(re.search(r'核实|核对|确认|正确|是否|是不是|对吗|对不对|吧[？?]|意味着|直接算|换算|verify|check|correct|is it|does .* mean',question,re.I))
    return numeric and verification


def plan_crosscheck(question,evidences,requirements,catalog):
    ledger=deepcopy(requirements)
    audit=dict(version=VERSION,triggered=numeric_verification_requested(question),
        policy='numeric verification only; same paper; missing abstract/results; shared two-action budget',
        added_requirement_ids=[],deferred_requirement_ids=[])
    if not audit['triggered'] or catalog is None or not evidences:
        audit['status']='not_requested' if not audit['triggered'] else 'catalog_unavailable'
        return ledger,[r for r in ledger if r['status']=='lookup'],audit
    # First source identifies the primary paper, not an expected answer. Never expand to new papers.
    anchor=evidences[0];doc=anchor.document_id
    ids={cid for e in evidences if e.document_id==doc for cid in
        ([s.chunk_id for s in e.source_chunks] or [e.chunk_id])}
    regions=set()
    for cid in ids:
        m=catalog.mapping.get(cid,{})
        if m.get('role_status')!='identified':continue
        if m.get('content_role')=='abstract':regions.add('abstract')
        if m.get('content_role') in {'body','table','equation'} and re.search(
                r'result|discussion|结果|讨论',' / '.join(m.get('section_path',[])),re.I):
            regions.add('results')
    audit.update(document_id=doc,observed_regions=sorted(regions))
    priority=[]
    for target in ('abstract','results'):
        if target in regions:continue
        existing=next((r for r in ledger if r['status']=='lookup'
            and r['lookup']['target']==target and next((e.document_id for e in evidences
                if e.ref==r['lookup']['document_ref']),None)==doc),None)
        if existing:
            priority.append(existing);continue
        used={r['id'] for r in ledger}
        rid=next('R'+str(i) for i in range(90,100) if 'R'+str(i) not in used)
        region='摘要' if target=='abstract' else '结果与讨论'
        item=dict(id=rid,requirement=f'核对同篇论文{region}与已提供材料中涉及用户问题的数值及统计口径。',
            status='lookup',evidence_refs=[anchor.ref],claim_indexes=[],issue_indexes=[],
            reason=f'用户在核实数值；当前证据未覆盖{region}。需要检查同材料、同指标关系与同条件下是否存在不同报告，不能预设矛盾。',
            lookup=dict(query=question,document_ref=anchor.ref,target=target,locator=''))
        ledger.append(item);priority.append(item);audit['added_requirement_ids'].append(rid)
    priority_ids={r['id'] for r in priority}
    actions=(priority+[r for r in ledger if r['status']=='lookup' and r['id'] not in priority_ids])[:2]
    selected={r['id'] for r in actions}
    for r in ledger:
        if r['status']=='lookup' and r['id'] not in selected:
            audit['deferred_requirement_ids'].append(r['id'])
            r.update(status='unresolved',reason=r['reason']+'；本轮两个补查动作预算已用于更优先的核对。')
            r.pop('lookup',None)
            # Any safe first-round edits have already been applied; the pending gap remains unresolved.
            r['issue_indexes']=[]
    audit['status']='scheduled' if priority else 'regions_already_supplied'
    return ledger,actions,audit
