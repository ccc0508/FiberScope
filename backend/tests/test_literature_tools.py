import json
from types import SimpleNamespace
from pathlib import Path
from hashlib import sha256

import pytest
from literature_rag.application.tools import LiteratureTools,ToolTraceStore
from literature_rag.domain.models import Chunk,VisualAsset,Evidence

@pytest.fixture
def kit(tmp_path):
    chunks=[Chunk(str(i),'doc','paper.pdf',i+1,i+1,i,'x'*300,100,'test',kind='table' if i==1 else 'text') for i in range(3)]
    catalog=SimpleNamespace(chunks={c.id:c for c in chunks},mapping={c.id:dict(section_id='s',section_path=['Section'],content_role='table' if c.id=='1' else 'body') for c in chunks})
    r=SimpleNamespace(body_context_catalog=catalog,visual_catalog=SimpleNamespace(assets=[]),retrieve=lambda *a,**kw:[Evidence('[1]','0','doc','paper.pdf',1,1,'x'*300,.9)])
    return LiteratureTools(r,tmp_path,ToolTraceStore(tmp_path/'traces.db'))

def test_search_keeps_pipeline_and_trace(kit):
    out=kit.call(dict(tool='search_literature',query='q',reason='find evidence'),run_id='run')
    assert out['result']['evidence'][0]['locator']['section_id']=='s'
    record=kit.store.read('run')[0]
    assert record['status']=='completed' and record['input']['query']=='q'
    assert record['result']==out['result']

def test_section_pagination_and_dedup(kit):
    p=dict(tool='read_section',document_id='doc',section_id='s',max_chars=256,exclude_chunk_ids=['0'],reason='context')
    texts=[];offset=0
    while True:
        out=kit.call(dict(p,offset=offset),run_id='run')['result']
        texts.extend(s['text'] for s in out['sources'])
        if out['next_offset'] is None:break
        offset=out['next_offset']
    assert len(''.join(texts))==600
    assert len(kit.store.read('run'))==3


def test_section_discovery_recovery_and_document_isolation(kit):
    from literature_rag.application.agent_context import EvidenceProjection
    listing=kit.call(dict(tool='list_sections',document_id='doc',reason='discover'),run_id='r')
    assert listing['result']['sections'][0]['section_id']=='s'
    assert listing['result']['sections'][0]['page_end']==3
    bad=kit.call(dict(tool='read_section',document_id='doc',section_id='sec_1',reason='read'),run_id='r')
    assert bad['status']=='failed' and bad['error_code']=='unknown_section'
    projected=EvidenceProjection().project(bad)
    sid=projected['result']['sections'][0]['section_id']
    good=kit.call(dict(tool='read_section',document_id='doc',section_id=sid,reason='retry'),run_id='r')
    assert good['status']=='completed' and good['result']['sources']
    assert kit.store.read('r')[1]['recovery']==bad['result']
    other=kit.call(dict(tool='list_sections',document_id='other',reason='discover'),run_id='r')
    assert other['error_code']=='unknown_document' and not other['result']['sections']


def test_section_directory_pagination(kit):
    c=kit.catalog.chunks['0']
    from dataclasses import replace
    kit.catalog.chunks={str(i):replace(c,id=str(i),chunk_index=i) for i in range(23)}
    kit.catalog.mapping={str(i):dict(section_id='s'+str(i),section_path=['Section '+str(i)]) for i in range(23)}
    first=kit.call(dict(tool='list_sections',document_id='doc',reason='list'),run_id='r')['result']
    second=kit.call(dict(tool='list_sections',document_id='doc',offset=first['next_offset'],reason='more'),run_id='r')['result']
    assert len(first['sections'])==20 and len(second['sections'])==3
    assert second['next_offset'] is None

def test_table_checks_document_and_role(kit):
    p=dict(tool='read_table',document_id='doc',chunk_id='1',reason='table')
    assert kit.call(p,run_id='r')['result']['table']['text']=='x'*300
    assert kit.call(dict(p,document_id='other'),run_id='r')['status']=='failed'
    assert kit.call(dict(p,chunk_id='0'),run_id='r')['status']=='failed'

def test_invalid_args_do_not_persist_extra_fields(kit):
    out=kit.call(dict(tool='search_literature',query='q',reason='r',api_key='private'),run_id='r')
    assert out['status']=='invalid_arguments'
    assert 'private' not in json.dumps(kit.store.read('r'))

