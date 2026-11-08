"""Best-effort HTTP/job tracing; no cookies, headers or request bodies exported."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import asyncio
import json
import re
from literature_rag.observability import LangfuseTrace, redact

current = ContextVar('qa_trace_node', default=None)


@lru_cache(maxsize=1)
def telemetry():
    return LangfuseTrace.configured(Path(__file__).resolve().parents[2])


def context():
    node=current.get()
    return {'trace_id':node.trace_id,'parent_span_id':node.id} if node else None


def history_context(path):
    match=re.fullmatch(r'/api/v1/literature/history/([a-f0-9]{32})',path)
    if not match:return None
    try:
        from .literature import LiteratureSettings
        import sqlite3
        file=LiteratureSettings().root/'qa_history.sqlite3'
        with sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True,timeout=1) as db:
            row=db.execute('SELECT configuration_json FROM questions WHERE id=?',(match[1],)).fetchone()
        return json.loads(row[0]).get('observability') if row else None
    except Exception:return None


@contextmanager
def step(name, **metadata):
    node=None
    try:
        parent=current.get()
        if parent:node=parent.start_observation(name=name,as_type='span',metadata=redact(metadata))
    except Exception:pass
    token=current.set(node or current.get())
    try:
        yield node
    except BaseException as error:
        if node:
            try:node.update(level='ERROR',status_message=type(error).__name__)
            except Exception:pass
        raise
    finally:
        current.reset(token)
        if node:
            try:node.end()
            except Exception:pass


class QATraceMiddleware:
    def __init__(self, app):self.app=app

    async def __call__(self, scope, receive, send):
        path=scope.get('path','')
        if scope['type']!='http' or not (path=='/api/v1/literature/ask' or path.startswith('/api/v1/literature/history/')):
            return await self.app(scope,receive,send)
        node=None
        try:
            client=telemetry().client
            inherited=await asyncio.to_thread(history_context,path) if client else None
            if client:node=client.start_observation(trace_context=inherited,name='HTTP '+scope['method']+' '+path,
                as_type='span',metadata={'method':scope['method'],'path':path})
        except Exception:pass
        token=current.set(node)
        async def traced_send(message):
            if node and message['type']=='http.response.start':
                try:node.update(metadata={'http_status':message['status']})
                except Exception:pass
            await send(message)
        try:
            await self.app(scope,receive,traced_send)
        except BaseException as error:
            if node:
                try:node.update(level='ERROR',status_message=type(error).__name__)
                except Exception:pass
            raise
        finally:
            current.reset(token)
            if node:
                try:node.end()
                except Exception:pass
