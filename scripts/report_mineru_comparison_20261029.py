"""Audit one real MinerU response against fresh and archived PyMuPDF extraction."""
from collections import Counter
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import argparse
import json
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.rag-data/parsing-comparisons/mineru-vs-pymupdf-20261029'
PUBLIC=ROOT/'data/literature/parsing-comparisons/mineru-vs-pymupdf-20261029'
DOC=ROOT/'docs/QA_MINERU_COMPARISON_20261029.md'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


class PlainText(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)


def plain(text):
    parser=PlainText();parser.feed(text);return ''.join(parser.parts)


class TableRows(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        elif tag in {'td','th'}:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in {'td','th'} and self.cell is not None:
            if self.row is None:raise ValueError('Table cell outside row')
            self.row.append(''.join(self.cell).strip());self.cell=None
        elif tag=='tr':
            if self.row is not None:self.rows.append(self.row)
            self.row=None


class SafeTable(HTMLParser):
    """Provider text is data; render only table/math markup with bounded spans."""
    allowed={'table','thead','tbody','tfoot','tr','th','td','caption','colgroup','col','sup','sub','br'}
    def __init__(self):super().__init__();self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag not in self.allowed:return
        values=[]
        for key,value in attrs:
            if key in {'colspan','rowspan'} and value and re.fullmatch(r'[1-9][0-9]?',value):
                values.append(f' {key}="{value}"')
        self.parts.append('<'+tag+''.join(values)+'>')
    def handle_endtag(self,tag):
        if tag in self.allowed:self.parts.append('</'+tag+'>')
    def handle_data(self,data):self.parts.append(escape(data))


def safe_table(text):
    parser=SafeTable();parser.feed(text);return ''.join(parser.parts)


def numeric_rows(body):
    parser=TableRows();parser.feed(body)
    return [row for row in parser.rows if row and re.fullmatch(r'(?:0|4,?000|8,?000|12,?000|16,?000)',row[0])]


def compare_table(actual,expected_text):
    expected=[line.split() for line in expected_text.splitlines() if re.match(r'^(?:0|4,?000|8,?000|12,?000|16,?000)\s',line)]
    rows=numeric_rows(actual)
    if len(rows)!=len(expected) or any(len(a)!=len(b) for a,b in zip(rows,expected)):
        raise ValueError('Numeric table shape differs from frozen source')
    checks=[dict(row=i+1,column=j+1,source=b,mineru=a,equal=Decimal(a.replace(',',''))==Decimal(b.replace(',','')))
        for i,(ar,er) in enumerate(zip(rows,expected)) for j,(a,b) in enumerate(zip(ar,er))]
    return dict(data_rows=len(rows),numeric_cells=len(checks),matching_cells=sum(c['equal'] for c in checks),checks=checks)


def main(refresh=False):
    if refresh:
        publication=read(PUBLIC/'publication.json')
        if any(digest(PUBLIC/name)!=checksum for name,checksum in publication['files'].items()):raise ValueError('Existing report changed')
        if digest(DOC)!=publication['document_sha256']:raise ValueError('Existing report document changed')
    elif PUBLIC.exists() or DOC.exists():raise ValueError('Use a new report destination')
    baseline=read(PRIVATE/'pymupdf-baseline.json');state=read(PRIVATE/'api-state.json')
    if state['status']!='completed' or state['source_pdf_sha256']!=baseline['pdf_sha256']:raise ValueError('Incomplete or different PDF experiment')
    for name,checksum in state['artifacts'].items():
        if digest(PRIVATE/'mineru'/name)!=checksum:raise ValueError('MinerU artifact changed')
    content=next((PRIVATE/'mineru').glob('*_content_list.json'))
    blocks=read(content);layout=read(PRIVATE/'mineru/layout.json')
    if not all(0<=b['page_idx']<14 and len(b['bbox'])==4 for b in blocks):raise ValueError('Page/bbox audit failed')
    identical=[c['text'] for c in baseline['fresh_fixed_chunks']]==[c['text'] for c in baseline['archived_fixed_chunks']]
    if not identical:raise ValueError('Fresh old pipeline is not identical to archived chunk texts')
    tables=[]
    for block in [b for b in blocks if b['type']=='table']:
        page=block['page_idx']+1
        old=next(c for c in baseline['current_structural_chunks'] if c['kind']=='table' and c['page_start']==page)
        snapshot=next(p['text'] for p in baseline['archived_page_snapshots'] if p['page_start']==page)
        start=snapshot.index(old['text']);end=start+len(old['text']);intersections=[]
        for c in baseline['archived_fixed_chunks']:
            if c['page_start']!=page:continue
            a=snapshot.index(c['text']);z=a+len(c['text'])
            if a<end and start<z:
                intersections.append(dict(chunk_id=c['id'],chunk_index=c['chunk_index'],contains_full_table=a<=start and end<=z,text=c['text']))
        tables.append(dict(pdf_page=page,mineru=block,current_table_text=old['text'],old_intersections=intersections,
                           numeric_verification=compare_table(block['table_body'],old['text'])))
    headings=[dict(block_index=i,pdf_page=b['page_idx']+1,reported_level=b['text_level'],raw_text=b['text'],visible_text=plain(b['text']),bbox=b['bbox'])
        for i,b in enumerate(blocks) if b.get('text_level')]
    repeat_checks=[]
    for page,phrase in [(4,'3. Results and Discussions'),(4,'3.1. The Morphological Analysis'),(5,'The value of the CI-XI')]:
        source=baseline['fresh_pages'][page-1]['text']
        target=plain('\n'.join(b.get('text','') for b in blocks if b['page_idx']==page-1 and b['type']=='text'))
        repeat_checks.append(dict(pdf_page=page,phrase=phrase,pymupdf_occurrences=source.count(phrase),mineru_occurrences=target.count(phrase)))
    duration=(datetime.fromisoformat(state['completed_at'])-datetime.fromisoformat(state['started_at'])).total_seconds()
    image_files=[p for p in (PRIVATE/'mineru/images').iterdir() if p.is_file()]
    summary=dict(experiment='mineru-vs-pymupdf-20261029',source_pdf_sha256=baseline['pdf_sha256'],pdf_pages=14,
        original_fixed_chunks=len(baseline['archived_fixed_chunks']),fresh_fixed_chunks=len(baseline['fresh_fixed_chunks']),
        fresh_matches_archived_texts=identical,current_structural_chunks=len(baseline['current_structural_chunks']),
        mineru_native_blocks=len(blocks),mineru_type_counts=dict(Counter(b['type'] for b in blocks)),
        mineru_heading_candidates=len(headings),reported_heading_levels=dict(Counter(h['reported_level'] for h in headings)),
        mineru_image_asset_files=len(image_files),blocks_with_page_and_bbox=len(blocks),
        numeric_table_cells=sum(t['numeric_verification']['numeric_cells'] for t in tables),
        matching_numeric_table_cells=sum(t['numeric_verification']['matching_cells'] for t in tables),
        repeat_checks=repeat_checks,pymupdf_version=baseline['pymupdf_version'],requested_mineru_model=state['request']['model_version'],
        reported_mineru_backend=layout.get('_backend'),reported_mineru_version=layout.get('_version_name'),reported_ocr_enabled=layout.get('_ocr_enable'),
        local_text_extraction_and_chunk_seconds=baseline['extraction_and_fixed_chunk_seconds'],cloud_submission_through_download_seconds=duration,
        api_billed_cost=None,embedding_calls=0,answer_generation_calls=0,active_library_changed=False,
        parser_or_api_schema='Observed cloud result; do not assume current local 4.x schemas.',
        numeric_scope='Both tables: 20 data rows x 6 numeric columns including revolutions. Compared to frozen table text; not whole-paper semantic accuracy.',
        headings=headings,
        cautions=['161 native blocks are not final RAG retrieval chunks; counts include headers, footers and references.',
                  'All chapter and subsection candidates share level 2; a reliable section tree needs normalization and verification.',
                  'The image label 4.1 nm was returned as a title; several titles contain duplicated or unrelated text.',
                  'Some body text repeats; the abstract renders a chemical prime as superscript 0.',
                  'Table 1 first plane overbar is not preserved as such in the parsed HTML; numeric agreement does not validate headers.',
                  'Image assets include table/equation crops, logos and subfigures; 28 files do not mean 28 scientific figures.',
                  'Charts have empty content fields in this response; no validated curve data or image understanding is demonstrated.',
                  'The service-returned origin.pdf differs in bytes; retain the uploaded original as the source of truth.'])
    PUBLIC.mkdir(parents=True,exist_ok=refresh)
    shutil.copytree(PRIVATE/'mineru/images',PUBLIC/'images',dirs_exist_ok=refresh)
    for page in [6,8]:shutil.copyfile(PRIVATE/f'pdf-page-{page}.png',PUBLIC/f'pdf-page-{page}.png')
    # Render original PDF regions directly; never redraw or regenerate source values.
    import pdfplumber
    original=ROOT/'.rag-data/index-versions/structure-v1-20261029/papers'/ (baseline['pdf_sha256']+'.pdf')
    if digest(original)!=baseline['pdf_sha256']:raise ValueError('Original PDF changed')
    with pdfplumber.open(original) as document:
        for index,table in enumerate(tables,1):
            page=document.pages[table['pdf_page']-1];x0,y0,x1,y1=table['mineru']['bbox']
            region=(x0*page.width/1000,y0*page.height/1000,x1*page.width/1000,y1*page.height/1000)
            page.crop(region).to_image(resolution=144).save(PUBLIC/f'pdf-table-{index}.png')
    shutil.copyfile(PRIVATE/'mineru/full.md',PUBLIC/'mineru-full.md')
    shutil.copyfile(content,PUBLIC/'mineru-content-list.json')
    shutil.copyfile(next((PRIVATE/'mineru').glob('*_content_list_v2.json')),PUBLIC/'mineru-content-list-v2.json')
    shutil.copyfile(PRIVATE/'pymupdf-full.txt',PUBLIC/'pymupdf-full.txt')
    for label,rows in [('old-fixed-chunks',baseline['archived_fixed_chunks']),('current-structural-chunks',baseline['current_structural_chunks'])]:
        (PUBLIC/(label+'.jsonl')).write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in rows),encoding='utf-8',newline='\n')
    save(PUBLIC/'summary.json',summary)
    save(PUBLIC/'table-checks.json',[dict(pdf_page=t['pdf_page'],**t['numeric_verification']) for t in tables])
    render(summary,baseline,blocks,tables)
    save(PUBLIC/'publication.json',dict(files={p.relative_to(PUBLIC).as_posix():digest(p) for p in PUBLIC.rglob('*') if p.is_file() and p.name!='publication.json'},
        document_sha256=digest(DOC),source_api_state_sha256=digest(PRIVATE/'api-state.json'),
        source_baseline_sha256=digest(PRIVATE/'pymupdf-baseline.json'),source_archive_sha256=state['archive_sha256'],
        exporter_sha256=digest(Path(__file__)),original_pdf_sha256=baseline['pdf_sha256'],credentials_or_signed_urls_published=False))
    print(json.dumps({k:summary[k] for k in ['original_fixed_chunks','current_structural_chunks','mineru_native_blocks','mineru_type_counts','matching_numeric_table_cells','numeric_table_cells','reported_mineru_version','cloud_submission_through_download_seconds']},ensure_ascii=False))


