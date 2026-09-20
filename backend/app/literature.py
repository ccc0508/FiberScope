"""Read-only literature catalogue and bounded document-QA worker."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[1]


class LiteratureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / '.env.literature', env_prefix='LITERATURE_', extra='ignore')
    enabled: bool = False
    data_dir: Path = BACKEND.parent / '.rag-data'
    timeout_seconds: int = Field(90, ge=5, le=90)

    @property
    def root(self) -> Path:
        return (BACKEND / self.data_dir).resolve()


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=2000)


@contextmanager
def connect(config: LiteratureSettings):
    path = config.root / 'metadata.sqlite3'
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
        path = config.root / path
    path = path.resolve()
    if not path.is_relative_to((config.root / 'papers').resolve()) or path.suffix.lower() != '.pdf' or not path.is_file():
        raise HTTPException(404, '文献原文件暂不可用。')
    return path, row['filename']


def run_answer(config: LiteratureSettings, question: str):
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-X', 'utf8', str(BACKEND / 'literature_worker.py')],
            input=json.dumps({'question': question, 'data_dir': str(config.root)}, ensure_ascii=False),
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
        if body['status'] not in ('answered', 'refused') or not isinstance(body['citations'], list):
            raise ValueError()
        return body
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, '文献问答响应无法读取，请稍后重试。') from None


def router(config: LiteratureSettings | None = None):
    config = config or LiteratureSettings()
    routes = APIRouter(prefix='/api/v1/literature', tags=['literature'])
    slot = BoundedSemaphore(1)

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
    def ask(body: Question):
        if not config.enabled:
            raise HTTPException(503, '文献问答尚未启用。')
        if not slot.acquire(blocking=False):
            raise HTTPException(429, '已有文献问答正在处理，请稍后再试。')
        try:
            if not documents(config):
                return {'status': 'refused', 'answer': '文献库中暂无已完成导入的文献，请先补充文献。', 'citations': [], 'latency_ms': 0}
            return run_answer(config, body.question)
        finally:
            slot.release()

    return routes
