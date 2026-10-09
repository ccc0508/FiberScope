"""Public durable extraction jobs, with session-owned submissions and reviews."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from math import ceil, isfinite
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import BoundedSemaphore, Lock
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from filelock import FileLock, Timeout as LockTimeout

from .qa_history import HistoryStore, now
from .extraction_review import ReviewStoreMixin, initialize_reviews, review_summary

BACKEND = Path(__file__).resolve().parents[1]
MAX_PDF_BYTES = 12 * 1024 * 1024
ERROR_MESSAGES = {
    'invalid_pdf': 'PDF无法解析或已加密，请提供可复制文字的PDF。',
    'invalid_page': '所选页码无效，或PDF超过200页。',
    'invalid_crop': '表格区域超出页面范围。',
    'text_unavailable': '该页没有足够的可提取文字，第一版暂不支持扫描件OCR。',
    'page_too_complex': '所选区域文字过多，请缩小表格区域。',
    'table_not_found': '所选区域未找到指定表格标题，请检查页码和区域。',
    'unsupported_page_size': '页面尺寸过大，请提供常规版面的PDF。',
    'source_changed': '保存的原文与提交文件指纹不一致，请重新提交。',
    'provider_error': '模型调用失败，请稍后重试。',
    'model_balance_exhausted': '模型服务余额不足，请补充模型额度后重新提取。',
    'model_rate_limited': '模型服务限流，请稍后重新提取。',
    'model_auth_failed': '模型服务认证失败，请检查模型配置。',
    'missing_configuration': '文献提取的模型配置不完整。',
    'validation_failed': '模型提取结果未通过原文证据校验。',
    'timeout': '提取超时，已保存可用的证据及诊断信息。',
    'service_restarted': '服务重启导致提取中断，请重新提交。',
}


class ExtractionStore(ReviewStoreMixin, HistoryStore):
    # Reuse the existing hashed browser-session protocol and connection helper;
    # this database has no questions/feedback tables and no QA writes.
    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS extraction_tasks (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES sessions(id),
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('processing','completed','failed','interrupted')),
                    created_at TEXT NOT NULL, completed_at TEXT, latency_ms INTEGER,
                    reason_code TEXT, snapshot_json TEXT,
                    UNIQUE(owner_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS extraction_owner_time ON extraction_tasks(owner_id,created_at DESC,id DESC);
                CREATE INDEX IF NOT EXISTS extraction_time ON extraction_tasks(created_at DESC,id DESC);
                PRAGMA user_version=1;
            ''')
            initialize_reviews(conn)

    def recover(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT id FROM extraction_tasks WHERE status='processing'").fetchall()
            for row in rows:
                saved = self.artifacts(self.path.parent / 'jobs' / row['id'])
                conn.execute("UPDATE extraction_tasks SET status='interrupted',reason_code='service_restarted',completed_at=?,snapshot_json=? WHERE id=?",
                             (now(), json.dumps(saved, ensure_ascii=False), row['id']))

    @staticmethod
    def artifacts(artifact):
        saved = {}
        for name in ('configuration', 'evidence', 'diagnostics', 'result', 'progress'):
            path = artifact / (name + '.json')
            try:
                if path.exists():
                    saved[name] = json.loads(path.read_text(encoding='utf-8'))
            except ValueError:
                # Atomic checkpoints normally prevent this; keep other evidence
                # if a damaged checkpoint is encountered after a crash.
                continue
        return saved

    def by_key(self, owner, key):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM extraction_tasks WHERE owner_id=? AND request_key=?', (owner, key)).fetchone()
            return dict(row) if row else None

    def create(self, owner, key, fingerprint, source):
        record_id = str(uuid4())
        with self.connection() as conn:
            conn.execute('INSERT INTO extraction_tasks(id,owner_id,request_key,fingerprint,source_json,status,created_at) VALUES(?,?,?,?,?,?,?)',
                         (record_id, owner, key, fingerprint, json.dumps(source, ensure_ascii=False), 'processing', now()))
        return record_id

    def finish(self, record_id, state, reason, snapshot, latency):
        with self.connection() as conn:
            conn.execute('UPDATE extraction_tasks SET status=?,reason_code=?,snapshot_json=?,completed_at=?,latency_ms=? WHERE id=?',
                         (state, reason, json.dumps(snapshot, ensure_ascii=False), now(), latency, record_id))

    @staticmethod
    def public(row, detail=True):
        result = {k: row[k] for k in ('id', 'status', 'created_at', 'completed_at', 'latency_ms', 'reason_code')}
        result['source'] = json.loads(row['source_json'])
        result['message'] = ERROR_MESSAGES.get(row['reason_code'], '提取失败，请重新提交。') if row['reason_code'] else None
        if detail:
            result['snapshot'] = json.loads(row['snapshot_json']) if row['snapshot_json'] else None
            saved = result['snapshot'] or {}
            result['has_reviewable_result'] = result['status'] == 'completed' or (
                result['status'] in ('failed','interrupted') and row['reason_code'] != 'source_changed'
                and bool(result['source'].get('pdf_sha256'))
                and saved.get('evidence',{}).get('pdf_sha256') == result['source'].get('pdf_sha256')
                and bool(saved.get('result',{}).get('measurements')))
        return result

    def get(self, owner, record_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM extraction_tasks WHERE id=?', (record_id,)).fetchone()
            if row is None:
                return None
            result = self.public(row)
            result['can_review'] = row['owner_id'] == owner
            if result['status'] == 'processing':
                try:
                    progress = self.path.parent / 'jobs' / record_id / 'progress.json'
                    if progress.is_file():
                        result['progress'] = json.loads(progress.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
            result['reviews'] = self.reviews(record_id)
            result['review_summary'] = review_summary(result,result['reviews'])
            return result

    def list(self, owner, page, page_size, q=''):
        with self.connection() as conn:
            conn.execute('BEGIN')
            where="(instr(lower(json_extract(source_json,'$.filename')),lower(?))>0 OR instr(lower(json_extract(source_json,'$.table')),lower(?))>0)"
            values=(q,q)
            total = conn.execute('SELECT count(*) FROM extraction_tasks WHERE '+where,values).fetchone()[0]
            rows = conn.execute('SELECT * FROM extraction_tasks WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                                (*values, page_size, (page - 1) * page_size)).fetchall()
            return {'data': [self.public(r, False) for r in rows], 'pagination': {
                'page': page, 'page_size': page_size, 'total': total, 'total_pages': ceil(total / page_size)}}


def run_worker(config, path, source, artifact):
    mode = source.get('mode', 'table')
    timeout = config.document_extraction_timeout_seconds if mode == 'document' else config.extraction_timeout_seconds
    body = {'pdf_path': str(path), 'artifact_dir': str(artifact),
            'page': source['page'], 'table': source['table'], 'crop': source['crop'],
            'mode': mode, 'budget_seconds': timeout - 10}
    try:
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(BACKEND / 'extraction_worker.py')],
            input=json.dumps(body), text=True, encoding='utf-8', capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return json.loads(result.stdout) if result.returncode == 0 else {'ok': False, 'reason': 'worker_error'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'reason': 'timeout'}
    except (OSError, ValueError):
        return {'ok': False, 'reason': 'worker_error'}


class ExtractionRunner:
    def __init__(self, config):
        self.config = config
        self.root = config.root / 'extraction'
        self.store = ExtractionStore(self.root / 'records.sqlite3')
        self.process_lock = FileLock(str(self.root / '.process.lock'), thread_local=False)
        self.lock, self.slot = Lock(), BoundedSemaphore(1)
        self.executor = None
        self.save_errors = set()

    def ensure(self):
        if not self.config.enabled:
            raise HTTPException(503, '文献功能尚未启用。')
        with self.lock:
            if self.executor is not None:
                return
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                self.process_lock.acquire(timeout=0)
                self.store.initialize()
                self.store.recover()
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='literature-extraction')
            except (sqlite3.Error, OSError, LockTimeout):
                self.process_lock.release()
                raise HTTPException(503, '文献提取记录库不可用，请检查目录权限或是否启动了多个服务实例。') from None

    def database(self, method, *args):
        self.ensure()
        try:
            return method(*args)
        except (sqlite3.Error, OSError):
            raise HTTPException(503, '提取记录读取或保存失败。') from None

    def session(self, request, response):
        owner, token = self.database(self.store.session, request.cookies.get('fiber_extraction_session'))
        response.headers['Cache-Control'] = 'no-store'
        if token:
            response.set_cookie('fiber_extraction_session', token, httponly=True, samesite='lax',
                secure=request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https',
                path='/api/v1/literature/extractions', max_age=180 * 86400)
        return owner

    def perform(self, record_id, pdf, source, artifact, started):
        try:
            outcome = run_worker(self.config, pdf, source, artifact)
            snapshot = self.store.artifacts(artifact)
            success = outcome.get('ok') is True and 'result' in snapshot and 'evidence' in snapshot
            if success and snapshot['evidence']['pdf_sha256'] != source['pdf_sha256']:
                outcome = {'ok': False, 'reason': 'source_changed'}
                success = False
            reason = None if success else outcome.get('reason', 'worker_error')
            self.store.finish(record_id, 'completed' if success else 'failed', reason, snapshot,
                              int((perf_counter() - started) * 1000))
        except Exception:
            try:
                self.store.finish(record_id, 'failed', 'worker_error', {}, int((perf_counter() - started) * 1000))
            except (sqlite3.Error, OSError):
                with self.lock:
                    self.save_errors.add(record_id)
        finally:
            self.slot.release()

    def submit(self, owner, key, source, content, started):
        fingerprint = sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        with self.lock:
            existing = self.store.by_key(owner, key)
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise HTTPException(409, '同一提交编号不能用于不同文件或提取参数。')
                return existing['id']
            if not self.slot.acquire(blocking=False):
                raise HTTPException(429, '已有文献提取正在处理，请稍后提交。')
            record_id = None
            try:
                pdf = self.root / 'pdfs' / (source['pdf_sha256'] + '.pdf')
                pdf.parent.mkdir(exist_ok=True)
                if not pdf.exists():
                    # Hash-addressed names cannot contain uploaded path components.
                    temp = pdf.with_suffix('.tmp')
                    temp.write_bytes(content)
                    temp.replace(pdf)
                record_id = self.store.create(owner, key, fingerprint, source)
                artifact = self.root / 'jobs' / record_id
                artifact.mkdir(parents=True)
                self.executor.submit(self.perform, record_id, pdf, source, artifact, started)
                return record_id
            except Exception:
                self.slot.release()
                if record_id:
                    self.store.finish(record_id, 'failed', 'worker_error', {}, int((perf_counter() - started) * 1000))
                raise

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True)
            self.executor = None
            self.process_lock.release()


def router(config, check_origin):
    runner = ExtractionRunner(config)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            runner.close()

    routes = APIRouter(prefix='/extractions', tags=['literature-extraction'], lifespan=lifespan)

    def detail(owner, record_id):
        result = runner.database(runner.store.get, owner, record_id)
        if result is None:
            raise HTTPException(404, '没有找到这条提取记录。')
        if record_id in runner.save_errors:
            raise HTTPException(503, '提取结果保存失败，请重新提交。')
        return result

    @routes.post('', openapi_extra={'requestBody': {'required': True, 'content': {
        'application/pdf': {'schema': {'type': 'string', 'format': 'binary'}}}}})
    async def submit(request: Request, response: Response, page: int | None = Query(None, ge=1, le=200),
                     table: str | None = Query(None, min_length=1, max_length=60, pattern=r'(?i)^table\s+\d+[a-z]?$'),
                     mode: Literal['document', 'table'] | None = Query(None),
                     request_id: UUID = Query(default_factory=uuid4),
                     filename: str = Query('paper.pdf', min_length=1, max_length=200),
                     crop: str | None = Query(None, max_length=100)):
        started = perf_counter()
        check_origin(request)
        mode = mode or ('table' if page is not None or table is not None else 'document')
        if mode == 'table' and (page is None or table is None):
            raise HTTPException(422, '指定表格模式需要页码和表格编号。')
        if mode == 'document' and (page is not None or table is not None or crop is not None):
            raise HTTPException(422, '整篇自动模式不需要页码、表格编号或裁剪区域。')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/pdf':
            raise HTTPException(415, '请以application/pdf提交PDF文件。')
        bounds = None
        if crop:
            try:
                bounds = [float(x) for x in crop.split(',')]
                if len(bounds) != 4 or not all(isfinite(x) for x in bounds) or not (0 <= bounds[0] < bounds[2] and 0 <= bounds[1] < bounds[3]):
                    raise ValueError
            except ValueError:
                raise HTTPException(422, '表格区域必须为x0,top,x1,bottom四个有效坐标。') from None
        runner.ensure()
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_PDF_BYTES:
                raise HTTPException(413, 'PDF不能超过12MB。')
        if not content.startswith(b'%PDF-'):
            raise HTTPException(422, '提交内容不是PDF。')
        owner = runner.session(request, response)
        source = {'filename': filename.replace('\\', '/').split('/')[-1],
                  'pdf_sha256': sha256(content).hexdigest(), 'page': page,
                  'table': table.strip() if table else '全文自动', 'crop': bounds, 'mode': mode}
        try:
            record_id = runner.database(runner.submit, owner, str(request_id), source, bytes(content), started)
        except HTTPException:
            raise
        result = detail(owner, record_id)
        response.status_code = 202 if result['status'] == 'processing' else 200
        return result

    @routes.get('')
    def listing(request: Request, response: Response, page: int = Query(1, ge=1, le=100000), page_size: int = Query(10, ge=1, le=100), q: str = Query('',max_length=200)):
        owner = runner.session(request, response)
        return runner.database(runner.store.list, owner, page, page_size,q)

    @routes.get('/{record_id}')
    def get(record_id: UUID, request: Request, response: Response):
        owner = runner.session(request, response)
        return detail(owner, str(record_id))

    @routes.get('/{record_id}/pdf')
    def pdf(record_id: UUID, request: Request):
        headers = Response()
        owner = runner.session(request, headers)
        item = detail(owner, str(record_id))
        path = runner.root / 'pdfs' / (item['source']['pdf_sha256'] + '.pdf')
        if not path.is_file():
            raise HTTPException(404, '原文PDF暂不可用。')
        response_headers = {k: v for k, v in headers.headers.items() if k != 'content-length'}
        return FileResponse(path, media_type='application/pdf', headers=response_headers,
                            filename=item['source']['filename'], content_disposition_type='inline')

    @routes.get('/{record_id}/export')
    def export(record_id: UUID, request: Request):
        headers = Response()
        owner = runner.session(request, headers)
        item = detail(owner, str(record_id))
        response_headers = {k: v for k, v in headers.headers.items() if k != 'content-length'}
        return Response(json.dumps(item, ensure_ascii=False) + '\n', media_type='application/x-ndjson',
                        headers={**response_headers, 'Content-Disposition': 'attachment; filename="literature-extraction.jsonl"'})

    @routes.get('/{record_id}/page')
    def page_image(record_id: UUID,request: Request, page: int | None = Query(None,ge=1,le=200)):
        holder=Response()
        owner=runner.session(request,holder)
        item=detail(owner,str(record_id))
        source=item['source']
        page_no = page or source.get('page')
        if page_no is None:
            raise HTTPException(422,'请选择一条候选数据查看对应原文页。')
        evidence = (item.get('snapshot') or {}).get('evidence', {})
        if evidence.get('page_count') and page_no > evidence['page_count']:
            raise HTTPException(422,'原文页码超出范围。')
        image=runner.root/'jobs'/str(record_id)/f'page-{page_no}.png'
        if not image.exists():
            pdf=runner.root/'pdfs'/(source['pdf_sha256']+'.pdf')
            try:
                result=subprocess.run([sys.executable,'-I',str(BACKEND/'extraction_page_worker.py'),str(pdf),str(page_no),str(image)],
                    capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode or not image.exists():
                    raise HTTPException(422,'该页无法预览，请查看完整PDF。')
            except (OSError,subprocess.TimeoutExpired):
                raise HTTPException(503,'原文预览暂时不可用。') from None
        headers={k:v for k,v in holder.headers.items() if k!='content-length'}
        return FileResponse(image,media_type='image/png',headers=headers)

    from .extraction_review import router as review_router
    routes.include_router(review_router(runner,detail,check_origin))

    return routes
