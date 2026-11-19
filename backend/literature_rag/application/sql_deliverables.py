"""Conservative verification of numeric deliverables against executed query snapshots."""
from decimal import Decimal, InvalidOperation
from typing import Literal

import sqlglot
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp


class Metric(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    population: Literal['samples', 'recycled', 'blends', 'beating', 'lineage', 'quality', 'unmapped']
    operation: Literal['count', 'value', 'sum', 'avg', 'min', 'max', 'unmapped']
    keys: list[str] = Field(min_length=1, max_length=8)
    group_by: list[str] = Field(default_factory=list, max_length=8)
    equals: dict[str, str] = Field(default_factory=dict)


class MetricCell(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ref: str = Field(pattern=r'^\[[1-9][0-9]*\]$')
    row: int = Field(ge=0)
    column: str
    value: int | float | str | None


# Certified populations and natural row grains, not expected answers.
VIEWS = {
    'v_sample_overview': ('samples', ('canonical_code',)),
    'v_fiber_paper_analysis': ('samples', ('canonical_code',)),
    'v_recycled_cycle_detail': ('recycled', ('block_code', 'cycle_no', 'replicate_no')),
    'v_recycled_cycle_summary': ('recycled', ('block_code', 'cycle_no')),
    'v_blend_analysis': ('blends', ()), 'v_beating_analysis': ('beating', ()),
    'v_data_lineage': ('lineage', ()), 'v_recycled_data_quality': ('quality', ()),
}

FIELD_TERMS = {
    '规范样本':'canonical_code', '样本':'canonical_code', '样本类型':'sample_type',
    '数据块':'block_code', '数据块编号':'block_code', '块编号':'block_code',
    '循环':'cycle_no', '循环编号':'cycle_no', '重复观测编号':'replicate_no',
}


def column_names(expressions):
    if not all(isinstance(node, exp.Column) for node in expressions):
        raise ValueError('unsupported field expression')
    return sorted(node.name for node in expressions)


def filters(query):
    where = query.args.get('where')
    result = {}
    if where:
        parts = where.this.flatten() if isinstance(where.this, exp.And) else [where.this]
        for part in parts:
            if not isinstance(part, exp.EQ) or not isinstance(part.this, exp.Column) or not isinstance(part.expression, exp.Literal):
                raise ValueError('unsupported filter')
            if part.this.name in result:
                raise ValueError('repeated filter')
            result[part.this.name] = part.expression.this
    return result


def shape(query):
    if not isinstance(query, exp.Select) or any(query.args.get(key) for key in
            ('joins','with_','having','limit','offset','qualify','windows','distinct','into')):
        raise ValueError('unsupported query shape')
    group = query.args.get('group')
    groups = column_names(group.expressions) if group else []
    if group and any(value for key,value in group.args.items() if key != 'expressions'):
        raise ValueError('complex grouping')
    return query.args['from_'].this, groups, filters(query)


def signatures(sql, columns):
    """Describe independently provable output columns. Unknown SQL stays unverified."""
    result = {}
    try:
        query = sqlglot.parse_one(sql, read='postgres')
        table, groups, predicates = shape(query)
        grain = None
        if isinstance(table, exp.Subquery):
            inner = table.this
            table, grain, inner_filters = shape(inner)
            if not grain or column_names(inner.selects) != grain or predicates or groups:
                return {}
            predicates = inner_filters
        if not isinstance(table, exp.Table) or table.db != 'fiber' or table.name not in VIEWS:
            return {}
        population, natural = VIEWS[table.name]
        if len(query.selects) != len(columns):
            return {}
        for name, projection in zip(columns, query.selects):
            if columns.count(name) != 1:
                continue
            node = projection.unalias()
            if grain and not (isinstance(node, exp.Count) and isinstance(node.this, exp.Star)):
                continue
            if isinstance(node, exp.Count) and isinstance(node.this, exp.Star):
                operation, keys = 'count', sorted(grain or natural)
            elif isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct):
                parts = node.this.expressions
                if len(parts)==1 and isinstance(parts[0], exp.Tuple):
                    parts=parts[0].expressions
                if not all(isinstance(part,exp.Column) for part in parts):
                    continue
                operation, keys = 'count', column_names(parts)
            elif isinstance(node, (exp.Sum,exp.Avg,exp.Min,exp.Max)) and isinstance(node.this,exp.Column):
                operation, keys = node.key, [node.this.name]
            elif isinstance(node,exp.Column):
                operation, keys = 'value', [node.name]
            else:
                continue
            # Summary measurements are already per-block/cycle averages. The
            # metric schema cannot express that grain. Only certify counts and
            # values over natural keys, with filters/grouping on those same keys.
            if (table.name == 'v_recycled_cycle_summary' and
                    (operation not in ('count', 'value') or
                     not set(keys + groups + list(predicates)).issubset(natural))):
                continue
            result[name] = dict(population=population, operation=operation, keys=keys, group_by=groups, equals=predicates)
    except (ValueError, KeyError, AttributeError, sqlglot.errors.SqlglotError):
        return {}
    return result


def same_value(actual, claimed):
    if actual is None or claimed is None:
        return actual is None and claimed is None
    return Decimal(str(actual)) == Decimal(str(claimed))


def verify_metric(need, item, trace):
    spec = dict(need['metric'])
    spec.update(keys=sorted(FIELD_TERMS.get(key,key) for key in spec['keys']),
                group_by=sorted(FIELD_TERMS.get(key,key) for key in spec['group_by']),
                equals={FIELD_TERMS.get(key,key):value for key,value in spec['equals'].items()})
    cells = item.get('cells', [])
    if not cells:
        return 'numeric_cell_missing'
    refs = {cell['ref'] for cell in cells}
    if len(refs)!=1 or not refs.issubset(item.get('refs', [])):
        return 'numeric_snapshot_mismatch'
    events = list(trace.get('tool_calls', []))
    if not need.get('fresh_query'):
        events += trace.get('inherited_tool_calls', [])
    for event in events:
        raw=event.get('result', {})
        data=raw.get('result', {})
        if (event.get('request',{}).get('tool')!='query_experiment_data' or raw.get('status')!='completed'
                or event.get('model_delivery',{}).get('status')!='delivered' or data.get('ref') not in refs):
            continue
        columns, rows=data.get('columns',[]),data.get('rows',[])
        if data.get('truncated') or len(rows)!=data.get('row_count', len(rows)):
            continue
        if 'selected_row_indices' in data and sorted(data['selected_row_indices'])!=list(range(len(rows))):
            continue
        if not spec['group_by'] and len(rows)!=1:
            continue
        if sorted(cell['row'] for cell in cells)!=list(range(len(rows))):
            continue
        proof=data.get('metric_signatures') if 'selected_row_indices' in data else None
        proof=proof if proof is not None else signatures(data.get('sql',''), columns)
        if not all(any(p==dict(spec,operation='value',keys=[key]) for p in proof.values())
                   for key in spec['group_by']):
            continue
        try:
            if all(columns.count(cell['column'])==1 and proof.get(cell['column'])==spec and
                   same_value(rows[cell['row']][columns.index(cell['column'])], cell['value'])
                   for cell in cells):
                return None
        except (IndexError, InvalidOperation, TypeError):
            pass
    return 'numeric_value_or_query_scope_unverified'
