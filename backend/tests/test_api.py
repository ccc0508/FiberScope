"""Real PostgreSQL integration tests against an explicitly selected test environment.

TEST_DB_ENV must point to the ignored app.env created by restore_drill.py.
No import, migration, or write to business data is performed by these tests.
"""
import os
from pathlib import Path

import psycopg
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError
from psycopg import sql
from psycopg.rows import dict_row

from app.catalog import VIEWS
from app.main import Params, Settings, build_query, create_app


@pytest.fixture(scope='module')
def settings():
    path = os.environ.get('TEST_DB_ENV')
    if not path:
        pytest.skip('Set TEST_DB_ENV to a restore-drill app.env for integration tests')
    assert Path(path).is_file()
    return Settings(_env_file=path)


@pytest.fixture(scope='module')
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


@pytest.fixture
def database(settings):
    with psycopg.connect(host=settings.pghost, port=settings.pgport, dbname=settings.pgdatabase,
                         user=settings.pguser, password=settings.pgpassword, row_factory=dict_row) as conn:
        yield conn


def test_query_input_remains_a_parameter():
    payload = "x'; DROP TABLE fiber.sample; --"
    _, query, values = build_query('samples', Params(q=payload))
    assert payload not in query.as_string()
    assert values == [f'%{payload}%', f'%{payload}%']


def test_rejects_admin_application_account():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pguser='postgres')


@pytest.mark.parametrize('endpoint', VIEWS)
def test_all_views_match_real_database(client, database, endpoint):
    spec = VIEWS[endpoint]
    response = client.get('/api/v1/'+endpoint, params={'page_size':500})
    assert response.status_code == 200, response.text
    body = response.json()
    expected = database.execute(sql.SQL('SELECT * FROM {} ORDER BY {}').format(
        sql.Identifier('fiber',spec.view), sql.SQL(', ').join(map(sql.Identifier,spec.order)))).fetchall()
    assert body['data'] == jsonable_encoder(expected)
    assert body['pagination']['total'] == spec.expected
    assert body['pagination']['total_pages'] == 1
    assert body['meta']['view'] == 'fiber.'+spec.view
    assert len(response.headers['X-Request-ID']) == 32


def test_health_and_metadata(client):
    response = client.get('/api/v1/health')
    assert response.status_code == 200
    assert response.json()['database'] == 'connected'
    assert response.json()['checked_at'].endswith('+00:00')
    response = client.get('/api/v1/metadata')
    assert response.status_code == 200
    metadata = response.json()
    assert metadata['counts']['samples'] == 61
    assert metadata['counts']['sources'] == 178
    assert metadata['counts']['quality'] == 4
    indicators = metadata['indicators']
    assert len([i for i in indicators if 'core' in i['scope']]) == 21
    assert len([i for i in indicators if 'recycled' in i['scope']]) == 25
    by_key = {i['key']:i for i in indicators}
    assert by_key['air_permeability']['unit_status'] == 'tentative'
    assert by_key['folding_endurance_raw']['unit'] is None
    assert by_key['folding_endurance_raw']['unit_status'] == 'unconfirmed'
    assert len(metadata['blocks']) == 14
    assert all(b['condition_label'] is None and b['metadata_status']=='unknown' for b in metadata['blocks'])
    assert next(b for b in metadata['blocks'] if b['block_code']=='G11')['raw_material_grade'] == '美废13#'
    assert 'canonical_code' in metadata['views']['samples']['columns']


def test_pagination_is_complete_and_stable(client):
    a = client.get('/api/v1/samples',params={'page_size':50}).json()
    b = client.get('/api/v1/samples',params={'page_size':50,'page':2}).json()
    all_rows = client.get('/api/v1/samples',params={'page_size':500}).json()['data']
    assert len(a['data']) == 50 and len(b['data']) == 11
    assert a['data']+b['data'] == all_rows
    assert a['pagination']['total_pages'] == 2
    empty = client.get('/api/v1/samples',params={'page':100}).json()
    assert empty['data'] == [] and empty['pagination']['total'] == 61


def test_filters_and_literal_search(client):
    for kind, expected in [('softwood',28),('hardwood',24),('blend',9)]:
        result = client.get('/api/v1/samples',params={'sample_type':kind}).json()
        assert result['pagination']['total'] == expected
        assert all(r['sample_type']==kind for r in result['data'])
    result = client.get('/api/v1/samples',params={'q':'sw_r14000'}).json()
    assert [r['canonical_code'] for r in result['data']] == ['SW_R14000']
    percent = client.get('/api/v1/samples',params={'q':'%'}).json()
    assert percent['pagination']['total'] == 9
    assert all('%' in r['display_name'] for r in percent['data'])
    for term in ["'; DROP TABLE fiber.sample; --",'没有这个样本']:
        response = client.get('/api/v1/samples',params={'q':term})
        assert response.status_code == 200
        assert response.json()['data'] == []
    response = client.get('/api/v1/beating',params={'material_code':'SW','min_revolutions':14000,'max_revolutions':14000})
    assert response.status_code == 200
    assert response.json()['data'][0]['canonical_code'] == 'SW_R14000'
    assert len(response.json()['data']) == 1
    result = client.get('/api/v1/recycled/cycles',params=[('block_code','G01'),('block_code','G11'),('cycle_no',1)]).json()
    assert {r['block_code'] for r in result['data']} == {'G01','G11'}
    assert all(r['cycle_no']==1 for r in result['data'])


