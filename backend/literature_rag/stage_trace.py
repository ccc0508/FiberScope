"""Measured internal stages; optional remote parent supplied by the tool caller."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter_ns, time_ns
from uuid import uuid4
from .observability import redact

_collector = ContextVar('stage_collector', default=None)
_parent = ContextVar('stage_parent', default=None)


class StageTrace:
    def __init__(self, client=None, trace_context=None):
        self.client, self.context = client, trace_context
        self.records = []

    def __enter__(self):
        self.token = _collector.set(self)
        return self

    def __exit__(self, *args):
        _collector.reset(self.token)


def records():
    c = _collector.get()
    return list(c.records) if c else []


@contextmanager
def stage(name, **inputs):
    collector = _collector.get()
    if collector is None:
        yield {}
        return
    parent = _parent.get()
    record = dict(id=str(uuid4()), parent_id=parent[0] if parent else None,
                  name=name, status='started', started_at_ns=time_ns(), input=redact(inputs))
    collector.records.append(record)
    node = None
    try:
        if parent and parent[1]:
            node = parent[1].start_observation(name=name, as_type='span', input=redact(inputs))
        elif collector.client and collector.context:
            node = collector.client.start_observation(name=name, as_type='span',
                trace_context=collector.context, input=redact(inputs))
    except Exception:
        pass  # Tracing cannot affect tool execution.
    token = _parent.set((record['id'], node))
    started = perf_counter_ns()
    output = {}
    try:
        yield output
        record['status'] = 'completed'
    except BaseException as error:
        record.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        record.update(ended_at_ns=time_ns(), duration_ms=(perf_counter_ns()-started)/1e6,
                      output=redact(output))
        _parent.reset(token)
        if node:
            try:
                node.update(output=record['output'], metadata={k:record[k] for k in
                    ('status','duration_ms','started_at_ns','ended_at_ns')},
                    level='ERROR' if record['status']=='failed' else 'DEFAULT',
                    status_message=record.get('error_type'))
                node.end(end_time=record['ended_at_ns'])
            except Exception:
                pass
