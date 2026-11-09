from literature_rag.application.coverage_priority import CoveragePriority
from literature_rag.application.agent_loop import AgentLoop
from tests.test_agent_loop import Fake, decision
from literature_rag.adapters.providers.agent_chat import ToolCall

REQ=[dict(requirement_id='need_1',role='literature',paper_quote='A',source_quote='输入'),
     dict(requirement_id='need_2',role='literature',paper_quote='B',source_quote='输出')]
UPDATE=dict(requirement_id='need_1',status='verified',document_id='A',refs=['[1]'],finding='input',gap='')

def test_section_streak_redirect_and_exceptions():
    def setup():
        p=CoveragePriority(REQ[:1]);t=dict(search_calls=0,max_search_calls=2,tool_calls=[])
        for sid in ['a','b']:
            t['tool_calls'].append(dict(request=dict(tool='read_section',document_id='A',section_id=sid),coverage_schedule=dict(target_requirements=['need_1']),model_delivery=dict(status='delivered'),result=dict(status='completed',result=dict(next_offset=200))))
        return p,t
    req=dict(tool='read_section',document_id='A',section_id='c',target_requirements=['need_1'],coverage_updates=[],revisit_reason='')
    p,t=setup();d=p.prepare(req,t)[1]
    assert d['blocked'] and d['redirect_reason']=='targeted_search_before_more_sections'
    assert not p.prepare(req,t)[1]['blocked']  # bounded warning
    p,t=setup();t['search_calls']=2
    assert not p.prepare(req,t)[1]['blocked']
    p,t=setup()
    assert not p.prepare(dict(req,section_id='b',offset=200),t)[1]['blocked']
    p,t=setup()
    assert not p.prepare(dict(req,revisit_reason='Check a concrete contradictory value'),t)[1]['blocked']
    p,t=setup();t['tool_calls'].append(dict(request=dict(tool='search_literature',document_ids=['A'])))
    assert not p.prepare(req,t)[1]['blocked']
def trace(delivered=True):
    return {'tool_calls':[dict(request={'tool':'search_literature'},model_delivery={'status':'delivered' if delivered else 'withheld'},
        result=dict(status='completed',result={'evidence':[dict(ref='[1]',document_id='A',text='input')]}))]}

def test_redirect_covered_item_and_allow_targeted_gap_or_essential_recheck():
    p=CoveragePriority(REQ);t=trace()
    request,decision=p.prepare(dict(tool='read_section',document_id='A',target_requirements=['need_1'],coverage_updates=[UPDATE],revisit_reason=''),t)
    assert decision['blocked'] and decision['unresolved']==['need_2']
    assert request==dict(tool='read_section',document_id='A')
    assert not p.prepare(dict(target_requirements=['need_2'],coverage_updates=[],revisit_reason=''),t)[1]['blocked']
    assert not p.prepare(dict(target_requirements=['need_1'],coverage_updates=[],revisit_reason='Resolve inconsistent units'),t)[1]['blocked']
    assert not p.prepare(dict(target_requirements=['need_1'],coverage_updates=[],revisit_reason=''),t)[1]['blocked']

def test_withheld_or_wrong_document_cannot_mark_verified():
    for t,u in [(trace(False),UPDATE),(trace(),dict(UPDATE,document_id='B'))]:
        p=CoveragePriority(REQ);p.prepare(dict(target_requirements=['need_1'],coverage_updates=[u]),t)
        assert p.report(t)['items'][0]['status']=='missing'

def test_first_source_for_other_paper_precedes_more_partial_detail():
    p=CoveragePriority(REQ);t=trace()
    t['tool_calls'][0]['coverage_schedule']={'target_requirements':['need_1']}
    u=dict(UPDATE,status='partial',gap='need another detail')
    _,d=p.prepare(dict(target_requirements=['need_1'],coverage_updates=[u],revisit_reason=''),t)
    assert d['blocked'] and d['redirect_reason']=='paper_without_source'
    assert p.snapshot(t)['papers_without_source']==['need_2']

def test_targeting_two_papers_does_not_establish_both_were_returned():
    p=CoveragePriority(REQ);t=trace()
    t['tool_calls'][0]['coverage_schedule']={'target_requirements':['need_1','need_2']}
    p.prepare(dict(target_requirements=['need_2'],coverage_updates=[UPDATE]),t)
    assert p.papers_without_source(t)==['need_2']

def test_loop_delivers_priority_and_strips_schedule_from_real_executor():
    p=CoveragePriority(REQ)
    calls=[ToolCall('a','search_literature',dict(query='A',reason='input',target_requirements=['need_1'],coverage_updates=[],revisit_reason='')),
           ToolCall('b','read_section',dict(document_id='A',section_id='s',reason='more background',target_requirements=['need_1'],coverage_updates=[UPDATE],revisit_reason='')),
           ToolCall('c','search_literature',dict(query='B',reason='output',target_requirements=['need_2'],coverage_updates=[],revisit_reason=''))]
    a=Fake([decision(calls=[c]) for c in calls]+[decision('done [1]')]);executed=[]
    def execute(request,*args):
        executed.append(request);return trace()['tool_calls'][0]['result']
    r=AgentLoop(a,execute,lambda s:None,review_enabled=False,coverage_priority=p).run('compare','r')
    assert len(executed)==2 and all('coverage_updates' not in v for v in executed)
    assert r['tool_calls'][1]['result']['error_code']=='prioritize_uncovered_requirements'
    assert 'coverage_priority' in r['tool_calls'][0]['model_delivery']['messages'][0]['content']
    assert 'coverage_updates' in a.requests[0][1]['search_literature']['required']
