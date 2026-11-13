"""Opt-in bounded native-tool agent. Keeps the website's existing pipeline unchanged."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import os
import signal
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.agent_loop import AgentLoop,AgentBudget
from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
from literature_rag.config import Settings
from literature_rag.application.tools import ToolTraceStore
from literature_rag.application.paper_directory import load_paper_directory
from literature_rag.state_io import save_state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--question',required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=None);p.add_argument('--max-tools',type=int,default=None)
    p.add_argument('--max-model-calls',type=int,default=None);p.add_argument('--run-id',default=None)
    p.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--prompt-file',type=Path,help='Evaluation only: frozen PROMPT and REVIEW_PROMPT JSON; does not change website defaults')
    p.add_argument('--architecture',choices=['single','specialists'],default='single')
    p.add_argument('--no-task-feedback',action='store_true',help='Specialists only: disable the optional follow-up for comparison; keep all other current code.')
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
            review_policy='parent synthesis and evidence review; no repeated child review' if a.architecture=='specialists' else 'one full-answer review, no content gate; not legacy structured corrective review')
        save_state(state_path,payload)
        telemetry.update(payload)
        if telemetry.url:
            try:
                (out/'langfuse.json').write_text(json.dumps({'url':telemetry.url},ensure_ascii=False),encoding='utf8')
            except OSError:
                pass  # Optional remote link must never fail the local answer.
    def execute(request,rid,timeout):
        body=dict(tool_call=request,run_id=rid,data_dir=str(a.library.resolve()))
        context=telemetry.active_tool_context()
        if context:body['trace_context']=context
        try:
            r=subprocess.run([sys.executable,'-I','-X','utf8',str(ROOT/'backend/literature_worker.py')],
                input=json.dumps(body,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=timeout,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return json.loads(r.stdout) if r.returncode==0 else dict(status='failed',error_code='worker_failed')
        except subprocess.TimeoutExpired:return dict(status='failed',error_code='tool_timeout')
    directory=load_paper_directory(a.library)
    loop=AgentLoop
    if a.architecture=='specialists':
        from literature_rag.application.specialist_agent import SpecialistCoordinator
        loop=SpecialistCoordinator
    try:
        options=dict(feedback_enabled=not a.no_task_feedback) if a.architecture=='specialists' else {}
        result=loop(ChatAgentAdapter(settings),execute,checkpoint,b,paper_directory=directory,**options).run(a.question,run_id)
    finally:
        telemetry.close()
        telemetry.flush()
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    (out/'evidence.json').write_text(json.dumps(store.evidence(run_id),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],run_id=run_id)))

if __name__=='__main__':main()
