import json

from literature_rag.application.agent_loop import AgentBudget
from literature_rag.application.planner_inputs import DelegateStep, fill_inputs, pack_evidence, source_entries
from literature_rag.application.specialist_agent import ResultDrivenCoordinator
from tests.test_specialist_agent import Fake, answer, route, tool


QUESTION = '查A论文的方法条件，再核对本地样本有哪些所需字段。'
NEEDS = [
    dict(role='literature', source_quote='查A论文的方法条件', paper_quote='A'),
    dict(role='sql', source_quote='核对本地样本有哪些所需字段'),
]
PAPER_TOOL = tool('read_section', dict(document_id='A', section_id='methods', reason='方法'))
SQL_TOOL = tool('query_experiment_data', dict(sql='SELECT density', reason='核对字段'))


def findings(ref, need, *, document_id='', finding='已查核', status='verified'):
    coverage = dict(requirement_id=need, document_id=document_id, refs=[ref], finding=finding, status=status)
    return answer(json.dumps(dict(status='ok', summary=ref, coverage=[coverage]), ensure_ascii=False))


def dispatch(role, ids, **kw):
    return tool(f'ask_{role}_agent', dict(requirement_ids=ids, task='查剩下的要求', reason='补齐证据', **kw))


def fake_executor(req, rid, timeout):
    if req['tool'] == 'read_section':
        return dict(status='completed', result=dict(sources=[
            dict(ref='[1]', document_id='A', text='方法需要真密度。仅供测试的无关段落。'),
            dict(ref='[2]', document_id='A', text='不相关图注'),
        ]))
    return dict(status='completed', result=dict(ref='[3]', columns=['density', 'other'], rows=[[1.2, 99]],
                                                column_metadata=[dict(name='density', unit='g/cm³'), dict(name='other')]))


def run(decisions, **kw):
    adapter = Fake(decisions)
    result = ResultDrivenCoordinator(adapter, fake_executor, lambda s: None, **kw).run(QUESTION, 'r')
    return result, adapter


def test_direct_route_uses_no_specialists():
    result, _ = run([route('direct', answer='你好')])
    assert result['status'] == 'completed'
    assert result['children'] == []


def test_planner_starts_literature_and_selects_only_the_exact_requested_excerpt_for_sql():
    selection = dict(need='方法需要的字段', source_child_id='r/literature', ref='[1]', quote='方法需要真密度。')
    steps = [
        route('both', requirements=NEEDS, first_specialist='literature',
              dependency='literature_to_sql', dependency_checklist=['方法需要的字段']),
        PAPER_TOOL, findings('[1]', 'need_1', document_id='A'),
        dispatch('sql', ['need_2'], inputs=[selection], budget=dict(model_calls=5, tool_calls=2)),
        SQL_TOOL, findings('[3]', 'need_2'),
        tool('finish_tasks', dict(reason='覆盖齐全', stop_condition='sufficient')),
        answer('方法需要真密度[1]，本地查到对应字段[3]'),
    ]
    result, adapter = run(steps)
    assert result['status'] == 'completed'
    assert result['task_schedule']['initial_order'] == ['literature', 'sql']
    sql = result['children'][1]
    assert sql['allocation']['max_model_calls'] == 5
    assert sql['allocation']['max_tool_calls'] == 2
    assert sql['handoff'][0]['ref'] == '[1]'
    first_input = json.dumps(adapter.requests[4][0], ensure_ascii=False)
    assert '方法需要真密度。' in first_input
    assert '无关段落' not in first_input and '不相关图注' not in first_input
    assert 'previous_results' not in first_input
    assert {x['ref'] for x in sql['trace']['citation_validation']['available_records']} == {'[1]', '[3]'}


