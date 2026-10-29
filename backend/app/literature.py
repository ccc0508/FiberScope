"""Read-only literature catalogue and bounded document-QA worker."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager, asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from filelock import FileLock, Timeout as LockTimeout
from .qa_history import HistoryStore
from literature_rag.diagnostics import configuration_snapshot

BACKEND = Path(__file__).resolve().parents[1]


class LiteratureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / '.env.literature', env_prefix='LITERATURE_', extra='ignore')
    enabled: bool = False
    data_dir: Path = BACKEND.parent / '.rag-data'
    library_dir: Path | None = None
    timeout_seconds: int = Field(90, ge=5, le=300)
    extraction_timeout_seconds: int = Field(180, ge=10, le=300)
    document_extraction_timeout_seconds: int = Field(1800, ge=60, le=3600)

    @property
    def root(self) -> Path:
        return (BACKEND / self.data_dir).resolve()

    @property
    def library_root(self) -> Path:
        return (BACKEND / self.library_dir).resolve() if self.library_dir is not None else self.root


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=2000)
    request_id: UUID = Field(default_factory=uuid4)


class Feedback(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    rating: Literal['helpful', 'inaccurate']
    tags: list[Literal['numeric_error', 'unsupported_citation', 'irrelevant', 'incomplete', 'wrong_refusal']] = Field(default_factory=list, max_length=5)
    note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_tags(self):
        if len(set(self.tags)) != len(self.tags) or (self.rating == 'helpful' and self.tags):
            raise ValueError('评价标签无效')
        return self


@contextmanager
def connect(config: LiteratureSettings):
    path = config.library_root / 'metadata.sqlite3'
    if not path.is_file():
        raise HTTPException(503, '文献库尚未配置，请联系管理员导入文献。')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def documents(config: LiteratureSettings):
    with connect(config) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id,filename,page_count,chunk_count FROM documents WHERE status='completed' ORDER BY filename,id")]


def pdf_path(config: LiteratureSettings, document_id: str):
    with connect(config) as conn:
        row = conn.execute("SELECT file_path,filename FROM documents WHERE id=? AND status='completed'", (document_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '没有找到这篇文献。')
    path = Path(row['file_path'])
    if not path.is_absolute():
        path = config.library_root / path
    path = path.resolve()
    if not path.is_relative_to((config.library_root / 'papers').resolve()) or path.suffix.lower() != '.pdf' or not path.is_file():
        raise HTTPException(404, '文献原文件暂不可用。')
    return path, row['filename']


def run_answer(config: LiteratureSettings, question: str):
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-X', 'utf8', str(BACKEND / 'literature_worker.py')],
            input=json.dumps({'question': question, 'data_dir': str(config.library_root)}, ensure_ascii=False),
            capture_output=True, text=True, encoding='utf-8', timeout=config.timeout_seconds,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '文献问答耗时过长，请稍后重试或缩短问题。') from None
    if result.returncode:
        # Provider errors may contain credentials; never return worker stderr.
        raise HTTPException(503, '文献问答服务暂不可用，请检查模型配置或稍后重试。')
    try:
        body = json.loads(result.stdout)
        if body['status'] not in ('answered', 'refused', 'failed') or not isinstance(body['citations'], list) or not isinstance(body['answer'], str):
            raise ValueError()
        return body
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, '文献问答响应无法读取，请稍后重试。') from None


class QuestionRunner:
    """One process owns recovery and one bounded worker; accepted jobs outlive HTTP requests."""
    def __init__(self, config):
        self.config = config
        self.store = HistoryStore(config.root / 'qa_history.sqlite3')
        self.process_lock = FileLock(str(config.root / '.qa-history.lock'), thread_local=False)
        self.lock = Lock()
        self.slot = BoundedSemaphore(1)
        self.executor = None
        self.save_errors = set()

    def ensure(self):
        if not self.config.enabled:
            raise HTTPException(503, '文献问答尚未启用。')
        with self.lock:
            if self.executor is not None:
                return
            try:
                self.config.root.mkdir(parents=True, exist_ok=True)
                self.process_lock.acquire(timeout=0)
                self.store.initialize()
                self.store.recover()
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='literature-qa')
            except (sqlite3.Error, OSError, LockTimeout):
                self.process_lock.release()
                raise HTTPException(503, '问答记录库暂不可用，请检查目录权限或是否启动了多个服务实例。') from None

    def database(self, method, *args):
        self.ensure()
        try:
            return method(*args)
        except (sqlite3.Error, OSError):
            raise HTTPException(503, '问答记录读取或保存失败，请稍后重试。') from None

    def session(self, request, response):
        owner, token = self.database(self.store.session, request.cookies.get('fiber_qa_session'))
        response.headers['Cache-Control'] = 'no-store'
        if token:
            response.set_cookie('fiber_qa_session', token, httponly=True, samesite='lax',
                                secure=request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https',
                                max_age=180 * 86400, path='/api/v1/literature')
        return owner

    def perform(self, record_id, question, configuration, started):
        try:
            try:
                if not documents(self.config):
                    result = {'status': 'refused', 'answer': '文献库中暂无已完成导入的文献，请先补充文献。', 'citations': [],
                              'latency_ms': 0, 'reason_code': 'empty_library', 'retrieved_evidence': [], 'claims': [], 'generation_calls': []}
                else:
                    result = run_answer(self.config, question)
                result.setdefault('configuration', configuration)
                self.store.complete(record_id, result, int((perf_counter() - started) * 1000))
            except HTTPException as error:
                reason = 'timeout' if error.status_code == 504 else 'worker_error'
                self.store.fail(record_id, reason, error.status_code, int((perf_counter() - started) * 1000))
        except (sqlite3.Error, OSError):
            with self.lock:
                self.save_errors.add(record_id)
        except Exception:
            try:
                self.store.fail(record_id, 'worker_error', 503, int((perf_counter() - started) * 1000))
            except (sqlite3.Error, OSError):
                with self.lock:
                    self.save_errors.add(record_id)
        finally:
            self.slot.release()

    def submit(self, owner, body, started):
        key = str(body.request_id)
        # Serialize the check/create/schedule boundary for idempotent submissions.
        with self.lock:
            existing = self.store.by_key(owner, key)
            if existing:
                if existing['question'] != body.question:
                    raise HTTPException(409, '同一提交编号不能用于不同问题。')
                if existing['id'] in self.save_errors:
                    raise HTTPException(503, '回答保存失败，请重新提交问题。')
                return existing
            if not self.slot.acquire(blocking=False):
                raise HTTPException(429, '已有文献问答正在处理，请稍后再试。')
            try:
                try:
                    configuration = configuration_snapshot(BACKEND / '.env.literature')
                except Exception:
                    configuration = {'pipeline_version': 'literature-history-v1', 'configuration_available': False}
                record = self.store.create(owner, key, body.question, configuration)
                self.executor.submit(self.perform, record['id'], body.question, configuration, started)
                return record
            except Exception:
                self.slot.release()
                raise

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True)
            self.executor = None
            self.process_lock.release()


def router(config: LiteratureSettings | None = None, allowed_origins: list[str] | None = None):
    config = config or LiteratureSettings()
    runner = QuestionRunner(config)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            runner.close()

    routes = APIRouter(prefix='/api/v1/literature', tags=['literature'], lifespan=lifespan)
    origins = allowed_origins or ['http://localhost:5173', 'http://127.0.0.1:5173']

    def check_origin(request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' and origin not in origins:
            raise HTTPException(403, '请在本站页面提交操作。')
        if origin:
            parsed = urlsplit(origin)
            browser_host = request.headers.get('x-forwarded-host') or request.headers.get('host')
            if origin not in origins and (parsed.scheme not in ('http', 'https') or parsed.netloc != browser_host):
                raise HTTPException(403, '请在本站页面提交操作。')

    def detail(owner, record_id):
        item = runner.database(runner.store.get, owner, record_id)
        if item is None:
            raise HTTPException(404, '没有找到这条问答记录。')
        if record_id in runner.save_errors:
            raise HTTPException(503, '回答保存失败，请重新提交问题。')
        return item

    @routes.get('/documents')
    def library():
        if not config.enabled:
            return {'enabled': False, 'documents': [], 'message': '文献问答尚未启用。'}
        try:
            items = documents(config)
            return {'enabled': True, 'documents': items, 'message': '仅依据当前文献库回答，每次提问独立处理。'}
        except sqlite3.Error:
            raise HTTPException(503, '文献库读取失败，请联系管理员。') from None

    @routes.get('/documents/{document_id}/pdf')
    def pdf(document_id: str):
        if not config.enabled:
            raise HTTPException(503, '文献问答尚未启用。')
        path, name = pdf_path(config, document_id)
        return FileResponse(path, media_type='application/pdf', filename=name, content_disposition_type='inline')

    @routes.post('/ask')
    def ask(body: Question, request: Request, response: Response):
        started = perf_counter()
        check_origin(request)
        owner = runner.session(request, response)
        try:
            record = runner.submit(owner, body, started)
        except (sqlite3.Error, OSError):
            raise HTTPException(503, '问答保存失败，请稍后重试。') from None
        response.status_code = 202 if record['status'] == 'processing' else 200
        record['can_feedback'] = True
        return record

    @routes.get('/history')
    def history(request: Request, response: Response, page: int = Query(1, ge=1, le=100000),
                page_size: int = Query(10, ge=1, le=100), q: str = Query('', max_length=200)):
        owner = runner.session(request, response)
        return runner.database(runner.store.list, owner, page, page_size, q)

    @routes.get('/history/export')
    def export(request: Request):
        response = Response()
        runner.session(request, response)
        response = StreamingResponse(runner.store.export(), media_type='application/x-ndjson', headers=dict(response.headers))
        response.headers['Content-Disposition'] = 'attachment; filename="literature-qa.jsonl"'
        if 'content-length' in response.headers:
            del response.headers['content-length']
        return response

    @routes.get('/history/{record_id}')
    def record(record_id: str, request: Request, response: Response):
        owner = runner.session(request, response)
        return detail(owner, record_id)

    @routes.post('/history/{record_id}/feedback')
    def feedback(record_id: str, body: Feedback, request: Request, response: Response):
        check_origin(request)
        owner = runner.session(request, response)
        try:
            result = runner.database(runner.store.feedback, owner, record_id, body.rating, body.tags, body.note)
        except ValueError:
            raise HTTPException(409, '该记录尚未生成可评价的回答。') from None
        if result is None:
            detail(owner, record_id)
            raise HTTPException(403, '该记录公开可查看，评价仅限原提交浏览器修改。')
        return result

    from .extraction import router as extraction_router
    routes.include_router(extraction_router(config, check_origin))
    return routes
