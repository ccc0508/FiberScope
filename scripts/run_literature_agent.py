"""Opt-in bounded native-tool agent. Keeps the website's existing pipeline unchanged."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from literature_rag.application.agent_loop import AgentLoop,AgentBudget
from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
from literature_rag.config import Settings
from literature_rag.application.tools import ToolTraceStore


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--question',required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=240);p.add_argument('--max-tools',type=int,default=8)
    p.add_argument('--max-model-calls',type=int,default=10);p.add_argument('--run-id',default=None)
    p.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args();run_id=a.run_id or str(uuid4())
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
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            stdout,stderr=proc.communicate(timeout=a.seconds+5)
            if proc.returncode:raise RuntimeError('Agent worker failed; inspect saved state')
        except subprocess.TimeoutExpired:
            # Kill the process tree on Windows, including any outstanding tool worker.
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
            proc.wait()
            state=json.loads(state_path.read_text('utf-8')) if state_path.exists() else dict(run_id=run_id,answer='')
            state.update(status='partial' if state.get('answer') else 'failed',stop_reason='hard_deadline')
            state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(run_id=run_id,state_file=str(state_path)),ensure_ascii=False));return
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    def checkpoint(state):
        payload=dict(state,budget=asdict(b),model=settings.llm_model,mode='native-tools-agent-v2',
            review_policy='one full-answer review, no content gate; not legacy structured corrective review')
        tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(state_path)
    def execute(request,rid,timeout):
        body=dict(tool_call=request,run_id=rid,data_dir=str(a.library.resolve()))
        try:
            r=subprocess.run([sys.executable,'-I','-X','utf8',str(ROOT/'backend/literature_worker.py')],
                input=json.dumps(body,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=timeout,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return json.loads(r.stdout) if r.returncode==0 else dict(status='failed',error_code='worker_failed')
        except subprocess.TimeoutExpired:return dict(status='failed',error_code='tool_timeout')
    result=AgentLoop(ChatAgentAdapter(settings),execute,checkpoint,b).run(a.question,run_id)
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    (out/'evidence.json').write_text(json.dumps(store.evidence(run_id),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],run_id=run_id)))

if __name__=='__main__':main()
