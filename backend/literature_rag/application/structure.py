"""Conservative text-PDF rechunking: preserve same-page tables and sentence boundaries."""
from collections.abc import Sequence
from dataclasses import dataclass
import re

from literature_rag.application.context import join_chunks
from literature_rag.domain.models import Chunk

VERSION='text-structure-v1'
TABLE=re.compile(r'^\s*(?:Table\s+\d+[A-Za-z]?\b|表\s*\d+)',re.I)
HEADING=re.compile(r'^\s*(?:\d+(?:\.\d+)*\.\s+[A-Z]|(?:Figure|Fig\.)\s+\d+\b)',re.I)
ROW=re.compile(r'^\s*[+−-]?\d[\d,.]*\s+.*\d')


@dataclass(frozen=True)
class StructuralUnit:
    page_start: int
    page_end: int
    kind: str
    text: str
    start: int
    end: int
    source_chunk_ids: tuple[str,...]


def _row(line):
    return bool(ROW.match(line)) and len(re.findall(r'\d+(?:[.,]\d+)*',line))>=2 and not HEADING.match(line)


def split_page(text,page_start,page_end,source_ids,paragraph_chars=1200,max_chars=8000):
    """All output is an exact source substring. Unsupported oversized units fail explicitly."""
    lines=[];position=0
    for line in text.splitlines(keepends=True):
        lines.append((position,position+len(line),line));position+=len(line)
    table_ranges=[];warnings=[];i=0
    while i<len(lines):
        if not TABLE.match(lines[i][2]):i+=1;continue
        start=i;j=i+1;seen_rows=0;footnote=False
        while j<len(lines):
            line=lines[j][2].strip()
            if TABLE.match(line) or HEADING.match(line):break
            if _row(line):seen_rows+=1;footnote=False
            elif seen_rows:
                # Subtable labels, headers and short formula/header lines belong to the table.
                note=bool(re.match(r'^[a-z]\s+[A-Z]',line))
                narrative=bool(re.match(r'^(?:The|This|These|Those|It|In|For|During|As|However|Because|There|'
                                        r'Subsequently|Recently|Both|According)\s+',line)) and len(line)>55 and not note
                if narrative and not footnote:break
                if note:footnote=True
                elif footnote and re.search(r'[.!?。]\s*$',line):footnote=False
            j+=1
        if seen_rows:
            table_ranges.append((lines[start][0],lines[j-1][1]))
            if j==len(lines):warnings.append('table_reaches_page_end_cross_page_completeness_unverified')
            i=j
        else:
            warnings.append('table_caption_without_verified_numeric_rows');i+=1
    units=[]

    def add(start,end,kind):
        raw=text[start:end];left=len(raw)-len(raw.lstrip());right=len(raw.rstrip())
        if right<=left:return
        start+=left;end=start+right-left
        if end-start>max_chars:
            raise ValueError('source unit exceeds context budget; verify row/header-preserving splits before activation')
        units.append(StructuralUnit(page_start,page_end,kind,text[start:end],start,end,tuple(source_ids)))

    def prose(start,end):
        if end<=start:return
        piece_start=start;previous=''
        for a,b,line in lines:
            if a<start or b>end:continue
            if a>piece_start and (HEADING.match(line) or
                    a-piece_start>=paragraph_chars and re.search(r'[.!?。！？]\s*$',previous)):
                add(piece_start,a,'paragraph');piece_start=a
            if b-piece_start>max_chars:
                add(piece_start,a,'paragraph');piece_start=a
            previous=line
        add(piece_start,end,'paragraph')

    cursor=0
    for start,end in table_ranges:
        prose(cursor,start);add(start,end,'table');cursor=end
    prose(cursor,len(text))
    return units,warnings


def rechunk(chunks: Sequence[Chunk],paragraph_chars=1200,max_chars=8000):
    pages={}
    for c in chunks:pages.setdefault((c.document_id,c.page_start,c.page_end),[]).append(c)
    output=[];page_snapshots=[]
    for (document_id,start,end),group in sorted(pages.items()):
        group.sort(key=lambda c:c.chunk_index)
        if any(b.chunk_index!=a.chunk_index+1 for a,b in zip(group,group[1:])):
            raise ValueError('cannot reconstruct a source page with missing chunk positions')
        text=join_chunks(group)
        if any(c.text not in text for c in group):
            raise ValueError('source reconstruction lost original text')
        units,warnings=split_page(text,start,end,[c.id for c in group],paragraph_chars,max_chars)
        if start!=end:warnings.append('source_chunk_spans_multiple_pages_no_implicit_table_join')
        output.extend((document_id,u) for u in units)
        page_snapshots.append(dict(document_id=document_id,page_start=start,page_end=end,text=text,warnings=warnings,
                                   source_chunk_ids=[c.id for c in group]))
    return output,page_snapshots
