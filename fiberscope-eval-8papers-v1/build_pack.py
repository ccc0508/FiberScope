"""Build the human-readable and model-facing views from the frozen authored cases."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    cases = [json.loads(x) for x in (ROOT / 'gold.jsonl').read_text(encoding='utf-8').splitlines()]
    sources = json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))
    (ROOT / 'questions.jsonl').write_text(''.join(json.dumps({'id': x['id'], 'question': x['question']}, ensure_ascii=False) + '\n' for x in cases), encoding='utf-8')
    tasks = ROOT / 'tasks'
    tasks.mkdir(exist_ok=True)
    prompt = (ROOT / 'answer-instructions.md').read_text(encoding='utf-8')
    groups = {'single': '单篇论文', 'cross': '跨论文', 'no_paper': '不涉及论文'}
    md = ['# 八篇论文评测集：30题与参考答案', '', '版本：FS8-v1 · 2026-11-05。此文件含答案，不能交给被测模型。页码均为 PDF 物理页（从1开始），包含封面。', '',
          '16道单篇（每篇2道）＋8道跨篇＋6道非论文题。已做原文核对，尚未试跑或由独立专家审核；不是盲测集。', '', '## 论文目录', '']
    for d in sources:
        md.append(f"- **{d['id']}**：{d['title']}（{d['year']}），{d['filename']}")
    for x in cases:
        (tasks / (x['id'] + '.md')).write_text(prompt + '\n\n## 本题\n\n' + x['question'] + '\n', encoding='utf-8')
        md += ['', f"## {x['id']} · {groups[x['group']]} · {x['checks']}", '', '**题目**：' + x['question'], '', '**参考答案**：' + x['reference_answer'], '', '**必答要点（每项等权）**：', '']
        md += [f"{i}. {p}" for i, p in enumerate(x['key_points'], 1)]
        md += ['', '**重点错误**：' + '；'.join(x['critical_errors']), '', '**证据定位**：' + ('；'.join(f"{r['document']}，PDF第{','.join(map(str,r['pages']))}页，{r['locator']}" for r in x['evidence']) or '本题输入／算术与单位定义，不需要论文'), '', '**工具预期**：' + x['tool_expectation'], '', '**判分备注**：' + x['grading_notes']]
    (ROOT / 'QUESTIONS.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    esc = html.escape
    cards = []
    for x in cases:
        refs = '；'.join(f"{r['document']} PDF第{','.join(map(str,r['pages']))}页 · {r['locator']}" for r in x['evidence']) or '题目输入／计算，无论文引用要求'
        points = ''.join('<li>'+esc(p)+'</li>' for p in x['key_points'])
        cards.append(f'''<article data-group="{x['group']}"><header><b>{x['id']}</b><span>{groups[x['group']]}</span></header><h2>{esc(x['question'])}</h2><p class="tag">检查：{esc(x['checks'])}</p><details><summary>参考答案、评分要点与证据</summary><p>{esc(x['reference_answer'])}</p><h3>必答要点</h3><ol>{points}</ol><p><strong>重点错误：</strong>{esc('；'.join(x['critical_errors']))}</p><p><strong>证据：</strong>{esc(refs)}</p><p><strong>工具预期：</strong>{esc(x['tool_expectation'])}</p><p><strong>判分：</strong>{esc(x['grading_notes'])}</p></details></article>''')
    source_list = ''.join(f"<li><b>{s['id']}</b> {esc(s['title'])} · {s['year']}</li>" for s in sources)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FiberScope · 八篇论文30题评测集</title><style>
body{margin:0;background:#f4f7fb;color:#20334b;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1000px;margin:auto;padding:36px 22px}h1{font-size:30px;line-height:1.4}h2{font-size:19px;line-height:1.7}h3{font-size:16px}article{background:white;border:1px solid #d9e3ef;border-radius:12px;padding:24px;margin:18px 0}header{display:flex;gap:20px;color:#246394}header span,.tag{color:#6a7c91;font-size:14px}details{border-top:1px solid #e4eaf1;padding-top:12px}summary{cursor:pointer;color:#246394}nav{position:sticky;top:0;background:#f4f7fb;padding:12px 0;display:flex;gap:8px;flex-wrap:wrap}button,input{font:inherit;padding:7px 12px;border:1px solid #c6d6e6;border-radius:7px;background:white}button{cursor:pointer}button.active{background:#205d8c;color:white}.note{background:#e7f0f9;padding:16px;border-radius:8px}li{margin:6px 0}[hidden]{display:none!important}@media print{nav{display:none}article{break-inside:avoid}body{background:white}}
</style><main><p>FIBERSCOPE / EVALUATION / FS8-v1</p><h1>八篇论文 · 30道评测题</h1><p class="note">16道单篇 + 8道跨篇 + 6道非论文。包含参考答案，禁止作为答题模型输入。已核对原文，尚未运行评测或经独立专家审核。PDF页码包含封面，从1开始。新题集与旧32题不能直接用总分比较。</p><details><summary>八篇论文目录</summary><ul>''' + source_list + '''</ul></details><nav><button class="active" data-filter="all">全部30题</button><button data-filter="single">单篇16题</button><button data-filter="cross">跨篇8题</button><button data-filter="no_paper">非论文6题</button><input id="search" placeholder="搜索题目或编号" aria-label="搜索题目或编号"></nav><div id="cards">''' + ''.join(cards) + '''</div><p>判分见 rubric.json 与 README.md；此页为出题资料，不包含任何模型作答分数。</p></main><script>let group='all';const buttons=[...document.querySelectorAll('[data-filter]')];function filter(){const q=document.querySelector('#search').value.toLowerCase();document.querySelectorAll('article').forEach(a=>a.hidden=(group!=='all'&&a.dataset.group!==group)||!a.innerText.toLowerCase().includes(q));}buttons.forEach(b=>b.onclick=()=>{group=b.dataset.filter;buttons.forEach(v=>v.classList.toggle('active',v===b));filter();});document.querySelector('#search').oninput=filter;</script></html>'''
    (ROOT / 'QUESTIONS.html').write_text(page, encoding='utf-8')
    print(f'Generated {len(cases)} tasks, JSONL, Markdown and HTML.')


if __name__ == '__main__':
    main()
