"""Conservative, positional output units; never infer units from output aliases."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from app.experiment_directory import column_info


def output_metadata(query, columns, schema_rows):
    unknown = dict(unit=None, unit_status='unconfirmed',
        description='表达式单位无法可靠推断，请核对计算定义；不要按别名猜测单位')
    fallback = [dict(unknown, position=i, name=name) for i, name in enumerate(columns)]
    schema = {}
    for view, name, kind in schema_rows:
        schema.setdefault(view, {})[name] = kind
    try:
        tree = qualify(sqlglot.parse_one(query, read='postgres'), dialect='postgres',
            schema={'fiber': schema}, quote_identifiers=False)
        outputs = {}

        def resolve(node, scope):
            if isinstance(node, (exp.Alias, exp.Paren)):
                return resolve(node.this, scope)
            # PostgreSQL rendering inserts a DECIMAL cast around AVG for ROUND.
            # Numeric representation conversion preserves physical dimensions.
            if isinstance(node, exp.Cast) and node.args['to'].sql().upper().split('(')[0] in ('DECIMAL','NUMERIC'):
                return resolve(node.this,scope)
            if isinstance(node, exp.Column):
                source = scope.sources.get(node.table)
                if isinstance(source, exp.Table) and node.name in schema.get(source.name, {}):
                    info = column_info(source.name, node.name, schema[source.name][node.name])
                    info.pop('name', None)
                    info.setdefault('unit', None)
                    info.setdefault('unit_status', 'confirmed' if info['unit'] else 'not_applicable')
                    if info.get('semantic_status') == 'unconfirmed':
                        info['unit_status'] = 'unconfirmed'
                    info['source_columns'] = [f'fiber.{source.name}.{node.name}']
                    if info['unit'] == '%':
                        info['unit_note'] = '源字段按百分数存储，例如10表示10%，不是0.10；聚合值不保证在0—100范围内。'
                    return info
                if isinstance(source, Scope):
                    matches = [value for name, value in outputs.get(id(source), []) if name == node.name]
                    if len(matches) == 1:
                        return dict(matches[0])
                return dict(unknown)
            if isinstance(node, exp.Count):
                return dict(unit='个', unit_status='confirmed', description='SQL计数结果；计数对象由表达式与连接后的行粒度决定，不自动等同样本数')
            if isinstance(node, (exp.Avg, exp.Sum, exp.Min, exp.Max, exp.Round, exp.Abs, exp.Neg)):
                info = resolve(node.this, scope)
                return dict(info, description=f'{node.key.upper()}({info["description"]})')
            # Arithmetic, COALESCE, literals and scalar subqueries remain explicit unknowns.
            return dict(unknown)

        scopes = list(traverse_scope(tree))
        for scope in scopes:
            outputs[id(scope)] = [(projection.alias_or_name, resolve(projection, scope))
                for projection in scope.expression.selects]
        values = outputs[id(scopes[-1])]
        if len(values) != len(columns):
            return fallback
        return [dict(info, position=i, name=columns[i]) for i, (_, info) in enumerate(values)]
    except (sqlglot.errors.SqlglotError, KeyError, ValueError, IndexError):
        # Metadata uncertainty must not turn a successful SQL result into a failure.
        return fallback


def describe_outputs(db, query, columns, views):
    rows = db.execute("SELECT table_name,column_name,data_type FROM information_schema.columns "
        "WHERE table_schema='fiber' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position", (views,)).fetchall()
    return output_metadata(query, columns, rows)
