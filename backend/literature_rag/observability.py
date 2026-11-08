"""Optional live checkpoint projection. Local records remain authoritative."""
import logging
import os
import re
from pathlib import Path
from threading import Thread

log = logging.getLogger(__name__)


def redact(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'api.?key|secret|authorization|password|bearer', k, re.I)
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'\bsk-[A-Za-z0-9_.-]+', '[REDACTED]', value)
        value = re.sub(r'data:image/[^\s"\']+', '[IMAGE OMITTED]', value)
    return value


class LangfuseTrace:
    def __init__(self, client=None, model=None):
        self.client, self.model = client, model
        self.root = None
        self.nodes = {}
        self.ended = set()
        self.disabled = False
        self.url = None

    @classmethod
    def configured(cls, root, model=None):
        try:
            from dotenv import dotenv_values
            config = {**dotenv_values(Path(root)/'backend/.env.langfuse', encoding='utf-8-sig'), **os.environ}
            if config.get('LANGFUSE_ENABLED', 'false').lower() != 'true':
                return cls()
            from langfuse import Langfuse
            return cls(Langfuse(public_key=config['LANGFUSE_PUBLIC_KEY'],
                               secret_key=config['LANGFUSE_SECRET_KEY'],
                               base_url=config['LANGFUSE_BASE_URL'], timeout=5), model)
        except Exception as error:
            log.warning('Langfuse initialization unavailable: %s', type(error).__name__)
            return cls()

    def node(self, key, parent, name, kind, input=None):
        if key not in self.nodes:
            self.nodes[key] = parent.start_observation(name=name, as_type=kind, input=redact(input))
        return self.nodes[key]

    def end(self, key, node):
        if key not in self.ended:
            node.end()
            self.ended.add(key)

    def update(self, state):
        if not self.client or self.disabled:
            return
        try:
            self._update(state)
        except Exception as error:
            self.disabled = True
            log.warning('Langfuse projection disabled: %s', type(error).__name__)

    def _update(self, state):
        if not self.root:
            self.root = self.client.start_observation(name='FiberScope question', as_type='agent',
                input=redact(state.get('question')), metadata={'run_id': state['run_id'],
                'pipeline_version': state.get('pipeline_version'), 'source': 'live-checkpoints'})
            self.url = self.client.get_trace_url(trace_id=self.root.trace_id)
        parents = {}
        for child in state.get('children', []):
            key = 'child:'+child['id']
            node = self.node(key, self.root, child['role']+' agent', 'agent', child.get('task'))
            parents[child['role']] = node
            parents[child['id']] = node
            node.update(output=redact(child.get('result')), metadata=redact({
                'status': child['status'], 'coverage': child.get('coverage_report'),
                'allocation': child.get('allocation'),
                'evidence_delivery': [{k:e.get(k) for k in ('request','model_delivery')}
                    for e in child.get('trace',{}).get('tool_calls',[])]}))
        for i, call in enumerate(state.get('model_calls', [])):
            key = f'model:{i}'
            if key in self.ended:
                continue
            node = self.node(key, parents.get(call.get('stage'), self.root),
                             call.get('stage', 'model'), 'generation', call.get('input_messages'))
            usage = call.get('usage') or {}
            counts = {k: usage[v] for k, v in [('input','prompt_tokens'), ('output','completion_tokens')]
                      if isinstance(usage.get(v), int)}
            node.update(model=self.model, output=redact({k: call.get(k) for k in ('text','calls','raw_message')}),
                        usage_details=counts or None, metadata=redact({k: call.get(k) for k in
                        ('status','finish_reason','error_type','available_tools','usage')}),
                        level='ERROR' if call['status']=='failed' else 'DEFAULT')
            if call['status'] != 'started':
                self.end(key, node)
        for i, call in enumerate(state.get('tool_calls', [])):
            key = f'tool:{i}'
            if key in self.ended:
                continue
            node = self.node(key, parents.get(call.get('child_id'), self.root),
                             call['request']['tool'], 'tool', call['request'])
            node.update(output=redact(call.get('result')), metadata=redact({
                'status':call['status'], 'error_type':call.get('error_type'),
                'model_delivery':call.get('model_delivery')}),
                level='ERROR' if call['status']=='failed' else 'DEFAULT')
            if call['status'] != 'started':
                self.end(key,node)
        self.root.update(output=redact(state.get('answer')), metadata=redact({
            'status':state['status'], 'budget':state.get('budget_usage'),
            'plan':state.get('plan'), 'stop_reason':state.get('stop_reason'),
            'citation_validation':state.get('citation_validation')}))
        if state['status'] != 'running':
            self.close()

    def close(self):
        try:
            for key, node in reversed(list(self.nodes.items())):
                self.end(key,node)
            if self.root:
                self.end('root',self.root)
        except Exception as error:
            log.warning('Langfuse close unavailable: %s', type(error).__name__)

    def flush(self):
        if self.client:
            def send():
                try:
                    self.client.flush()
                except Exception as error:
                    log.warning('Langfuse flush unavailable: %s',type(error).__name__)
            thread=Thread(target=send, daemon=True)
            thread.start()
            thread.join(timeout=5)
