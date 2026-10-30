"""Isolated retrieval-only replay and source-position diagnostics for 32 frozen tasks."""
from argparse import ArgumentParser
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
from freeze_qa_baseline import verify
from qa_retrieval_alignment import span_coverage
from qa_retrieval_sources import load_library
from run_qa_baseline import clean_environment,source_hashes
from validate_qa_eval import require

VERSION='retrieval-diagnostic-v1-20261030'
PRIVATE=ROOT/'.rag-data/retrieval-diagnostics'/VERSION
OUTPUT=ROOT/'data/literature/qa-evaluation/reports'/VERSION
DOC=ROOT/'docs/QA_RETRIEVAL_DIAGNOSTIC_20261030.md'
CONFIG=ROOT/'.rag-data/configs/mineru-sections-v2-20261030.env'
SOURCES={
    'pymupdf':('pfi-context-v1-20261029-r1','qa-context-v1-20261029','PyMuPDF结构81块'),
    'native':('pfi-mineru-native-v1-20261029-r1','qa-mineru-native-v1-20261029','MinerU原生117块'),
    'sections':('pfi-mineru-sections-v2-20261030-r1','qa-mineru-sections-v2-20261030','MinerU章节107块')}
HARNESS=['diagnose_qa_retrieval.py','qa_retrieval_probe_worker.py','qa_retrieval_alignment.py','qa_retrieval_sources.py']


def save(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)


def prepare():
    require(not PRIVATE.exists(),'Diagnostic destination exists; retain its cached requests')
    runs={};historical={};libraries={};configuration=None;tasks=None;gold_cases=None;evidence=None
    for system,(run_id,baseline_id,_) in SOURCES.items():
        run_dir=ROOT/'.rag-data/evaluations'/run_id;baseline=ROOT/'.rag-data/baselines'/baseline_id
        verify(baseline)
        run,manifest,cases,_=judge.verify_run(run_dir)
        require(source_hashes(run_dir/'backend')==run['source_files'],'Frozen runtime source changed')
        if configuration is None:
            configuration=run['configuration_probe'];tasks=run['tasks'];gold_cases=cases
            evidence=judge.read_json(run_dir/'dataset/evidence.json')
        require(configuration==run['configuration_probe'] and tasks==run['tasks'],'Controlled configuration or questions differ')
        require(len(tasks)==32 and all(t['suite']=='core_text' and t['mode']=='retrieval' for t in tasks),'Expected 32 core text tasks')
        results={}
        for task in tasks:
            path,result=judge.read_result(run_dir,run,cases[task['case_id']],task)
            require(result['status']=='answered','Inspect historical failures separately before this diagnostic')
            results[task['id']]=dict(result_sha256=judge.digest(path),response=result['response'])
        libraries[system]=load_library(baseline/'library',evidence)
        historical[system]=results
        runs[system]=dict(run_id=run_id,baseline_id=baseline_id,run_sha256=judge.digest(run_dir/'run.json'),
            baseline_manifest_sha256=judge.digest(baseline/'manifest.json'),
            original_library_files={p.relative_to(baseline/'library').as_posix():judge.digest(p) for p in (baseline/'library').rglob('*') if p.is_file()})
    PRIVATE.mkdir(parents=True);(PRIVATE/'harness').mkdir();(PRIVATE/'replays').mkdir()
    for name in HARNESS:
        shutil.copyfile(ROOT/'scripts'/name,PRIVATE/'harness'/name)
    for system,entry in runs.items():
        library=ROOT/'.rag-data/baselines'/entry['baseline_id']/'library'
        shutil.copytree(library,PRIVATE/'libraries'/system)
        require({p.relative_to(PRIVATE/'libraries'/system).as_posix():judge.digest(p) for p in (PRIVATE/'libraries'/system).rglob('*') if p.is_file()}==entry['original_library_files'],'Library clone fingerprint mismatch')
    save(PRIVATE/'historical.json',historical)
    save(PRIVATE/'references.json',dict(cases=gold_cases,evidence=evidence,tasks=tasks))
    for system,library in libraries.items():
        save(PRIVATE/(system+'-alignment.json'),library['alignment'])
    contract=dict(version=VERSION,created_at=datetime.now(timezone.utc).isoformat(),configuration=configuration,
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        tasks=[dict(task_id=t['id'],case_id=t['case_id'],question=gold_cases[t['case_id']]['question']) for t in tasks],
        sources=runs,historical_sha256=judge.digest(PRIVATE/'historical.json'),references_sha256=judge.digest(PRIVATE/'references.json'),
        alignment_sha256={s:judge.digest(PRIVATE/(s+'-alignment.json')) for s in SOURCES},
        harness_sha256={name:judge.digest(PRIVATE/'harness'/name) for name in HARNESS},
        application_config_sha256=judge.digest(ROOT/'backend/.env.literature'),
        limitations=['Top50 are newly replayed, not retroactively observed historical candidates.',
            'Raw source-interval coverage is a diagnostic proxy, not semantic evidence sufficiency or an answer score.',
            'Near text alignment is provisional; scientific-number or formula differences require source review.',
            'Only one PDF and 32 development questions; no new-paper generalization claim.'])
    save(PRIVATE/'study.json',contract)
    print(json.dumps(dict(prepared_questions=32,indexes=3,provider_calls=0,
        alignment={s:dict(Counter(a['status'] for a in lib['alignment'].values())) for s,lib in libraries.items()}),ensure_ascii=False))