def test_tool_worker_reports_child_failure_without_recording_raw_stderr(monkeypatch):
    import json
    import subprocess

    from literature_rag.diagnostics import TOOL_WORKER_ERROR_PREFIX, worker_exception_details
    from scripts.run_literature_agent import run_tool_worker

    error = OSError(12, "private provider message")
    error.__cause__ = MemoryError("private allocation message")
    stderr = ("unrelated private stderr: failed to allocate\n" + TOOL_WORKER_ERROR_PREFIX
              + json.dumps(worker_exception_details(error))).encode()
    monkeypatch.setattr(subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 1, b'', stderr))

    result = run_tool_worker({"tool_call": {"tool": "search_literature"}}, 2)

    assert result["error_code"] == "worker_failed"
    diagnostic = result["worker_diagnostic"]
    assert diagnostic["kind"] == "nonzero_exit"
    assert diagnostic["returncode"] == 1
    assert diagnostic["exceptions"][0]["errno"] == 12
    assert diagnostic["exceptions"][1]["type"] == "MemoryError"
    assert diagnostic["stderr_signatures"] == ["memory_allocation"]
    assert "private" not in json.dumps(result)


def test_tool_worker_distinguishes_bad_json_from_an_os_failure(monkeypatch):
    import subprocess

    from scripts.run_literature_agent import run_tool_worker

    monkeypatch.setattr(subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 0, b'{', b''))
    assert run_tool_worker({"tool_call": {"tool": "read_table"}}, 2)["worker_diagnostic"] == {
        "kind": "invalid_json", "operation": "read_table", "message": "Expecting property name enclosed in double quotes",
        "line": 1, "column": 2, "stdout_bytes": 1, "stderr_bytes": 0,
    }

    def broken_spawn(*_, **__):
        raise OSError(12, "private process path")

    monkeypatch.setattr(subprocess, "run", broken_spawn)
    diagnostic = run_tool_worker({"tool_call": {"tool": "read_table"}}, 2)["worker_diagnostic"]
    assert diagnostic["kind"] == "process_io_error"
    assert diagnostic["exceptions"][0]["errno"] == 12
    assert "private process path" not in str(diagnostic)


def test_failure_redacts_provider_error_and_records(kit):
    def fail(*a):raise RuntimeError('secret upstream error')
    kit.retriever.retrieve=fail
    assert kit.call(dict(tool='search_literature',query='q',reason='r'),run_id='r')['status']=='failed'
    assert 'secret' not in json.dumps(kit.store.read('r'))

def test_image_integrity_and_delivery(kit):
    data=b'\x89PNG\r\n\x1a\ntest';digest=sha256(data).hexdigest()
    path=kit.root/'visual-assets'/f'{digest}.png';path.parent.mkdir();path.write_bytes(data)
    a=VisualAsset('image','doc','1','Table 1',2,(0,0,10,10),f'visual-assets/{digest}.png',digest,10,10,len(data))
    kit.retriever.visual_catalog.assets=[a]
    p=dict(tool='view_image',document_id='doc',asset_id='image',reason='check pixels')
    out=kit.call(p,run_id='r');assert out['image']['base64']
    assert 'base64' not in json.dumps(kit.store.read('r'))
    path.write_bytes(b'changed')
    assert kit.call(p,run_id='r')['status']=='failed'


def test_find_figure_handles_and_model_projection(kit):
    from literature_rag.application.agent_context import EvidenceProjection
    a=VisualAsset('image','doc','1','Figure 3. Strength',2,(0,0,10,10),'unused','unused',10,10,1)
    kit.retriever.visual_catalog.assets=[a]
    out=kit.call(dict(tool='find_figure',document_id='doc',figure_number='3',reason='locate'),run_id='r')
    assert out['status']=='completed'
    assert out['result']['status']=='matched'
    projected=EvidenceProjection().project(out)
    assert projected['result']['assets'][0]['asset_id']=='image'
    assert 'id' not in projected['result']['assets'][0]
    assert not kit.store.evidence('r')  # Discovery is not inspected-image evidence.
    assert EvidenceProjection.asset(dict(id='legacy',document_id='doc'))['asset_id']=='legacy'

