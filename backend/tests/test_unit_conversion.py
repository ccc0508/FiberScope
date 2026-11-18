from decimal import Decimal
import pytest
from literature_rag.application.unit_conversion import convert,UnitConversionError

@pytest.mark.parametrize('value,source,target,expected',[
    ('10','mg/100 m','mg/m','0.1'),('0.1','mg/m','mg/100m','10'),
    ('25','μm','mm','0.025'),('12','mg/100m','mg/m','0.12'),
    ('1','tex','mg/m','1'),('2','N·m/g','kN*m/kg','2')])
def test_dimensions_and_scaling(value,source,target,expected):
    assert Decimal(convert(value,source,target)['converted_value'])==Decimal(expected)

def test_unsupported_or_different_quantity():
    for source,target in [('MPa','N*m/g'),('unknown','m')]:
        with pytest.raises(UnitConversionError):convert('10',source,target)