def contract():
    study=judge.read_json(PRIVATE/'study.json')
    require(all(judge.digest(PRIVATE/'harness'/n)==h for n,h in study['harness_sha256'].items()),'Archived diagnostic harness changed')
    require(judge.digest(PRIVATE/'historical.json')==study['historical_sha256'],'Historical snapshot changed')
    require(judge.digest(PRIVATE/'references.json')==study['references_sha256'],'Reference snapshot changed')
    require(all(judge.digest(PRIVATE/(s+'-alignment.json'))==h for s,h in study['alignment_sha256'].items()),'Reference alignment changed')
    return study


def embeddings():
    from filelock import FileLock
    with FileLock(str(PRIVATE/'.embedding.lock'),timeout=0):
        study=contract();output=PRIVATE/'queries.json';attempt=PRIVATE/'embedding-attempt.json'
        if output.exists():
            row=judge.read_json(output)
            require(row['study_sha256']==judge.digest(PRIVATE/'study.json'),'Cached embedding study mismatch')
            require(judge.read_json(attempt).get('result_sha256')==judge.digest(output),'Embedding cache checksum mismatch')
            print(json.dumps(dict(status='cached',questions=len(row['queries']),new_provider_calls=0)));return
        require(not attempt.exists(),'A previous embedding attempt needs inspection; refusing automatic paid replay')
        sys.path.insert(0,str(ROOT/'backend'))
        from literature_rag.config import Settings
        from literature_rag.adapters.providers.openai import OpenAIEmbedder
        from openai import OpenAI
        settings=Settings(_env_file=CONFIG);cfg=study['configuration']
        require((settings.embedding_provider,settings.embedding_model,settings.embedding_dimensions)==
            (cfg['embedding_provider'],cfg['embedding_model'],cfg['embedding_dimensions']),'Embedding model settings changed')
        endpoint=sha256((settings.embedding_base_url or '<sdk-default>').encode()).hexdigest()
        require(endpoint==cfg['provider_endpoint_fingerprints']['embedding_base_url'],'Embedding endpoint changed')
        texts=[t['question'].strip() for t in study['tasks']]
        request=dict(model=settings.embedding_model,input=texts)
        save(attempt,dict(status='started',study_sha256=judge.digest(PRIVATE/'study.json'),request_sha256=judge.sha(request),logical_calls=1))
        client=OpenAI(api_key=settings.embedding_api_key.get_secret_value(),base_url=settings.embedding_base_url,
            max_retries=0,timeout=60,organization='',project='')
        client.organization=None;client.project=None;client._custom_headers={}
        embedder=OpenAIEmbedder(settings.embedding_model,settings.embedding_dimensions,'',client=client)
        start=perf_counter()
        try:
            vectors=embedder.embed_documents(texts)
            require(len(vectors)==32,'Embedding vector count mismatch')
            result=dict(study_sha256=judge.digest(PRIVATE/'study.json'),request_sha256=judge.sha(request),
                queries=[dict(**task,vector=vector) for task,vector in zip(study['tasks'],vectors)],
                requested_model=settings.embedding_model,dimensions=settings.embedding_dimensions,logical_api_calls=1,
                usage=getattr(embedder,'last_usage',None),elapsed_ms=round((perf_counter()-start)*1000),
                actual_billing_usd=None,batching='One batch of unchanged stripped questions; same vectors reused across all three indexes.')
            save(output,result);save(attempt,dict(status='completed',result_sha256=judge.digest(output),logical_calls=1))
        except Exception as error:
            save(attempt,dict(status='failed',error_type=type(error).__name__,logical_calls=1,
                usage=getattr(embedder,'last_usage',None),request_sha256=judge.sha(request)))
            raise
        finally:
            client.close()
        print(json.dumps(dict(status='completed',questions=32,logical_embedding_calls=1,usage=result['usage'],generation_calls=0,judge_calls=0),ensure_ascii=False))


