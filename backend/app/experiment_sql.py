from literature_rag.stage_trace import stage as trace_stage, records as trace_records
"""Read-only PostgreSQL SELECTs over allowlisted views, including joins/subqueries."""
import json
from datetime import datetime, timezone
from uuid import uuid4
import psycopg
import sqlglot
from sqlglot import exp
from app.catalog import VIEWS
from app.experiment_preflight import preflight, QueryPlanRejected


class UnsupportedSQL(ValueError):
    def __init__(self,nodes):
        self.nodes=nodes
        super().__init__('Unsupported SQL nodes: '+', '.join(nodes)+'. CASE and explicit CAST are not supported. Use supported GROUP BY/WHERE queries or COALESCE for null fallback. Do not retry the same unsupported construct.')

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
    unsupported=sorted({n.key for n in tree.walk() if n.key not in NODES})
    if unsupported:raise UnsupportedSQL(unsupported)
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
    normalized = None
    stage='validation'
    try:
        with trace_stage('sql.validation') as trace:
            p = INPUT.validate_python(request)
            normalized, view = validate_sql(p.sql) if p.tool == 'query_experiment_data' else (None, None)
            trace.update(sql=normalized, views=view)
        with trace_stage('sql.connection'):
            connection = connect()
        with connection as db:
            with trace_stage('sql.transaction_setup'):
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            if p.tool == 'describe_experiment_data':
                from app.experiment_directory import describe
                with trace_stage('sql.describe', views=p.views):
                    result = json.loads(encode(describe(db, p.views)))
            else:
                stage='explain'
                with trace_stage('sql.explain', sql=normalized) as trace:
                    plan=preflight(db,normalized)
                    trace.update(plan)
                stage='execute'
                with db.cursor(name='agent_experiment_rows') as cur:
                    with trace_stage('sql.execute', sql=normalized):
                        cur.execute(normalized)
                    with trace_stage('sql.fetch', limit=101) as trace:
                        rows=cur.fetchmany(101)
                        trace['fetched_rows']=len(rows)
                    columns=[c.name for c in cur.description]
                with trace_stage('sql.result_processing') as trace:
                    data=[]; size=0; truncated=len(rows)>100
                    for row in rows[:100]:
                        values=json.loads(encode(list(row)))
                        size += len(encode(values))
                        if size>24000:
                            truncated=True; break
                        data.append(values)
                    trace.update(returned_rows=len(data), truncated=truncated, serialized_chars=size)
                views=['fiber.'+name for name in view]
                from app.experiment_result_metadata import describe_outputs
                with trace_stage('sql.output_metadata', columns=columns):
                    column_metadata=describe_outputs(db,normalized,columns,view)
                result=dict(sql=normalized, view=', '.join(views), views=views, columns=columns, rows=data,
                    column_metadata=column_metadata,
                    preflight=plan,
                    row_count=len(data), truncated=truncated, row_limit=100,
                    queried_at=datetime.now(timezone.utc).isoformat(),
                    notice='Database result snapshot, not paper text. Decimal values may be strings. Missing values are null. A truncated result cannot support population-wide conclusions; use SQL aggregates.')
                result['result_state']='truncated' if truncated else 'empty' if not data else 'rows_returned'
                if not data:result['result_notice']='当前精确筛选未匹配记录；不代表整个数据库无相关数据，不得自动放宽条件。'
                elif truncated:result['result_notice']='仅返回部分行，不可据此计算总体统计；保持原筛选条件在SQL中聚合。'
                if data and any(value is None for row in data for value in row):
                    result['null_notice']='结果含NULL，不等于0。空集聚合可能返回一行NULL，不能把返回一行当成存在一个观测。'
        record.update(status='completed',result=result,internal_steps=trace_records())
        store.complete(record)
        return dict(call_id=record['call_id'],status='completed',result=record['result'])
    except QueryPlanRejected as error:
        record.update(status='failed',error_code='query_plan_rejected',message=str(error),diagnostic=dict(preflight=error.summary))
    except UnsupportedSQL as error:
        record.update(status='failed',error_code='unsupported_sql',message=str(error),diagnostic=dict(unsupported_nodes=error.nodes))
    except (ValueError, sqlglot.errors.SqlglotError) as error:
        record.update(status='failed',error_code='invalid_query',message=str(error)[:1000])
    except psycopg.Error as error:
        record.update(status='failed',error_code='database_query_failed',sqlstate=error.sqlstate,
            message='Query failed or timed out. Check columns with describe_experiment_data, simplify SQL and retry. Raw database errors are not exposed.')
        from app.experiment_errors import execution_diagnostic
        record.update(execution_diagnostic(error.sqlstate))
        if normalized:
            try:
                from app.experiment_errors import diagnose
                diagnostic=diagnose(error,normalized,connect,ALLOWED)
                if diagnostic:record.update(diagnostic)
            except Exception:
                # Diagnostic failure must not hide the original failure or leak credentials.
                record['diagnostic_status']='unavailable'
    except Exception:
        record.update(status='failed',error_code='query_execution_failed',message='Experimental data tool unavailable; no raw infrastructure details are exposed.')
    record['internal_steps']=trace_records()
    record['failure_stage']=stage
    store.save(record)
    return {k:record[k] for k in ('call_id','status','error_code','message','sqlstate','diagnostic','diagnostic_status','failure_stage') if k in record}
