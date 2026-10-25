"""Versioned v2 evaluation contracts, independent of the product QA implementation."""
from collections import Counter
import math
from pathlib import Path
import re
import sqlite3

from validate_qa_eval import (CATEGORIES, BEHAVIORS, POINT_KINDS, child, digest, nonempty,
                              normalized, read_json, read_jsonl, require, unique_ids, validate_sources)

SUITES = {'core_text', 'injection', 'figure'}
CATS = CATEGORIES | {'false_premise','coefficient_mixup','prompt_injection','figure_reading'}
EXPECTED = {'source_conflict':'flag_conflict','partial_answer':'partial','insufficient_evidence':'abstain',
            'false_premise':'correct_premise','coefficient_mixup':'correct_premise','figure_reading':'figure_approx'}
CORE_FILES = {'cases.jsonl','evidence.json','rubric.json','scorecard.template.jsonl','QUESTIONS.md','README.md',
              'tasks.json','pending/cross-document.jsonl','fixtures/force-injection.json'}


def inventory(pack):
    return {p.relative_to(pack).as_posix():digest(p) for p in sorted(pack.rglob('*'))
            if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def task_selection(pack, suite='core_text'):
    require(suite in SUITES | {'all_active'}, 'Unknown evaluation suite')
    return [t for t in read_json(Path(pack)/'tasks.json') if suite=='all_active' or t['suite']==suite]


def validate_pack(pack, baseline=None):
    pack=Path(pack).resolve()
    m=read_json(pack/'manifest.json')
    require(m.get('schema_version')==2, 'Expected v2 schema')
    require(m.get('review_status')=='source_checked_ai_draft' and m.get('quality_run_status')=='not_run', 'Dataset review/run status invalid')
    require(CORE_FILES<=set(m.get('files',{})), 'Missing canonical v2 files')
    require(set(inventory(pack))==set(m['files']), 'Unexpected or missing v2 pack files')
    for name,checksum in m['files'].items():
        require(isinstance(checksum,str) and bool(re.fullmatch('[0-9a-f]{64}',checksum)), 'Invalid file checksum')
        require(digest(child(pack,name))==checksum,name+': checksum mismatch')
    cases,evidence=read_jsonl(pack/'cases.jsonl'),read_json(pack/'evidence.json')
    ids,eids=unique_ids(cases,'Cases'),unique_ids(evidence,'Evidence')
    require(len(cases)==m['case_count'],'Case count mismatch')
    require(len(evidence)==m['evidence_count'],'Evidence count mismatch')
    unique_ids(m['source_documents'],'Documents')
    pages={d['id']:d['page_count'] for d in m['source_documents']}
    for e in evidence:
        require(e['document_id'] in pages,e['id']+': unknown document')
        for s in [e,*e.get('continuation',[])]:
            require(type(s.get('pdf_page')) is int and 1<=s['pdf_page']<=pages[e['document_id']],e['id']+': invalid PDF page')
            require(nonempty(s.get('baseline_chunk_id')) and nonempty(s.get('quote')),e['id']+': missing source locator')
        require(e.get('verification')=='pdf_visual_and_frozen_chunk_checked',e['id']+': unsupported source review')
        if 'figure_file' in e:
            require(e['figure_file'] in m['files'],'Unhashed figure')
            require(type(e.get('figure_pdf_page')) is int and 1<=e['figure_pdf_page']<=pages[e['document_id']],'Invalid figure page')
    used,questions,mapping=set(),set(),Counter()
    point_count=optional=0
    by_case={c['id']:c for c in cases}
    for c in cases:
        label=c['id']
        require(bool(re.fullmatch('PFI2-[0-9]{3}',label)),'Invalid v2 case ID')
        require(c.get('status')=='ready' and not c.get('template'),label+': template in executable set')
        require(c.get('suite') in SUITES and c.get('category') in CATS,label+': invalid suite/category')
        require(c.get('difficulty') in {'easy','medium','hard'},label+': invalid difficulty')
        require(c.get('expected_behavior') in BEHAVIORS | {'correct_premise','figure_approx'},label+': invalid behavior')
        require(c['expected_behavior']==EXPECTED.get(c['category'],'answer'),label+': category/behavior mismatch')
        require(nonempty(c.get('question')) and nonempty(c.get('reference_answer')) and 'TODO' not in c['reference_answer'],label+': incomplete question/reference')
        question=normalized(c['question'])
        require(question not in questions,label+': duplicate question')
        questions.add(question)
        if c.get('v1_id'): mapping.update(c['v1_id'].split('+'))
        require(c.get('critical_errors') and all(nonempty(v) for v in c['critical_errors']),label+': missing critical errors')
        if c['expected_behavior'] in {'abstain','partial'}: require(nonempty(c.get('absence_reason')),label+': missing absence rationale')
        unique_ids(c['key_points'],label+' points')
        require(any(not p.get('optional',False) and p.get('capability')=='text' for p in c['key_points']),label+': no required text points')
        for p in c['key_points']:
            point_count+=1
            require(type(p.get('optional')) is bool,label+': optional must be boolean')
            optional+=p['optional']
            require(p.get('capability') in {'text','image'} and p.get('kind') in POINT_KINDS | {'test_boundary'},label+': invalid point capability/kind')
            require(nonempty(p.get('text')),label+': empty point')
            refs=p.get('evidence_ids')
            require(isinstance(refs,list) and all(isinstance(r,str) for r in refs),label+': invalid evidence references')
            require(len(refs)==len(set(refs)) and set(refs)<=eids,label+': unknown or duplicate evidence')
            require(refs or p['kind'] in {'scope_limit','corpus_scope','test_boundary'},label+': evidence missing')
            require(p['evidence_requirement'] in {'all','any'},label+': invalid evidence requirement')
            used.update(refs)
            require(isinstance(p.get('numeric_checks'),list),label+': invalid numeric checks')
            for n in p['numeric_checks']:
                require(all(nonempty(n.get(k)) for k in ['label','unit']),label+': numeric role/unit missing')
                for key in ['value','absolute_tolerance']:
                    require(type(n.get(key)) in (int,float) and math.isfinite(n[key]),label+': invalid numeric value')
                require(n['absolute_tolerance']>=0,label+': negative numeric tolerance')
                if n.get('figure_read'): require(p['capability']=='image',label+': figure point not image capability')
    require(point_count==m['key_point_count'],'Key point count mismatch')
    require(optional==m['optional_key_point_count'],'Optional point count mismatch')
    for field in ['category','difficulty','expected_behavior','suite']:
        require(dict(Counter(c[field] for c in cases))==m['counts_by_'+field],field+' count mismatch')
    require(eids-used==set(m['auxiliary_evidence_ids']),'Unused evidence not declared auxiliary')
    # Numeric roles are explicit; verify the two revised arithmetic tasks rather than matching substrings.
    for cid,initial,final in [('PFI2-009',47.16,42.35),('PFI2-021',33.06,29.28)]:
        points=by_case[cid]['key_points']
        inputs=points[0]['numeric_checks']
        require([n['value'] for n in inputs]==[initial,final],cid+': calculation input roles changed')
        for point,expected,unit in [(points[1],initial-final,'percentage_points'),(points[2],(initial-final)/initial*100,'%')]:
            check=point['numeric_checks'][0]
            require(check['unit']==unit and abs(check['value']-expected)<=check['absolute_tolerance'],cid+': derived value/unit mismatch')
    pending=read_jsonl(pack/'pending/cross-document.jsonl')
    require(len(pending)==m['deferred_case_count'] and not ({c['id'] for c in pending}&ids),'Deferred inventory mismatch')
    for c in pending:
        require(c['status']=='deferred_by_user' and c['excluded_from_scoring'] is True,'Cross-document case not deferred')
        require(c['category']=='cross_document' and c.get('requires_corpus'),'Deferred corpus requirement missing')
    require(set(mapping)=={f'PFI-{i:03}' for i in range(1,31)} and set(mapping.values())=={1},'v1 mapping mismatch')
    tasks=read_json(pack/'tasks.json')
    unique_ids(tasks,'Tasks')
    require(len(tasks)==m['task_count'] and {t['case_id'] for t in tasks}==ids,'Task coverage mismatch')
    for t in tasks:
        require(bool(re.fullmatch(r'PFI2-[0-9]{3}(?:-(?:clean|attack|text))?',t['id'])),'Invalid or unsafe task ID')
        require(t['case_id'] in ids and t['suite']==by_case[t['case_id']]['suite'],'Task suite mismatch')
        require(set(t['capabilities'])=={'text'},'Current runner accepts declared text input only')
        if t['suite']=='injection':
            require(t['mode']=='controlled_evidence' and t['variant'] in {'clean','attack'},'Invalid injection task')
            require(t['fixture'] in m['fixture_files'],'Unfrozen injection fixture')
        else: require(t['mode']=='retrieval','Invalid retrieval task')
    f=read_json(pack/'fixtures/force-injection.json')
    require(f['case_id']=='PFI2-033' and f['mode']=='controlled_retrieved_evidence','Fixture identity mismatch')
    require(f['variants']==['clean','attack'] and nonempty(f.get('injected_text')),'Missing attack/control')
    require(nonempty(f.get('clean_text')) and f['source_evidence_id'] in eids,'Fixture source missing')
    require({t.get('variant') for t in tasks if t['suite']=='injection'}=={'clean','attack'},'Both injection variants required')
    e=next(e for e in evidence if e['id']==f['source_evidence_id'])
    require(e['baseline_chunk_id']==f['source_chunk_id'] and e['document_id']==f['original_document_id'],'Fixture source locator mismatch')
    require(f['original_pdf_sha256']==next(d['file_hash'] for d in m['source_documents'] if d['id']==f['original_document_id']),'Fixture PDF fingerprint mismatch')
    require(normalized(e['quote']) in normalized(f['clean_text']),'Fixture omitted real method evidence')
    rubric=read_json(pack/'rubric.json')
    require(rubric['id']==m['rubric_id'] and rubric['version']==2,'Rubric version mismatch')
    require(set(rubric['key_point_scores'])=={'0','0.5','1'},'Unsupported point scale')
    require(len({c['category'] for c in cases})<=rubric['blind_review']['minimum_cases']<=len(cases),'Blind sample cannot cover active categories')
    cards=read_jsonl(pack/'scorecard.template.jsonl')
    require(len(cards)==len(tasks) and {c['task_id'] for c in cards}=={t['id'] for t in tasks},'Scorecard coverage mismatch')
    for card in cards:
        require(card['review_status']=='unreviewed','Template contains reviews')
        for name in ['key_point_scores','point_notes']:
            require(set(card[name])=={p['id'] for p in by_case[card['case_id']]['key_points']} and all(v is None for v in card[name].values()),'Prefilled or missing point template')
        for name in ['run_id','reviewer','reviewer_type','reviewed_at','participated_in_authoring','answerability_score','observed_behavior',
                     'claim_assessments','citation_assessments','retrieval_point_assessments','defects','critical_errors','injection_assessment']:
            require(card[name] is None,'Prefilled scorecard result')
    source_check='not_requested'
    if baseline is not None:
        expanded=[]
        for e in evidence:
            expanded.append(e)
            expanded.extend({**s,'id':e['id']+'-continuation','document_id':e['document_id']} for s in e.get('continuation',[]))
        source_check=validate_sources(m,expanded,baseline)
        with sqlite3.connect((Path(baseline).resolve()/'library/metadata.sqlite3').as_uri()+'?mode=ro',uri=True) as connection:
            text=connection.execute('SELECT text FROM chunks WHERE id=?',(f['source_chunk_id'],)).fetchone()[0]
            require(text==f['clean_text'],'Fixture source differs from frozen chunk')
    return dict(dataset_id=m['dataset_id'],cases=len(cases),tasks=len(tasks),key_points=point_count,
                optional_key_points=optional,deferred_cases=len(pending),counts_by_suite=m['counts_by_suite'],
                pack_validation='passed',source_check=source_check,quality_evaluation='not_run',provider_calls=0)
