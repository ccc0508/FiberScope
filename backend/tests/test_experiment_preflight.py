import pytest
from app.experiment_preflight import preflight, QueryPlanRejected
from app.experiment_sql import execute, validate_sql
from app.experiment_errors import execution_diagnostic
from literature_rag.application.tools import ToolTraceStore


class PlanDB:
    def __init__(self,plan):self.plan=plan;self.commands=[]
    def execute(self,sql):self.commands.append(sql);return self
    def fetchone(self):return ([{'Plan':self.plan}],)


def test_sequential_scan_is_allowed_and_raw_plan_not_exposed():
    db=PlanDB({'Node Type':'Seq Scan','Total Cost':10,'Plan Rows':131,'Relation Name':'internal_name'})
    r=preflight(db,'SELECT 1')
    assert r['status']=='passed' and r['max_node_rows']==131
    assert db.commands==['EXPLAIN (FORMAT JSON) SELECT 1']
    assert 'internal_name' not in str(r)


def test_small_aggregate_does_not_hide_huge_intermediate():
    db=PlanDB({'Node Type':'Aggregate','Total Cost':10,'Plan Rows':1,
        'Plans':[{'Node Type':'Nested Loop','Plan Rows':2_000_000}]})
    with pytest.raises(QueryPlanRejected):preflight(db,'SELECT 1')


def test_large_cost_rejected():
    db=PlanDB({'Node Type':'Sort','Total Cost':2_000_000,'Plan Rows':1})
    with pytest.raises(QueryPlanRejected):preflight(db,'SELECT 1')


def test_preflight_rejection_never_executes_select(tmp_path,monkeypatch):
    class DB(PlanDB):
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def cursor(self,*args,**kwargs):pytest.fail('SELECT must not execute')
    db=DB({'Node Type':'Nested Loop','Total Cost':2_000_000,'Plan Rows':1})
    monkeypatch.setattr('app.experiment_sql.connect',lambda:db)
    store=ToolTraceStore(tmp_path/'trace.db')
    r=execute(dict(tool='query_experiment_data',sql='SELECT * FROM v_sample_overview',reason='test'),'run',store)
    assert r['error_code']=='query_plan_rejected' and r['failure_stage']=='explain'
    assert not store.evidence('run')


def test_unsupported_feedback_names_node_without_connection(tmp_path,monkeypatch):
    monkeypatch.setattr('app.experiment_sql.connect',lambda:pytest.fail('no DB needed'))
    r=execute(dict(tool='query_experiment_data',sql='SELECT CASE WHEN sample_id=1 THEN 1 ELSE 0 END FROM v_sample_overview',reason='test'),
        'run',ToolTraceStore(tmp_path/'trace.db'))
    assert r['error_code']=='unsupported_sql'
    assert 'case' in r['diagnostic']['unsupported_nodes']
    assert r['failure_stage']=='validation'


@pytest.mark.parametrize('state,code',[('22012','division_by_zero'),('42883','operator_or_function_mismatch'),
    ('42803','grouping_error'),('57014','query_timeout_or_cancelled'),('21000','scalar_subquery_multiple_rows')])
def test_safe_error_categories(state,code):
    assert execution_diagnostic(state)['error_code']==code


def test_round_avg_unit_after_real_sql_normalization():
    from app.experiment_result_metadata import output_metadata
    query,_=validate_sql('SELECT ROUND(AVG(tensile_index),2) AS mean FROM v_fiber_paper_analysis')
    metadata=output_metadata(query,['mean'],[('v_fiber_paper_analysis','tensile_index','numeric')])
    assert metadata[0]['unit']=='N·m/g'
    assert metadata[0]['unit_status']=='confirmed'
