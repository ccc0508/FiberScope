"""Result-driven delegation, inherited evidence and one shared budget."""
import json
from copy import deepcopy
import pytest
from tests.test_specialist_agent import Fake, route, tool, answer
from literature_rag.application.specialist_agent import SpecialistCoordinator
from literature_rag.application.agent_loop import AgentLoop, AgentBudget


QUESTION='查询本地记录，结合A判断是否能填孔隙率。'
NEEDS=[dict(role='sql',source_quote='查询本地记录'),
       dict(role='literature',source_quote='结合A判断是否能填孔隙率',paper_quote='A')]


def findings(role,ref,*,next_info=False,unresolved=False):
    need='need_1' if role=='sql' else 'need_2'
    return answer(json.dumps(dict(status='ok',summary='厚度89.1' + ref if role=='sql' else '方法还需真密度'+ref,
        coverage=[dict(requirement_id=need,status='verified',document_id='' if role=='sql' else 'A',
            refs=[ref],finding='真实记录' if role=='sql' else '方法条件')],
        unresolved_items=['本地真密度待核查'] if unresolved else [],
        next_information=[dict(role='sql',requirement_ids=['need_1'],question='本地是否有真密度？',
            reason='原问题判断所需条件',source_refs=[ref])] if next_info else []),ensure_ascii=False))


def ask_sql(**changes):
    args=dict(requirement_ids=['need_1'],source_child_id='r/literature',source_refs=['[2]'],
        task='核查本地是否具备真密度与测量条件',reason='论文方法要求真密度，首次样本查询未核对该字段',
        expected_information='字段存在性、条件及来源，或明确的未取得记录')
    args.update(changes)
    return tool('ask_sql_agent',args)


def initial(*,dependency='sql_to_literature',next_info=True):
    return [route('both',requirements=deepcopy(NEEDS),dependency=dependency),
        tool('query_experiment_data',dict(sql='sample',reason='sample')),findings('sql','[1]'),
        tool('read_section',dict(document_id='A',section_id='methods',reason='conditions')),
        findings('literature','[2]',next_info=next_info)]


def executor(log):
    def execute(req,rid,timeout):
        log.append((req,rid,timeout))
        if req['tool']=='query_experiment_data':
            return dict(status='completed',call_id=req['sql'],result=dict(ref='[1]' if req['sql']=='sample' else '[3]',rows=[[89.1]]))
        return dict(status='completed',call_id='methods',result=dict(sources=[dict(ref='[2]',text='孔隙率需真密度',document_id='A')]))
    return execute


