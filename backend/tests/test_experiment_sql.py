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
    assert normalized.startswith('SELECT') and all(v.startswith('v_') for v in view)

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
    "SELECT 'x'::regclass FROM fiber.v_sample_overview",
    'SELECT * FROM fiber.v_sample_overview LIMIT -1',
    'SELECT * FROM fiber.v_sample_overview UNION SELECT * FROM pg_catalog.pg_authid',
])
def test_reject_queries(query):
    with pytest.raises(ValueError): validate_sql(query)

@pytest.mark.parametrize('query', [
    'SELECT a.sample_id FROM v_sample_overview a JOIN v_data_lineage b ON a.sample_id=b.sample_id',
    'SELECT a.sample_id FROM v_sample_overview a LEFT JOIN v_fiber_paper_analysis b USING(sample_id)',
    'SELECT * FROM v_sample_overview a CROSS JOIN v_sample_overview b',
    'SELECT * FROM v_sample_overview a FULL OUTER JOIN v_data_lineage b ON a.sample_id=b.sample_id',
    'SELECT * FROM v_fiber_paper_analysis WHERE tensile_index > (SELECT AVG(tensile_index) FROM v_fiber_paper_analysis)',
    'SELECT * FROM v_sample_overview s WHERE EXISTS (SELECT 1 FROM v_data_lineage l WHERE l.sample_id=s.sample_id)',
    'SELECT * FROM v_sample_overview WHERE sample_id IN (SELECT sample_id FROM v_data_lineage)',
    'SELECT * FROM (SELECT sample_id FROM v_sample_overview LIMIT 5) q',
    'SELECT (SELECT 1) FROM v_sample_overview',
    'SELECT * FROM v_sample_overview s JOIN LATERAL (SELECT sample_id FROM v_data_lineage l WHERE l.sample_id=s.sample_id LIMIT 1) q ON true',
])
def test_joins_and_subqueries(query):
    normalized, views=validate_sql(query)
    assert views and 'fiber.' in normalized

@pytest.mark.parametrize('query', [
    'SELECT * FROM v_sample_overview WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_authid)',
    'SELECT (SELECT pg_read_file(\'/etc/passwd\')) FROM v_sample_overview',
    'SELECT * FROM (SELECT * FROM public.secret) q JOIN v_sample_overview s ON true',
    'SELECT * FROM v_sample_overview WHERE sample_id IN (SELECT sample_id FROM fiber.sample)',
    'SELECT * FROM v_sample_overview WHERE EXISTS (SELECT * INTO stolen FROM v_data_lineage)',
    'SELECT * FROM (SELECT * FROM v_sample_overview LIMIT -1) q',
    'SELECT * FROM (SELECT * FROM v_sample_overview FOR UPDATE) q',
    'SELECT * FROM v_sample_overview s JOIN LATERAL pg_ls_dir(\'/\') f ON true',
])
def test_nested_rejections(query):
    with pytest.raises(ValueError): validate_sql(query)

def test_all_views_are_recorded():
    _,views=validate_sql('SELECT * FROM v_sample_overview s JOIN v_data_lineage l USING(sample_id) WHERE EXISTS (SELECT 1 FROM v_fiber_paper_analysis f WHERE f.sample_id=s.sample_id)')
    assert views==['v_data_lineage','v_fiber_paper_analysis','v_sample_overview']

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