def render(s,baseline,blocks,tables):
    md=['# 当前PFI论文：MinerU与PyMuPDF实际解析对照','',
        '2026-10-29。使用同一份14页PDF，先重跑原PyMuPDF解析器及1200/200固定切块，再调用官方精准解析API。请求model_version=vlm，实际结果报告backend=hybrid、version=3.4.4，不能把官网本地4.x版本当作本次云端版本。','',
        '**结果：MinerU提供了更完整的结构化表格、图片资源和页面坐标；本次结果同时出现正文重复、标题误识别和标题层级不准确，尚不宜直接替换当前问答库。**','',
        '| 项目 | 原PyMuPDF流程 | 当前规则切块 | 本次MinerU输出 |','| --- | --- | --- | --- |',
        '| 处理单位 | 按页提取文字，1200字符、重叠200字符 | 句末/标题规则与单页表格分组 | 模型识别的结构块 |',
        f"| 数量 | {s['original_fixed_chunks']}个检索块 | {s['current_structural_chunks']}个检索块 | {s['mineru_native_blocks']}个原始结构块，尚未转成RAG检索块 |",
        '| 表格 | 纯文本，表头/数字的行列关系弱 | 2个完整单页表格文本块 | 2个HTML表格，保留跨行/跨列表头 |',
        '| 标题 | 文字中包含标题，原流程不保存章节树 | 部分标题用于切分，没有章节树 | 16个标题候选；含误判、重复，章节和小节都被标成level 2 |',
        '| 图片 | 原问答流程没有提取/索引图片 | 仍为文本问答 | 17个chart块、4个image块、28个图像文件；含子图、表格、公式裁剪及标志 |',
        '| 定位 | 页码、块编号 | 页码、块编号和组成块 | 161个结构块均有page_idx和bbox |','',
        '以上对比的是项目实际启用的PyMuPDF用法；PyMuPDF库本身也有提取坐标、图片和表格等其他接口。','',
        '## 数值与切块核对','',
        '- 原流程本次重跑得到44块，44块文字与原库逐块完全一致。',
        '- 表1在旧固定切块中已经完整落在一个块内；表2跨两个旧块，两块都不单独包含完整表格。当前规则版本将两张表各保存为一个表格块。',
        f"- MinerU两张表的20行、每行6个数值（含转数列），共{s['numeric_table_cells']}个单元格，与已核对原表的冻结文本有{s['matching_numeric_table_cells']}个数值一致。",
        '- 这不等于整表或整篇100%准确：表1晶面指数的上划线仍未得到正确保留，表头、脚注、公式和语义不在上述数值一致率内。','',
        '## 实际发现的问题','',
        '- 第4页：3. Results and Discussions和3.1标题在MinerU文字中各重复两次，原PyMuPDF提取各一次。',
        '- 第5页：The value of the CI-XI在正文中被输出三次，原PyMuPDF提取一次；部分文字混入sup/sub标记。',
        '- 第7页：图片中的4.1 nm被识别成标题。3.2标题混入前一个图注，Conclusions标题也混入前文。',
        '- 摘要中的O(3′)附近出现O(3<sup>0</sup>)形式，科学符号仍需核对。',
        '- 所有非文档标题候选均为level 2，未可靠区分章与节。',
        '- chart块的content为空；当前证明的是提取图像区域，不是可靠提取曲线数值或理解显微图。','',
        '## API入口与实施建议','',
        '- [官方Token管理](https://mineru.net/apiManage/token)：登录后创建Token。本次已验证用户提供的Token可调用官方精准接口。',
        '- [官方API文档](https://mineru.net/apiManage/docs)：精准API需要Token并提供Markdown/JSON；免Token轻量API主要输出Markdown，不能默认等同于本次精准模式。账号额度和免费条件以控制台为准。',
        '- Token只保存在被Git忽略的backend/.env.mineru。临时上传地址、下载地址、任务响应留在本地私有目录。','',
        f"本地PyMuPDF提取加固定切块约{s['local_text_extraction_and_chunk_seconds']:.2f}秒；MinerU从申请上传到结果下载约{s['cloud_submission_through_download_seconds']:.2f}秒，包含网络与排队，两者计时范围不同。API未返回费用，不能记录为已证实的零费用。",'',
        '本次没有Embedding、答题或评委调用，没有切换原问答索引。后续应先处理正文重复与标题误判，再建立章节树、结构化分块和页面区域引用；再独立验证问答效果。','',
        '[打开并排对照HTML](../data/literature/parsing-comparisons/mineru-vs-pymupdf-20261029/comparison.html)。','',
        '## 复现与私有配置','',
        '配置样例：[.env.mineru.example](../backend/.env.mineru.example)。复制为backend/.env.mineru后填写Token，实际配置已被Git忽略。','',
        '- [本次API提交与恢复脚本](../scripts/parse_mineru_pfi_20261029.py)：submit提交一次，poll查询并下载；已有任务会阻止重复提交，已完成任务的poll直接使用本地结果。',
        '- [原PyMuPDF基线脚本](../scripts/baseline_pymupdf_pfi_20261029.py)：本实验用相邻旧项目srp的Python环境及其解析器/切块代码运行，保留版本和源文件指纹。',
        '- [离线对照报告脚本](../scripts/report_mineru_comparison_20261029.py)：保留私有原始结果后可离线重建；--refresh会先核验既有报告指纹，拒绝覆盖手工修改。','',
        '```powershell', '.\\.venv\\Scripts\\python.exe scripts\\parse_mineru_pfi_20261029.py poll',
        '.\\.venv\\Scripts\\python.exe scripts\\report_mineru_comparison_20261029.py --refresh', '```']
    DOC.write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
    pieces=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MinerU与PyMuPDF实际对照</title>',
        '<style>body{margin:0;background:#f3f6fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1480px;margin:32px auto;padding:0 24px}h1{font-size:28px}h2{font-size:21px}article,details,.card{background:white;border:1px solid #dce5ef;border-radius:10px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fb;padding:12px;font:13px/1.65 ui-monospace,monospace;max-height:500px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}td,th{border:1px solid #dce5ef;padding:6px;text-align:left;overflow-wrap:anywhere}.scroll{overflow:auto}img{max-width:100%;height:auto}summary{cursor:pointer;font-weight:650}small{color:#63768b}.warn{background:#fff5de;border-color:#ead79f}a{color:#2166ac}.badge{display:inline-block;background:#e8f1ff;padding:4px 10px;border-radius:6px;margin:4px}@media(max-width:1050px){.grid{display:block}}</style><main>',
        '<h1>同一篇论文：MinerU与PyMuPDF解析对照</h1>',
        '<p>14页PFI论文 · 原PDF SHA256 '+escape(s['source_pdf_sha256'][:16])+'… · 官方精准API实测</p>',
        '<div class="card warn"><strong>表格结构与来源坐标有明显新增价值，正文与标题也存在实际错误。</strong><p>本次尚未切换RAG索引。161个MinerU结构块与44/81个检索块不是同一概念，不能据数量判断质量。</p></div>',
        '<p><span class="badge">原固定切块：44</span><span class="badge">当前规则切块：81</span><span class="badge">MinerU原始结构块：161</span><span class="badge">表格数据行数值：120/120一致</span></p>',
        '<p>请求vlm；实际云端结果报告hybrid / 3.4.4。数值检查含转数列，不覆盖表头、公式和整篇语义。</p>',
        '<p><a href="mineru-full.md">MinerU原始Markdown</a> · <a href="mineru-content-list.json">原始结构JSON</a> · <a href="mineru-content-list-v2.json">按页JSON V2</a> · <a href="pymupdf-full.txt">PyMuPDF原始文字</a> · <a href="old-fixed-chunks.jsonl">原44块</a> · <a href="current-structural-chunks.jsonl">当前81块</a></p>',
        '<h2>解析与切块分别做什么</h2><div class="grid"><article><h3>原项目实际实现</h3><pre>PyMuPDF: page.get_text("text", sort=True)\n→ 按页获得文字\n→ PageChunker(1200, 200)\n→ 44个检索块\n\n当前优化：重建页面文本\n→ 标点/标题规则 + 单页表格分组\n→ 81个检索块</pre></article>',
        '<article><h3>本次MinerU实际结果</h3><pre>官方精准解析API\n→ 文本/标题、表格、图表、图片、公式等结构块\n→ Markdown + JSON + 图片\n→ 161个原始结构块\n\n尚需我们实现：\n标题清理与层级校验 → 章节树\n按段落、表格等组织检索块 → 长度控制\n保存页码/坐标 → 精准引用</pre></article></div>',
        '<h2>两张表：原文、切块与MinerU行列结构</h2>']
    for index,t in enumerate(tables,1):
        b=t['mineru'];checks=t['numeric_verification'];old=t['old_intersections']
        pieces += [f'<article><h3>表{index} · PDF第{t["pdf_page"]}页</h3>',
            f'<p>旧固定切块涉及{len(old)}块；其中完整容纳表格的块数：{sum(c["contains_full_table"] for c in old)}。当前规则版本为1个表格块。MinerU数据行数值核对：{checks["matching_cells"]}/{checks["numeric_cells"]}。</p>',
            '<div class="grid"><section><h4>上传PDF的表格区域</h4><p>按返回坐标直接裁剪原PDF，未改写数值。</p><img loading="lazy" src="pdf-table-'+str(index)+'.png" alt="原PDF表格区域">',
            '<details><summary>查看原PDF整页</summary><img loading="lazy" src="pdf-page-'+str(t['pdf_page'])+'.png" alt="原PDF表格所在页面"></details></section><section><h4>MinerU实际HTML表格</h4>',
            '<p>'+escape(' '.join(b.get('table_caption',[])))+'</p><div class="scroll">'+safe_table(b['table_body'])+'</div>',
            '<p>JSON来源定位：page_idx='+str(b['page_idx'])+'（对应第'+str(t['pdf_page'])+'页），bbox='+escape(str(b['bbox']))+'。</p>',
            '<details><summary>当前规则版本保留的表格纯文本</summary><pre>'+escape(t['current_table_text'])+'</pre></details>',
            '<details><summary>原固定长度块：查看表格是否在边界被切断</summary>'+''.join('<p>chunk_index='+str(c['chunk_index'])+'</p><pre>'+escape(c['text'])+'</pre>' for c in old)+'</details></section></div></article>']
    pieces += ['<h2>标题：识别出来不等于层级已经正确</h2>',
        '<p>16个标题候选，文档题名为level 1，其余15个全是level 2。章与小节仍需根据编号和版面校验；“4.1 nm”是图片标注，不是章节标题。</p>',
        '<div class="scroll"><table><tr><th>PDF页</th><th>返回层级</th><th>实际返回的标题文字（保留错误）</th></tr>']
    for h in s['headings']:pieces.append('<tr><td>'+str(h['pdf_page'])+'</td><td>'+str(h['reported_level'])+'</td><td>'+escape(h['visible_text'])+'</td></tr>')
    pieces += ['</table></div><h2>正文：原样对比第5页</h2>',
        '<p>“The value of the CI-XI”在原PyMuPDF结果出现1次，在本次MinerU对应页的正文出现3次。右侧保留原输出中的HTML标记和重复，不做人工修正。</p><div class="grid"><article><h3>PyMuPDF</h3><pre>'+escape(baseline['fresh_pages'][4]['text'])+'</pre></article>',
        '<article><h3>MinerU</h3><pre>'+escape('\n\n'.join(b.get('text','') for b in blocks if b['page_idx']==4 and b['type']=='text'))+'</pre></article></div>',
        '<h2>图片与图表：已提取资源，尚未证明能读出科学结论</h2>',
        '<p>17个chart块、4个image块；28个图像文件还包含表格、公式裁剪和标志。下面两张是同一幅图的子图，第一张caption为空，第二张携带整幅图注；不能据文件数当作独立科学图片数。</p><div class="grid">']
    for b in [b for b in blocks if b['type']=='chart'][:2]:
        pieces.append('<article><img loading="lazy" src="'+escape(b['img_path'],quote=True)+'" alt="MinerU提取的图表区域"><p>第'+str(b['page_idx']+1)+'页；content='+escape(repr(b.get('content')))+'；caption='+escape(str(b.get('chart_caption')))+ '</p></article>')
    pieces += ['</div><h2>输出统计与已知限制</h2><pre>'+escape(json.dumps({k:v for k,v in s.items() if k!='headings'},ensure_ascii=False,indent=2))+'</pre>',
        '<h2>免费API在哪里获取</h2><p>登录<a href="https://mineru.net/apiManage/token">官方Token管理</a>创建Token，使用<a href="https://mineru.net/apiManage/docs">官方API文档</a>中的精准解析入口。本次已成功调用。免费条件、配额和限流以账号控制台为准；轻量免Token接口不等同于本次精准结构解析。</p>',
        '<p>Token和带签名的上传/下载链接不在报告中。源PDF、原始结果包与运行状态保留在本机私有实验目录；报告未触发Embedding、答题或评委调用。</p></main></html>']
    (PUBLIC/'comparison.html').write_text('\n'.join(pieces),encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true')
    main(refresh=parser.parse_args().refresh)