def test_sql_result_and_exact_evidence_guide_initial_literature():
    a=Fake(initial(next_info=False)+[answer('已有厚度89.1[1]，方法需真密度[2]')]);log=[]
    r=SpecialistCoordinator(a,executor(log),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['used']==0
    assert '89.1' in str(a.requests[3][0])
    child=r['children'][1]
    assert len(child['trace']['inherited_tool_calls'])==1
    assert {x['ref'] for x in child['trace']['citation_validation']['available_records']}=={'[1]','[2]'}
    assert r['task_schedule']['dependency']=='sql_to_literature'


def test_disabling_optional_feedback_keeps_initial_dependency_handoff():
    a=Fake(initial()+[answer('保留已有结果和缺口[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[],feedback_enabled=False).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['status']=='disabled'
    assert len(r['children'])==2 and r['children'][1]['trace']['inherited_tool_calls']
    assert not any(m['stage']=='feedback_plan' for m in r['model_calls'])


def test_literature_conditions_trigger_exactly_one_sql_followup():
    a=Fake(initial()+[ask_sql(),tool('query_experiment_data',dict(sql='density',reason='new prerequisite')),
        findings('sql','[3]'),answer('已有记录[1]，文献条件[2]，补查结果[3]')]);log=[]
    r=SpecialistCoordinator(a,executor(log),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and len(r['children'])==3
    assert r['feedback']['used']==1 and r['feedback']['stop_reason']=='max_followups_reached'
    assert [c['phase'] for c in r['children']]==['initial','initial','followup']
    assert all(rid=='r' for _,rid,_ in log)
    assert r['budget_usage']['model']==9 and r['budget_usage']['tools']==3
    assert r['children'][-1]['id']=='r/sql/followup-1'
    assert r['model_calls'][-3]['child_id']=='r/sql/followup-1'
    assert {e['ref'] for e in r['citation_validation']['available_records']}=={'[1]','[2]','[3]'}
    assert 'ask_sql_agent' in a.requests[5][1] and 'ask_literature_agent' in a.requests[5][1]
    assert '[2]' in str(a.requests[6][0]) and '89.1' in str(a.requests[6][0])


def test_sql_can_check_a_literature_prerequisite_without_completing_the_scientific_need():
    payload=json.loads(findings('sql','[3]').text)
    payload['coverage'][0]['requirement_id']='need_2'
    a=Fake(initial()+[ask_sql(requirement_ids=['need_2']),
        tool('query_experiment_data',dict(sql='density',reason='new prerequisite')),
        answer(json.dumps(payload)),answer('本地前提已核实[3]，文献结论仍按原文判断[2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['used']==1
    child=r['children'][-1]
    task=json.loads(child['task'])
    assert task['requirements'][0]['owner_role']=='literature'
    assert task['requirements'][0]['role']=='sql'
    report=child['coverage_report']
    assert report['complete'] and not report['original_requirements_complete']
    assert report['items'][0]['fulfills_original_requirement'] is False
    assert r['task_contract']['requirements'][1]['role']=='literature'


def test_sql_findings_can_trigger_one_literature_followup():
    request=tool('ask_literature_agent',dict(requirement_ids=['need_2'],source_child_id='r/sql',
        source_refs=['[1]'],task='核查论文方法是否适用于这条本地记录',reason='本地记录缺少方法输入',
        expected_information='方法所需条件与适用边界'))
    read=tool('read_section',dict(document_id='A',section_id='limitations',reason='applicability',
        target_requirements=['need_2'],coverage_updates=[],revisit_reason=''))
    a=Fake(initial()+[request,read,findings('literature','[2]'),answer('本地[1]，方法边界[2]')])
    log=[]
    r=SpecialistCoordinator(a,executor(log),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['used']==1
    assert r['children'][-1]['id']=='r/literature/followup-1'
    assert len(log)==3 and log[-1][0]['section_id']=='limitations'


def test_followup_cannot_introduce_a_role_absent_from_the_original_contract():
    from literature_rag.application.task_feedback import FollowupRequest, validate_followup
    req=FollowupRequest.model_validate(ask_sql().calls[0].arguments)
    with pytest.raises(ValueError,match='original task'):
        validate_followup(req,'sql',[dict(requirement_id='need_1',role='literature')],
            [dict(id='r/literature')],{'[2]':{}})


def test_paper_prerequisites_can_precede_initial_sql():
    a=Fake([route('both',requirements=deepcopy(NEEDS),dependency='literature_to_sql'),
        tool('read_section',dict(document_id='A',section_id='methods',reason='requirements')),findings('literature','[2]'),
        tool('query_experiment_data',dict(sql='sample',reason='check prerequisites')),findings('sql','[1]'),answer('结果[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and [c['role'] for c in r['children']]==['literature','sql']
    assert '孔隙率需真密度' in str(a.requests[3][0])


def test_independent_tasks_do_not_receive_unneeded_other_role_context():
    a=Fake(initial(dependency='independent',next_info=False)+[answer('结果[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed'
    assert not r['children'][1]['trace']['inherited_tool_calls']
    assert not json.loads(r['children'][1]['task'])['previous_results']


def test_explicit_no_useful_path_finishes_without_dispatch():
    a=Fake(initial()+[tool('finish_tasks',dict(reason='没有额外可用来源',stop_condition='no_useful_path')),answer('保留缺口[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and len(r['children'])==2
    assert r['feedback']['stop_reason']=='no_useful_path' and r['feedback']['used']==0


@pytest.mark.parametrize('changes',[dict(requirement_ids=['invented']),dict(source_child_id='other-run/sql'),dict(source_refs=['[99]'])])
def test_invalid_dispatch_preserves_initial_findings(changes):
    a=Fake(initial()+[ask_sql(**changes),answer('保留已确认内容[1][2]')]);log=[]
    r=SpecialistCoordinator(a,executor(log),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and len(r['children'])==2 and len(log)==2
    assert r['feedback']['status']=='failed' and r['feedback']['used']==0


def test_multiple_followup_requests_in_one_round_never_execute():
    request=ask_sql();request.calls.append(deepcopy(request.calls[0]))
    a=Fake(initial()+[request,answer('保留已确认内容[1][2]')]);log=[]
    r=SpecialistCoordinator(a,executor(log),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and len(log)==2 and r['feedback']['used']==0


def test_followup_failure_does_not_erase_initial_answer_evidence():
    a=Fake(initial()+[ask_sql(),answer('{broken'),answer('{still broken'),answer('初始结果仍可回答[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['used']==1
    assert r['children'][-1]['status']=='failed' and r['children'][-1]['duration_ms']>=0
    assert {e['ref'] for e in r['citation_validation']['available_records']}=={'[1]','[2]'}


def test_shared_tool_budget_prevents_optional_followup_without_reset():
    a=Fake(initial()+[answer('已有结果[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[],budget=AgentBudget(max_model_calls=20,max_tool_calls=2)).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['stop_reason']=='insufficient_remaining_budget'
    assert r['budget_usage']['tools']==2 and len(r['children'])==2


def seed_event(status='completed',delivery='delivered',error=None):
    result=dict(status=status,result=dict(ref='[1]',rows=[[89.1]]))
    if error:result=dict(status=status,error_code=error)
    return dict(request=dict(tool='query_experiment_data',sql='sample',reason='old'),
        result=result,status=status,model_delivery=dict(status=delivery))


def test_successful_inherited_request_is_reused_and_not_reexecuted():
    a=Fake([tool('query_experiment_data',dict(sql='sample',reason='cosmetic')),answer('89.1[1]')]);log=[]
    r=AgentLoop(a,executor(log),lambda s:None,review_enabled=False).run('q','r',inherited_tool_calls=[seed_event()])
    assert r['status']=='completed' and not log
    assert r['tool_calls'][0]['result']['error_code']=='duplicate_call'
    assert r['tool_attempts']==1 and r['citation_validation']['available_records'][0]['ref']=='[1]'


def test_withheld_prior_result_is_not_inherited_or_used_to_block_retry():
    a=Fake([tool('query_experiment_data',dict(sql='sample',reason='read')),answer('89.1[1]')]);log=[]
    r=AgentLoop(a,executor(log),lambda s:None,review_enabled=False).run('q','r',inherited_tool_calls=[seed_event(delivery='withheld')])
    assert r['status']=='completed' and len(log)==1 and not r['inherited_tool_calls']


def test_transient_retry_limit_survives_child_boundary():
    a=Fake([tool('query_experiment_data',dict(sql='sample',reason='retry')),answer('仍未取得结果')]);log=[]
    events=[seed_event(status='failed',error='ReadTimeout')]*2
    r=AgentLoop(a,executor(log),lambda s:None,review_enabled=False).run('q','r',inherited_tool_calls=events)
    assert r['status']=='completed' and not log
    assert r['tool_calls'][0]['result']['error_code']=='transient_retry_exhausted'


def test_feedback_provider_failure_falls_back_to_initial_material():
    class FailedPlanning(Fake):
        def decide(self,messages,schemas,*args):
            if 'ask_sql_agent' in schemas:raise ConnectionError('temporary')
            return super().decide(messages,schemas,*args)
    a=FailedPlanning(initial()+[answer('已有结果[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['stop_reason']=='ConnectionError'
    assert len(r['children'])==2 and r['answer']=='已有结果[1][2]'


def test_small_global_budget_still_funds_initial_tasks():
    a=Fake(initial(next_info=False)+[answer('已有结果[1][2]')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[],budget=AgentBudget(max_model_calls=15)).run(QUESTION,'r')
    assert r['status']=='completed' and r['budget_usage']['model']==6


def test_no_second_dispatch_even_when_followup_requests_more_work():
    a=Fake(initial()+[ask_sql(),tool('query_experiment_data',dict(sql='density',reason='new prerequisite')),
        findings('sql','[3]',next_info=True),answer('新结果[3]，其余缺口保留')])
    r=SpecialistCoordinator(a,executor([]),lambda s:None,paper_directory=[]).run(QUESTION,'r')
    assert r['status']=='completed' and r['feedback']['used']==1 and len(r['children'])==3
    assert sum(m['stage']=='feedback_plan' for m in r['model_calls'])==1


def test_inherited_evidence_is_bounded_and_omitted_refs_are_not_usable():
    a=Fake([answer('未获得可用证据')]);event=seed_event()
    event['result']['result']['rows']=[['x'*30000]]
    r=AgentLoop(a,executor([]),lambda s:None,review_enabled=False,budget=AgentBudget(max_context_chars=24000)).run(
        'q','r',inherited_tool_calls=[event])
    assert r['status']=='completed' and not r['inherited_tool_calls']
    assert not r['citation_validation']['available_records']