def test_interrupted_record_remains_visible(kit):
    kit.store.save(dict(call_id='c',run_id='r',status='started'))
    assert kit.store.read('r')[0]['status']=='started'

@pytest.mark.parametrize('tool,args',[
    ('calculate_change',dict(initial='47.16',final='42.35',unit='%',source_call_ids=['source'])),
    ('convert_units',dict(value='10',from_unit='mg/100m',to_unit='mg/m')),
])
def test_retired_calculation_tools_unavailable(kit,tool,args):
    from literature_rag.application.specialist_agent import SQL_TOOLS,PAPER_TOOLS
    from literature_rag.application.tools import SCHEMAS
    assert tool not in SCHEMAS and tool not in SQL_TOOLS and tool not in PAPER_TOOLS
    assert kit.call(dict(tool=tool,reason='calculation',**args),run_id='r')['status']=='invalid_arguments'
    assert not kit.store.evidence('r')


def add_second_paper(kit, text='y'*300):
    c=Chunk('b','doc_b','b.pdf',1,1,0,text,50,'test',kind='paragraph')
    kit.catalog.chunks[c.id]=c
    kit.catalog.mapping[c.id]=dict(section_id='methods',section_path=['Methods'],content_role='body')


def test_directory_batch_keeps_valid_papers_and_separate_errors(kit):
    add_second_paper(kit)
    res=kit.call(dict(tool='list_sections',document_ids=['doc','missing','doc_b'],reason='find sections'),run_id='r')
    assert res['status']=='completed'
    first,invalid,last=res['result']['documents']
    assert [first['sections'][0]['section_id'],last['sections'][0]['section_id']]==['s','methods']
    assert invalid['status']=='failed' and invalid['error_code']=='unknown_document'
    assert len(kit.store.read('r'))==1 and not kit.store.evidence('r')


def test_section_batch_shares_budget_and_preserves_refs_for_multiple_papers(kit):
    from literature_rag.application.agent_context import EvidenceProjection
    add_second_paper(kit)
    targets=[dict(document_id='doc',section_id='s',exclude_chunk_ids=['0']),
             dict(document_id='doc_b',section_id='missing'),dict(document_id='doc_b',section_id='methods',offset=50)]
    r=kit.call(dict(tool='read_section',targets=targets,max_chars=320,reason='compare'),run_id='r')
    assert r['status']=='completed'
    a,b,c=r['result']['sections']
    assert (a['returned_chars'],c['returned_chars'])==(160,160)
    assert (a['next_offset'],c['next_offset'])==(160,210)
    assert b['status']=='failed' and b['recovery']['sections'][0]['section_id']=='methods'
    sources=EvidenceProjection().project(r)['result']['sources']
    assert [(s['document_id'],s['section_id'],s['chunk_id'],s['ref']) for s in sources]==[
        ('doc','s','1','[1]'),('doc_b','methods','b','[2]')]
    assert len(kit.store.read('r'))==1
    assert len(kit.store.evidence('r'))==2
    continuation=kit.call(dict(tool='read_section',**{**targets[2],'offset':c['next_offset']},reason='continue'),run_id='r')
    assert continuation['result']['sources'][0]['start_char']==210


def test_short_section_donates_remaining_budget_and_all_invalid_add_no_citations(kit):
    add_second_paper(kit,'y'*40)
    targets=[dict(document_id='doc',section_id='s'),dict(document_id='doc_b',section_id='methods')]
    r=kit.call(dict(tool='read_section',targets=targets,max_chars=280,reason='compare'),run_id='r')
    assert [s['returned_chars'] for s in r['result']['sections']]==[240,40]
    bad=[dict(t,section_id='unknown') for t in targets]
    error=kit.call(dict(tool='read_section',targets=bad,reason='compare'),run_id='r')
    assert error['status']=='failed' and error['error_code']=='batch_lookup_failed'
    assert all(s['error_code']=='unknown_section' for s in error['result']['sections'])
    assert len(kit.store.evidence('r'))==2

