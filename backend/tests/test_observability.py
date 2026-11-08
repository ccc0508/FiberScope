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
    def end(self):
        self.ends += 1
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
