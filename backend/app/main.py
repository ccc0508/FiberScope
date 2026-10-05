from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg import Error, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from starlette.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from .catalog import INDICATORS, NOTES, VIEWS
from .literature import router as literature_router


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / '.env', extra='ignore')
    pghost: str = '127.0.0.1'
    pgport: int = 5432
    pgdatabase: str = 'plant_fiber_db'
    pguser: Literal['fiber_app','fiber_reader'] = 'fiber_app'
    pgpassword: str = Field(default='', repr=False)
    cors_origins: list[str] = ['http://localhost:5173','http://127.0.0.1:5173']


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page: int = Field(1, ge=1, le=100000)
    page_size: int = Field(50, ge=1, le=500)
    sample_type: Literal['softwood','hardwood','blend'] | None = None
    material_code: Literal['SW','HW'] | None = None
    canonical_code: str | None = Field(None, max_length=64)
    q: str | None = Field(None, max_length=100)
    block_code: list[str] = Field(default_factory=list, max_length=14)
    cycle_no: int | None = Field(None, ge=1, le=4)
    min_revolutions: int | None = Field(None, ge=0)
    max_revolutions: int | None = Field(None, ge=0)
    usage_type: Literal['experiment_sample','sample_component','fiber_measurement','paper_measurement','source_only'] | None = None
    file_name: str | None = Field(None, max_length=255)

    @model_validator(mode='after')
    def validate_values(self):
        if any(b not in [f'G{i:02}' for i in range(1,15)] for b in self.block_code):
            raise ValueError('数据块必须为 G01—G14')
        if self.min_revolutions is not None and self.max_revolutions is not None and self.min_revolutions > self.max_revolutions:
            raise ValueError('最小转数不能超过最大转数')
        return self


def build_query(endpoint: str, params: Params):
    spec = VIEWS[endpoint]
    clauses, values = [], []
    for key, value in params.model_dump(exclude_unset=True).items():
        if key in ('page','page_size') or value is None or value == []:
            continue
        if key not in spec.filters:
            raise HTTPException(422, f'此接口不支持筛选字段：{key}')
        if key == 'q':
            escaped = value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            clauses.append(sql.SQL("(canonical_code ILIKE %s OR display_name ILIKE %s)"))
            values.extend([f'%{escaped}%'] * 2)
        elif key == 'block_code':
            clauses.append(sql.SQL('block_code = ANY(%s)'))
            values.append(value)
        elif key in ('min_revolutions','max_revolutions'):
            clauses.append(sql.SQL('beating_revolutions {} %s').format(sql.SQL('>=' if key=='min_revolutions' else '<=')))
            values.append(value)
        else:
            clauses.append(sql.SQL('{} = %s').format(sql.Identifier(key)))
            values.append(value)
    where = sql.SQL(' WHERE ') + sql.SQL(' AND ').join(clauses) if clauses else sql.SQL('')
    table = sql.Identifier('fiber', spec.view)
    count = sql.SQL('SELECT count(*) AS total FROM {}{}').format(table, where)
    order = sql.SQL(', ').join(sql.Identifier(x) for x in spec.order)
    query = sql.SQL('SELECT * FROM {}{} ORDER BY {} LIMIT %s OFFSET %s').format(table,where,order)
    return count, query, values


def create_app(settings: Settings | None = None):
    config = settings or Settings()
    pool = ConnectionPool('', kwargs=dict(host=config.pghost, port=config.pgport, dbname=config.pgdatabase,
        user=config.pguser, password=config.pgpassword, row_factory=dict_row, connect_timeout=3,
        options='-c default_transaction_read_only=on -c statement_timeout=10000 -c timezone=Asia/Shanghai'),
        min_size=0, max_size=5, timeout=4, open=False)

    @asynccontextmanager
    async def lifespan(app):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title='植物纤维数据分析 API', version='1.0.0', lifespan=lifespan)
    app.state.pool = pool
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_credentials=True, allow_methods=['GET','POST'], allow_headers=['Accept','Content-Type'])
    app.include_router(literature_router(allowed_origins=config.cors_origins))

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    def failure(request, status, code, message):
        trace_id = getattr(request.state,'request_id',uuid4().hex)
        return JSONResponse(status_code=status, content={'error': {'code':code, 'message':message,
            'request_id':trace_id}}, headers={'X-Request-ID':trace_id})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return failure(request,422,'INVALID_QUERY','请求参数无效，请检查输入内容、筛选条件或分页设置。')

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return failure(request,exc.status_code,'INVALID_QUERY' if exc.status_code==422 else 'HTTP_ERROR',str(exc.detail))

    @app.exception_handler(PoolTimeout)
    @app.exception_handler(Error)
    async def database_error(request, exc):
        return failure(request,503,'DATABASE_UNAVAILABLE','数据库暂时不可用，请稍后重试或联系管理员。')

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return failure(request,500,'INTERNAL_ERROR','服务暂时出现问题，请凭请求编号联系管理员。')

    @app.get('/api/v1/health')
    def health():
        with pool.connection() as conn:
            conn.execute('SELECT 1').fetchone()
        return {'status':'ok','database':'connected','checked_at':datetime.now(timezone.utc).isoformat()}

    @app.get('/api/v1/metadata')
    def metadata():
        with pool.connection() as conn:
            counts = {name:conn.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier('fiber',s.view))).fetchone()['n'] for name,s in VIEWS.items()}
            counts['sources'] = conn.execute('SELECT count(DISTINCT source_id) AS n FROM fiber.v_data_lineage').fetchone()['n']
            blocks = conn.execute('SELECT DISTINCT block_code, block_name, block_order, raw_material_grade, condition_label, metadata_status FROM fiber.v_recycled_cycle_summary ORDER BY block_order').fetchall()
            columns = {name:[r['column_name'] for r in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',('fiber',s.view))] for name,s in VIEWS.items()}
        return {'indicators':INDICATORS,'notes':NOTES,'counts':counts,'blocks':blocks,
                'views':{name:{'view':s.view,'columns':columns[name],'sort':s.order,'filters':s.filters,'baseline':s.expected} for name,s in VIEWS.items()},
                'sample_types':{'softwood':'针叶木浆','hardwood':'阔叶木浆','blend':'针阔复配'}}

    def register(endpoint):
        spec = VIEWS[endpoint]

        def listing(params: Annotated[Params, Query()]):
            count, query, values = build_query(endpoint, params)
            with pool.connection() as conn:
                # Count and page use one consistent snapshot even if an importer commits meanwhile.
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                total = conn.execute(count, values).fetchone()['total']
                rows = conn.execute(query, [*values,params.page_size,(params.page-1)*params.page_size]).fetchall()
            return jsonable_encoder({'data':rows,'pagination':{'page':params.page,'page_size':params.page_size,
                'total':total,'total_pages':ceil(total/params.page_size)},'meta':{'view':f'fiber.{spec.view}',
                'indicators':[i for i in INDICATORS if spec.scope in i['scope']], 'notes':NOTES}})
        app.get('/api/v1/'+endpoint, name=endpoint.replace('/','_'))(listing)

    for endpoint in VIEWS:
        register(endpoint)
    return app


app = create_app()