def test_ledger_dedup_content_change_and_run_isolation(kit):
    p=dict(tool='search_literature',query='q',reason='search')
    first=kit.call(p,run_id='r');second=kit.call(p,run_id='r')
    assert first['result']['evidence'][0]['ref']==second['result']['evidence'][0]['ref']=='[1]'
    assert len(kit.store.evidence('r')[0]['call_ids'])==2
    kit.retriever.retrieve=lambda *a,**kw:[Evidence('[1]','0','doc','paper.pdf',1,1,'changed',.8)]
    third=kit.call(p,run_id='r')
    assert third['result']['evidence'][0]['ref']=='[2]'
    assert kit.store.evidence('r',['[1]'])[0]['content']['text']=='x'*300
    assert kit.call(p,run_id='other')['result']['evidence'][0]['ref']=='[1]'
    with pytest.raises(LookupError):kit.store.evidence('other',['[2]'])
    assert ToolTraceStore(kit.store.path).evidence('r')==kit.store.evidence('r')

def test_same_full_text_cross_tool_reuses_identity(kit):
    first=kit.call(dict(tool='search_literature',query='q',reason='s'),run_id='r')
    second=kit.call(dict(tool='read_section',document_id='doc',section_id='s',max_chars=600,reason='read'),run_id='r')
    assert first['result']['evidence'][0]['ref']==second['result']['sources'][0]['ref']
    table=kit.call(dict(tool='read_table',document_id='doc',chunk_id='1',reason='table'),run_id='r')
    assert table['result']['table']['ref']==second['result']['sources'][1]['ref']

def test_ledger_concurrent_numbering(kit):
    from concurrent.futures import ThreadPoolExecutor
    def one(i):
        record=dict(call_id=str(i),run_id='r',status='completed',input=dict(tool='view_image'),
            result=dict(asset=dict(id=str(i),document_id='doc'),image_sha256=str(i),image_bytes=1))
        kit.store.complete(record)
        return record['result']['ref']
    with ThreadPoolExecutor(max_workers=4) as pool:refs=list(pool.map(one,range(12)))
    assert len(set(refs))==12
    assert [r['ref'] for r in kit.store.evidence('r')]==[f'[{i}]' for i in range(1,13)]

def test_failed_registration_rolls_back_snapshot_and_completion(kit):
    r=dict(call_id='bad',run_id='r',status='started')
    kit.store.save(r)
    r.update(status='completed',input=dict(tool='search_literature'),result=dict(evidence=[
        dict(ref='[1]',chunk_id='0',document_id='doc',filename='p',page_start=1,page_end=1,text='ok'),
        dict(ref='[2]')]))
    with pytest.raises(KeyError):kit.store.complete(r)
    assert kit.store.evidence('r')==[]
    assert kit.store.read('r')[0]['status']=='started'

@pytest.mark.parametrize('caption', ['Table 1. Definitions', '表1实验结果'])
def test_directory_and_exact_table_number(kit, caption):
    from dataclasses import replace
    c=kit.catalog.chunks['1'];kit.catalog.chunks['1']=replace(c,text=caption+'\n<table></table>')
    out=kit.call(dict(tool='find_documents',query='paper',reason='identify'),run_id='r')
    assert out['result']['documents'][0]['document_id']=='doc'
    from literature_rag.application.tools import SCHEMAS
    assert 'read_table' in SCHEMAS and 'find_table' not in SCHEMAS
    request = dict(tool='read_table', document_id='doc', reason='read')
    for number in ('10', 'S1'):
        out = kit.call(dict(request, table_number=number), run_id='r')
        assert out['result']['total'] == 0
        assert 'table' not in out['result']
    out = kit.call(dict(request, document_id='other', table_number='1'), run_id='r')
    assert out['result']['total'] == 0
    assert not kit.store.evidence('r')
    out = kit.call(dict(request, table_number='1'), run_id='r')
    assert out['result']['table']['text'] == kit.catalog.chunks['1'].text
    assert out['result']['table']['ref'] == '[1]'
    direct = kit.call(dict(request, chunk_id='1'), run_id='r')
    assert direct['result']['table']['ref'] == '[1]'
    assert len(kit.store.evidence('r')) == 1


