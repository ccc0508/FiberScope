"""Conservative content roles and role-safe regrouping of immutable MinerU spans.

No question, reference answer or model is used. Status is rule evidence, never a
probability of correctness. Unknown/mixed native blocks remain independent.
"""
from collections import Counter
import re

from mineru_sections import organize, plain, prefix_for

VERSION = 'mineru-content-roles-v1'
PREFIXES = {
    'abstract': r'(?:abstract|摘要)',
    'keywords': r'(?:key\s*words|关键词|关键字)',
    'authors': r'(?:authors?|作者)',
    'affiliation': r'(?:affiliations?|作者单位|工作单位|机构)',
    'dates': r'(?:received|accepted|published|收稿日期|录用日期|发表日期)',
    'author_contributions': r'(?:author contributions|作者贡献)',
    'funding': r'(?:funding|基金项目|资助信息)',
    'conflicts': r'(?:conflicts? of interest|利益冲突)',
    'supplementary': r'(?:supplementary materials?|补充材料)',
    'publisher_note': r'(?:publisher[’\x27]s note|出版者声明)',
}
LABELS = {k:re.compile(r'^\s*'+v+r'\s*[:：]\s*',re.I) for k,v in PREFIXES.items()}
EXACT = {k:re.compile(r'^\s*'+v+r'\s*[:：]?\s*$',re.I) for k,v in PREFIXES.items()}
INSTITUTION = re.compile(r'\b(?:university|institute|school of|department of|laboratory|research cent(?:er|re))\b|大学|研究所|研究院|实验室|学院',re.I)
NAME = r'[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:[ -][A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+){1,3}'
NAMES = re.compile(r'^'+NAME+r'(?:\s*(?:,|;|&|\band\b)\s*'+NAME+r')+\s*$',re.UNICODE)
MAIN_HEADING = re.compile(r'^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:introduction|materials(?: and methods)?|methods|experimental(?: setup)?|results(?: and discussion[s]?)?|discussion|conclusions?|references|bibliography|引言|绪论|材料与方法|实验方法|结果|讨论|结论|参考文献)\s*$',re.I)
REF_HEADING = re.compile(r'^\s*(?:\d+\.?\s*)?(?:references|bibliography|参考文献)\s*$',re.I)


def classify(units):
    roles={};front=True;abstract_group=None;abstract_level=0;references=False;metadata_section=None
    for u in units:
        text=plain(u['text']);kind=u['kind'];sid=u['source_id']
        result=dict(role='unknown',status='uncertain',signals=['insufficient_role_evidence'],group=None)
        explicit=[k for k,p in LABELS.items() if p.match(text)]
        # Embedded role labels require a boundary, not an arbitrary word match.
        embedded=[]
        for k,prefix in PREFIXES.items():
            if re.search(r'(?:\n|[.;。；]\s+|\s+)'+prefix+r'\s*[:：]',u['text'],re.I):embedded.append(k)
        mixed=set(explicit+embedded)
        if len(mixed)>1:
            result.update(role='mixed',signals=['multiple_role_labels:'+','.join(sorted(mixed))]);abstract_group=None
        elif explicit:
            role=explicit[0]
            if role=='abstract' and not front:
                result['signals']=['abstract_label_outside_front_matter']
            else:
                if role=='abstract':
                    abstract_group='abstract:'+sid;abstract_level=u.get('native_text_level') or 0
                elif role!='abstract':abstract_group=None
                result=dict(role=role,status='identified',signals=['explicit_label'],group=abstract_group)
        elif '©' in text or re.match(r'^(?:copyright\b|版权声明|著作权声明)',text,re.I):
            result=dict(role='copyright',status='identified',signals=['copyright_marker'],group=None);abstract_group=None
        elif front and EXACT['abstract'].fullmatch(text):
            abstract_group='abstract:'+sid;abstract_level=u.get('native_text_level') or 0
            result=dict(role='abstract',status='identified',signals=['abstract_heading'],group=abstract_group)
        elif kind=='heading' and any(EXACT[k].fullmatch(text) for k in ['author_contributions','funding','conflicts','supplementary']):
            metadata_section=next(k for k in ['author_contributions','funding','conflicts','supplementary'] if EXACT[k].fullmatch(text))
            abstract_group=None
            result=dict(role=metadata_section,status='identified',signals=['metadata_section_heading'],group=None)
        elif abstract_group and kind=='heading' and (u.get('native_text_level') or 0)>abstract_level and re.match(
                r'^(?:background|aims?|objectives?|methods?|results?|conclusions?|背景|目的|方法|结果|结论)\s*[:：]?$',text,re.I):
            result=dict(role='abstract',status='identified',signals=['structured_abstract_subheading'],group=abstract_group)
        elif MAIN_HEADING.fullmatch(text) and (kind=='heading' or len(text)<80):
            front=False;abstract_group=None;metadata_section=None;references=bool(REF_HEADING.fullmatch(text))
            result=dict(role='heading',status='identified',signals=['main_section_heading'],group=None)
        elif abstract_group:
            if kind=='paragraph':
                result=dict(role='abstract',status='identified',signals=['within_explicit_abstract_range'],group=abstract_group)
            else:
                abstract_group=None
        elif kind in {'table','equation','figure_caption'}:
            result=dict(role=kind,status='identified',signals=['native_content_type'],group=None)
        elif metadata_section and kind=='paragraph':
            result=dict(role=metadata_section,status='identified',signals=['within_explicit_metadata_section'],group=None)
        elif kind=='reference' or references:
            if re.match(r'^\s*(?:\[\d+\]|\d+\.)\s*\S+',text) and re.search(r'\b(?:18|19|20)\d{2}\b',text):
                result=dict(role='reference',status='identified',signals=['bibliographic_number_and_year','reference_region_or_native_type'],group=None)
            elif kind=='reference' and re.search(r'\b(?:18|19|20)\d{2}\b',text) and re.search(r'\bdoi\b|https?://doi\.',text,re.I):
                result=dict(role='reference',status='identified',signals=['native_reference_with_year_and_doi'],group=None)
        elif front and kind=='paragraph':
            # Layout position alone is never sufficient to label a person's name.
            cleaned=re.sub(r'<[^>]*>|[\\*\d†‡]','',u['text'])
            cleaned=re.sub(r',\s+and\s+',', ',cleaned)
            if INSTITUTION.search(text) and len(text)<1200:
                result=dict(role='affiliation',status='identified',signals=['front_matter','institution_terms'],group=None)
            elif len(text)<240 and NAMES.fullmatch(cleaned.strip()):
                result=dict(role='authors',status='identified',signals=['front_matter','multiple_person_name_pattern'],group=None)
            elif text.lower() in {'article','research article','review article','research paper'}:
                result=dict(role='publication_type',status='identified',signals=['front_matter_publication_type'],group=None)
        elif kind=='heading':
            metadata_section=None
            result=dict(role='heading',status='identified',signals=['native_heading'],group=None)
        elif kind=='paragraph' and not references:
            result=dict(role='body',status='identified',signals=['main_body_range'],group=None)
        roles[sid]=result
    return roles


