from decimal import Decimal
import pytest
from literature_rag.application.unit_conversion import convert,UnitConversionError
from tests.test_literature_tools import kit

@pytest.mark.parametrize('value,source,target,expected',[
    ('10','mg/100 m','mg/m','0.1'),('0.1','mg/m','mg/100m','10'),
    ('25','μm','mm','0.025'),('12','mg/100m','mg/m','0.12'),
    ('1','tex','mg/m','1'),('2','N·m/g','kN*m/kg','2')])
def test_dimensions_and_scaling(value,source,target,expected):
    assert Decimal(convert(value,source,target)['converted_value'])==Decimal(expected)

def test_unsupported_or_different_quantity():
    for source,target in [('MPa','N*m/g'),('unknown','m')]:
        with pytest.raises(UnitConversionError):convert('10',source,target)

def test_conversion_tool_and_reject_prefilled_result(kit):
    request=dict(tool='convert_units',value='10',from_unit='mg/100m',to_unit='mg/m',reason='hypothetical conversion')
    r=kit.call(request,run_id='r')
    assert r['status']=='completed' and Decimal(r['result']['converted_value'])==Decimal('.1')
    assert kit.store.evidence('r')
    assert kit.call(dict(request,final='1000'),run_id='r')['status']=='invalid_arguments'
    assert kit.call(dict(request,source_call_ids=['missing']),run_id='r')['status']!='completed'

def test_change_does_not_verify_conversion(kit):
    source=kit.call(dict(tool='search_literature',query='units',reason='source'),run_id='r')
    r=kit.call(dict(tool='calculate_change',initial='10',final='1000',unit='mg/100m -> mg/m',source_call_ids=[source['call_id']],reason='convert'),run_id='r')
    assert r['error_code']=='unit_conversion_requires_convert_units'