def test_numbered_read_returns_ambiguous_handles_without_evidence(kit):
    from dataclasses import replace

    first = replace(kit.catalog.chunks['1'], text='Table 1. Definitions\n<table></table>')
    second = replace(first, id='continued', page_start=3, page_end=3)
    other = replace(first, id='different', text='Table 1a. Another table\n<table></table>')
    kit.catalog.chunks.update({'1': first, second.id: second, other.id: other})
    kit.catalog.mapping.update({source.id: kit.catalog.mapping['1'] for source in (second, other)})
    request = dict(tool='read_table', document_id='doc', reason='read')
    out = kit.call(dict(request, table_number='1'), run_id='r')
    assert out['status'] == 'completed'
    assert out['result']['total'] == 2
    assert [row['chunk_id'] for row in out['result']['tables']] == ['1', 'continued']
    assert 'table' not in out['result']
    assert kit.store.evidence('r') == []
    out = kit.call(dict(request, chunk_id='continued'), run_id='r')
    assert out['result']['table']['ref'] == '[1]'


@pytest.mark.parametrize('selectors', [{}, {'table_number': '1', 'chunk_id': '1'}, {'chunk_id': '1', 'offset': 1}])
def test_read_table_requires_one_selector(kit, selectors):
    out = kit.call(dict(tool='read_table', document_id='doc', reason='read', **selectors), run_id='r')
    assert out['status'] == 'invalid_arguments'


def test_scoped_search_validates_ids_and_passes_filter(kit):
    calls = []
    kit.retriever.retrieve = lambda *a, **kw: calls.append((a, kw)) or []
    base = dict(tool='search_literature', query='unit', reason='target')
    assert kit.call(base, run_id='r')['status'] == 'completed'
    assert kit.call(dict(base, document_id='doc'), run_id='r')['status'] == 'completed'
    assert calls == [
        (('unit', 8, .35), {'document_ids': None, 'max_seeds_per_document': 3}),
        (('unit', 3, .35), {'document_ids': ['doc'], 'max_seeds_per_document': 3}),
    ]
    assert kit.call(dict(base, document_id='missing'), run_id='r')['status'] == 'failed'
    assert kit.call(dict(base, document_ids=['doc']), run_id='r')['status'] == 'invalid_arguments'
    assert kit.call(dict(base, top_k=1), run_id='r')['status'] == 'invalid_arguments'
    assert kit.call(dict(base, document_id='doc', top_k=2), run_id='r')['status'] == 'invalid_arguments'
    assert len(calls) == 2


def test_five_parallel_scoped_searches_register_in_request_order(tmp_path):
    from scripts.run_literature_agent import execute_parallel_searches
    from threading import Barrier, Event

    store = ToolTraceStore(tmp_path / 'traces.db')
    executions_started = Barrier(5, timeout=5)
    last_finished = Event()
    indices = dict(zip('abcde', (2, 5, 6, 7, 8), strict=True))
    contexts = []

    def execute(request, run_id, timeout, *, context, defer_search_registration):
        assert defer_search_registration
        document_id = request['document_id']
        assert context == {'index': indices[document_id]}
        executions_started.wait()
        chunk = Chunk(document_id, document_id, document_id + '.pdf', 1, 1, 0, 'text', 1, 'test')
        evidence = Evidence('[1]', chunk.id, chunk.document_id, chunk.filename, 1, 1, chunk.text, .9)
        retriever = SimpleNamespace(
            body_context_catalog=SimpleNamespace(chunks={chunk.id: chunk}, mapping={}),
            retrieve=lambda *args, **kwargs: [evidence],
        )
        if document_id == 'a':
            assert last_finished.wait(5)
        result = LiteratureTools(retriever, tmp_path, store).call(
            request, run_id=run_id, defer_search_registration=defer_search_registration,
        )
        assert store.evidence(run_id) == []
        if document_id == 'e':
            last_finished.set()
        return result

    def tool_context(*, index):
        contexts.append(index)
        return {'index': index}

    base = dict(tool='search_literature', query='unit', reason='target')
    executions = [(dict(base, document_id=doc), index) for doc, index in indices.items()]
    results = list(execute_parallel_searches(
        executions, 'run', 10, execute=execute, trace_store=store, tool_context=tool_context,
    ))
    assert contexts == list(indices.values())
    assert [(e['document_id'], e['ref']) for r in results for e in r['result']['evidence']] == [
        (doc, f'[{i}]') for i, doc in enumerate(indices, 1)
    ]

