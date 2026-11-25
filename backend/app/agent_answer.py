"""Adapt the evaluated agent run to the website/history answer contract."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[2]


def adapt_run(state, evidence, trace, elapsed_ms):
    from literature_rag.application.citation_policy import CITABLE_KINDS, invalid_references
    # Last boundary: validate against the persisted ledger, not only model-facing
    # tool outputs. Never silently drop unresolved refs from the citation list.
    invalid=invalid_references(state.get('answer',''),
        {e['ref'] for e in evidence if e['kind'] in CITABLE_KINDS})
    if invalid:
        state=dict(state,answer='',status='failed',stop_reason='invalid_citations',
            citation_boundary_failure=dict(invalid_refs=invalid,rejected_answer=state.get('answer','')))
    used=set(re.findall(r'\[\d+\]', state.get('answer','')))
    citations=[]; snapshots=[]
    for e in evidence:
        c=e['content'];kind=e['kind']
        if kind=='source_text':
            parts=c.get('sources',[])
            # Section-read offsets are chunk-relative for a single source.
            if (len(parts) == 1 and parts[0]['text'] == c['text']
                    and 'start_char' in c and 'end_char' in c):
                parts = [dict(parts[0], start_char=c['start_char'], end_char=c['end_char'])]
            row=dict(ref=e['ref'],kind=kind,document_id=c['document_id'],filename=c['filename'],
                page_start=c['page_start'],page_end=c['page_end'],chunk_id=parts[0]['chunk_id'] if parts else '',
                excerpt=c['text'],text=c['text'],source_chunks=parts,visual_assets=c.get('images',[]),document_hash=c.get('document_hash'))
        elif kind=='source_image':
            a=c['asset']
            row=dict(ref=e['ref'],kind=kind,document_id=a['document_id'],filename=a['label'],
                page_start=a['page'],page_end=a['page'],chunk_id=a['parent_chunk_id'],excerpt='模型查看的原PDF图片：'+a['label'],visual_assets=[a],
                document_hash=c.get('document_hash'))
        elif kind=='experiment_query':
            row=dict(ref=e['ref'],kind=kind,document_id='',filename='实验数据库查询 · '+c['view'],
                page_start=0,page_end=0,chunk_id='',excerpt=json.dumps(c,ensure_ascii=False,indent=2))
        elif kind=='calculation':
            row=dict(ref=e['ref'],kind=kind,document_id='',filename='计算结果（非论文原文）',page_start=0,page_end=0,chunk_id='',
                excerpt=f"初值：{c['initial']}；终值：{c['final']}；单位：{c['unit']}；差值：{c['difference']}；相对变化：{c.get('relative_change_percent')}%。公式：{c['formula']}",source_refs=c.get('source_refs',[]))
        else:continue
        snapshots.append(row)
        if e['ref'] in used:citations.append(row)
    completed=state.get('status')=='completed' and bool(state.get('answer','').strip())
    review_status=state.get('review_status')
    review_summary={}
    if review_status!='disabled':
        review_summary['review_summary']=dict(
            status=review_status if review_status in ('not_required','completed') else 'incomplete',
            notice=('本次使用公开搜索；网页来源单独列出。' if state.get('public_web_sources') else
                    '本次为直接答复或澄清，未调用研究子任务。') if review_status=='not_required' else '已完成答案复核；复核不保证所有陈述正确。' if review_status=='completed' else '答案复核未完成，请核对引用原文。',
            unresolved=[],supplement_rounds=0,review_rounds=int(review_status=='completed'))
    stop_reason = state.get('stop_reason')
    specific_errors = {'invalid_citations', 'missing_literature_citations', 'invalid_research_output'}
    reason_code = stop_reason if stop_reason in specific_errors else 'agent_incomplete'
    return dict(status='answered' if completed else 'failed',answer=state.get('answer',''),citations=citations,
        public_web_sources=state.get('public_web_sources',[]),
        latency_ms=elapsed_ms,reason_code=None if completed else reason_code,
        **({} if completed else dict(error_status=503)),
        configuration=dict(pipeline_version=state.get('pipeline_version','agentic-rag-directory-v1'),model=state.get('model'),budget=state.get('budget'),directory_policy=state.get('directory_policy')),
        generation_calls=state.get('model_calls',[]),retrieved_evidence=snapshots,claims=[],
        agent_run=state,agent_tool_trace=trace,agent_evidence=evidence,**review_summary)


def run_agent_answer(config, question, *, run_id=None, intent_evaluation_case=None):
    rid=run_id or 'web-'+uuid4().hex
    specialists=getattr(config,'agent_architecture','single')=='specialists'
    seconds=min(360 if specialists else 240,config.timeout_seconds-10)
    if seconds<30:raise HTTPException(503,'Agent问答超时配置至少需要40秒。')
    start=perf_counter()
    # The CLI owns the process-tree deadline; do not kill only its parent.
    from .qa_tracing import step, context
    with step('qa.agent_process', run_id=rid):
        env=dict(os.environ)
        if context():env['FIBERSCOPE_TRACE_CONTEXT']=json.dumps(context())
        args = [sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
        '--question',question,'--library',str(config.library_root),'--run-id',rid,'--seconds',str(seconds),
        '--architecture',getattr(config,'agent_architecture','single'),
        '--max-model-calls','20' if specialists else '10']
        if intent_evaluation_case:
            args.extend(['--intent-evaluation-case', intent_evaluation_case])
        result=subprocess.run(args,
        env=env,capture_output=True,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    folder=ROOT/'.rag-data/agent-runs'/rid
    if result.returncode or not (folder/'state.json').is_file():
        raise HTTPException(503,'文献问答服务暂不可用，请稍后重试。')
    with step('qa.read_agent_state', run_id=rid):
        state=json.loads((folder/'state.json').read_text('utf-8'))
    from literature_rag.application.tools import ToolTraceStore
    store=ToolTraceStore(ROOT/'.rag-data/tool-traces.sqlite3')
    with step('qa.adapt_answer', run_id=rid):
        return adapt_run(state,store.evidence(rid),store.read(rid),round((perf_counter()-start)*1000))
