from app.experiment_result_metadata import output_metadata

ROWS = [('v_fiber_paper_analysis', name, 'numeric') for name in
    ['tensile_index', 'fines_length_pct', 'air_permeability', 'folding_endurance_raw']]


def metadata(projection, names, source='fiber.v_fiber_paper_analysis'):
    return output_metadata(f'SELECT {projection} FROM {source}', names, ROWS)


def test_units_follow_source_not_alias():
    result = metadata('tensile_index AS percent, fines_length_pct AS tensile_index', ['percent', 'tensile_index'])
    assert result[0]['unit'] == 'N·m/g'
    assert 'unit_note' not in result[0]
    assert result[1]['unit'] == '%'
    assert '10%' in result[1]['unit_note']


def test_aggregates_and_uncertain_units():
    result = metadata('ROUND(AVG(tensile_index),2), COUNT(*), MAX(air_permeability), folding_endurance_raw', ['avg','count','max','raw'])
    assert [r['unit'] for r in result] == ['N·m/g','个','μm/(Pa·s)',None]
    assert result[2]['unit_status'] == 'tentative'
    assert result[3]['unit_status'] == 'unconfirmed'


def test_arithmetic_does_not_inherit_misleading_unit():
    result = metadata('tensile_index/100 AS tensile_index', ['tensile_index'])
    assert result[0]['unit'] is None
    assert result[0]['unit_status'] == 'unconfirmed'


def test_star_and_derived_alias():
    assert metadata('*', [r[1] for r in ROWS])[0]['unit'] == 'N·m/g'
    result = metadata('q.value', ['value'], '(SELECT AVG(tensile_index) AS value FROM fiber.v_fiber_paper_analysis) q')
    assert result[0]['unit'] == 'N·m/g'


def test_duplicate_names_are_positional():
    result = metadata('a.tensile_index AS value,b.fines_length_pct AS value', ['value','value'],
        'fiber.v_fiber_paper_analysis a CROSS JOIN fiber.v_fiber_paper_analysis b')
    assert [r['position'] for r in result] == [0,1]
    assert [r['unit'] for r in result] == ['N·m/g','%']
