import json
from literature_rag.application.paper_directory import routing_catalog, routing_catalog_prompt
from literature_rag.application.task_coverage import CoverageItem, coverage_report, completion_feedback
from literature_rag.application.specialist_agent import SpecialistCoordinator
from tests.test_specialist_agent import Fake, route, answer, tool


def test_catalog_only_includes_active_documents_and_preserves_unknown_identity():
    items = routing_catalog([
        {'document_id': 'doc_cec3e2f8b5abaa89', 'filename': 'renamed.pdf'},
        {'document_id': 'new-doc', 'title': 'New study', 'filename': 'new.pdf'},
    ])
    assert len(items) == 2
    assert items[0]['filename'] == 'renamed.pdf'
    assert items[0]['label'] == 'Morais与Curto（2022）'
    assert items[1]['title'] == 'New study' and items[1]['topics'] == ''
    assert routing_catalog([]) == []
    prompt = routing_catalog_prompt(items)
    assert 'Morais与Curto' in prompt and 'New study' in prompt
    assert 'doc_cec3e2f8b5abaa89' not in prompt and 'renamed.pdf' not in prompt
    assert 'metadata_status' not in prompt


def test_planner_sees_catalog_without_forwarding_it_to_sql():
    a = Fake([route('direct', answer='打浆度是描述浆料滤水性能的指标。')])
    r = SpecialistCoordinator(a, lambda *a: 1/0, lambda s: None,
        paper_directory=[{'document_id': 'new-doc', 'title': 'PFI study'}]).run('打浆度是什么', 'r')
    assert 'PFI study' in a.requests[0][0][0]['content']
    assert r['routing_catalog'][0]['document_id'] == 'new-doc'
    assert r['budget_usage']['tools'] == 0


def test_partial_requires_gap_and_real_delivered_evidence():
    needs = [dict(requirement_id='need_1', role='literature', source_quote='解释机制', paper_quote='A')]
    event = dict(request={'tool':'read_section'}, model_delivery={'status':'delivered'},
        result={'status':'completed','result':{'sources':[{'ref':'[1]','document_id':'A','text':'关联'}]}})
    item = CoverageItem(requirement_id='need_1',status='partial',document_id='A',refs=['[1]'],finding='有相关证据')
    report = coverage_report(needs,[item],{'tool_calls':[event]})
    assert 'missing_gap' in report['items'][0]['errors']
    item.gap = '没有因果实验'
    report = coverage_report(needs,[item],{'tool_calls':[event]})
    assert report['evidence_adequacy'] == 'partial' and not report['complete']
    event['model_delivery']['status'] = 'withheld'
    assert coverage_report(needs,[item],{'tool_calls':[event]})['evidence_adequacy'] == 'insufficient'


def test_empty_checklist_is_not_sufficient():
    assert coverage_report([], [], {})['evidence_adequacy'] == 'insufficient'
    assert not coverage_report([], [], {})['complete']


def test_partial_evidence_reaches_parent_with_gap_and_no_new_budget():
    req=dict(role='literature',source_quote='解释机制',paper_quote='A')
    partial=json.dumps(dict(status='insufficient_evidence',summary='有关联[1]，因果未确认',
        coverage=[dict(requirement_id='need_1',status='partial',document_id='A',refs=['[1]'],
                       finding='有关联',gap='没有因果证据')]),ensure_ascii=False)
    a=Fake([route('literature',requirements=[req]),tool('read_section',{'document_id':'A','section_id':'s','reason':'核查'}),
            answer(partial),answer(partial),answer('论文报告关联[1]，因果仍未确认。一般原理解释（非本次文献证实）：需控制条件判断。')])
    def execute(*args):return dict(status='completed',result={'sources':[{'ref':'[1]','document_id':'A','text':'关联'}]})
    r=SpecialistCoordinator(a,execute,lambda s:None).run('A解释机制','r')
    assert r['status']=='completed'
    assert r['children'][0]['coverage_report']['evidence_adequacy']=='partial'
    assert r['children'][0]['trace']['coverage_retry_requested']
    assert r['budget_usage']['model']==5 and r['budget_usage']['tools']==1
    parent=json.loads(a.requests[-1][0][1]['content'])
    assert parent['specialists'][0]['coverage_report']['items'][0]['reported']['gap']=='没有因果证据'
    assert parent['allowed_refs'][0]['ref']=='[1]'


def test_unresolved_origin_check_overrides_self_reported_verified():
    needs = [dict(requirement_id='need_1', role='literature', source_quote='比较来源', paper_quote='A')]
    event = dict(request={'tool':'read_section'}, model_delivery={'status':'delivered'},
        result={'status':'completed','result':{'sources':[{'ref':'[1]','document_id':'A','text':'Public dataset'}]}})
    item = CoverageItem(requirement_id='need_1', status='verified', document_id='A',
        refs=['[1]'], finding='公开数据集', checks=[dict(aspect='data_origin', status='missing',
        refs=[], finding='', gap='生成方式未说明')])
    report = coverage_report(needs, [item], {'tool_calls':[event]})
    assert report['evidence_adequacy'] == 'partial'
    assert not report['complete']
    assert report['items'][0]['reported']['checks'][0]['gap'] == '生成方式未说明'


def test_facet_evidence_must_have_been_delivered():
    needs = [dict(requirement_id='need_1', role='literature', source_quote='范围', paper_quote='A')]
    event = dict(request={'tool':'read_section'}, model_delivery={'status':'delivered'},
        result={'status':'completed','result':{'sources':[{'ref':'[1]','document_id':'A','text':'table'}]}})
    item = CoverageItem(requirement_id='need_1', status='verified', document_id='A',
        refs=['[1]'], finding='范围', checks=[dict(aspect='numeric_range', status='verified',
        refs=['[2]'], finding='A:1 B:2; min=1 max=2', gap='')])
    report = coverage_report(needs, [item], {'tool_calls':[event]})
    assert 'check_0_unavailable_ref' in report['items'][0]['errors']
    assert not report['complete']
    item.checks[0].refs = ['[1]']
    assert coverage_report(needs, [item], {'tool_calls':[event]})['complete']
