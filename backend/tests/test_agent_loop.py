from types import SimpleNamespace
from literature_rag.application.agent_loop import AgentLoop,AgentBudget
from literature_rag.adapters.providers.agent_chat import Decision,ToolCall,ChatAgentAdapter

class Fake:
    tool_messages=staticmethod(ChatAgentAdapter.tool_messages)
    def __init__(self,decisions):self.decisions=iter(decisions);self.requests=[]
    def decide(self,messages,schemas,timeout,max_tokens):
        self.requests.append((list(messages),schemas,timeout))
        return next(self.decisions)

def decision(text='',calls=None):
    return Decision(text,calls or [],dict(role='assistant',content=text),None,'stop')

def test_native_tool_then_draft_review():
    call=ToolCall('a','search_literature',dict(query='q',reason='find'))
    a=Fake([decision(calls=[call]),decision('draft [1]'),decision('reviewed [1]')]);executed=[];states=[]
    def execute(*args):executed.append(args);return dict(status='completed',call_id='c',result=dict(evidence=[dict(ref='[1]',text='source')]))
    result=AgentLoop(a,execute,lambda s:states.append(s['status'])).run('q','r')
    assert result['answer']=='reviewed [1]' and result['review_status']=='completed'
    assert len(executed)==1 and len(a.requests)==3
    assert not a.requests[-1][1]


def test_directory_provided_without_tool_call():
    directory=[dict(document_id='doc_123',filename='paper.pdf',title='Paper')]
    a=Fake([decision('draft'),decision('final')]);executed=[]
    r=AgentLoop(a,lambda *args:executed.append(args),lambda s:None,paper_directory=directory).run('q','r')
    assert not executed and r['paper_directory']==directory
    assert 'doc_123' in a.requests[0][0][0]['content']
    assert 'find_documents' not in a.requests[0][1]
    assert 'search_literature' in a.requests[0][1]


def test_directory_redundant_call_not_executed():
    a=Fake([decision(calls=[ToolCall('a','find_documents',dict(reason='list'))]),decision('draft'),decision('final')])
    r=AgentLoop(a,lambda *args:(_ for _ in ()).throw(AssertionError()),lambda s:None,paper_directory=[]).run('q','r')
    assert r['tool_calls'][0]['result']['error_code']=='directory_already_provided'

def test_duplicate_and_batch_limit():
    calls=[ToolCall(str(i),'search_literature',dict(query='q',reason=str(i))) for i in range(4)]
    a=Fake([decision(calls=calls),decision('draft'),decision('final')]);executed=[]
    def execute(*args):executed.append(args);return dict(status='completed')
    r=AgentLoop(a,execute,lambda s:None,AgentBudget(max_tool_calls=2)).run('q','r')
    assert len(executed)==1 and r['tool_attempts']==1
    assert len([m for m in a.requests[1][0] if m['role']=='tool'])==4
    assert [e['result'].get('error_code') for e in r['tool_calls'][1:]]==['one_tool_per_turn']*3


def test_duplicate_in_later_turn_is_still_blocked():
    call=ToolCall('a','search_literature',dict(query='q',reason='find'))
    again=ToolCall('b','search_literature',dict(query='q',reason='other reason'))
    a=Fake([decision(calls=[call]),decision(calls=[again]),decision('draft'),decision('final')])
    executed=[]
    r=AgentLoop(a,lambda *args:executed.append(args) or dict(status='completed'),lambda s:None).run('q','r')
    assert len(executed)==1 and r['tool_attempts']==2
    assert r['tool_calls'][1]['result']['error_code']=='duplicate_call'


def test_oversized_tool_result_is_saved_but_not_sent_and_finalizes():
    call=ToolCall('a','search_literature',dict(query='q',reason='find'))
    raw=dict(status='completed',call_id='stored',result=dict(evidence=[dict(ref='[1]',document_id='d',text='x'*50000)]))
    a=Fake([decision(calls=[call]),decision('Evidence unavailable; cannot conclude.'),decision('Evidence unavailable; cannot conclude.')])
    # Leave room for the real system/tool policy; the 50k payload still exceeds collection capacity.
    r=AgentLoop(a,lambda *args:raw,lambda s:None,AgentBudget(max_context_chars=24000)).run('q','r')
    assert r['status']=='completed' and r['stop_reason']=='context_budget'
    assert r['tool_calls'][0]['result']==raw
    assert r['tool_calls'][0]['model_delivery']['status']=='withheld'
    assert not a.requests[1][1]  # Forced final answer, not another tool decision.
    assert 'x'*100 not in str(a.requests[1][0])


