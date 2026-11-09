import json
from literature_rag.application.task_coverage import Requirement, CoverageItem, ground_requirements, coverage_report
from tests.test_specialist_agent import Fake, route, result, answer, tool
from literature_rag.application.specialist_agent import SpecialistCoordinator


def test_verbatim_contract_drops_invented_conclusions():
    good=Requirement(role='literature',source_quote='核对粗度单位',paper_quote='Morais')
    bad=Requirement(role='literature',source_quote='1 tex=1000 mg/m',paper_quote='Morais')
    accepted,rejected=ground_requirements([good,bad],'Morais：核对粗度单位')
    assert len(accepted)==1 and rejected[0]['reason']=='not_verbatim_user_text'


def test_planner_generated_formula_never_reaches_children_or_parent():
    a=Fake([route('sql',sql_task='1 tex=1000 mg/m',answer='本地=进口'),result(summary='无证据'),answer('无法确认')])
    r=SpecialistCoordinator(a,lambda *a:None,lambda s:None).run('核对字段','r')
    assert r['status']=='completed'
    for messages,_,_ in a.requests[1:]:
        assert '1 tex=1000' not in str(messages) and '本地=进口' not in str(messages)
    assert r['children'][0]['coverage_report']['checklist_missing']


def test_report_rejects_wrong_document_and_undelivered_ref():
    req=[dict(requirement_id='need_1',role='literature',source_quote='单位',paper_quote='A')]
    coverage=[CoverageItem(requirement_id='need_1',status='verified',document_id='B',refs=['[1]'],finding='mg/m')]
    event=dict(request={'tool':'search_literature'},model_delivery={'status':'delivered'},result=dict(status='completed',result={'evidence':[{'ref':'[1]','document_id':'A'}]}))
    r=coverage_report(req,coverage,{'tool_calls':[event]})
    assert not r['complete'] and 'document_not_supported_by_refs' in r['items'][0]['errors']
    coverage[0].document_id='A';event['model_delivery']['status']='withheld'
    assert 'unavailable_ref' in coverage_report(req,coverage,{'tool_calls':[event]})['items'][0]['errors']


def test_incomplete_item_gets_one_bounded_chance_then_reports_gap():
    req=dict(role='literature',source_quote='核对A单位',paper_quote='A')
    a=Fake([route('literature',literature_task='ignored',requirements=[req]),
            result('insufficient_evidence','尚未查'),
            tool('search_literature',dict(query='A单位',reason='gap')),
            answer(json.dumps(dict(status='ok',summary='mg/m [1]',coverage=[dict(requirement_id='need_1',status='verified',document_id='A',refs=['[1]'],finding='mg/m')]))),
            answer('mg/m [1]')])
    def execute(*args):return dict(status='completed',result={'evidence':[{'ref':'[1]','document_id':'A','text':'mg/m'}]})
    r=SpecialistCoordinator(a,execute,lambda s:None).run('核对A单位','r')
    assert r['status']=='completed' and r['children'][0]['coverage_report']['complete']
    assert r['children'][0]['trace']['coverage_retry_requested']
    assert r['budget_usage']['model']==5 and r['budget_usage']['tools']==1


def test_missing_coverage_cannot_remain_ok():
    a=Fake([route('sql',sql_task='x',requirements=[dict(role='sql',source_quote='查总数')]),
            result(summary='未查'),result(summary='未查'),answer('总数尚未核对')])
    r=SpecialistCoordinator(a,lambda *a:None,lambda s:None).run('查总数','r')
    assert r['status']=='completed'
    assert r['children'][0]['result']['status']=='insufficient_evidence'
    assert len(r['children'][0]['trace']['coverage_checks'])==2



def test_clarification_does_not_force_paper_lookup_for_coverage():
    a=Fake([route('both',sql_task='x',literature_task='y',requirements=[dict(role='sql',source_quote='查高转数强度'),dict(role='literature',source_quote='参考A',paper_quote='A')]),result('needs_clarification','',['阈值和指标？']),answer('请确认阈值和指标')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('查高转数强度，参考A','r')
    assert r['status']=='completed' and len(r['children'])==1
    assert not r['children'][0]['trace'].get('coverage_retry_requested')


def test_same_requirement_for_two_papers_is_not_deduplicated():
    req=[Requirement(role='literature',source_quote='核对单位',paper_quote=p) for p in ['A','B']]
    accepted,_=ground_requirements(req,'A与B核对单位')
    assert len(accepted)==2
    report=coverage_report(accepted,[CoverageItem(requirement_id='need_1',status='missing')],{})
    assert report['items'][1]['errors']==['missing_or_duplicate_coverage_item']


def test_cross_paper_synthesis_need_accepts_multiple_sources_without_one_document():
    req=[dict(requirement_id='need_1',role='literature',source_quote='比较换算',paper_quote='')]
    items=[CoverageItem(requirement_id='need_1',status='verified',refs=['[1]','[2]'],finding='分别换算')]
    event=dict(request={'tool':'search_literature'},model_delivery={'status':'delivered'},result=dict(status='completed',result={'evidence':[{'ref':'[1]','document_id':'A'},{'ref':'[2]','document_id':'B'}]}))
    assert coverage_report(req,items,{'tool_calls':[event]})['complete']


def test_figure_ref_uses_asset_document_identity():
    req=[dict(requirement_id='need_1',role='literature',source_quote='看图',paper_quote='A')]
    items=[CoverageItem(requirement_id='need_1',status='verified',document_id='A',refs=['[1]'],finding='图中趋势')]
    event=dict(request={'tool':'view_image'},model_delivery={'status':'delivered'},result=dict(status='completed',result={'ref':'[1]','asset':{'document_id':'A'}}))
    assert coverage_report(req,items,{'tool_calls':[event]})['complete']


def test_coverage_reference_lists_preserve_more_than_twelve_sources():
    from literature_rag.application.task_coverage import EvidenceCheck
    refs = [f'[{i}]' for i in range(1, 14)]
    check = EvidenceCheck(aspect='validation', status='verified', refs=refs)
    item = CoverageItem(requirement_id='need_1', status='verified', refs=refs, checks=[check])
    assert item.refs == refs
    assert item.checks[0].refs == refs
    schema = CoverageItem.model_json_schema()
    assert 'maxItems' not in schema['properties']['refs']
    assert 'maxItems' not in schema['$defs']['EvidenceCheck']['properties']['refs']


def test_online_coverage_schema_has_no_reference_count_cap():
    from literature_rag.application.coverage_priority import CoveragePriority
    schema = {'type': 'object', 'properties': {}, 'required': []}
    enriched = CoveragePriority([]).schemas({'read_section': schema})['read_section']
    refs = enriched['properties']['coverage_updates']['items']['properties']['refs']
    assert 'maxItems' not in refs
