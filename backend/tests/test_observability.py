from literature_rag.observability import LangfuseTrace, redact


class Node:
    trace_id = 'test-trace'
    def __init__(self, **kwargs):
        self.values = kwargs
        self.children = []
        self.ends = 0
    def start_observation(self, **kwargs):
        n = Node(**kwargs)
        self.children.append(n)
        return n
    def update(self, **kwargs):
        assert not self.ends
        self.values.update(kwargs)
    def end(self, **kwargs):
        self.ends += 1
        self.end_time=kwargs.get('end_time')
    def get_trace_url(self, **kwargs):
        return 'https://example.test/trace'


def test_projection_parentage_usage_and_no_duplicate_model_calls():
    c=Node(); t=LangfuseTrace(c,'model')
    s=dict(run_id='r',question='q',status='running',children=[dict(id='r/literature',
        role='literature',task='task',status='running')],model_calls=[dict(stage='literature',
        status='started',input_messages=['q'])],tool_calls=[])
    t.update(s)
    s['model_calls'][0].update(status='completed',text='a',usage={'prompt_tokens':12,'completion_tokens':3})
    t.update(s);t.update(s)
    generation=t.nodes['model:0']
    assert generation in t.nodes['child:r/literature'].children
    assert generation.values['usage_details']=={'input':12,'output':3}
    assert generation.ends==1
    s.update(status='completed',answer='a');t.update(s)
    assert not t.disabled and t.root.ends==1


def test_observability_failure_is_isolated():
    class Broken:
        def start_observation(self,**kwargs):raise RuntimeError('network')
    t=LangfuseTrace(Broken())
    t.update(dict(run_id='r',question='q'))
    assert t.disabled


def test_private_fields_and_images_redacted():
    x=redact({'api_key':'secret','text':'sk-example-secret', 'image':'data:image/png;base64,AAAA'})
    assert x=={'api_key':'[REDACTED]','text':'[REDACTED]','image':'[IMAGE OMITTED]'}


def test_child_closes_before_parent_synthesis():
    t=LangfuseTrace(Node(),'model')
    child=dict(id='r/literature',role='literature',status='running')
    s=dict(run_id='r',status='running',children=[child],model_calls=[],tool_calls=[])
    t.update(s)
    child.update(status='completed',ended_at_ns=123,duration_ms=12)
    t.update(s)
    node=t.nodes['child:r/literature']
    assert node.ends==1 and node.end_time==123 and t.root.ends==0
    s['model_calls']=[dict(stage='synthesis_review',status='completed',text='answer')]
    t.update(s)
    assert not t.disabled and node.ends==1


def test_internal_stages_record_failures_and_retrieval_boundaries():
    import pytest
    from literature_rag.stage_trace import StageTrace, stage
    from tests.test_literature_retrieval import make_chunk, ScriptedVectorStore
    from tests.literature_fakes import InMemoryMetadataStore, SpyEmbedder
    from literature_rag.domain.models import VectorMatch
    from literature_rag.application.retrieve import RetrievalService
    metadata=InMemoryMetadataStore();chunk=make_chunk();metadata.chunks[chunk.id]=chunk
    service=RetrievalService(metadata,ScriptedVectorStore([VectorMatch(chunk.id,0.9)]),SpyEmbedder())
    with StageTrace() as trace:
        answer=service.retrieve('fiber',8,0.35)
        with pytest.raises(ValueError):
            with stage('test_failure'):
                raise ValueError('do not persist raw exception')
    assert answer[0].chunk_id==chunk.id
    assert [r['name'] for r in trace.records][:6]==['retrieval.embedding','retrieval.vector_search',
        'retrieval.filter_deduplicate','retrieval.metadata','retrieval.select_seeds','retrieval.context_assembly']
    assert all(r['duration_ms']>=0 and r['ended_at_ns']>=r['started_at_ns'] for r in trace.records)
    assert trace.records[-1]['status']=='failed' and trace.records[-1]['error_type']=='ValueError'


def test_invalid_sql_records_validation_failure_without_connecting(tmp_path,monkeypatch):
    from literature_rag.stage_trace import StageTrace
    from literature_rag.application.tools import ToolTraceStore
    from app import experiment_sql
    monkeypatch.setattr(experiment_sql,'connect',lambda: (_ for _ in ()).throw(AssertionError()))
    store=ToolTraceStore(tmp_path/'trace.sqlite3')
    with StageTrace():
        result=experiment_sql.execute({'tool':'query_experiment_data','sql':'DELETE FROM fiber.v_sample_overview','reason':'test'},'r',store)
    assert result['status']=='failed'
    assert store.read('r')[0]['internal_steps'][0]['name']=='sql.validation'
    assert store.read('r')[0]['internal_steps'][0]['status']=='failed'