def probe_payload(study,system,queries):
    source=study['sources'][system]
    return dict(backend=str(ROOT/'.rag-data/evaluations'/source['run_id']/'backend'),
        library=str(PRIVATE/'libraries'/system),configuration={k:study['configuration'][k] for k in
            ['embedding_provider','embedding_model','embedding_dimensions','top_k','min_score','context_expansion']},
        queries=[{k:q[k] for k in ['task_id','question','vector']} for q in queries])


def replay():
    from filelock import FileLock
    with FileLock(str(PRIVATE/'.replay.lock'),timeout=0):
        study=contract();query_cache=judge.read_json(PRIVATE/'queries.json')
        require(judge.read_json(PRIVATE/'embedding-attempt.json')['result_sha256']==judge.digest(PRIVATE/'queries.json'),'Query cache changed')
        require(query_cache['study_sha256']==judge.digest(PRIVATE/'study.json'),'Query cache identity changed')
        for system,source in study['sources'].items():
            path=PRIVATE/'replays'/(system+'.json');seal=PRIVATE/'replays'/(system+'-seal.json')
            if path.exists():
                require(judge.digest(path)==judge.read_json(seal)['result_sha256'],'Saved replay changed');continue
            run_dir=ROOT/'.rag-data/evaluations'/source['run_id'];run=judge.read_json(run_dir/'run.json')
            require(judge.digest(run_dir/'run.json')==source['run_sha256'] and source_hashes(run_dir/'backend')==run['source_files'],'Frozen runtime changed')
            payload=probe_payload(study,system,query_cache['queries'])
            process=subprocess.run([sys.executable,'-I','-X','utf8',str(PRIVATE/'harness/qa_retrieval_probe_worker.py')],
                input=json.dumps(payload,ensure_ascii=False),env=clean_environment(),capture_output=True,
                encoding='utf-8',timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            require(process.returncode==0,'Frozen retrieval replay failed; private stderr SHA '+sha256(process.stderr.encode()).hexdigest())
            result=json.loads(process.stdout)
            require(len(result['records'])==32,'Incomplete retrieval replay')
            save(path,result);save(seal,dict(result_sha256=judge.digest(path),payload_sha256=judge.sha(payload),
                queries_sha256=judge.digest(PRIVATE/'queries.json'),worker_sha256=judge.digest(PRIVATE/'harness/qa_retrieval_probe_worker.py')))
            print(json.dumps(dict(system=system,replayed=32,new_model_calls=0),ensure_ascii=False),flush=True)


def final_ids(evidences):
    return list(dict.fromkeys(s['chunk_id'] for e in evidences for s in (e.get('source_chunks') or [e])))


def context_signature(evidences):
    return [(e['ref'],e['text'],tuple(s['chunk_id'] for s in e.get('source_chunks',[]))) for e in evidences]


def replay_agreement(probe,historical):
    new_ids=[e['chunk_id'] for e in probe['seeds']]
    old_ids=[e['chunk_id'] for e in historical['retrieval_seed_evidence']]
    return dict(top8_equal_history=new_ids==old_ids,top8_members_equal_history=set(new_ids)==set(old_ids),
        context_equal_history=context_signature(probe['final'])==context_signature(historical['retrieved_evidence']),
        context_sources_equal_history=set(final_ids(probe['final']))==set(final_ids(historical['retrieved_evidence'])))


def bottleneck(stages):
    if stages['library']['status']!='complete':return 'source_not_fully_indexed'
    if stages['top50']['status']!='complete':return 'outside_top50_or_partial'
    if stages['passing50']['status']!='complete':return 'threshold_or_missing_metadata'
    if stages['final']['status']=='complete':
        return 'context_present' if stages['top8']['status']=='complete' else 'neighbor_recovered'
    if stages['top8']['status']!='complete':return 'outside_top8_or_partial'
    return 'context_assembly_loss'


def evidence_trace(target,probe,historical,library):
    candidate_ids=[c['chunk_id'] for c in probe['candidates'] if c['metadata_present']]
    passing=[c['chunk_id'] for c in probe['candidates'] if c['metadata_present'] and c['passes_threshold']]
    ids=dict(library=list(library['chunks']),top50=candidate_ids,passing50=passing,
        top8=[e['chunk_id'] for e in probe['seeds']],final=final_ids(probe['final']),
        historical_top8=[e['chunk_id'] for e in historical['retrieval_seed_evidence']],
        historical_final=final_ids(historical['retrieved_evidence']))
    stages={name:span_coverage(target,selected,library['chunk_spans']) for name,selected in ids.items()}
    first=None;complete=None
    for candidate in probe['candidates']:
        cid=candidate['chunk_id']
        if not candidate['metadata_present']:
            continue
        one=span_coverage(target,[cid],library['chunk_spans'])
        if first is None and one['covered']:
            first=dict(rank=candidate['rank'],score=candidate['score'],chunk_id=cid,passes_threshold=candidate['passes_threshold'])
        prefix=[c['chunk_id'] for c in probe['candidates'][:candidate['rank']] if c['metadata_present']]
        if complete is None and span_coverage(target,prefix,library['chunk_spans'])['status']=='complete':
            complete=candidate['rank']
    return dict(alignment_status=target['status'],stages=stages,first_intersection=first,completion_rank=complete,
        positional_bottleneck=bottleneck(stages) if target['status']!='unresolved' else 'alignment_unresolved',
        semantic_sufficiency='not_assessed',alignment_review_required=target['status']!='located')


def report(refresh=False):
    if refresh:
        old=judge.read_json(OUTPUT/'publication.json')
        require(all(judge.digest(OUTPUT/n)==h for n,h in old['files'].items()),'Published report changed')
        require(judge.digest(DOC)==old['document_sha256'],'Published document changed')
    else:
        require(not OUTPUT.exists() and not DOC.exists(),'Report destination exists')
    study=contract();references=judge.read_json(PRIVATE/'references.json');evidence=references['evidence']
    history=judge.read_json(PRIVATE/'historical.json');queries=judge.read_json(PRIVATE/'queries.json')
    require(judge.read_json(PRIVATE/'embedding-attempt.json')['result_sha256']==judge.digest(PRIVATE/'queries.json'),'Query cache changed')
    libraries={s:load_library(PRIVATE/'libraries'/s,evidence) for s in SOURCES}
    probes={}
    for system,source in study['sources'].items():
        path=PRIVATE/'replays'/(system+'.json');seal=judge.read_json(PRIVATE/'replays'/(system+'-seal.json'))
        require(judge.digest(path)==seal['result_sha256'],'Replay data changed')
        require(seal['payload_sha256']==judge.sha(probe_payload(study,system,queries['queries'])),'Replay inputs changed')
        require(libraries[system]['alignment']==judge.read_json(PRIVATE/(system+'-alignment.json')),'Alignment no longer reproduces')
        original=ROOT/'.rag-data/baselines'/source['baseline_id']/'library'
        require({p.relative_to(original).as_posix():judge.digest(p) for p in original.rglob('*') if p.is_file()}==source['original_library_files'],'Original library changed')
        for tid,entry in history[system].items():
            require(judge.digest(ROOT/'.rag-data/evaluations'/source['run_id']/'results'/(tid+'.json'))==entry['result_sha256'],'Original historical answer changed')
        probes[system]={r['task_id']:r for r in judge.read_json(path)['records']}
    common_strict=[e['id'] for e in evidence if all(libraries[s]['alignment'][e['id']]['status']=='located' for s in SOURCES)]
    rows=[];summary={s:dict(queries=32,top8_equal_history=0,top8_members_equal_history=0,
        context_equal_history=0,context_sources_equal_history=0,strict_requests=0,
        strict_counts=Counter(),strict_bottlenecks=Counter(),alignment_counts=dict(Counter(a['status'] for a in libraries[s]['alignment'].values()))) for s in SOURCES}
    for task in study['tasks']:
        tid=task['task_id'];case=references['cases'][task['case_id']]
        required_points=[p for p in case['key_points'] if not p['optional'] and p['capability']=='text']
        wanted=list(dict.fromkeys(eid for p in required_points if p['kind'] not in {'scope_limit','corpus_scope','test_boundary'} for eid in p['evidence_ids']))
        row=dict(task_id=tid,question=task['question'],category=case['category'],expected_behavior=case['expected_behavior'],
            reference_answer=case['reference_answer'],required_points=required_points,requested_evidence_ids=wanted,systems={})
        for system in SOURCES:
            probe=probes[system][tid];old=history[system][tid]['response'];lib=libraries[system]
            agreement=replay_agreement(probe,old)
            for name,value in agreement.items():summary[system][name]+=value
            traces={eid:evidence_trace(lib['alignment'][eid],probe,old,lib) for eid in wanted}
            for eid,trace in traces.items():
                if eid not in common_strict:
                    continue
                summary[system]['strict_requests']+=1;summary[system]['strict_bottlenecks'][trace['positional_bottleneck']]+=1
                for name,status in trace['stages'].items():
                    summary[system]['strict_counts'][name]+=status['status']=='complete'
            row['systems'][system]=dict(**agreement,evidence=traces,
                probe=probe,historical_answer=old['answer'],historical_final=old['retrieved_evidence'],
                historical_result_sha256=history[system][tid]['result_sha256'])
        rows.append(row)
    for system in summary:
        summary[system]['strict_counts']=dict(summary[system]['strict_counts']);summary[system]['strict_bottlenecks']=dict(summary[system]['strict_bottlenecks'])
    require(len({s['strict_requests'] for s in summary.values()})==1,'Cross-index strict denominators differ')
    result=dict(version=VERSION,question_count=32,indexes=3,summary=summary,common_strict_evidence_ids=common_strict,
        embedding=dict(logical_api_calls=queries['logical_api_calls'],usage=queries['usage'],actual_billing_usd=None,
            dimensions=queries['dimensions'],requested_model=queries['requested_model'],batching=queries['batching']),
        generation_calls=0,judge_calls=0,reference_evidence_count=len(evidence),
        policy='Reported coverage measures identified raw source spans. Near alignment is provisional; scope points are not graded. No page-only, keyword-only, answer-quality or semantic-sufficiency score is assigned.',
        limitations=study['limitations'],application_default_unchanged=judge.digest(ROOT/'backend/.env.literature')==study['application_config_sha256'])
    require(result['application_default_unchanged'],'Application configuration changed during diagnostics')
    OUTPUT.mkdir(parents=True,exist_ok=refresh)
    save(OUTPUT/'summary.json',result)
    save(OUTPUT/'alignment.json',{s:lib['alignment'] for s,lib in libraries.items()})
    save(OUTPUT/'chunks.json',{s:{cid:dict(text=c['text'],kind=c['kind'],page_start=c['page_start'],page_end=c['page_end'],
        section_path=lib['manifest']['mapping'][cid].get('section_path',[])) for cid,c in lib['chunks'].items()} for s,lib in libraries.items()})
    (OUTPUT/'questions.jsonl').write_text(''.join(judge.encode(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    save(OUTPUT/'audit.json',dict(study_sha256=judge.digest(PRIVATE/'study.json'),query_vectors_sha256=judge.digest(PRIVATE/'queries.json'),
        replay_seals={s:judge.read_json(PRIVATE/'replays'/(s+'-seal.json')) for s in SOURCES},
        original_run_sha256={s:source['run_sha256'] for s,source in study['sources'].items()},
        rules_sha256=judge.digest(ROOT/'scripts/qa_retrieval_alignment.py'),worker_sha256=judge.digest(PRIVATE/'harness/qa_retrieval_probe_worker.py'),
        original_libraries_unchanged=True,no_scientific_scores_assigned=True))
    render(result,rows,evidence,libraries)
    save(OUTPUT/'publication.json',dict(files={p.name:judge.digest(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!='publication.json'},
        document_sha256=judge.digest(DOC),exporter_sha256=judge.digest(Path(__file__)),model_calls=0))
    print(json.dumps(dict(summary=summary,embedding=result['embedding'],generation_calls=0,judge_calls=0),ensure_ascii=False))


def render(result,rows,evidence,libraries):
    e=lambda x:escape(str(x),quote=True)
    names={s:SOURCES[s][2] for s in SOURCES}
    labels={'complete':'齐全','partial':'部分','missing':'无','unresolved':'待定位'}
    align_labels={'located':'严格定位','review_required':'近似定位，待核查','unresolved':'未可靠定位'}
    reasons={'source_not_fully_indexed':'标注原文未完整入索引','outside_top50_or_partial':'50候选未覆盖齐全',
        'threshold_or_missing_metadata':'阈值筛选或元数据缺失','outside_top8_or_partial':'前8名未覆盖齐全',
        'context_assembly_loss':'补全后未覆盖齐全','context_present':'已提供对应原文',
        'neighbor_recovered':'通过邻块补回','alignment_unresolved':'先核查原文对齐'}
    stage_order=['top50','passing50','top8','final','historical_final']
    stage_names=['重放50候选','通过阈值','重放前8','重放上下文','历史上下文']
    fraction=lambda n,d:f'{n}/{d} ({n/d*100:.2f}%)' if d else '不适用'
    focused={r['task_id']:r for r in rows if r['task_id'] in {'PFI2-011','PFI2-032'}}
    findings=[]
    for tid,eid,name in [('PFI2-011','E08','Table 1关键数值表'),('PFI2-032','E20','摘要相关系数段')]:
        trace=focused[tid]['systems']['sections']['evidence'][eid]
        first=trace['first_intersection'];agreement=focused[tid]['systems']['sections']
        findings.append(f"{tid}：章节107块版的{name}在本次重放中排第{first['rank'] if first else '未定位'}，"
            f"分数{first['score']:.6f}，通过0.35阈值；前8{labels[trace['stages']['top8']['status']]}、最终上下文{labels[trace['stages']['final']['status']]}。"
            f"这两阶段与历史记录{'一致' if agreement['top8_equal_history'] and agreement['context_equal_history'] else '存在差异，需分开解释'}。")
    findings+=['这两个重点案例支持优先诊断50候选到前8的排序与证据覆盖，而不是直接降低相似度阈值。摘要段存在近似文字对齐，仍保留差异记录，不混入严格覆盖汇总。',
        '共同严格定位的20个关联引文请求均进入50候选并通过阈值，但最终只有18个齐全；这只是限定引文集合，不能推断其余问题也都属于排序问题。']
    md=['# 32题检索诊断：候选、排序与原文覆盖','',
        '2026-10-30。本次只重放检索，不重新答题、不调用Jev或Luna、不修改旧答案与评分。三套封存索引共用同一批BGE-M3问题向量。','',
        '**50个候选属于本次诊断重放；历史运行没有保存50候选。** 历史前8和上下文来自原始答题记录，另行核对是否与本次重放一致。','',
        '## 本轮主要发现','',*['- '+line for line in findings],'',
        '## 统计口径','',
        f"三套索引共同可严格定位的标注引文为{len(result['common_strict_evidence_ids'])}/{len(evidence)}条："+', '.join(result['common_strict_evidence_ids'])+'。汇总按“题目×关联引文”去重计数，三个版本使用相同分母，不是32题的答案正确率。同一表格可能支撑多条标注，这些请求不视为独立实验。',
        '引文跨块时检查全部原文范围是否覆盖；表格通过表号、页码与全部标注数据行定位。相同页码或相同关键词不算齐全。近似对齐和未定位单列，不记为漏召回，也不进入共同严格统计。',
        '部分引文比某个要点实际需要的内容更长，也可能存在未标注的替代证据。因此这里诊断的是标注原文的位置覆盖，不是语义充分性、标准答案得分或正式第六项评分。','',
        '## 共同严格定位引文的覆盖','',
        '| 版本 | 引文请求数 | 50候选齐全 | 阈值后齐全 | 前8齐全 | 最终上下文齐全 | 历史前8复现 | 历史上下文复现 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>32题检索诊断</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1560px;margin:32px auto;padding:0 24px}article,details{background:white;border:1px solid #dce5ef;border-radius:8px;padding:16px;margin:14px 0}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fb;padding:12px;font:13px/1.65 monospace}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:white}td,th{padding:8px;border:1px solid #dce5ef;text-align:left;vertical-align:top}a{color:#216dba}input{width:min(600px,90%);padding:12px;border:1px solid #bdcfe2;border-radius:6px}h2{font-size:21px}h3{font-size:18px}.warn{color:#8a6100}.ok{color:#116944}.tiny{font-size:13px}.case[hidden]{display:none}</style><main>',
        '<h1>32题检索诊断：候选、排序与原文覆盖</h1>',
        '<p>仅调用一次Embedding获得32个问题向量，三套索引共用。新增答题调用0次，新增评分调用0次。历史答案、评分、索引和应用默认配置保留。</p>',
        '<p><strong>重放与历史分开：</strong>50候选由本次重放采集；历史仅有前8与最终上下文。下面逐题检查两者是否一致，不把新采集的排名冒充历史观测。</p>',
        '<p><strong>覆盖定义：</strong>按原文范围或验证后的完整表格定位。标注引文覆盖不是语义充分性；可能遗漏其他有效证据。近似文字对齐单列待核查，范围声明类要点不参与位置覆盖统计。</p>',
        f'<p>共同严格定位引文{len(result["common_strict_evidence_ids"])}/{len(evidence)}条；汇总采用相同“题目×引文”分母。近似映射结果仍在每题明细展示。</p>',
        '<h2>本轮主要发现</h2><ul>'+''.join('<li>'+e(line)+'</li>' for line in findings)+'</ul>',
        '<h2>共同严格定位引文：相同请求集合</h2><div class="scroll"><table><tr><th>版本</th><th>引文请求</th><th>50候选齐全</th><th>阈值后齐全</th><th>前8齐全</th><th>最终上下文齐全</th><th>历史前8一致</th><th>历史上下文一致</th></tr>']
    for system,s in result['summary'].items():
        values=[names[system],str(s['strict_requests']),*[fraction(s['strict_counts'].get(stage,0),s['strict_requests']) for stage in stage_order[:-1]],
            f"{s['top8_equal_history']}/32",f"{s['context_equal_history']}/32"]
        md.append('| '+' | '.join(values)+' |');h.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in values)+'</tr>')
    h.append('</table></div><p>上表“一致”要求顺序及文字严格相同。下方另列来源集合是否相同；排序变化不等于换了一套证据。部分重放成员发生变化，具体历史50候选仍不可回溯，不能据本次排名断言其历史精确排名。</p>')
    md+=['','上表复现计数要求顺序及文字严格一致；成员集合另列如下。部分重放存在成员变化，其原因未被本次实验识别，不把本次排名当作历史精确排名。','']
    for system,s in result['summary'].items():
        line=f"{names[system]}：前8成员集合与历史相同{s['top8_members_equal_history']}/32，最终上下文来源集合相同{s['context_sources_equal_history']}/32。"
        md.append('- '+line);h.append('<p>'+e(line)+'</p>')
    h.append('<h2>重点题：第11、32题</h2>')
    md+=['','## 重点题定位','']
    for row in rows:
        if row['task_id'] not in {'PFI2-011','PFI2-032'}:continue
        md+=['### '+row['task_id']+' '+row['question'],'']
        h.append('<article><h3><a href="#'+e(row['task_id'])+'">'+e(row['task_id'])+'</a> · '+e(row['question'])+'</h3>')
        for system,item in row['systems'].items():
            for eid,t in item['evidence'].items():
                first=t['first_intersection'];rank=str(first['rank']) if first else '50名内无交集/待定位'
                line=f"{names[system]} / {eid}：{align_labels[t['alignment_status']]}；首次定位交集第{rank}，齐全所需排名{t['completion_rank']}；前8{labels[t['stages']['top8']['status']]}，最终{labels[t['stages']['final']['status']]}，历史最终{labels[t['stages']['historical_final']['status']]}。"
                md.append('- '+line);h.append('<p class="tiny">'+e(line)+'</p>')
        h.append('</article>')
    h+=['<h2>全部32题诊断</h2><p><a href="#PFI2-011">跳到第11题</a> · <a href="#PFI2-032">跳到第32题</a></p>',
        '<p><input id="search" type="search" placeholder="搜索题号或问题，例如 PFI2-011、结晶度"><span id="count">32题</span></p>']
    by_eid={x['id']:x for x in evidence}
    for row in rows:
        h.append('<details class="case" id="'+e(row['task_id'])+'" data-search="'+e(row['task_id']+' '+row['question'])+'"><summary>'+e(row['task_id'])+' · '+e(row['question'])+'</summary>')
        h.append('<details><summary>参考答案、必答要点与标注来源</summary><pre>'+e(row['reference_answer'])+'</pre><pre>'+e(json.dumps(row['required_points'],ensure_ascii=False,indent=2))+'</pre></details>')
        if not row['requested_evidence_ids']:
            h.append('<p class="warn">本题所需要点属于范围或语料库边界声明，位置覆盖不适用。仍保留完整检索轨迹和历史回答供核查。</p>')
        for system,item in row['systems'].items():
            order_note='一致' if item['top8_equal_history'] else ('成员相同，顺序不同' if item['top8_members_equal_history'] else '成员不同')
            context_note='一致' if item['context_equal_history'] else ('来源集合相同，分组/顺序/引用编号不同' if item['context_sources_equal_history'] else '来源集合不同')
            h.append('<h3>'+e(names[system])+'</h3><p>前8与历史：'+e(order_note)+'；最终上下文与历史：'+e(context_note)+'。</p>')
            h.append('<div class="scroll"><table><tr><th>标注引文</th><th>来源对齐</th><th>首次交集 / 齐全排名</th>'+''.join('<th>'+e(n)+'</th>' for n in stage_names)+'<th>定位瓶颈</th></tr>')
            for eid,t in item['evidence'].items():
                first=t['first_intersection'];rank=f"{first['rank']} / {t['completion_rank']}" if first else '无/待定位'
                source=by_eid[eid]
                cells=[eid+' · 第'+str(source['pdf_page'])+'页 · '+source['locator'],align_labels[t['alignment_status']],rank,
                    *[labels[t['stages'][name]['status']] for name in stage_order],reasons[t['positional_bottleneck']]]
                h.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in cells)+'</tr>')
            h.append('</table></div><p class="tiny">“首次交集”只表示某个候选包含引文的一部分；“齐全排名”才表示累计覆盖全部定位范围。近似映射各列仅表示暂定位置，需看解析差异。</p>')
            for eid,t in item['evidence'].items():
                h.append('<details><summary>'+e(eid)+' 原文、定位与解析差异</summary><pre>'+e(by_eid[eid]['quote'])+'</pre><pre>'+e(json.dumps(libraries[system]['alignment'][eid],ensure_ascii=False,indent=2))+'</pre><pre>'+e(json.dumps(t,ensure_ascii=False,indent=2))+'</pre></details>')
            h.append('<details><summary>全部50个候选：排名、分数、阈值、类型和原文</summary><div class="scroll"><table><tr><th>排名</th><th>分数</th><th>过阈值</th><th>主命中</th><th>类型 / 页码</th><th>章节</th><th>标注位置交集</th><th>原文</th></tr>')
            selected={x['chunk_id'] for x in item['probe']['seeds']}
            for c in item['probe']['candidates']:
                cid=c['chunk_id'];intersections=[]
                if c['metadata_present']:
                    intersections=[eid for eid in row['requested_evidence_ids'] if span_coverage(libraries[system]['alignment'][eid],[cid],libraries[system]['chunk_spans'])['covered']]
                cells=[str(c['rank']),f"{c['score']:.6f}",'是' if c['passes_threshold'] else '否','是' if cid in selected else '否',
                    str(c['kind'])+' / '+str(c['page_start'])+'–'+str(c['page_end']),
                    ' > '.join(libraries[system]['manifest']['mapping'].get(cid,{}).get('section_path',[])) or '未记录',', '.join(intersections)]
                h.append('<tr>'+''.join('<td>'+e(x)+'</td>' for x in cells)+'<td><a href="#source-'+e(system+'-'+cid)+'">'+e(cid)+'</a></td></tr>')
            h.append('</table></div></details><details><summary>最终上下文、原文块和预算记录</summary><pre>'+e(json.dumps(dict(context=item['probe']['context'],evidence=item['probe']['final']),ensure_ascii=False,indent=2))+'</pre></details>')
            h.append('<details><summary>历史回答（本次未重新生成）</summary><pre>'+e(item['historical_answer'])+'</pre></details>')
        h.append('</details>')
    h.append('<h2>所有索引块原文</h2><p>候选表中的原文链接指向这里。章节标签如存在，属于程序整理的元数据。</p>')
    for system,lib in libraries.items():
        h.append('<h3>'+e(names[system])+'</h3>')
        for cid,c in lib['chunks'].items():
            h.append('<details id="source-'+e(system+'-'+cid)+'"><summary>'+e(cid)+f' · {e(c["kind"])} · 第{c["page_start"]}–{c["page_end"]}页</summary><pre>'+e(c['text'])+'</pre></details>')
    md+=['','## 对齐限制与调用记录','',
        *[f"- {names[s]}：{json.dumps(x['alignment_counts'],ensure_ascii=False)}；共同严格请求的定位瓶颈：{json.dumps(x['strict_bottlenecks'],ensure_ascii=False)}。" for s,x in result['summary'].items()],
        '',f"新增Embedding逻辑请求{result['embedding']['logical_api_calls']}次，用量{json.dumps(result['embedding']['usage'],ensure_ascii=False)}；向量维度{result['embedding']['dimensions']}。实际货币费用未知。新增答题0次、评分0次。",'',
        '现有参考引文属于AI检查的开发集标注，不是专家金标准。报告没有给旧答案补分、改分或重新评测，也没有更改检索配置或上线索引。',
        '', '[全部32题、三套索引、50候选与原文](../data/literature/qa-evaluation/reports/retrieval-diagnostic-v1-20261030/comparison.html)。',
        '', '离线重新导出：`python scripts/diagnose_qa_retrieval.py refresh`；需要保留本机私有诊断缓存，不会调用模型。']
    DOC.write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
    h+=['<details><summary>调用记录和汇总JSON</summary><pre>'+e(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></details>',
        '<script>function reveal(){const t=document.getElementById(location.hash.slice(1));if(t){if(t.classList.contains("case")&&t.hidden){document.getElementById("search").value="";for(const c of document.querySelectorAll(".case"))c.hidden=false;document.getElementById("count").textContent="32题";}for(let n=t;n;n=n.parentElement){if(n.tagName==="DETAILS")n.open=true;}t.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();let n=0;for(const c of document.querySelectorAll(".case")){c.hidden=!c.dataset.search.toLowerCase().includes(q);if(!c.hidden)n++;}document.getElementById("count").textContent=n+"题";});</script></main></html>']
    (OUTPUT/'comparison.html').write_text('\n'.join(h),encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','embed','replay','report','refresh']);args=parser.parse_args()
    try:
        if args.action=='prepare':prepare()
        elif args.action=='embed':embeddings()
        elif args.action=='replay':replay()
        else:report(refresh=args.action=='refresh')
    except Exception as error:
        message=str(error) if type(error) is ValueError else type(error).__name__
        print('Retrieval diagnostic failed: '+message,file=sys.stderr);sys.exit(1)
