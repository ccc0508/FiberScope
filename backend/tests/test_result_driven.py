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
    selection = dict(input_id='input_1', need='required field', source_child_id='r/literature', ref='[1]', quote='方法需要真密度。')
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


def test_bad_format_and_invalid_reference_get_one_combined_repair():
    result, _ = run([route('sql', first_budget=dict(collection_rounds=2)), SQL_TOOL,
                     answer('{"summary":"[99]"}'), answer('{"status":"ok","summary":"[3]"}'),
                     tool('finish_tasks',dict(reason='complete',stop_condition='sufficient')), answer('结果[3]')])
    child=result['children'][0]
    assert result['status']=='completed'
    assert child['allocation']['max_model_calls']==4
    assert child['trace']['citation_validation']['status']=='repaired'
    errors=child['trace']['citation_validation']['attempts'][0]['errors']
    assert 'format' in errors and errors['invalid_refs']==['[99]']
    assert [m['stage'] for m in child['trace']['model_calls']].count('result_repair')==1


def test_parallel_roles_overlap_and_keep_their_own_evidence_and_budgets():
    from threading import Barrier
    rendezvous=Barrier(2)
    class Parallel(Fake):
        def decide(self,messages,schemas,timeout,max_tokens):
            if 'route_task' in schemas:
                return route('both',requirements=NEEDS,parallel_start=True,
                             first_budget=dict(collection_rounds=3),second_budget=dict(collection_rounds=3))
            if 'finish_tasks' in schemas:return tool('finish_tasks',dict(reason='done',stop_condition='sufficient'))
            if not schemas:return answer('两项证据[1][3]')
            is_sql='query_experiment_data' in schemas
            if messages[-1]['role']=='tool':
                return findings('[3]','need_2') if is_sql else findings('[1]','need_1',document_id='A')
            rendezvous.wait(timeout=4)
            return SQL_TOOL if is_sql else PAPER_TOOL
    result=ResultDrivenCoordinator(Parallel([]),fake_executor,lambda s:None).run(QUESTION,'parallel')
    assert result['status']=='completed'
    children=result['children']
    assert len(children)==2 and max(c['started_at_ns'] for c in children)<min(c['ended_at_ns'] for c in children)
    assert all(c['allocation']['collection_rounds']==3 and not c['handoff'] for c in children)
    assert {c['child_id'] for c in result['tool_calls']}=={c['id'] for c in children}
    assert result['budget_usage']['model']==7 and result['budget_usage']['tools']==2


def test_invalid_batch_member_does_not_discard_valid_dispatch():
    batch=dispatch('literature',['need_1'])
    batch.calls.extend(dispatch('sql',['nonexistent']).calls)
    result,_=run([route('both',requirements=NEEDS),SQL_TOOL,findings('[3]','need_2'),
                  batch,PAPER_TOOL,findings('[1]','need_1',document_id='A'),
                  tool('finish_tasks',dict(reason='done',stop_condition='sufficient')),answer('结果[1][3]')])
    assert result['status']=='completed'
    assert [c['role'] for c in result['children']]==['sql','literature']
    assert result['feedback']['decisions'][0]['status']=='partial'


def test_continuation_retains_context_and_is_bounded():
    report=answer(json.dumps(dict(status='insufficient_evidence',summary='schema only',
        unresolved_items=['density'],next_information=[dict(role='sql',requirement_ids=['need_1'],
        question='Count density records with query_experiment_data',reason='database count missing')])))
    result,adapter=run([route('sql',first_budget=dict(collection_rounds=1,tool_calls=1)),
        tool('describe_experiment_data',dict(reason='schema')),report,answer('{"approve":true}'),
        SQL_TOOL,findings('[3]','need_1'),tool('finish_tasks',dict(reason='done',stop_condition='sufficient')),
        answer('结果[3]')])
    assert result['status']=='completed'
    assert len(result['children'])==1
    child=result['children'][0]
    assert child['extension']['status']=='approved' and child['extension']['rounds']<=2
    assert len([m for m in result['model_calls'] if m['stage']=='planner_extension'])==1
    assert any(m['role']=='tool' for m in adapter.requests[4][0])


def test_previous_dependency_does_not_block_next_independent_followup_in_batch():
    first=dispatch('sql',['need_2'],inputs=[dict(input_id='input_1',need='actual field',
                   source_child_id='r/literature',ref='[1]',quote='方法需要真密度。')])
    batch=dispatch('sql',['need_2'])
    batch.calls.extend(dispatch('literature',['need_1']).calls)
    result,_=run([route('both',requirements=NEEDS,first_specialist='literature',
                        dependency='literature_to_sql',dependency_checklist=['required property']),
                  PAPER_TOOL,findings('[1]','need_1',document_id='A'),first,SQL_TOOL,findings('[3]','need_2'),
                  batch,SQL_TOOL,findings('[3]','need_2'),answer('结果[1][3]')])
    assert [c['role'] for c in result['children']]==['literature','sql','sql']
    assert result['children'][-1]['handoff']==[]
    assert result['task_schedule']['stops']=='max_specialist_calls'


def test_mistaken_prerequisite_can_be_explicitly_retracted_after_empty_handoff_rejected():
    steps = [
        route('both', requirements=NEEDS, first_specialist='sql',
              dependency='sql_to_literature', dependency_checklist=['sample unit']),
        SQL_TOOL, findings('[3]', 'need_2'),
        dispatch('literature', ['need_1']),
        dispatch('literature', ['need_1'], independence_reason='The named paper and indicator already determine the lookup.'),
        PAPER_TOOL, findings('[1]', 'need_1', document_id='A'),
        tool('finish_tasks', dict(reason='covered', stop_condition='sufficient')),
        answer('文献[1]与本地[3]'),
    ]
    state,_=run(steps)
    assert state['status']=='completed'
    assert state['feedback']['decisions'][0]['rejected_actions']
    assert state['task_schedule']['dependency_corrections'][0]['role']=='literature'
    assert not state['children'][1]['handoff']
