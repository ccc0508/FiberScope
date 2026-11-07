"""Compact view directory and live, view-scoped semantic details."""
import json
from pathlib import Path
from datetime import datetime, timezone
from psycopg import sql
from app.catalog import INDICATORS, VIEWS, NOTES

SEMANTICS=json.loads(Path(__file__).with_name('experiment_semantics.json').read_text('utf8'))
SPECS={spec.view:spec for spec in VIEWS.values()}
INDICATOR_MAP={i['key']:i for i in INDICATORS}

def selection(views):
    names=[]
    for value in views or []:
        name=value.removeprefix('fiber.')
        if name not in SPECS: raise ValueError('Unknown view. Allowed: '+', '.join('fiber.'+v for v in SPECS))
        if name not in names: names.append(name)
    return names

def column_info(view, name, kind):
    out=dict(name=name,type=kind)
    if name in INDICATOR_MAP:
        i=INDICATOR_MAP[name];out.update(description=i['name'],unit=i['unit'],unit_status=i['unit_status'])
    elif name in SEMANTICS['fields']:
        description,unit=SEMANTICS['fields'][name];out.update(description=description,unit=unit)
    elif name.startswith(('sw_','hw_')):
        material='针叶木' if name.startswith('sw_') else '阔叶木'
        suffix=name[3:]
        description,unit={'proportion_pct':('组分比例，0—100口径','%'),
            'beating_revolutions':('累计打浆转数，不是转速','转'),
            'beating_degree_sr':('组分打浆度','°SR')}.get(suffix,('含义尚未整理',None))
        out.update(description=material+description,unit=unit)
    else: out.update(description='字段含义尚未整理，请勿按名称推断',semantic_status='unconfirmed')
    if name=='replicate_count' and view=='v_recycled_cycle_summary':
        out['description']='该数据块×循环的原始观测行数；各指标非空值数量可能不同'
    return out

def describe(db, views=None):
    names=selection(views)
    result=dict(mode='details' if names else 'directory',views={},
        policy='Only allowlisted fiber views. SELECT, arbitrary joins and nested/correlated subqueries allowed; no CTEs/UNION/casts/arbitrary functions. Supported functions: COUNT/SUM/AVG/MIN/MAX/ROUND/ABS/COALESCE/NULLIF. Joins can multiply rows; preserve intended grain. Query results limited to 100 rows/24000 row characters.',
        next_step='Call describe_experiment_data with views=[qualified view names] for actual columns, units and live enums before writing SQL.')
    for name in names or SPECS:
        purpose,grain=SEMANTICS['views'][name]
        result['views']['fiber.'+name]=dict(description=purpose,row_grain=grain)
    if not names: return result
    rows=db.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='fiber' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position",(names,)).fetchall()
    for name in names:
        entry=result['views']['fiber.'+name]
        columns=[column_info(name,c,t) for v,c,t in rows if v==name]
        entry.update(columns=columns,default_order=list(SPECS[name].order))
        for c in columns:
            if c['name'] not in SEMANTICS['enum_fields']: continue
            query=sql.SQL('SELECT DISTINCT {} FROM {} ORDER BY {} NULLS LAST LIMIT 201').format(
                sql.Identifier(c['name']),sql.Identifier('fiber',name),sql.Identifier(c['name']))
            values=[r[0] for r in db.execute(query).fetchall()]
            # Null has separate presence semantics and is not a selectable label.
            has_null=db.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {} WHERE {} IS NULL)').format(sql.Identifier('fiber',name),sql.Identifier(c['name']))).fetchone()[0]
            nonnull=[v for v in values if v is not None]
            c['enum']=dict(values=nonnull[:200],has_null=has_null,truncated=len(nonnull)>200,limit=200)
            labels=SEMANTICS['value_labels'].get(c['name'],{})
            if labels:c['enum']['labels']={str(v):labels[str(v)] for v in nonnull[:200] if str(v) in labels}
        fields={c['name'] for c in columns}
        entry['ambiguities']=[a for a in SEMANTICS['ambiguities'] if fields.intersection(a['fields'])]
        if {'material_code','beating_revolutions'}<=fields:
            pairs=db.execute(sql.SQL('SELECT DISTINCT material_code,beating_revolutions FROM {} ORDER BY material_code,beating_revolutions NULLS LAST LIMIT 501').format(sql.Identifier('fiber',name))).fetchall()
            entry['beating_levels_by_material']=dict(rows=[list(r) for r in pairs[:500]],columns=['material_code','beating_revolutions'],truncated=len(pairs)>500)
    result.update(enums_queried_at=datetime.now(timezone.utc).isoformat(),notes=NOTES,
        enum_notice='Live DISTINCT values from selected views in this transaction. Not legal ranges; individual enum membership does not guarantee a combination exists. Truncated enums are not complete; use targeted SQL. Continuous measurements are not enumerated.')
    return result
