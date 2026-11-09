"""Explicit multiplicative unit conversions; no arbitrary expressions or model factors."""
from decimal import Decimal, localcontext
import re

# Scale to the group's base unit. Physically different targets never mix.
UNITS={
    'nm':('length','0.000000001'),'μm':('length','0.000001'),
    'mm':('length','0.001'),'cm':('length','0.01'),'m':('length','1'),'km':('length','1000'),
    'mg':('mass','0.001'),'g':('mass','1'),'kg':('mass','1000'),
    'mg/100m':('coarseness','0.00001'),'mg/m':('coarseness','0.001'),
    'mg/km':('coarseness','0.000001'),'g/m':('coarseness','1'),
    'g/km':('coarseness','0.001'),'tex':('coarseness','0.001'),
    'Pa':('stress','1'),'kPa':('stress','1000'),'MPa':('stress','1000000'),
    'N*m/g':('tensile_index','1'),'kN*m/kg':('tensile_index','1'),
}

class UnitConversionError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)

def canonical_unit(unit):
    return re.sub(r'\s+','',unit).replace('µ','μ').replace('um','μm').replace('·','*').replace('⋅','*').replace('Nm/','N*m/')

def convert(value,source,target):
    source,target=canonical_unit(source),canonical_unit(target)
    if source not in UNITS or target not in UNITS:raise UnitConversionError('unsupported_unit')
    a,b=UNITS[source],UNITS[target]
    if a[0]!=b[0]:raise UnitConversionError('incompatible_quantities')
    with localcontext() as ctx:
        ctx.prec=50
        factor=Decimal(a[1])/Decimal(b[1]);answer=Decimal(value)*factor
    return dict(value=value,from_unit=source,to_unit=target,factor=format(factor,'f'),
        converted_value=format(answer,'f'),quantity=a[0],
        formula=f'{value} × {format(factor,"f")} = {format(answer,"f")}',
        notice='Program-calculated unit conversion only. Input/source identification and measurement comparability are not verified. Not an experimental measurement.')