def test_independent_roles_and_repeat_dispatch_receive_no_implicit_handoff():
    steps = [
        route('both', requirements=NEEDS, first_specialist='sql'),
        SQL_TOOL, findings('[3]', 'need_2'),
        dispatch('literature', ['need_1']),
        PAPER_TOOL, findings('[1]', 'need_1', document_id='A'),
        dispatch('sql', ['need_2']),
        SQL_TOOL, findings('[3]', 'need_2'),
        answer('文献[1]，本地[3]'),
    ]
    result, _ = run(steps)
    assert result['status'] == 'completed'
    assert [c['id'] for c in result['children']] == ['r/sql', 'r/literature', 'r/sql/followup-1']
    assert all(not c['trace']['inherited_tool_calls'] and not c['handoff'] for c in result['children'])
    assert result['task_schedule']['stops'] == 'max_specialist_calls'
    assert sum(c['stage'] == 'planner_step' for c in result['model_calls']) == 2


def test_fabricated_quote_requires_a_new_planner_decision_without_charging_a_dispatch():
    selection = dict(need='字段', source_child_id='r/literature', ref='[1]', quote='方法需要孔隙率。')
    steps = [
        route('both', requirements=NEEDS, first_specialist='literature',
              dependency='literature_to_sql', dependency_checklist=['字段']),
        PAPER_TOOL, findings('[1]', 'need_1', document_id='A'),
        dispatch('sql', ['need_2'], inputs=[selection]),
        dispatch('sql', ['need_2'], missing_inputs=['字段']),
        SQL_TOOL, findings('[3]', 'need_2'),
        tool('finish_tasks', dict(reason='已说明缺口', stop_condition='sufficient')),
        answer('文献[1]，本地[3]'),
    ]
    result, _ = run(steps)
    assert result['status'] == 'completed' and len(result['children']) == 2
    assert result['feedback']['decisions'][0]['status'] == 'rejected'
    assert json.loads(result['children'][1]['task'])['missing_inputs'] == ['字段']


def test_budget_suggestion_is_clamped_and_leaves_room_for_the_other_role():
    steps = [
        route('both', requirements=NEEDS, first_specialist='sql',
              first_budget=dict(model_calls=20, tool_calls=20)),
        SQL_TOOL, findings('[3]', 'need_2'),
        dispatch('literature', ['need_1'], budget=dict(model_calls=20, tool_calls=20)),
        PAPER_TOOL, findings('[1]', 'need_1', document_id='A'),
        tool('finish_tasks', dict(reason='覆盖齐全', stop_condition='sufficient')),
        answer('完成[1][3]'),
    ]
    result, _ = run(steps, budget=AgentBudget(max_model_calls=12, max_tool_calls=4))
    assert result['status'] == 'completed'
    assert result['children'][0]['allocation']['max_model_calls'] == 5
    assert result['children'][0]['allocation']['max_tool_calls'] == 3
    assert result['budget_usage']['model'] <= 12
    assert result['budget_usage']['tools'] <= 4


def test_parent_evidence_is_packed_per_record_and_selection_preserves_sql_units():
    sources = [dict(ref='[1]', document_id='A', text='z'*12000),
               dict(ref='[2]', document_id='A', text='方法需要真密度')]
    events = [
        dict(request=dict(tool='read_section'), model_delivery=dict(status='delivered'),
             result=dict(status='completed', result=dict(sources=sources))),
        dict(request=dict(tool='query_experiment_data'), model_delivery=dict(status='delivered'),
             result=fake_executor(dict(tool='query_experiment_data'), 'r', 1)),
    ]
    children = [dict(id='r/sql', trace=dict(tool_calls=events))]
    entries = source_entries(children)
    evidence, refs, offered = pack_evidence(children, entries, 5000)
    assert {r for r in refs} == {'[2]', '[3]'}
    assert '方法需要真密度' in json.dumps(evidence, ensure_ascii=False)
    step = DelegateStep.model_validate(dict(requirement_ids=['need_1'], task='核对', reason='依赖',
        inputs=[dict(need='密度', source_child_id='r/sql', ref='[3]', columns=['density'], row_indices=[0])]))
    selected, _ = fill_inputs(step, entries, offered, 3000)
    data = selected[0]['result']['result']
    assert data['rows'] == [[1.2]] and data['columns'] == ['density']
    assert data['column_metadata'] == [dict(name='density', unit='g/cm³')]
