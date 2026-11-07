from types import SimpleNamespace
from app.experiment_errors import field_diagnostic

SCHEMA={'v_sample_overview':['sample_id','canonical_code'],
        'v_fiber_paper_analysis':['sample_id','tensile_index','fiber_length_weighted_mm']}
def error(code,message):return SimpleNamespace(sqlstate=code,diag=SimpleNamespace(message_primary=message))

def test_wrong_view():
    r=field_diagnostic(error('42703','column "fiber_length_weighted_mm" does not exist'),
        'SELECT fiber_length_weighted_mm FROM fiber.v_sample_overview',SCHEMA)
    assert r['diagnostic']['available_in']==['fiber.v_fiber_paper_analysis']
    assert not r['diagnostic']['candidate_scopes'][0]['sources'][0]['has_column']

def test_typo():
    r=field_diagnostic(error('42703','column "tensil_index" does not exist'),
        'SELECT tensil_index FROM fiber.v_fiber_paper_analysis',SCHEMA)
    assert r['diagnostic']['available_in']==[]
    assert 'tensile_index' in r['diagnostic']['candidate_scopes'][0]['sources'][0]['similar_columns']

def test_ambiguous():
    r=field_diagnostic(error('42702','column reference "sample_id" is ambiguous'),
        'SELECT sample_id FROM fiber.v_sample_overview a JOIN fiber.v_fiber_paper_analysis b ON a.sample_id=b.sample_id',SCHEMA)
    assert r['error_code']=='ambiguous_column'
    assert {s['alias'] for s in r['diagnostic']['candidate_scopes'][0]['sources']}=={'a','b'}

def test_no_raw_error_leak():
    r=field_diagnostic(error('42703','private connection secret'), 'SELECT x FROM fiber.v_sample_overview',SCHEMA)
    assert 'secret' not in str(r) and not r['diagnostic']['column_identified']

def test_nested_scope():
    r=field_diagnostic(error('42703','column "tensil_index" does not exist'),
        'SELECT * FROM fiber.v_sample_overview s WHERE EXISTS(SELECT tensil_index FROM fiber.v_fiber_paper_analysis f)',SCHEMA)
    assert r['diagnostic']['candidate_scopes'][0]['sources'][0]['alias']=='f'

def test_other_errors_not_field_errors():
    assert field_diagnostic(error('57014','timeout'),'SELECT 1',SCHEMA) is None
