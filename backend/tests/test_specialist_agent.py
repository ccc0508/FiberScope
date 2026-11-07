import json
from literature_rag.application.specialist_agent import SpecialistCoordinator,SQL_TOOLS,PAPER_TOOLS
from literature_rag.application.agent_loop import AgentBudget
from literature_rag.adapters.providers.agent_chat import Decision,ToolCall,ChatAgentAdapter


class Fake:
    tool_messages=staticmethod(ChatAgentAdapter.tool_messages)
    def __init__(self,decisions):self.decisions=iter(decisions);self.requests=[]
    def decide(self,messages,schemas,timeout,max_tokens):
        self.requests.append((messages,schemas,timeout));return next(self.decisions)


def answer(text):return Decision(text,[],dict(role='assistant',content=text),None,'stop')
def tool(name,args):
    return Decision('',[ToolCall('tc',name,args)],dict(role='assistant',content=None),None,'tool_calls')
def route(name,**kw):return tool('route_task',dict(route=name,reason='test',**kw))
def result(status='ok',summary='发现 [1]',missing=None):
    return answer(json.dumps(dict(status=status,summary=summary,missing_choices=missing or [],limitations=[]),ensure_ascii=False))


def test_direct_has_no_tools_or_children():
    a=Fake([route('direct',answer='你好')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('你好','r')
    assert r['answer']=='你好' and r['status']=='completed' and not r['children']
    assert r['budget_usage']['model']==1


def test_sql_isolated_same_root_and_parent_review_only():
    a=Fake([route('sql',sql_task='count'),tool('describe_experiment_data',dict(reason='schema')),
        tool('query_experiment_data',dict(sql='SELECT COUNT(*)',reason='count')),result(),answer('61个 [1]')])
    calls=[]
    def execute(req,rid,timeout):
        calls.append((req,rid));return dict(status='completed',result=dict(ref='[1]',rows=[[61]]) if req['tool']=='query_experiment_data' else {})
    r=SpecialistCoordinator(a,execute,lambda s:None,paper_directory=[{'document_id':'secret-paper'}]).run('count','root')
    assert r['status']=='completed' and r['answer']=='61个 [1]'
    assert all(rid=='root' for _,rid in calls)
    assert set(a.requests[1][1])==SQL_TOOLS
    assert 'secret-paper' not in str(a.requests[1][0])
    assert r['children'][0]['trace']['review_status']=='delegated_to_parent'
    assert [x['stage'] for x in r['model_calls']].count('synthesis_review')==1


def test_unauthorized_child_tool_never_executes():
    a=Fake([route('sql',sql_task='count'),tool('search_literature',dict(query='q',reason='bad')),
        result('insufficient_evidence','无结果'),answer('无法确认')])
    calls=[]
    r=SpecialistCoordinator(a,lambda *a:calls.append(a),lambda s:None).run('q','r')
    assert not calls
    assert r['children'][0]['trace']['tool_calls'][0]['result']['error_code']=='tool_not_allowed'


def test_clarification_stops_remaining_child():
    a=Fake([route('both',sql_task='ambiguous',literature_task='paper'),
        result('needs_clarification','', ['哪项指标？']),answer('请确认指标。')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
    assert r['status']=='completed' and len(r['children'])==1


def test_mixed_refs_and_tools_shared_budget():
    a=Fake([route('both',sql_task='count',literature_task='explain'),
        tool('query_experiment_data',dict(sql='SELECT COUNT(*)',reason='count')),result(summary='61 [1]'),
        tool('search_literature',dict(query='paper',reason='find')),result(summary='paper [2]'),answer('61 [1]；论文解释 [2]')])
    def execute(req,rid,timeout):
        if req['tool']=='query_experiment_data':return dict(status='completed',result=dict(ref='[1]',rows=[[61]]))
        return dict(status='completed',result=dict(evidence=[dict(ref='[2]',text='source',document_id='d')]))
    r=SpecialistCoordinator(a,execute,lambda s:None,paper_directory=[]).run('q','root')
    assert r['status']=='completed'
    assert r['budget_usage']['model']==6 and r['budget_usage']['tools']==2
    assert set(a.requests[3][1])==PAPER_TOOLS-{'find_documents'}
    assert {e['ref'] for e in r['citation_validation']['available_records']}=={'[1]','[2]'}


def test_invalid_parent_reference_repaired_with_shared_budget():
    a=Fake([route('sql',sql_task='count'),tool('query_experiment_data',dict(sql='q',reason='test')),
        result(),answer('61 [99]'),answer('61 [1]')])
    r=SpecialistCoordinator(a,lambda *a:dict(status='completed',result=dict(ref='[1]',rows=[[61]])),lambda s:None).run('q','r')
    assert r['status']=='completed' and r['citation_validation']['status']=='repaired'
    assert r['budget_usage']['model']==5


def test_bad_route_or_child_json_fails_without_replanning():
    for decisions in ([answer('unstructured route')],[route('sql',sql_task='count'),answer('not json')]):
        a=Fake(decisions)
        r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
        assert r['status']=='failed' and not r['answer']


def test_insufficient_shared_budget_does_not_reset_for_children():
    a=Fake([route('both',sql_task='count',literature_task='paper')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None,budget=AgentBudget(max_model_calls=6)).run('q','r')
    assert r['status']=='failed' and r['stop_reason']=='BudgetExhausted'
    assert len(a.requests)==1


def test_one_tool_total_cannot_fund_two_children():
    a=Fake([route('both',sql_task='count',literature_task='paper')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None,budget=AgentBudget(max_tool_calls=1)).run('q','r')
    assert r['status']=='failed' and r['budget_usage']['tools']==0


def test_deadline_includes_routing():
    now=[0]
    class Slow(Fake):
        def decide(self,*args):
            now[0]=241
            return super().decide(*args)
    a=Slow([route('sql',sql_task='count')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None,clock=lambda:now[0]).run('q','r')
    assert r['status']=='failed' and not r['children']


def test_parent_never_cites_payload_omitted_by_context_budget():
    a=Fake([route('sql',sql_task='count'),tool('query_experiment_data',dict(sql='q',reason='test')),
        result('insufficient_evidence','无证据'),answer('invalid [1]'),answer('无法确认')])
    raw=dict(status='completed',result=dict(ref='[1]',rows=[['x'*50000]]))
    r=SpecialistCoordinator(a,lambda *a:raw,lambda s:None,budget=AgentBudget(max_context_chars=24000)).run('q','r')
    assert r['status']=='completed' and r['citation_validation']['available_records']==[]
    assert r['answer']=='无法确认'


def test_fenced_child_normalized_without_model_repair():
    original='\ufeff```json\n'+result(summary='无证据').text+'\n```'
    a=Fake([route('sql',sql_task='count'),answer(original),answer('无法确认')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
    assert r['status']=='completed' and len(a.requests)==3
    assert r['children'][0]['trace']['answer']==original
    assert r['format_checks'][1]['wrapper_removed']


def test_empty_route_one_format_repair_no_tools():
    a=Fake([tool('route_task',{}),answer('{"route":"direct","reason":"greeting","answer":"你好"}')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('你好','r')
    assert r['status']=='completed' and r['answer']=='你好'
    assert r['budget_usage']['model']==2 and a.requests[1][1]=={}
    assert r['format_checks'][0]['raw_output']=={}
    assert r['format_checks'][0]['status']=='repaired'


def test_malformed_native_arguments_preserved_and_repaired():
    d=tool('route_task',{})
    d.message['tool_calls']=[dict(function=dict(name='route_task',arguments='{"route":'))]
    a=Fake([d,answer('{"route":"direct","reason":"greeting","answer":"你好"}')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('你好','r')
    assert r['status']=='completed'
    assert r['format_checks'][0]['raw_output']=='{"route":'
    assert r['model_calls'][0]['raw_message']==d.message


def test_child_repair_once_preserves_initial_output():
    a=Fake([route('sql',sql_task='count'),answer('发现信息不足'),result('insufficient_evidence','信息不足'),answer('信息不足')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
    assert r['status']=='completed' and r['budget_usage']['model']==4
    assert r['children'][0]['trace']['answer']=='发现信息不足'
    assert r['format_checks'][1]['status']=='repaired'
    assert r['model_calls'][2]['stage']=='sql_format_repair'


def test_irrecoverable_output_stops_after_one_correction():
    a=Fake([route('sql',sql_task='count'),answer('{broken'),answer('{still broken')])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
    assert r['status']=='failed' and len(a.requests)==3
    check=r['format_checks'][1]
    assert check['status']=='repair_failed' and check['raw_output']=='{broken'
    assert check['repair_output']=='{still broken'
    assert r['children'][0]['status']=='failed'


def test_repair_does_not_consume_reserved_calls_or_time():
    a=Fake([tool('route_task',{})])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None,budget=AgentBudget(max_model_calls=3)).run('q','r')
    assert len(a.requests)==1 and r['format_checks'][0]['status']=='repair_skipped_budget'
    now=[0]
    class Slow(Fake):
        def decide(self,*args):
            now[0]=220
            return super().decide(*args)
    a=Slow([tool('route_task',{})])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None,clock=lambda:now[0]).run('q','r')
    assert len(a.requests)==1 and r['format_checks'][0]['status']=='repair_skipped_budget'


def test_do_not_extract_json_from_surrounding_prose():
    from literature_rag.application.specialist_agent import unwrap_json
    text='explanation\n```json\n{}\n```'
    assert unwrap_json(text)==text
    a=Fake([route('sql',sql_task='count'),answer(text),answer(text)])
    r=SpecialistCoordinator(a,lambda *a:1/0,lambda s:None).run('q','r')
    assert r['status']=='failed' and r['format_checks'][1]['repair_attempted']