def can_merge(a,b):
    return (a['status']==b['status']=='identified' and a['role']==b['role'] and
            a['role'] in {'body','abstract'} and a.get('group')==b.get('group'))


def organize_roles(units,document_id,native_blocks,target_chars=1200,max_chars=8000):
    base=organize(units,document_id,native_blocks,target_chars,max_chars)
    roles=classify(units);chunks=[]
    for index,old in enumerate(base['chunks']):
        def span_role(span):
            r=roles[span['source_id']]
            if r['role']=='heading' and old['kind']!='heading':
                return dict(role='unknown',status='uncertain',group=None,signals=['heading_body_fragment_requires_review'])
            return r
        groups=[]
        for span in old['source_spans']:
            role=span_role(span)
            if groups and can_merge(span_role(groups[-1][-1]),role):groups[-1].append(span)
            else:groups.append([span])
        for spans in groups:
            first=span_role(spans[0]);body='\n\n'.join(s['text'] for s in spans)
            text=prefix_for(old['section_path'])+body
            if len(text)>max_chars:raise ValueError('Classified chunk exceeds original budget')
            chunk={**old,'source_spans':spans,'body_text':body,'text':text,
                'page_start':min(s['page'] for s in spans),'page_end':max(s['page'] for s in spans),
                'content_role':first['role'],'role_status':first['status'],'role_group':first.get('group'),
                'role_signals':sorted({s for span in spans for s in span_role(span)['signals']}),
                'parent_chunk_index':index}
            chunks.append(chunk)
    # Independently verify conservation after splitting any old mixed-role groups.
    expected=Counter((s['source_id'],s['start'],s['end'],s['text']) for c in base['chunks'] for s in c['source_spans'])
    actual=Counter((s['source_id'],s['start'],s['end'],s['text']) for c in chunks for s in c['source_spans'])
    if actual!=expected:raise ValueError('Role organization changed original spans')
    for c in chunks:
        records=[roles[s['source_id']] for s in c['source_spans']]
        if len(records)>1 and (c['role_status']!='identified' or not all(can_merge(records[0],r) for r in records[1:])):
            raise ValueError('Cross-role or uncertain merge')
    return dict(**{k:v for k,v in base.items() if k not in {'version','chunks','chunk_kinds','policy'}},
        version=VERSION,chunks=chunks,chunk_kinds=dict(Counter(c['kind'] for c in chunks)),
        native_roles=roles,content_role_counts=dict(Counter(c['content_role'] for c in chunks)),
        previous_chunks=len(base['chunks']),classification_model_calls=0,
        policy='Rule-evidenced content roles; unknown/mixed and metadata remain independent. Only continuous body/abstract spans of the same role within an original section chunk may merge. No text rewritten, deleted, or new vector search.')
