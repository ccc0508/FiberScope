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
    def execute(*args):executed.append(args);return dict(status='completed',call_id='c',result=dict(ref='[1]'))
    result=AgentLoop(a,execute,lambda s:states.append(s['status'])).run('q','r')
    assert result['answer']=='reviewed [1]' and result['review_status']=='completed'
    assert len(executed)==1 and len(a.requests)==3
    assert not a.requests[-1][1]

def test_duplicate_and_batch_limit():
    calls=[ToolCall(str(i),'search_literature',dict(query='q',reason=str(i))) for i in range(4)]
    a=Fake([decision(calls=calls),decision('draft'),decision('final')]);executed=[]
    def execute(*args):executed.append(args);return dict(status='completed')
    r=AgentLoop(a,execute,lambda s:None,AgentBudget(max_tool_calls=2)).run('q','r')
    assert len(executed)==1 and r['tool_attempts']==2
    assert len([m for m in a.requests[1][0] if m['role']=='tool'])==4

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
    d=adapter.decide([],{},10,1000)
    assert d.calls[0].arguments=={'chunk_id':'x'} and d.message['reasoning_content']=='continuation'
    assert captured['timeout']==10
