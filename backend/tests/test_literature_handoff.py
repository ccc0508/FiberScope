from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from literature_rag.application.literature_handoff import section_handoff
from tests.test_agent_loop import Fake, decision


def test_followup_gets_scoped_handles_and_reuses_directory_without_execution():
    def page(doc,need):
        return dict(request=dict(tool='list_sections',document_id=doc,reason='directory'),
                    model_delivery=dict(status='delivered'),coverage_schedule=dict(target_requirements=[need]),
                    result=dict(status='completed',result=dict(sections=[dict(section_id='methods',title='Methods')])))
    pages,hints=section_handoff([dict(role='literature',trace=dict(tool_calls=[page('A','n1'),page('B','n2')]))],
                                [dict(requirement_id='n1')],'methods')
    assert [(h['document_id'],h['section_id']) for h in hints]==[('A','methods')]
    def request(i,doc,**args):
        return ToolCall(str(i),'list_sections',dict(document_id=doc,reason='directory',**args))
    calls=[request(1,'A'),request(2,'C',independent_in_turn=True),request(3,'D')]
    adapter=Fake([decision(calls=calls),decision('done')])
    executed=[]
    def execute(req,*args):
        executed.append(req['document_id'])
        return dict(status='completed',result=dict(sections=[]))
    state=AgentLoop(adapter,execute,lambda _:None,AgentBudget(),literature_batches=True,
                    directory_pages=pages,review_enabled=False).run('read','r')
    assert executed==['C']
    assert state['tool_calls'][0]['reused_directory']
    assert state['tool_calls'][2]['result']['error_code']=='literature_dependency_requires_next_turn'
