import pytest
from literature_rag.application.tool_retry import ToolRetryPolicy
from tests.test_agent_loop import Fake, decision
from literature_rag.application.agent_loop import AgentLoop, AgentBudget
from literature_rag.adapters.providers.agent_chat import ToolCall


def search(**overrides):
    return dict(tool='search_literature', query='PFI', reason='find', **overrides)


def test_missing_reason_requires_valid_correction():
    p=ToolRetryPolicy();req=search();req.pop('reason')
    p.observe(req,dict(status='invalid_arguments',error_code='invalid_arguments'))
    assert p.block(req)['error_code']=='parameters_not_corrected'
    assert p.block(dict(req,query='changed'))
    assert p.block(dict(req,reason='find')) is None


def test_sql_error_requires_sql_change_not_reason_change():
    p=ToolRetryPolicy();req=dict(tool='query_experiment_data',sql='SELECT missing',reason='find')
    p.observe(req,dict(status='failed',error_code='invalid_query'))
    assert p.block(dict(req,reason='try again'))['error_code']=='parameters_not_corrected'
    assert p.block(dict(req,sql='SELECT corrected')) is None


@pytest.mark.parametrize('code',['tool_timeout','APIConnectionError','ReadTimeout'])
def test_transient_only_one_unchanged_retry(code):
    p=ToolRetryPolicy();req=search();failure=dict(status='failed',error_code=code)
    p.observe(req,failure);assert p.block(req) is None
    p.observe(req,failure);assert p.block(dict(req,reason='again'))['error_code']=='transient_retry_exhausted'


@pytest.mark.parametrize('code',['PermissionError','forbidden','query_plan_rejected','worker_failed','unknown_failure'])
def test_refusals_and_unknown_errors_do_not_retry_unchanged(code):
    p=ToolRetryPolicy();req=search();p.observe(req,dict(status='failed',error_code=code))
    assert p.block(dict(req,reason='new reason'))['error_code']=='non_retryable_failure'


def test_database_timeout_vs_permission():
    req=dict(tool='query_experiment_data',sql='SELECT 1',reason='find')
    for sqlstate,allowed in [('57014',True),('08006',True),('42501',False)]:
        p=ToolRetryPolicy();p.observe(req,dict(status='failed',error_code='database_query_failed',sqlstate=sqlstate))
        assert (p.block(req) is None)==allowed


def test_loop_records_and_blocks_third_transient_attempt():
    calls=[ToolCall(str(i),'read_section',dict(document_id='d',section_id='s',reason='read')) for i in range(3)]
    a=Fake([*(decision(calls=[c]) for c in calls),decision('draft'),decision('final')]);executed=[]
    r=AgentLoop(a,lambda *args:executed.append(args) or dict(status='failed',error_code='tool_timeout'),lambda s:None).run('q','r')
    assert len(executed)==2 and r['tool_attempts']==3
    assert r['tool_calls'][2]['result']['error_code']=='transient_retry_exhausted'
    assert r['tool_calls'][2]['result']['previous_error_code']=='tool_timeout'
