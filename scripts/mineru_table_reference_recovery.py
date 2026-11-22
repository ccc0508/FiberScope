"""Confirm damaged Chinese table references within the original PDF region."""
import base64
from collections import defaultdict
from pathlib import Path
import os
import re
import shutil
import subprocess
import unicodedata

import fitz

from index_table_evidence import identified_role, plain, unique_table_targets


# Require a reference cue and either a missing number or a common lookalike.
# Ordinary mentions of a table and intact references are not sent to OCR.
SUSPECT = re.compile(
    r'(?:如|见|由|与|及|据|和|按|对照)\s*(?P<label>表(?:\s*[lI|](?=\s*(?:所示|可|中|内|显示))'
    r'|\s*(?=所示|可知|可以看出|可见|中|内|显示|列出|给出)|\s+(?=[\u3400-\u9fff])))')
NUMBERED = re.compile(r'(?<![列图])表(\d+)(?![\da-zA-Z]|[.-]\d)')


def normalized(text):
    return unicodedata.normalize('NFKC',plain(text))


def compact(text):
    return re.sub(r'\s+','',text)


def context_size(left,right,other_left,other_right):
    def shared(a,b):
        return next((i for i,(u,v) in enumerate(zip(a,b)) if u!=v),min(len(a),len(b)))
    a=shared(left[::-1],other_left[::-1]);b=shared(right,other_right)
    return a>=3 and b>=2 and a+b>=8


def aligned_numbers(text,left,right):
    candidate=compact(normalized(text))
    return [int(m.group(1)) for m in NUMBERED.finditer(candidate)
        if context_size(left,right,candidate[max(0,m.start()-16):m.start()],candidate[m.end():m.end()+16])]


def local_ocr(png):
    """Use installed local OCR only. A missing backend leaves a review item."""
    commands=[]
    if os.name=='nt' and shutil.which('powershell.exe'):
        commands.append((['powershell.exe','-NoProfile','-NonInteractive','-File',
            str(Path(__file__).with_name('ocr_chinese_line_windows.ps1'))],base64.b64encode(png)))
    if shutil.which('tesseract'):
        commands.append((['tesseract','stdin','stdout','-l','chi_sim+eng','--psm','6'],png))
    for argv,image in commands:
        try:
            p=subprocess.run(argv,input=image,capture_output=True,timeout=12,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired):
            continue
        if not p.returncode:return p.stdout.decode('utf-8',errors='replace')
    return None


def line_region(page,region,left,right):
    """Prefer the aligned PDF line; keep the parser block when no line aligns."""
    lines=[]
    for b in page.get_text('dict',clip=region)['blocks']:
        for line in b.get('lines',[]):
            text=normalized(''.join(s['text'] for s in line['spans']))
            for m in SUSPECT.finditer(text):
                start,end=m.span('label')
                if context_size(left,right,compact(text[:start]),compact(text[end:])):
                    lines.append(fitz.Rect(line['bbox']))
    if len(lines)==1:
        r=lines[0]
        # A few points of padding keep glyphs at the edge and nearby context.
        return fitz.Rect(r.x0-5,r.y0-3,r.x1+5,r.y1+3)&page.rect
    return region


def recover_table_references(pdf,chunks,mapping,*,ocr=local_ocr,max_ocr_calls=12):
    """Return recovered link labels and an audit ledger without changing the chunks."""
    chunks=list(chunks);targets=unique_table_targets(chunks,mapping)
    recovered=defaultdict(set);ledger=[];ocr_calls=0;ocr_cache={}
    if not targets:return recovered,ledger
    for c in chunks:
        if c.kind!='paragraph' or not identified_role(c,mapping,'body'):continue
        for span in mapping[c.id]['source_spans']:
            text=normalized(span['text']);matches=list(SUSPECT.finditer(text))
            if not matches:continue
            page=pdf[span['page']-1];r=page.rect
            x0,y0,x1,y1=span['bbox']
            clip=fitz.Rect(r.x0+x0*r.width/1000-5,r.y0+y0*r.height/1000-5,
                r.x0+x1*r.width/1000+5,r.y0+y1*r.height/1000+5)&r
            if clip.is_empty:continue
            text_layer=page.get_text('text',clip=clip,sort=True)
            for m in matches:
                start,end=m.span('label');left=compact(text[:start])[-16:];right=compact(text[end:])[:16]
                row=dict(document_id=c.document_id,chunk_id=c.id,source_id=span['source_id'],
                    page=span['page'],native_bbox=span['bbox'],original=m['label'].strip(),
                    context=left+m['label']+right,status='review_required')
                ledger.append(row)
                if len(left)<3 or len(right)<2 or len(left)+len(right)<8:
                    row['reason']='insufficient_context';continue
                numbers=aligned_numbers(text_layer,left,right);method='pdf_text_layer'
                if len(numbers)>1:
                    row['reason']='ambiguous_pdf_alignment';continue
                if not numbers:
                    region=line_region(page,clip,left,right)
                    if region.is_empty or region.height>210 or region.width>610:
                        row['reason']='ocr_region_too_large';continue
                    key=(span['page'],*tuple(region))
                    if key not in ocr_cache:
                        if ocr is None or ocr_calls>=max_ocr_calls:
                            row['reason']='local_ocr_unavailable_or_budget';continue
                        pix=page.get_pixmap(matrix=fitz.Matrix(3.5,3.5),clip=region,alpha=False)
                        ocr_cache[key]=ocr(pix.tobytes('png'));ocr_calls+=1
                    text_ocr=ocr_cache[key]
                    if text_ocr is None:
                        row['reason']='local_ocr_unavailable';continue
                    numbers=aligned_numbers(text_ocr,left,right);method='local_ocr'
                    if len(numbers)!=1:
                        row['reason']='ocr_reference_not_unique';continue
                    row['ocr_rect_points']=list(region)
                number=numbers[0];target=targets.get((c.document_id,number))
                if compact(m['label']) in {'表l','表I','表|'} and number!=1:
                    row.update(reason='lookalike_conflicts_with_number',candidate_number=number);continue
                if target is None:
                    row.update(reason='table_label_not_unique_or_missing',candidate_number=number);continue
                recovered[c.id].add(number)
                row.update(status='confirmed',method=method,table_number=number,target_chunk_id=target.id)
    return recovered,ledger
