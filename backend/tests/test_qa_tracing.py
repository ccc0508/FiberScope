import time
from types import SimpleNamespace
from threading import Event
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import literature, qa_tracing
from tests.test_literature_api import configured, finished


class Node:
    def __init__(self, nodes, parent=None, **values):
        self.nodes=nodes; self.values=values; self.parent=parent
        self.trace_id=parent.trace_id if parent else 'a'*32
        self.id=f'{len(nodes)+1:016x}'; self.end_time=None
        nodes.append(self)
    def start_observation(self, **values):return Node(self.nodes,self,**values)
    def update(self, **values):self.values.update(values)
    def end(self):self.end_time=time.monotonic()


def test_accepted_job_survives_http_response_and_keeps_trace(configured,monkeypatch):
    nodes=[]; client=Node(nodes)
    monkeypatch.setattr(qa_tracing,'telemetry',lambda:SimpleNamespace(client=client))
    monkeypatch.setattr(qa_tracing,'history_context',lambda path:{'trace_id':'a'*32,'parent_span_id':'1'*16})
    gate=Event(); seen=[]
    def answer(*args):
        seen.append(qa_tracing.context())
        gate.wait(3)
        return dict(status='answered',answer='fixture',citations=[])
    monkeypatch.setattr(literature,'run_answer',answer)
    app=FastAPI();app.add_middleware(qa_tracing.QATraceMiddleware);app.include_router(literature.router(configured))
    with TestClient(app) as http:
        response=http.post('/api/v1/literature/ask',json={'question':'tracing fixture'})
        assert response.status_code==202
        root=next(n for n in nodes if n.values.get('name')=='HTTP POST /api/v1/literature/ask')
        assert root.end_time is not None
        gate.set(); result=finished(http,response.json()['id'])
        assert result['status']=='answered'
        assert result['configuration']['observability']['trace_id']==root.trace_id
        assert seen[0]['trace_id']==root.trace_id
        names=[n.values.get('name') for n in nodes]
        assert 'qa.create_record' in names and 'qa.save_result' in names and 'qa.read_history' in names
        job=next(n for n in nodes if n.values.get('name')=='qa.background_job')
        assert job.end_time>=root.end_time


def test_invalid_http_body_still_traced_without_sensitive_headers(configured,monkeypatch):
    nodes=[]; client=Node(nodes)
    monkeypatch.setattr(qa_tracing,'telemetry',lambda:SimpleNamespace(client=client))
    app=FastAPI();app.add_middleware(qa_tracing.QATraceMiddleware);app.include_router(literature.router(configured))
    with TestClient(app) as http:
        response=http.post('/api/v1/literature/ask',json={},headers={'Authorization':'secret'})
        assert response.status_code==422
    assert nodes[-1].values['metadata']['http_status']==422
    assert 'secret' not in str([n.values for n in nodes])