def test_large_draft_survives_when_review_cannot_fit():
    a=Fake([decision('d'*15000)])
    r=AgentLoop(a,lambda *args:None,lambda s:None,AgentBudget(max_context_chars=12000)).run('q','r')
    assert r['answer']=='d'*15000 and r['status']=='partial'
    assert r['review_status']=='skipped_context_budget' and len(a.requests)==1

def test_failed_review_retains_draft():
    a=Fake([decision('draft'),Decision('cut',[],dict(role='assistant',content='cut'),None,'length')])
    r=AgentLoop(a,lambda *a:None,lambda s:None).run('q','r')
    assert r['status']=='partial' and r['answer']=='draft'

def test_expired_deadline_never_executes_tool():
    times=iter([0,300,300])
    r=AgentLoop(Fake([]),lambda *a:(_ for _ in ()).throw(AssertionError()),lambda s:None,clock=lambda:next(times)).run('q','r')
    assert r['status']=='failed'

def test_adapter_conversion_and_no_retry_options():
    captured={}
    message=SimpleNamespace(content=None,reasoning_content='continuation',tool_calls=[SimpleNamespace(
        id='tc',function=SimpleNamespace(name='read_table',arguments='{"chunk_id":"x"}'),
        model_dump=lambda **k:dict(id='tc',type='function',function=dict(name='read_table',arguments='{}')))])
    def create(**kwargs):captured.update(kwargs);return SimpleNamespace(choices=[SimpleNamespace(message=message,finish_reason='tool_calls')],usage=None)
    settings=SimpleNamespace(llm_provider='deepseek',llm_model='deepseek-flash',llm_thinking_enabled=True,llm_reasoning_effort='high')
    adapter=ChatAgentAdapter(settings,SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    from literature_rag.application.tools import SCHEMAS
    d=adapter.decide([],SCHEMAS,10,1000)
    assert d.calls[0].arguments=={'chunk_id':'x'} and d.message['reasoning_content']=='continuation'
    assert captured['timeout']==10
    assert captured['parallel_tool_calls'] is False


def test_search_cap_blocks_third_but_allows_reading():
    calls=[ToolCall(str(i),'search_literature',dict(query=str(i),reason='gap')) for i in range(3)]
    read=ToolCall('read','read_section',dict(document_id='d',section_id='s',reason='read known section'))
    a=Fake([decision(calls=[c]) for c in calls]+[decision(calls=[read]),decision('draft'),decision('review')])
    executed=[]
    r=AgentLoop(a,lambda request,*args:executed.append(request) or dict(status='completed'),lambda s:None,AgentBudget(max_model_calls=8)).run('q','r')
    assert [c['tool'] for c in executed]==['search_literature','search_literature','read_section']
    assert r['search_calls']==2 and r['status']=='completed'
    assert r['tool_calls'][2]['result']['error_code']=='search_budget'
    assert 'search_literature' in a.requests[1][1]
    assert 'search_literature' not in a.requests[2][1]
    assert 'read_section' in a.requests[2][1]


def test_failed_search_consumes_search_budget():
    calls=[ToolCall(str(i),'search_literature',dict(query=str(i),reason='gap')) for i in range(3)]
    a=Fake([decision(calls=[c]) for c in calls]+[decision('draft'),decision('review')])
    executed=[]
    r=AgentLoop(a,lambda request,*args:executed.append(request) or dict(status='failed',error_code='worker_failed'),lambda s:None,AgentBudget(max_model_calls=8)).run('q','r')
    assert len(executed)==2 and r['search_calls']==2
    assert r['tool_calls'][2]['result']['error_code']=='search_budget'