def test_lineage_and_endpoint_reuse(client):
    rows = client.get('/api/v1/blends').json()['data']
    by_code = {r['display_code']:r for r in rows}
    assert by_code['zk010']['canonical_code'] == 'HW_R08000'
    assert by_code['zk100']['canonical_code'] == 'SW_R14000'
    assert all(r['sw_proportion_pct']+r['hw_proportion_pct']==100 for r in rows)
    result = client.get('/api/v1/lineage',params={'canonical_code':'SW_R14000','usage_type':'paper_measurement'}).json()
    assert result['pagination']['total'] == 1
    assert result['data'][0]['source_row'] > 0
    name = result['data'][0]['file_name']
    result = client.get('/api/v1/lineage',params={'file_name':name,'page_size':500}).json()
    assert all(r['file_name']==name for r in result['data'])


def test_nulls_and_quality_are_preserved(client):
    samples = client.get('/api/v1/samples',params={'canonical_code':'SW_R14000'}).json()['data']
    assert samples[0]['hw_beating_revolutions'] is None
    rows = client.get('/api/v1/quality').json()['data']
    assert [r['source_row'] for r in rows] == [5,6,13,60]
    assert rows[1]['length_distribution_sum_pct'] == 107.8
    assert rows[1]['deviation_from_100_pct'] == 7.8


@pytest.mark.parametrize('path,params',[
    ('samples',{'page':0}),('samples',{'page_size':501}),('samples',{'page':'abc'}),
    ('samples',{'sort':'canonical_code; DROP TABLE sample'}),('samples',{'sample_type':'other'}),
    ('samples',{'q':'x'*101}),('samples',{'material_code':'SW'}),('blends',{'sample_type':'blend'}),
    ('beating',{'min_revolutions':20,'max_revolutions':10}),('beating',{'material_code':'XX'}),
    ('recycled/cycles',{'block_code':'G99'}),('recycled/details',{'cycle_no':0}),
    ('lineage',{'usage_type':'made_up'}),
])
def test_invalid_queries_have_consistent_errors(client,path,params):
    response = client.get('/api/v1/'+path,params=params)
    assert response.status_code == 422, response.text
    error = response.json()['error']
    assert error['code'] == 'INVALID_QUERY'
    assert error['request_id'] == response.headers['X-Request-ID']


def test_app_cannot_read_base_tables_or_write(database):
    assert database.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only'] == 'on'
    assert database.execute("SELECT has_table_privilege(current_user, 'fiber.sample', 'SELECT') AS ok").fetchone()['ok'] is False
    assert database.execute("SELECT has_table_privilege(current_user, 'fiber.v_sample_overview', 'SELECT') AS ok").fetchone()['ok'] is True
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with database.transaction():
            database.execute('SELECT * FROM fiber.sample LIMIT 1')
    # Privilege lookup proves write denial without attempting a business-data mutation.
    for spec in VIEWS.values():
        assert database.execute('SELECT has_table_privilege(current_user,%s,%s) AS ok',
            ('fiber.'+spec.view,'INSERT,UPDATE,DELETE,TRUNCATE')).fetchone()['ok'] is False


def test_cors_and_methods(client):
    response = client.get('/api/v1/health',headers={'Origin':'http://localhost:5173'})
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    response = client.get('/api/v1/health',headers={'Origin':'https://untrusted.example'})
    assert 'access-control-allow-origin' not in response.headers
    response = client.post('/api/v1/samples',json={})
    assert response.status_code == 405
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']
    assert client.get('/api/v1/missing').status_code == 404


def test_database_outage_does_not_leak_credentials():
    config = Settings(_env_file=None,pghost='127.0.0.1',pgport=1,pgpassword='test-secret-not-real')
    with TestClient(create_app(config)) as client:
        response = client.get('/api/v1/health')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DATABASE_UNAVAILABLE'
    assert 'test-secret-not-real' not in response.text
    assert '127.0.0.1' not in response.text


def test_unexpected_error_has_request_id(settings):
    app = create_app(settings)

    @app.get('/test-only-error')
    def crash():
        raise RuntimeError('private implementation detail')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test-only-error')
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'INTERNAL_ERROR'
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']
    assert 'private implementation detail' not in response.text
