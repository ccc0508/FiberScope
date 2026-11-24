"""Opt-in bounded native-tool agent. Keeps the website's existing pipeline unchanged."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import os
import signal
import sys
from time import monotonic
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.agent_loop import AgentLoop,AgentBudget
from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
from literature_rag.config import Settings
from literature_rag.application.tools import SEARCH_HITS_PER_DOCUMENT, ToolTraceStore
from literature_rag.stage_trace import StageTrace, stage
from literature_rag.application.paper_directory import load_paper_directory
from literature_rag.state_io import save_state


def finalize_shared_search(records, run_id, timeout, *, assemble):
    """Select one distinct hit per query in rank order before filling the remaining quota."""
    ranked = [iter(record['candidate_evidence']) for record in records]
    seeds, owners = [], {}
    while len(seeds) < SEARCH_HITS_PER_DOCUMENT:
        previous_size = len(seeds)
        for owner, candidates in enumerate(ranked):
            candidate = next((row for row in candidates if row['chunk_id'] not in owners), None)
            if candidate is not None:
                owners[candidate['chunk_id']] = owner
                seeds.append({**candidate, 'ref': f'[{len(seeds) + 1}]'})
            if len(seeds) == SEARCH_HITS_PER_DOCUMENT:
                break
        if len(seeds) == previous_size:
            break

    shared_ids = [s['chunk_id'] for s in seeds]
    call_ids = [record['call_id'] for record in records]
    output = (assemble(seeds, ' '.join(record['input']['query'] for record in records), run_id, timeout)
              if seeds else {})
    result = output.get('result', {})
    if seeds and 'evidence' not in result:
        error = output.get('error_code', 'shared_context_failed')
        for record in records:
            record.update(status='failed', error_code=error)
            record.pop('result', None)
            record.pop('result_sha256', None)
        return
    evidence_by_owner = defaultdict(list)
    for evidence in result.get('evidence', []):
        # A section can merge several hits, and a linked table can have its own
        # chunk ID. Both retain their original hit IDs.
        source_ids = [evidence['chunk_id'], *evidence.get('seed_chunk_ids', [])]
        for owner in sorted({owners[chunk_id] for chunk_id in source_ids if chunk_id in owners}):
            evidence_by_owner[owner].append(evidence)
    for owner, record in enumerate(records):
        chosen = [s for s in seeds if owners[s['chunk_id']] == owner]
        with StageTrace() as trace:
            with stage('retrieval.select_seeds', top_k=SEARCH_HITS_PER_DOCUMENT,
                       max_seeds_per_document=SEARCH_HITS_PER_DOCUMENT, shared_call_ids=call_ids) as event:
                event['selected_ids'] = [s['chunk_id'] for s in chosen]
                event['shared_selected_ids'] = shared_ids
        record['seed_evidence'] = chosen
        record['internal_steps'].extend(trace.records)
        record['diagnostics']['last_context_diagnostics'] = output.get('context_diagnostics', {})
        rank_diagnostics = record['diagnostics'].get('last_rerank_diagnostics') or {}
        if rank_diagnostics:
            selected = {s['chunk_id'] for s in chosen}
            rank_diagnostics['selected_chunk_ids'] = [s['chunk_id'] for s in chosen]
            for item in rank_diagnostics['candidates']:
                item['selected'] = item['chunk_id'] in selected
        if owner == 0:
            record['internal_steps'].extend(output.get('internal_steps', []))
        record['result'].update(result, evidence=evidence_by_owner[owner], shared_search={
            'call_ids': call_ids, 'selected_chunk_ids': shared_ids,
            'notice': 'These same-paper queries share a single evidence pool. Read the other results in this group.',
        })


def execute_parallel_searches(executions, run_id, timeout, *, execute, trace_store, tool_context,
                              assemble=None):
    # Each subprocess has its own retriever. Register final evidence in request order.
    deadline = monotonic() + timeout
    contexts = [tool_context(index=index) for _, index in executions]
    document_counts = Counter(request.get('document_id') for request, _ in executions)

    def search(request, context):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return dict(status='failed', error_code='tool_timeout')
        document = request.get('document_id')
        shared = assemble is not None and document and document_counts[document] > 1
        return execute(request, run_id, remaining, context=context, defer_search_registration=True,
                       **({'rank_search_only': True} if shared else {}))

    with ThreadPoolExecutor(max_workers=min(5, len(executions))) as pool:
        futures = [pool.submit(search, request, context)
                   for (request, _), context in zip(executions, contexts, strict=True)]
        results = [future.result() for future in futures]
        batches = defaultdict(list)
        for (request, _), result in zip(executions, results, strict=True):
            record = result.get('deferred_search_record')
            document = request.get('document_id')
            if record is not None and assemble is not None and document and document_counts[document] > 1:
                batches[document].append(record)
        assemblies = [pool.submit(finalize_shared_search, records, run_id, deadline - monotonic(), assemble=assemble)
                      for records in batches.values()]
        for future in assemblies:
            future.result()
    for result in results:
        record = result.get('deferred_search_record')
        if record is not None:
            if record['status'] == 'completed':
                trace_store.complete(record)
                result = dict(call_id=record['call_id'], status=record['status'], result=record['result'])
            else:
                trace_store.save(record)
                result = dict(call_id=record['call_id'], status=record['status'], error_code=record['error_code'])
        yield result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--question',required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=None);p.add_argument('--max-tools',type=int,default=None)
    p.add_argument('--max-model-calls',type=int,default=None);p.add_argument('--run-id',default=None)
    p.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--prompt-file',type=Path,help='Evaluation only: frozen PROMPT and REVIEW_PROMPT JSON; does not change website defaults')
    p.add_argument('--architecture',choices=['single','specialists'],default='single')
    p.add_argument('--no-task-feedback',action='store_true',help='Specialists only: limit each selected role to one invocation for comparison.')
    a=p.parse_args();run_id=a.run_id or str(uuid4())
    if a.no_task_feedback and a.architecture!='specialists':p.error('--no-task-feedback requires --architecture specialists')
    if a.max_model_calls is None:a.max_model_calls=20 if a.architecture=='specialists' else 10
    if a.seconds is None:a.seconds=360 if a.architecture=='specialists' else 240
    if a.max_tools is None:a.max_tools=12 if a.architecture=='specialists' else 8
    if not run_id.replace('-','').replace('_','').isalnum() or len(run_id)>100:raise ValueError('Invalid run ID')
    b=AgentBudget(total_seconds=a.seconds,max_tool_calls=a.max_tools,max_model_calls=a.max_model_calls,
        reserve_seconds=min(45,a.seconds/3))
    out=ROOT/'.rag-data/agent-runs'/run_id;state_path=out/'state.json'
    if not a.child:
        if out.exists():raise ValueError('Run already exists; inspect it, do not replay paid requests')
        out.mkdir(parents=True)
        args=[sys.executable,'-X','utf8',__file__,'--child','--run-id',run_id,'--question',a.question,
            '--library',str(a.library.resolve()),'--seconds',str(a.seconds),'--max-tools',str(a.max_tools),
            '--max-model-calls',str(a.max_model_calls)]
        args.extend(['--architecture',a.architecture])
        if a.no_task_feedback:args.append('--no-task-feedback')
        if a.prompt_file:args.extend(['--prompt-file',str(a.prompt_file.resolve())])
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=os.name!='nt',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            stdout,stderr=proc.communicate(timeout=a.seconds+5)
            (out/'worker.stdout.log').write_bytes(stdout)
            (out/'worker.stderr.log').write_bytes(stderr)
            if proc.returncode:
                state=json.loads(state_path.read_text('utf-8')) if state_path.exists() else dict(run_id=run_id,answer='')
                state.update(status='failed',stop_reason='worker_process_failed',worker_returncode=proc.returncode,
                             diagnostic_file='worker.stderr.log',previous_stop_reason=state.get('stop_reason'))
                save_state(state_path,state)
                raise RuntimeError('Agent worker failed; inspect worker.stderr.log and state-errors.log')
        except subprocess.TimeoutExpired:
            # Kill the process tree on Windows, including any outstanding tool worker.
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
            else:os.killpg(proc.pid,signal.SIGKILL)
            stdout,stderr=proc.communicate()
            (out/'worker.stdout.log').write_bytes(stdout)
            (out/'worker.stderr.log').write_bytes(stderr)
            state=json.loads(state_path.read_text('utf-8')) if state_path.exists() else dict(run_id=run_id,answer='')
            state.update(status='partial' if state.get('answer') else 'failed',stop_reason='hard_deadline')
            save_state(state_path,state)
        print(json.dumps(dict(run_id=run_id,state_file=str(state_path)),ensure_ascii=False));return
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    from literature_rag.observability import LangfuseTrace
    telemetry=LangfuseTrace.configured(ROOT, settings.llm_model)
    prompt_identity=None
    if a.prompt_file:
        if a.architecture!='single':raise ValueError('Prompt overrides apply only to frozen single-agent evaluation')
        from hashlib import sha256
        import literature_rag.application.agent_loop as loop_module
        raw=a.prompt_file.read_bytes();prompts=json.loads(raw)
        if set(prompts)!={'PROMPT','REVIEW_PROMPT'} or any(not isinstance(v,str) or not v.strip() for v in prompts.values()):
            raise ValueError('Invalid frozen prompts')
        loop_module.PROMPT=prompts['PROMPT'];loop_module.REVIEW_PROMPT=prompts['REVIEW_PROMPT']
        prompt_identity=dict(file=str(a.prompt_file.resolve()),sha256=sha256(raw).hexdigest())
    def checkpoint(state):
        payload=dict(state,budget=asdict(b),model=settings.llm_model,prompt_override=prompt_identity,mode=a.architecture,
            task_feedback_enabled=a.architecture=='specialists' and not a.no_task_feedback,
            model_options=dict(thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort),
            review_policy=('parent synthesis and evidence review' if a.architecture=='specialists'
                           else 'same-context evidence review' if a.prompt_file
                           else 'no full-answer review; evidence check and citation validation still apply'))
        save_state(state_path,payload)
        telemetry.update(payload)
        if telemetry.url:
            try:
                (out/'langfuse.json').write_text(json.dumps({'url':telemetry.url},ensure_ascii=False),encoding='utf8')
            except OSError:
                pass  # Optional remote link must never fail the local answer.
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')

    def worker(body, timeout, context=None):
        if timeout <= 0:
            return dict(status='failed', error_code='tool_timeout')
        body['data_dir'] = str(a.library.resolve())
        if context:
            body['trace_context'] = context
        try:
            r=subprocess.run([sys.executable,'-I','-X','utf8',str(ROOT/'backend/literature_worker.py')],
                input=json.dumps(body,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=timeout,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return json.loads(r.stdout) if r.returncode==0 else dict(status='failed',error_code='worker_failed')
        except subprocess.TimeoutExpired:return dict(status='failed',error_code='tool_timeout')
        except (json.JSONDecodeError, OSError):return dict(status='failed',error_code='worker_failed')

    def execute(request, rid, timeout, *, context=None, defer_search_registration=False, rank_search_only=False):
        body = dict(tool_call=request, run_id=rid, defer_search_registration=defer_search_registration,
                    rank_search_only=rank_search_only)
        return worker(body, timeout, context if defer_search_registration else telemetry.active_tool_context())

    def assemble(seeds, query, rid, timeout):
        return worker(dict(assemble_scoped_search=dict(seeds=seeds, query=query), run_id=rid), timeout)

    def parallel_search(executions, rid, timeout):
        return execute_parallel_searches(executions, rid, timeout, execute=execute,
                                         trace_store=store, tool_context=telemetry.active_tool_context, assemble=assemble)

    directory=load_paper_directory(a.library)
    loop=AgentLoop
    if a.architecture=='specialists':
        from literature_rag.application.specialist_agent import ResultDrivenCoordinator
        loop=ResultDrivenCoordinator
    try:
        from literature_rag.adapters.providers.jev_evidence import JevEvidenceJudge
        unified = a.architecture == 'single' and not a.prompt_file
        options=(dict(feedback_enabled=not a.no_task_feedback) if a.architecture=='specialists'
                 else dict(unified_research=bool(unified),
                           evidence_judge=JevEvidenceJudge.configured(ROOT) if unified else None,
                           parallel_search_executor=parallel_search if unified else None))
        result=loop(ChatAgentAdapter(settings),execute,checkpoint,b,paper_directory=directory,**options).run(a.question,run_id)
    finally:
        telemetry.close()
        telemetry.flush()
    (out/'evidence.json').write_text(json.dumps(store.evidence(run_id),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],run_id=run_id)))

if __name__=='__main__':main()
