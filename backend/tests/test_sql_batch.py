import pytest

from app.experiment_sql import validate_sql
from literature_rag.adapters.providers.agent_chat import ToolCall
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from tests.test_agent_loop import Fake, decision


def select(call_id, sql, **options):
    return ToolCall(call_id,'query_experiment_data',dict(sql=sql, reason='count', **options))


def run_batch(calls, budget=4):
    adapter=Fake([decision(calls=calls),decision('done')])
    executed=[]
    def execute(request,*_):
        assert 'independent_in_turn' not in request
        executed.append(request['tool'])
        if 'sql' in request:
            try:validate_sql(request['sql'])
            except ValueError:return dict(status='failed',error_code='invalid_query')
        return dict(status='completed')
    state=AgentLoop(adapter,execute,lambda _:None,AgentBudget(max_tool_calls=budget),
                    sql_batches=True,review_enabled=False).run('count','test')
    assert state['status']=='completed'
    replies=[message for message in adapter.requests[-1][0] if message['role']=='tool']
    assert [message['tool_call_id'] for message in replies]==[call.id for call in calls]
    return executed,state


BLOCKS='SELECT COUNT(DISTINCT block_code) FROM fiber.v_recycled_cycle_detail'
COMBINATIONS="SELECT COUNT(DISTINCT block_code || '-' || cycle_no) FROM fiber.v_recycled_cycle_detail"


def test_independent_queries_execute_in_order_even_if_one_fails_validation():
    executed,state=run_batch([select('first',BLOCKS),select('invalid','SELECT',independent_in_turn=True),
                              select('last',COMBINATIONS,independent_in_turn=True)])
    assert len(executed)==state['tool_attempts']==3
    assert [event['status'] for event in state['tool_calls']]==['completed','failed','completed']


@pytest.mark.parametrize('calls,budget,reason',[
    ([select('1',BLOCKS),select('2',COMBINATIONS)],3,'sql_dependency_requires_next_turn'),
    ([select('1',BLOCKS),select('2',COMBINATIONS,independent_in_turn=True)],1,'tool_budget'),
    ([select('1',BLOCKS),select('2',BLOCKS,independent_in_turn=True)],3,'duplicate_call'),
    ([ToolCall('1','describe_experiment_data',dict(reason='get columns')),
      select('2',COMBINATIONS,independent_in_turn=True)],3,'one_tool_per_turn'),
])
def test_sql_batch_respects_dependency_budget_dedup_and_mixed_tools(calls,budget,reason):
    executed,state=run_batch(calls,budget)
    assert len(executed)==1
    assert state['tool_calls'][1]['result']['error_code']==reason


def test_concatenation_preserves_operand_validation_and_single_select_rule():
    normalized,_=validate_sql(COMBINATIONS)
    assert '||' in normalized
    with pytest.raises(ValueError):
        validate_sql("SELECT block_code || upper(block_code) FROM fiber.v_recycled_cycle_detail")
    with pytest.raises(ValueError):
        validate_sql(COMBINATIONS+'; '+BLOCKS)