@pytest.mark.parametrize('expand', [False, True])
def test_same_paper_queries_share_eight_distinct_anchors_and_expand_once(tmp_path, expand):
    from threading import Barrier
    from scripts.run_literature_agent import execute_parallel_searches

    store = ToolTraceStore(tmp_path / 'traces.db')
    overlap = Barrier(2, timeout=5)
    assembled = []
    doc = 'paper'
    rankings = {
        'methods': ['common', 'methods', 'methods-2', 'methods-3', 'unused'],
        'validation': ['common', 'validation', 'validation-2', 'validation-3', 'validation-4'],
    }

    def execute(request, run_id, timeout, *, context, defer_search_registration, rank_search_only):
        assert rank_search_only and defer_search_registration
        overlap.wait()
        chunks = [
            Chunk(chunk_id, doc, 'paper.pdf', i + 1, i + 1, i, chunk_id, 1, 'test')
            for i, chunk_id in enumerate(rankings[request['query']])
        ]
        raw = [Evidence('', c.id, doc, c.filename, c.page_start, c.page_end, c.text, .9) for c in chunks]
        def retrieve(query, top_k, min_score, **kwargs):
            assert query == request['query'] and kwargs['rank_only']
            return raw
        retriever = SimpleNamespace(body_context_catalog=SimpleNamespace(chunks={c.id: c for c in chunks}, mapping={}),
                                    retrieve=retrieve, last_candidate_evidences=raw)
        return LiteratureTools(retriever, tmp_path, store).call(
            request, run_id=run_id, defer_search_registration=True, rank_search_only=True,
        )

    def assemble(seeds, query, run_id, timeout):
        assembled.append([seed['chunk_id'] for seed in seeds])
        assert query == 'methods validation' and timeout > 0
        assert store.evidence(run_id) == []
        if not expand:
            return {'result': {'evidence': seeds}, 'internal_steps': []}
        common, validation, methods, *remaining = seeds
        merged = dict(common, seed_chunk_ids=['common', 'validation'], text='common and validation')
        linked = dict(validation, ref='[4]', chunk_id='table', seed_chunk_ids=['validation'], text='related table')
        return {'result': {'evidence': [merged, methods, linked, *remaining]}, 'internal_steps': []}

    executions = [(dict(tool='search_literature', document_id=doc, query=query, reason='target'), i)
                  for i, query in enumerate(rankings)]
    results = list(execute_parallel_searches(executions, 'run', 10, execute=execute, trace_store=store,
                                             tool_context=lambda **kw: kw, assemble=assemble))
    assert assembled == [[
        'common', 'validation', 'methods', 'validation-2', 'methods-2', 'validation-3', 'methods-3', 'validation-4',
    ]]
    first = [('common', '[1]'), ('methods', '[2]'), ('methods-2', '[3]'), ('methods-3', '[4]')]
    second = [('common', '[1]'), ('table', '[5]')] if expand else [('validation', '[5]')]
    second += [('validation-2', '[6]'), ('validation-3', '[7]'), ('validation-4', '[8]')]
    assert [[(e['chunk_id'], e['ref']) for e in r['result']['evidence']] for r in results] == [first, second]
    assert len(store.evidence('run')) == 8
    if expand:
        assert len(store.evidence('run')[0]['call_ids']) == 2
    assert all(r['result']['shared_search']['selected_chunk_ids'] == assembled[0] for r in results)


def test_shared_search_keeps_fitting_seeds_and_reuses_a_shared_hit_for_uncovered_query():
    from scripts.run_literature_agent import finalize_shared_search

    source = dict(chunk_id="common", text="x" * 3300)
    rankings = [[source, *[dict(chunk_id=f"a{i}", text="a" * 3300) for i in range(7)]], [source]]
    records = [dict(candidate_evidence=hits, call_id=str(i), input=dict(query=str(i)),
                    status="completed", result=dict(evidence=[]), internal_steps=[], diagnostics={})
               for i, hits in enumerate(rankings)]

    def assemble(seeds, *_):
        assert len(seeds) == 7
        assert sum(len(seed["text"]) for seed in seeds) < 24000
        return dict(result=dict(evidence=seeds))

    finalize_shared_search(records, "run", 5, assemble=assemble, context_limits=(8000, 24000))
    assert all(record["status"] == "completed" for record in records)
    assert [hit["chunk_id"] for hit in records[1]["result"]["evidence"]] == ["common"]
