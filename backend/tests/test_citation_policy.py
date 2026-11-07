from literature_rag.application.citation_policy import citation_records, invalid_references
from literature_rag.application.agent_loop import AgentLoop, AgentBudget
from literature_rag.adapters.providers.agent_chat import ToolCall, Decision, ChatAgentAdapter


class Fake:
    tool_messages=staticmethod(ChatAgentAdapter.tool_messages)
    def __init__(self, decisions):
        self.decisions=iter(decisions)
        self.requests=[]
    def decide(self,messages,schemas,timeout,max_tokens):
        self.requests.append((list(messages),schemas,timeout))
        return next(self.decisions)


def decision(text='',calls=None):
    return Decision(text,calls or [],dict(role='assistant',content=text),None,'stop')


def test_types_and_failures():
    r=dict(status='completed',result=dict(ref='[1]'))
    assert citation_records('query_experiment_data',r)[0]['kind']=='experiment_query'
    assert citation_records('calculate_change',r)[0]['kind']=='calculation'
    assert citation_records('describe_experiment_data',r)==[]
    assert citation_records('query_experiment_data',dict(r,status='failed'))==[]
    assert invalid_references('text [1] [99] [T15] [1,2]',{'[1]'})==['[1,2]','[99]','[T15]']


def run_case(final,repair,tool='query_experiment_data',status='completed',budget=None):
    adapter=Fake([decision(calls=[ToolCall('call',tool,dict(reason='test',sql='SELECT 1'))]),
        decision('draft [1]'),decision(final),decision(repair)])
    result=AgentLoop(adapter,lambda *a:dict(status=status,result=dict(ref='[1]',rows=[[61]])),
        lambda s:None,budget).run('q','run')
    return result,adapter


def test_unknown_reference_repaired_once_without_tools():
    r,a=run_case('61 rows [3]','61 rows [1]')
    assert r['status']=='completed' and r['answer']=='61 rows [1]'
    assert r['citation_validation']['status']=='repaired'
    assert r['model_calls'][-1]['stage']=='citation_repair'
    assert not a.requests[-1][1]


def test_failed_query_cannot_create_reference():
    r,a=run_case('61 rows [1]','查询失败，无法确认数量。',status='failed')
    assert r['citation_validation']['available_records']==[]
    assert r['answer']=='查询失败，无法确认数量。'


def test_directory_cannot_create_reference():
    r,_=run_case('61 rows [1]','61 rows [1]',tool='describe_experiment_data')
    assert r['status']=='failed' and r['answer']==''
    assert r['citation_validation']['status']=='failed'
    assert r['citation_validation']['attempts'][-1]['answer']=='61 rows [1]'


def test_repair_respects_call_budget():
    r,_=run_case('61 rows [2]','unused',budget=AgentBudget(max_model_calls=3))
    assert r['status']=='failed' and r['answer']==''
    assert len(r['model_calls'])==3


def test_valid_reference_needs_no_extra_call():
    r,_=run_case('61 rows [1]','unused')
    assert r['citation_validation']['status']=='passed'
    assert len(r['model_calls'])==3


def test_withheld_evidence_not_citable():
    adapter=Fake([decision(calls=[ToolCall('call','search_literature',dict(query='q',reason='test'))]),
        decision('answer [1]'),decision('answer [1]'),decision('证据未送达，无法确认。')])
    raw=dict(status='completed',result=dict(evidence=[dict(ref='[1]',text='x'*50000)]))
    r=AgentLoop(adapter,lambda *a:raw,lambda s:None,AgentBudget(max_context_chars=24000)).run('q','run')
    assert r['citation_validation']['available_records']==[]
    assert '[1]' not in r['answer']


def test_website_checks_persisted_ledger():
    from app.agent_answer import adapt_run
    r=adapt_run(dict(status='completed',answer='61 rows [3]',review_status='completed'),[],[],10)
    assert r['status']=='failed' and r['answer']==''
    assert r['reason_code']=='invalid_citations'
    assert r['agent_run']['citation_boundary_failure']['rejected_answer']=='61 rows [3]'
