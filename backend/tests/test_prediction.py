"""Prediction contract and numerical regression against delivered CSV fixtures. No DB needed."""
import csv
from fastapi.testclient import TestClient
import pytest

from app.main import Settings, create_app
from app.prediction import FIBER_NAMES, MODEL_DIR, get_engine


@pytest.fixture(scope='module')
def client():
    # Do not start the database lifespan: the real prediction routes must work without it.
    return TestClient(create_app(Settings(_env_file=None)))


def rows(name):
    with (MODEL_DIR / name).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def example(species='softwood'):
    return dict(get_engine().examples[species])


def test_metadata_is_independent_of_database(client):
    response = client.get('/api/v1/prediction/metadata')
    assert response.status_code == 200
    assert response.headers['X-Request-ID']
    data = response.json()
    assert [s['sample_count'] for s in data['species']] == [28, 24]
    assert len(data['model_version']) == 16
    for model in data['species']:
        assert len(model['features']) == 12
        assert set(model['example']['features']) == {f['key'] for f in model['features']}
    assert any('整链' in note for note in data['notes'])


@pytest.mark.parametrize('source,expected', list(zip(rows('demo_input.csv'), rows('demo_output.csv'))))
def test_fiber_predictions_match_delivered_demo(client, source, expected):
    features = {key: float(source[name]) for name, key in FIBER_NAMES.items()}
    response = client.post('/api/v1/prediction/fiber', json={'species': source['species'], 'features': features})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['paper']) == 9 and data['fiber'] == []
    for item in data['paper']:
        assert item['value'] == pytest.approx(float(expected[item['name']]), rel=1e-10)
        if not item['model_reliable']:
            assert item['reference_only']
    assert data['input']['features'] == features


@pytest.mark.parametrize('source,expected', list(zip(rows('demo_chain_input.csv'), rows('demo_chain_output.csv'))))
def test_chain_predictions_match_delivered_demo_without_claiming_chain_accuracy(client, source, expected):
    response = client.post('/api/v1/prediction/degree', json={'species': source['species'], 'degree': float(source['degree'])})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['paper']) == 9 and len(data['fiber']) == 12
    for item in data['paper']:
        assert item['value'] == pytest.approx(float(expected['预测_' + item['name']]), abs=0.000051)
        assert item['reference_only']
    for item in data['fiber']:
        name = next(name for name, key in FIBER_NAMES.items() if key == item['key'])
        assert item['value'] == pytest.approx(float(expected['纤维_' + name]), abs=0.000051)
    assert any(item['unreliable_inputs'] for item in data['paper'])
    assert any('未经独立验证' in warning for warning in data['warnings'])


@pytest.mark.parametrize('species,canonical', [(0, 'softwood'), (1, 'hardwood'), ('0', 'softwood'),
                                             ('1.0', 'hardwood'), (' 针叶木 ', 'softwood'), ('阔叶木', 'hardwood')])
def test_species_aliases_work_in_both_routes(client, species, canonical):
    for endpoint, payload in [('degree', {'degree': 50}), ('fiber', {'features': example(canonical)})]:
        response = client.post('/api/v1/prediction/' + endpoint, json={'species': species, **payload})
        assert response.status_code == 200
        assert response.json()['species'] == canonical


@pytest.mark.parametrize('body', [
    {'species': 'blend', 'degree': 50}, {'species': True, 'degree': 50},
    {'species': 'softwood', 'degree': 0}, {'species': 'softwood', 'degree': -1},
    {'species': 'softwood', 'degree': 101}, {'species': 'softwood', 'degree': True},
    {'species': 'softwood', 'degree': '50'}, {'species': 'softwood'},
    {'species': 'softwood', 'degree': 50, 'unexpected': 1},
])
def test_invalid_degree_inputs_return_safe_422(client, body):
    response = client.post('/api/v1/prediction/degree', json=body)
    assert response.status_code == 422
    assert response.json()['error']['request_id']


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_inputs_are_rejected(client, literal):
    response = client.post('/api/v1/prediction/degree', content='{"species":"softwood","degree":' + literal + '}',
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 422


def test_missing_and_unknown_features_report_useful_errors(client):
    response = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': {}})
    assert response.status_code == 422
    assert '必需指标' in response.json()['error']['message']
    response = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': {'typo': 1}})
    assert response.status_code == 422
    assert '无法识别' in response.json()['error']['message']


@pytest.mark.parametrize('value', [None, True, -1, 'invalid'])
def test_bad_feature_values_are_rejected(client, value):
    values = example()
    values['fiber_length_arithmetic_mm'] = value
    assert client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': values}).status_code == 422


def test_only_model_required_features_are_needed(client):
    required = get_engine().required_features('softwood')
    values = {key: value for key, value in example().items() if key in required}
    response = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': values})
    assert response.status_code == 200


def test_percentage_units_are_checked(client):
    values = example()
    values['fines_length_pct'] = 101
    response = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': values})
    assert response.status_code == 422
    assert '物理范围' in response.json()['error']['message']


def test_direct_extrapolation_downgrades_affected_paper_results(client):
    values = example()
    values['fiber_length_arithmetic_mm'] = 2
    data = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': values}).json()
    assert any('训练范围' in warning for warning in data['warnings'])
    affected = [item for item in data['paper'] if not item['in_range']]
    assert affected and all(item['reference_only'] and item['notes'] for item in affected)


def test_chain_checks_both_stage_ranges(client):
    data = client.post('/api/v1/prediction/degree', json={'species': 'softwood', 'degree': 95}).json()
    assert any('打浆度' in warning and '外推' in warning for warning in data['warnings'])
    assert any('纤维指标超出' in warning for warning in data['warnings'])
    assert all(not item['in_range'] and item['reference_only'] for item in data['paper'])
    assert all(not item['in_range'] for item in data['fiber'])


def test_unconfirmed_units_are_not_silently_confirmed(client):
    data = client.post('/api/v1/prediction/degree', json={'species': 'softwood', 'degree': 50}).json()
    results = {item['key']: item for item in data['paper']}
    assert results['folding_endurance_raw']['unit'] is None
    assert results['air_permeability']['unit_status'] == 'tentative'


def test_overflow_returns_validation_error_not_server_error(client):
    values = example()
    values['fiber_length_arithmetic_mm'] = 1e308
    response = client.post('/api/v1/prediction/fiber', json={'species': 'softwood', 'features': values})
    assert response.status_code == 422


def test_missing_model_files_produce_service_error(client, monkeypatch):
    from app import prediction
    def missing():
        raise FileNotFoundError('private/path')
    monkeypatch.setattr(prediction, 'get_engine', missing)
    response = client.get('/api/v1/prediction/metadata')
    assert response.status_code == 503
    assert 'private/path' not in response.text
