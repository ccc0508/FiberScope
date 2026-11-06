"""Read-only PostgreSQL SELECTs over allowlisted views, including joins/subqueries."""
import json
from datetime import datetime, timezone
from uuid import uuid4
import psycopg
import sqlglot
from sqlglot import exp
from app.catalog import VIEWS, INDICATORS, NOTES

ALLOWED = {v.view for v in VIEWS.values()}
# Every nested node and physical relation is checked, not just the outer SELECT.
NODES = set('select from table identifier column star alias tablealias literal null boolean where and or not paren eq neq gt gte lt lte is in between like ilike order ordered group having distinct limit offset add sub mul div neg count sum avg min max round abs coalesce nullif'.split())
NODES.update('join subquery exists any all tuple lateral'.split())


def validate_sql(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 8000:
        raise ValueError('SQL must contain 1–8000 characters')
    trees = sqlglot.parse(text, read='postgres')
    if len(trees) != 1 or not isinstance(trees[0], exp.Select):
        raise ValueError('Only one SELECT is allowed')
    tree = trees[0]
    if any(n.key not in NODES for n in tree.walk()):
        raise ValueError('Unsupported SQL: SELECT with joins/subqueries allowed; no CTEs, set operations, casts, writes or arbitrary functions')
    tables = list(tree.find_all(exp.Table))
    if not tables or any(t.db not in ('', 'fiber') or t.catalog or t.name not in ALLOWED for t in tables):
        raise ValueError('Every relation, including inside subqueries, must be an allowed fiber analysis view; call describe_experiment_data')
    for table in tables:
        table.set('db', exp.to_identifier('fiber'))
    for select in tree.find_all(exp.Select):
        for key in ('limit', 'offset'):
            node = select.args.get(key)
            if not node: continue
            value = node.expression
            if not isinstance(value, exp.Literal) or not value.is_int or not 0 <= int(value.this) <= 10000:
                raise ValueError('LIMIT/OFFSET must be an integer between 0 and 10000')
    # Execute regenerated AST, never the unchecked original SQL text.
    return tree.sql(dialect='postgres', comments=False), sorted({t.name for t in tables})


def connect():
    from app.main import Settings
    s = Settings()
    return psycopg.connect(host=s.pghost, port=s.pgport, dbname=s.pgdatabase,
        user=s.pguser, password=s.pgpassword, connect_timeout=3,
        options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000 -c search_path=pg_catalog')


def execute(request, run_id, store):
    from literature_rag.application.tools import INPUT, encode
    record = dict(call_id=str(uuid4()), run_id=run_id, status='started',
        started_at=datetime.now(timezone.utc).isoformat(), input=request)
    store.save(record)
    try:
        p = INPUT.validate_python(request)
        normalized, view = validate_sql(p.sql) if p.tool == 'query_experiment_data' else (None, None)
        with connect() as db:
            db.execute('SET TRANSACTION READ ONLY')
            if p.tool == 'describe_experiment_data':
                rows = db.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='fiber' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position", (sorted(ALLOWED),)).fetchall()
                result = dict(views={'fiber.'+name:dict(columns=[dict(name=c,type=t) for v,c,t in rows if v==name],
                    default_order=list(spec.order)) for _,spec in VIEWS.items() for name in [spec.view]},
                    indicators=INDICATORS, notes=NOTES, material_codes={'SW':'针叶木','HW':'阔叶木'},
                    grains={'v_sample_overview':'one canonical sample; use this for sample counts',
                        'v_beating_analysis':'one experiment display row; samples may appear in multiple experiments',
                        'v_blend_analysis':'one blend experiment row including pure-pulp endpoints; not the number of blend-only samples',
                        'v_fiber_paper_analysis':'one canonical sample with fiber/paper measurements',
                        'v_recycled_cycle_summary':'one data block and cycle summary',
                        'v_recycled_cycle_detail':'one raw replicate per block and cycle',
                        'v_recycled_data_quality':'one flagged raw observation',
                        'v_data_lineage':'one source usage association; multiple usages can share a sample or source row'},
                    sample_types=['softwood','hardwood','blend'],
                    policy='SELECT over allowed fiber views, arbitrary joins between those views and nested/correlated SELECT subqueries permitted. WHERE/GROUP BY/HAVING/ORDER BY; COUNT/SUM/AVG/MIN/MAX/ROUND/ABS/COALESCE/NULLIF. No CTEs, set operations or casts. Include sample IDs for raw rows. Add ORDER BY for deterministic results. Explain join keys and resulting grain; one-to-many joins can multiply samples and bias counts/averages. lineage has multiple usages per sample. Max 100 returned rows; truncated results are not the full population.')
            else:
                with db.cursor(name='agent_experiment_rows') as cur:
                    cur.execute(normalized)
                    rows=cur.fetchmany(101)
                    columns=[c.name for c in cur.description]
                data=[]; size=0; truncated=len(rows)>100
                for row in rows[:100]:
                    values=json.loads(encode(list(row)))
                    size += len(encode(values))
                    if size>24000:
                        truncated=True; break
                    data.append(values)
                views=['fiber.'+name for name in view]
                result=dict(sql=normalized, view=', '.join(views), views=views, columns=columns, rows=data,
                    row_count=len(data), truncated=truncated, row_limit=100,
                    queried_at=datetime.now(timezone.utc).isoformat(), notes=NOTES,
                    notice='Database result snapshot, not paper text. Decimal values may be strings. Missing values are null. A truncated result cannot support population-wide conclusions; use SQL aggregates.')
        record.update(status='completed',result=result)
        store.complete(record)
        return dict(call_id=record['call_id'],status='completed',result=record['result'])
    except (ValueError, sqlglot.errors.SqlglotError) as error:
        record.update(status='failed',error_code='invalid_query',message=str(error)[:1000])
    except psycopg.Error as error:
        record.update(status='failed',error_code='database_query_failed',sqlstate=error.sqlstate,
            message='Query failed or timed out. Check columns with describe_experiment_data, simplify SQL and retry. Raw database errors are not exposed.')
    except Exception:
        record.update(status='failed',error_code='query_execution_failed',message='Experimental data tool unavailable; no raw infrastructure details are exposed.')
    store.save(record)
    return {k:record[k] for k in ('call_id','status','error_code','message')}
