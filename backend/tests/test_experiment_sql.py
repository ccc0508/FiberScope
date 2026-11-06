import pytest
from app.experiment_sql import validate_sql, execute
from literature_rag.application.tools import ToolTraceStore
from app.agent_answer import adapt_run

@pytest.mark.parametrize('query', [
    'SELECT canonical_code, tensile_index FROM fiber.v_fiber_paper_analysis WHERE sample_type=\'softwood\' ORDER BY tensile_index DESC LIMIT 5',
    'SELECT sample_type, COUNT(*), AVG(tensile_index) FROM fiber.v_fiber_paper_analysis GROUP BY sample_type',
    'SELECT * FROM fiber.v_sample_overview WHERE canonical_code IS NOT NULL',
])
def test_allowed_queries(query):
    normalized, view=validate_sql(query)
    assert normalized.startswith('SELECT') and view.startswith('v_')

def test_known_unqualified_view_is_qualified():
    normalized,_=validate_sql('SELECT count(*) FROM v_sample_overview')
    assert 'fiber.v_sample_overview' in normalized

@pytest.mark.parametrize('query', [
    'DELETE FROM fiber.v_sample_overview',
    'SELECT * FROM fiber.v_sample_overview; SELECT 1',
    'SELECT * INTO copied FROM fiber.v_sample_overview',
    'SELECT * FROM pg_catalog.pg_authid',
    'SELECT pg_sleep(10) FROM fiber.v_sample_overview',
    "SELECT pg_read_file('/etc/passwd') FROM fiber.v_sample_overview",
    'SELECT public.myfunc() FROM fiber.v_sample_overview',
    'SELECT * FROM fiber.v_sample_overview FOR UPDATE',
    'WITH x AS (DELETE FROM fiber.sample RETURNING *) SELECT * FROM x',
    'SELECT (SELECT 1) FROM fiber.v_sample_overview',
    'SELECT * FROM fiber.v_sample_overview a JOIN fiber.v_sample_overview b ON true',
    "SELECT 'x'::regclass FROM fiber.v_sample_overview",
    'SELECT * FROM fiber.v_sample_overview LIMIT -1',
    'SELECT * FROM fiber.v_sample_overview UNION SELECT * FROM pg_catalog.pg_authid',
])
def test_reject_queries(query):
    with pytest.raises(ValueError): validate_sql(query)

def test_snapshot_and_display(tmp_path):
    store=ToolTraceStore(tmp_path/'trace.db')
    record=dict(run_id='test',call_id='call',status='completed',input={'tool':'query_experiment_data'},
        result={'view':'fiber.v_sample_overview','sql':'SELECT count(*) FROM fiber.v_sample_overview','rows':[[61]],'columns':['count']})
    store.complete(record)
    evidence=store.evidence('test')
    assert evidence[0]['kind']=='experiment_query'
    result=adapt_run({'status':'completed','answer':'61个样本[1]'},evidence,[],1)
    assert result['citations'][0]['kind']=='experiment_query'
    assert result['citations'][0]['document_id']==''

def test_rejected_query_never_connects(tmp_path,monkeypatch):
    monkeypatch.setattr('app.experiment_sql.connect',lambda:pytest.fail('must not connect'))
    result=execute(dict(tool='query_experiment_data',sql='DELETE FROM fiber.sample',reason='test'),'bad',ToolTraceStore(tmp_path/'t.db'))
    assert result['error_code']=='invalid_query'
