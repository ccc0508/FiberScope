"""Freeze external answers and existing RAG answers without generating or grading anything."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

import judge_qa_eval as judge
from validate_qa_eval import normalized,require

VERSION='qa-system-import-v1'


def parse_mixed(text):
    """Decode complete top-level JSON objects; preserve all other text as an audit note."""
    decoder=json.JSONDecoder(object_pairs_hook=unique_fields)
    rows=[];outside=[];position=0
    while position<len(text):
        if text[position].isspace():position+=1;continue
        if text.startswith('```',position):
            end=text.find('\n',position)
            if end<0:end=len(text)
            require(text[position:end].strip() in {'```','```json'},'Unexpected code fence')
            outside.append(text[position:end]);position=end;continue
        if text[position]!='{':
            end=text.find('{',position)
            if end<0:end=len(text)
            outside.append(text[position:end]);position=end;continue
        start=position
        row,position=decoder.raw_decode(text,position)
        require(isinstance(row,dict),'Each external answer must be an object')
        rows.append(dict(value=row,start=start,end=position))
    return rows,outside


def unique_fields(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'Duplicate answer JSON key')
        out[key]=value
    return out


def reference(value):
    require(type(value) in {str,int},'Citation reference must be a string or integer')
    match=re.fullmatch(r'(?:\[([1-9][0-9]*)\]|([1-9][0-9]*))',str(value))
    require(match is not None,'Invalid citation reference')
    return '['+(match[1] or match[2])+']'


def normalize_external(row):
    require(set(row)=={'task_id','answer','claims','citations'},'Unexpected external answer fields')
    require(isinstance(row['task_id'],str) and re.fullmatch(r'PFI2-\d{3}',row['task_id']),'Invalid task ID')
    require(isinstance(row['answer'],str) and row['answer'].strip(),'Empty answer')
    require(isinstance(row['claims'],list) and row['claims'],'Empty claim list')
    require(isinstance(row['citations'],list),'Invalid citation list')
    claims=[];citations=[]
    for i,c in enumerate(row['claims'],1):
        require(set(c)=={'text','citation_refs'} and isinstance(c['text'],str) and c['text'].strip(),'Invalid claim')
        require(isinstance(c['citation_refs'],list),'Invalid claim references')
        refs=list(map(reference,c['citation_refs']))
        require(len(refs)==len(set(refs)),'Duplicate attached reference')
        claims.append(dict(id=f'C{i}',text=c['text'],citation_refs=refs))
    for c in row['citations']:
        require(set(c)=={'ref','page_start','page_end','quote'},'Invalid citation fields')
        require(type(c['page_start']) is int and type(c['page_end']) is int
                and 1<=c['page_start']<=c['page_end']<=14,'Invalid PDF physical pages')
        require(isinstance(c['quote'],str) and c['quote'].strip(),'Empty quote')
        citations.append(dict(ref=reference(c['ref']),page_start=c['page_start'],page_end=c['page_end'],text=c['quote']))
    refs=[c['ref'] for c in citations]
    require(len(refs)==len(set(refs)),'Duplicate citation definition')
    require({ref for c in claims for ref in c['citation_refs']}==set(refs),'Missing or unused citation definition')
    answer_body=normalized(re.sub(r'\[[1-9][0-9]*\]','',row['answer']))
    require(answer_body==normalized(''.join(c['text'] for c in claims)),'Answer and claims contain different content')
    return dict(task_id=row['task_id'],answer=row['answer'],claims=claims,citations=citations)


def typography(text):
    """Only documented character-level aliases; no number, unit, percent or word repairs."""
    return normalized(text).replace('◦','°').replace('−','-').replace('⋯','···').replace('’','′')


def verify_quote(citation,page_variants):
    s,e=citation['page_start'],citation['page_end'];quote=citation['text']
    for name,pages in page_variants.items():
        text='\n'.join(pages[s-1:e])
        if normalized(quote) in normalized(text):return dict(status='normalized_exact',extractor=name)
        if typography(quote) in typography(text):return dict(status='typography_only',extractor=name)
    elsewhere=sorted({i+1 for pages in page_variants.values() for i,text in enumerate(pages)
                      if typography(quote) in typography(text)})
    return dict(status='needs_source_review',exact_other_pages=elsewhere,
                note='A text extraction mismatch is not automatically a false citation or a zero quality score.')


def rag_citation(evidence,page_variants=None):
    citation=dict(ref=evidence['ref'],page_start=evidence['page_start'],page_end=evidence['page_end'],text=evidence['text'])
    citation['verification']=verify_quote(citation,page_variants) if page_variants is not None else dict(status='frozen_chunk_metadata_verified')
    return citation


def prepare(input_file,extra_files,pdf,rag_run,recovery_run,output,metadata=None,verify_rag_quotes=False):
    input_file,pdf,rag_run,recovery_run,output=map(lambda p:Path(p).resolve(),
                                                (input_file,pdf,rag_run,recovery_run,output))
    require(not output.exists(),'Use a new immutable import directory')
    run,manifest,cases,sources=judge.verify_run(rag_run)
    rec_run,rec_manifest,_,_=judge.verify_run(recovery_run)
    require(run['dataset_manifest_sha256']==rec_run['dataset_manifest_sha256'],'Recovery dataset differs')
    require(judge.digest(pdf)==manifest['source_documents'][0]['file_hash'],'PDF differs from frozen RAG corpus')
    selected={t['id'] for t in run['tasks']}
    require(selected=={f'PFI2-{i:03}' for i in range(1,33)},'This benchmark requires the same 32 core questions')
    source_bytes=input_file.read_bytes();parsed,outside=parse_mixed(source_bytes.decode('utf-8-sig'))
    original=[(p['value'],input_file,p['start'],p['end']) for p in parsed]
    for path in map(Path,extra_files):
        path=path.resolve();row=judge.strict_json(path.read_text(encoding='utf-8-sig'))
        original.append((row,path,None,None))
    external={};origins={}
    for row,path,start,end in original:
        normalized_row=normalize_external(row);tid=normalized_row['task_id']
        require(tid in selected and tid not in external,'Unknown or duplicate answer task')
        external[tid]=normalized_row
        origins[tid]=dict(source_filename=path.name,source_sha256=judge.digest(path),decoded_character_start=start,decoded_character_end=end)
    require(set(external)==selected,'External answer coverage is incomplete')
    # Optional analysis-only dependencies are imported lazily, never added to the production backend.
    from pypdf import PdfReader
    import pdfplumber
    pages_pypdf=[p.extract_text() for p in PdfReader(pdf).pages]
    with pdfplumber.open(pdf) as doc:pages_pdfplumber=[p.extract_text() or '' for p in doc.pages]
    require(len(pages_pypdf)==len(pages_pdfplumber)==14,'Wrong physical page count')
    variants=dict(pypdf=pages_pypdf,pdfplumber=pages_pdfplumber)
    rag={};rag_origins={};all_jobs=[]
    for task in run['tasks']:
        tid=task['id'];case=cases[task['case_id']]
        if tid in {t['id'] for t in rec_run['tasks']}:
            source_run,contract=recovery_run,rec_run
        else:source_run,contract=rag_run,run
        path,result=judge.read_result(source_run,contract,case,task)
        require(result['status']!='failed','No successful frozen RAG answer')
        r=result['response'];evidence={e['ref']:e for e in r['retrieved_evidence']}
        claims=[dict(id=f'C{i+1}',text=c['text'],citation_refs=c['citation_refs']) for i,c in enumerate(r['claims'])]
        cited={ref for c in claims for ref in c['citation_refs']}
        citations=[rag_citation(e,variants if verify_rag_quotes else None) for e in evidence.values() if e['ref'] in cited]
        require({c['ref'] for c in citations}==cited,'Frozen RAG citation is missing')
        rag[tid]=dict(task_id=tid,answer=r['answer'],claims=claims,citations=citations,
                      available_context=dict(kind='supplied_excerpts',texts=[e['text'] for e in evidence.values()]))
        rag_origins[tid]=dict(source_run_id=contract['run_id'],result_sha256=judge.digest(path),source_run_sha256=judge.digest(source_run/'run.json'))
        for c in external[tid]['citations']:c['verification']=verify_quote(c,variants)
        external[tid]['available_context']=dict(kind='supplied_document',document_id=manifest['source_documents'][0]['id'])
        for system,table in [('rag',rag),('dsh',external)]:
            # Stable opaque labels hide platform and model names from the grading requests.
            blind_id=judge.sha(dict(raw_sha256=judge.digest(input_file),task_id=tid,system=system))[:20]
            all_jobs.append(dict(blind_id=blind_id,task_id=tid,system=system,candidate=deepcopy(table[tid]),
                                 task=deepcopy(task),reference_case=deepcopy(case)))
    output.mkdir(parents=True,mode=0o700);(output/'raw').mkdir();(output/'answers').mkdir()
    (output/'raw/answer.txt').write_bytes(source_bytes)
    for path in map(Path,extra_files):(output/'raw'/path.name).write_bytes(path.read_bytes())
    for system,table in [('rag',rag),('dsh',external)]:
        for tid,row in table.items():judge.write(output/'answers'/f'{system}-{tid}.json',row)
    judge.write(output/'sources.json',sources)
    judge.write(output/'pdf-pages.json',variants)
    judge.write(output/'jobs.json',sorted(all_jobs,key=lambda j:judge.sha(j['blind_id'])))
    details=dict(version=VERSION,created_at=judge.now(),dataset_manifest_sha256=run['dataset_manifest_sha256'],
        pdf_sha256=judge.digest(pdf),source_documents=manifest['source_documents'],
        raw_input_sha256=judge.digest(input_file),external_origins=origins,rag_origins=rag_origins,
        external_non_json_text=outside,source_content_changed=False,format_normalization_only=True,
        question_count=32,answer_count=64,external_claims=sum(len(r['claims']) for r in external.values()),
        external_citations=sum(len(r['citations']) for r in external.values()),
        quote_verification=dict(Counter(c['verification']['status'] for r in external.values() for c in r['citations'])),
        rag_quote_validation='original_pdf_extractors' if verify_rag_quotes else 'frozen_chunk_metadata',
        rag_quote_verification=dict(Counter(c['verification']['status'] for r in rag.values() for c in r['citations'])),
        metadata=metadata or {},paper_reader_versions=reader_versions(),new_answer_generation_calls=0,
        files={str(p.relative_to(output)).replace('\\','/'):judge.digest(p) for p in sorted(output.rglob('*')) if p.is_file()})
    judge.write(output/'import.json',details)
    return details


def reader_versions():
    from importlib.metadata import version
    return {name:version(name) for name in ['pypdf','pdfplumber']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['input','pdf','rag-run','recovery-run','output']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--extra',type=Path,action='append',default=[])
    parser.add_argument('--metadata',type=Path)
    parser.add_argument('--verify-rag-quotes',action='store_true',help='Compare parser-produced citations to original PDF extracts; mismatches receive original-page review context.')
    args=parser.parse_args()
    result=prepare(args.input,args.extra,args.pdf,args.rag_run,args.recovery_run,args.output,
                   judge.read_json(args.metadata) if args.metadata else None,args.verify_rag_quotes)
    print(judge.encode({k:result[k] for k in ['question_count','answer_count','external_claims','external_citations','quote_verification']}))


if __name__=='__main__':main()
