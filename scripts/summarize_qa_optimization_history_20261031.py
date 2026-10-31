"""Summarize archived RAG experiments offline; never generate answers or assign grades."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import math
import statistics

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('data/literature/qa-evaluation/reports')
DEST=BASE/'optimization-history-20261031'
DOC=Path('docs/QA_OPTIMIZATION_HISTORY_20261031.md')
KEYS=('point','fact','citation','coverage','boundary','joint')
LABELS=('必答要点','事实完全支持','单条引用有效','引用组完整','边界/2','联合达标率')

# Observations are separated from component-level causal claims.
STEPS=[
 ('01','结构切块＋上下文补全','context-v1-full-20261029','old_rag','context_rag','paired_old_vs_new.jev',
  'PyMuPDF页内固定44块 → 句段/表格结构81块，并补全同页邻块、合并重叠和设置证据预算。',
  ['证据/回答观察：第10题补齐晶粒尺寸端点，第21题取得33.06%和29.28%，得以计算3.78个百分点及11.43%的相对降幅。',
   '第15题两版均有作用力数值，Jev的边界推断要点反而下降；第32题两版已有摘要/正文冲突，Luna增分有波动疑点。',
   '两项功能同时改变，不能单独计算重切块或补邻块各贡献多少。主表用Jev自身31题配对；早先含DSH共同28题表是另一分母。']),
 ('02','MinerU原生文本接入','mineru-native-v1-20261029','pymupdf','mineru','primary_comparison.jev',
  'PyMuPDF结构81块 → MinerU原生117块；保留其原生文本/标题/表格/图注，接入同一检索与生成流程。',
  ['回答观察：第11题虽有表格数值却未给数值反例；第24题漏掉独立贡献排序限制，第25题只提补充表而未完整说明数值不可得。',
   '第13题更保留“可能”的机制措辞（Luna观察到要点提高），Jev主要增分在第15题。',
   '解析内容和检索块同时变化。不能将所有分数差异归为MinerU解析错误；尤其已有表格却未用属于生成完整性问题。']),
 ('03','MinerU章节组织','mineru-sections-v2-20261030','native','sections','comparisons.native.jev',
  '原生117块 → 章节107块；校验标题、赋予章节路径、合并短正文，标题不独占检索名额。',
  ['第4、24、25题补充作用力差异、贡献排名限制和补充表不可得说明，两位裁判均观察到提高。',
   '证据诊断：第11题Table 1在重放候选第21位，前8和最终上下文均无；第32题摘要段第10位，冲突值缺失。',
   '第28题只总结PFI论文，没交代第二篇缺失，两评均判要点0；旧MinerU的Jev第28题缺失，所以不进入本行30题差值。',
   'Luna第10题以缺nm扣分，但答案已写nm，属于明确的裁判疑点。章节107块不是“一章一块”。']),
 ('04','解析质检、局部复核与修正','mineru-quality-jev-20261030','sections','quality','comparisons.sections',
  '章节107块 → 修正95块；规则标异常，DeepSeek仅查看异常局部图，保存修正账本后重新组块。',
  ['19个标记区域中18处通过修正、1处确认保留；修复标题身份、重复、上下标和表头上划线。两张表120个数据单元格保持不变。',
   '第32题上下文同时有摘要0.888和正文0.912，答案识别冲突；第28题恢复缺失材料说明。',
   '第11题仍没有Table 1关键数值，Jev两个要点均0；第4题未充分说明作用力条件，第15题未指出差异不能全归于浆种。',
   '解析修正通过率是局部工程检查，不是答案正确率；95块相对107块要点提高，但联合达标下降。']),
 ('05','表格行检索＋关联补全','table-evidence-jev-20261030','quality','tables','comparisons.quality',
  '保持95块正文/完整表格不变，增加20条带表头的行检索表示和9条正文—表格链接。',
  ['实际关联补全增加表格证据；第11题仍只补到Table 2，缺少所需Table 1数值，数值反例要点仍0。',
   '第13题已有相关原文，却把可能机制写成确定归因，保留不确定性要点1→0，并有陈述被判部分支持。',
   '第20题要点满分但单条引用失分；第32题保留0.888/0.912冲突并联合达标。',
   '行检索和关联补全同时加入，尚不能拆分两者效果。']),
 ('06','公式、元数据及跨页组织','content-units-jev-20261030','tables','content','comparisons.tables',
  '表格检索95块 → 内容85块；元数据分离、5个公式解释单元、明确跨页句衔接，保留20条行向量和9条关联。',
  ['来源保全：117个修正原生单位42,315字符逐字覆盖，76个向量复用、9块新增；组织更规整不等于答案更好。',
   '第23题明确指出摘要与正文冲突；第11题仍缺关键表，且回答又漏直接否定单调下降，要点继续下降。',
   '第27、29题要点满分但引用组部分支持；第28题边界2→1；第13题仍丢失“可能”，不能靠重组解决生成限定词。']),
 ('07','候选重排（首次）','candidate-rerank-jev-20261030','content','rerank','comparisons.content',
  '85块纯向量排序 → 对最多50个候选用BGE-reranker-v2-m3重排，再取前8并按原规则补全。',
  ['同次候选诊断：第11题Table 1由向量第15位升至重排第3位，进入最终证据；但首轮答案未明确数值反例，Jev满分可能偏高。',
   '第18题区分相对峰面积与绝对含量，第13题保留机制不确定性。第32题正文进入但摘要0.888未进入，漏报冲突。',
   '这是首次单轮结果，后续两轮未稳定复现要点收益，不能只用本行高分说明重排有效。']),
 ('08','完整性指引v1','answer-guidance-20261031','control','guidance','comparison',
  '同一批MinerU85块无重排历史最终证据，两版各重新答32题；附加326词通用指引。',
  ['只改变生成指引，Embedding/检索/重排均绕过；本行“control”是相同MinerU证据下的原提示，不是旧PyMuPDF。',
   '第15题唯一要点增分0→0.5混有裁判波动：两版都已有3.33/1.77 N/mm，均未明确不能全归于浆种。',
   '第13、23、29、30、32题因单条引用失分丢失联合达标；23/32复合句分工引用有裁判偏严疑点，30确有冗余引用。',
   '第26题范围说明缩窄，事实率提高部分来自fact→scope分类；范围声明仍部分支持。第11题封存证据缺表值，提示词无法补造。']),
 ('09','精简指引v2','answer-guidance-v2-20261031','control','guidance','comparison',
  '指引326→173词，要求聚焦问题、分开不同来源的事实、每条引用有实质贡献；重新生成原提示control作对照。',
  ['这不是v1答案与v2答案的直接配对。证据仍固定，重排仍关闭。',
   '第5题绑定含MORFI方法的正确来源；第13题保留可能措辞。第25题缺少精确数值不可提供的完整说明；第28题完全遗漏缺第二篇材料、无法比较的说明。',
   '第15/22题边界差异存在评委波动疑点。第11题仍无表值；指引更短并未让平均输出更短。']),
 ('10','缺失子问说明v3','answer-guidance-v3-20261031','control','guidance','comparison',
  '指引229词；每个无法回答的子问必须在实际展示的claims里明确说明，区分纯范围定位与科学事实支持。',
  ['仍是固定同证据的新原提示control对照，不是v2→v3直接比较。',
   '第25/28题补齐缺失材料说明，但本轮control也满分，不能据此证明超过原提示或稳定修复。',
   '第22题含量23.56、34.92漏%单位，唯一要点下降；第3题把每类5个水平写成“每个转数水平均为5个”，表述含混。',
   '第4/13/20/31题有附加陈述引用问题；第11题scope被判矛盾但证据确缺反例值，需复核裁判是否混淆全文与摘录。']),
 ('11','全部既有优化叠加','full-stack-20261031','control','guidance','comparison',
  'PyMuPDF结构81块＋上下文基线，与MinerU修正85块＋表格检索＋补全＋重排＋v3指引，真实端到端各答32题。',
  ['真实64条查询Embedding记录、全开32次重排成功；解析/文档向量复用验证成果，不是固定证据回放。',
   '第11题两版上下文都有表值，全开版明确列出70.42%→72.54%回升反例，获得联合达标。第24/26题要点也提高。',
   '第20题已取证、重排成功，两次生成仍未通过引用校验，程序拒答；第32题最终上下文无摘要0.888，漏报冲突。',
   '第29题答案全是纯范围说明，事实/引用分母0但联合条件按原规则成立；第32题基线单条分工引用0分也有裁判疑点。',
   '生成Token+33.03%，耗时中位15.88→18.45秒。多组件同时改变，只能确认组合的本轮表现，不能把收益全归重排/MinerU。']),
]


def require(ok,message):
    if not ok:raise ValueError(message)


def read(path):return json.loads(path.read_text('utf-8'))
def digest(path):return sha256(path.read_bytes()).hexdigest()
def ratio(n,d):return n/d if d else None


def aggregate(rows):
    facts=sum((Counter(m['support_counts']) for m in rows),Counter())
    n=len(rows);nc=sum(m['factual_citations'] for m in rows);nf=sum(m['factual_claims'] for m in rows)
    return dict(tasks=n,point=statistics.mean(m['point_mean'] for m in rows),fact=ratio(facts.get('supported',0),sum(facts.values())),
        citation=ratio(sum(m['supported_citations'] for m in rows),nc),coverage=ratio(sum(m['complete_groups'] for m in rows),nf),
        boundary=statistics.mean(m['boundary'] for m in rows),joint=sum(m['all_five_pass'] for m in rows)/n,
        joint_count=sum(m['all_five_pass'] for m in rows),support_counts=dict(facts),
        citation_counts=[sum(m['supported_citations'] for m in rows),nc],coverage_counts=[sum(m['complete_groups'] for m in rows),nf])


def per_question(m):
    return dict(point=m['point_mean'],fact=ratio(m['support_counts'].get('supported',0),sum(m['support_counts'].values())),
        citation=ratio(m['supported_citations'],m['factual_citations']),coverage=ratio(m['complete_groups'],m['factual_claims']),
        boundary=m['boundary'],joint=int(m['all_five_pass']))


def declared_score(s):
    counts=s['support_counts']
    return dict(point=s['point_macro_average'],fact=ratio(counts.get('supported',0),sum(counts.values())),
        citation=s['citation_precision']['value'],coverage=s['citation_coverage']['value'],boundary=s['boundary_mean'],
        joint=s['all_five_pass']/s['tasks'])


def load_pair(root,folder,control,candidate,selector,judge='jev',repeat_round=None):
    base=root/BASE/folder;summary=read(base/'comparison.json');rows=[json.loads(x) for x in (base/'questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]
    value=summary
    for k in selector.split('.'):value=value[k]
    pair=value if repeat_round is None else value[repeat_round-1]
    selected=pair['task_ids'];mapped={}
    for row in rows:
        if row['task_id'] not in selected:continue
        if 'systems' in row:
            m={s:(row['systems'][s]['judges'][judge] if 'judges' in row['systems'][s] else row['systems'][s])['metrics'] for s in [control,candidate]}
        else:
            key='system' if repeat_round else 'arm'
            cells={r[key]:r for r in row['records'] if repeat_round is None or r['round']==repeat_round}
            m={s:cells[s]['metrics'] for s in [control,candidate]}
        require(all(m[s] is not None and not m[s]['reference_concern'] for s in m),'Invalid grade in common paired subset')
        mapped[row['task_id']]=m
    require(set(mapped)==set(selected),'Archived comparison task coverage differs')
    scores={s:aggregate([mapped[t][s] for t in selected]) for s in [control,candidate]}
    for s in scores:
        declared=declared_score(pair['scores'][s])
        for k in KEYS:
            a,b=scores[s][k],declared[k]
            require(a==b if a is None or b is None else math.isclose(a,b,abs_tol=1e-12),'Archived aggregate mismatch: '+folder+' '+k)
    changed=[];directions={k:{'up':[],'down':[],'not_comparable':[]} for k in KEYS}
    for t in selected:
        before,after=[per_question(mapped[t][s]) for s in [control,candidate]]
        for k in KEYS:
            if before[k] is None or after[k] is None:
                if before[k]!=after[k]:directions[k]['not_comparable'].append(t)
            elif after[k]!=before[k]:directions[k]['up' if after[k]>before[k] else 'down'].append(t)
        if before!=after:changed.append(dict(task_id=t,before=before,after=after,
            original_metric_counts={s:mapped[t][s] for s in [control,candidate]}))
    require(directions['point']['up']==pair.get('point_wins',directions['point']['up']),'Point improvement list differs')
    require(directions['point']['down']==pair.get('point_losses',directions['point']['down']),'Point regression list differs')
    return dict(folder=folder,judge=judge,control=control,candidate=candidate,repeat_round=repeat_round,tasks=len(selected),task_ids=selected,
        excluded_task_ids=[f'PFI2-{i:03}' for i in range(1,33) if f'PFI2-{i:03}' not in selected],scores=scores,
        deltas={k:scores[candidate][k]-scores[control][k] if scores[candidate][k] is not None and scores[control][k] is not None else None for k in KEYS},
        directions=directions,changed_questions=changed,unchanged_questions=[t for t in selected if t not in {c['task_id'] for c in changed}],
        source_sha256={n:digest(base/n) for n in ['comparison.json','questions-answers-reviews.jsonl']},
        original_exclusions=pair.get('exclusions',[]),html_report=(BASE/folder/'comparison.html').as_posix())


def build(root=ROOT):
    root=Path(root);main=[]
    for sid,title,folder,control,candidate,selector,change,notes in STEPS:
        r=load_pair(root,folder,control,candidate,selector)
        r.update(id=sid,title=title,change=change,diagnosis=notes);main.append(r)
    supplementary=[]
    for r,selector in [(main[0],'paired_old_vs_new.luna'),(main[1],'primary_comparison.luna'),(main[2],'comparisons.native.luna')]:
        p=load_pair(root,r['folder'],r['control'],r['candidate'],selector,judge='luna');p.update(id=r['id']+'-luna',title=r['title']+'（Luna复核）');supplementary.append(p)
    anchored=[]
    for r,new in [(main[2],'sections'),(main[3],'quality'),(main[4],'tables'),(main[5],'content'),(main[6],'rerank')]:
        pair=load_pair(root,r['folder'],'pymupdf',new,'comparisons.pymupdf'+('.jev' if new=='sections' else ''))
        pair.update(id=r['id']+'-anchor',title=r['title']+'（对PyMuPDF81块）');anchored.append(pair)
    stability=[]
    for i in (1,2,3):
        r=load_pair(root,'rerank-stability-20261031','content','rerank','fixed_common.rounds',repeat_round=i)
        r.update(id='repeat-'+str(i),title='重排稳定性第'+str(i)+'轮（固定30题）');stability.append(r)
    stable=read(root/BASE/'rerank-stability-20261031/comparison.json')
    flash=read(root/BASE/'flash1017-high-20261028/comparison.json')
    example=read(root/BASE/'full-stack-20261031/comparison.json')
    questions={r['task_id']:r['reference_case']['question'] for r in [json.loads(x) for x in (root/BASE/'full-stack-20261031/questions-answers-reviews.jsonl').read_text('utf-8').splitlines()]}
    return dict(version='qa-optimization-history-v1',as_of='2026-10-31',main=main,luna_supplement=supplementary,pymupdf_anchor=anchored,
        stability_rounds=stability,stability_summary=dict(by_system=stable['fixed_common']['by_system'],deltas=stable['fixed_common']['deltas'],
            sensitivity=stable['sensitivity_without_pfi2_011'],source_sha256=digest(root/BASE/'rerank-stability-20261031/comparison.json')),
        model_configuration_phase=dict(source='flash1017-high-20261028',source_sha256=digest(root/BASE/'flash1017-high-20261028/comparison.json'),
            historical=flash['historical_same_task_summaries'],current={j:flash[j] for j in ['luna','jev']},
            note='早期独立原协议汇总，不与后续统一五维混合；模型别名可能已路由到同服务，另有超时恢复/预算变化，不能解释为纯模型升级因果收益。'),
        questions=questions,method='Offline aggregation of archived common-pair metrics. Original answers and judgments unchanged. No new semantic grades.',
        provider_calls=0,default_config_changed=False,script_sha256=digest(Path(__file__)))


def pct(v):return '不适用' if v is None else f'{v*100:.2f}%'
def val(v,k):return '不适用' if v is None else f'{v:.3f}' if k=='boundary' else str(int(v)) if k=='joint' else pct(v)
def ids(ts):return '、'.join(str(int(t.split('-')[-1])) for t in ts) or '无'
def delta(v,k):return '不适用' if v is None else f'{v:+.3f}分' if k=='boundary' else f'{v*100:+.2f}个百分点'
def link(pair):return '../'+pair['html_report']


def summary_table(pairs):
    lines=['| 轮次 / 直接对照 | 题数 | 要点变化 | 事实支持变化 | 单引变化 | 引用组变化 | 边界变化 | 联合达标题数 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in pairs:
        a,b=[r['scores'][s] for s in [r['control'],r['candidate']]]
        lines.append('| '+r['id']+' '+r['title']+' | '+str(r['tasks'])+' | '+' | '.join(delta(r['deltas'][k],k) for k in KEYS[:-1])+f" | {a['joint_count']}→{b['joint_count']} |")
    return lines


def render(data):
    lines=['# 文献问答优化全历程：基线、指标、逐题变化及原因','','截至2026-10-31。仅离线整理归档，不重新答题、评分或更改模型原判。','',
        '**结论：首轮结构切块与补全取得最明显的单轮收益；MinerU适配、重排和指引迭代均有收益与回归，尚无稳定全面胜出的组合。全开版引用指标改善，但要点略降、开销增加。**','',
        '阅读规则：每行只比较该轮自己的相同有效题集。不同轮的题数、排除题及基线不同，不能连成累计提升曲线，差值也不能相加。百分比差值为百分点；边界是0—2分差；联合达标是五项同时通过的条件，不是第六维或加权总分。','',
        '本总账主表统一用Jev；早期三轮Luna另列，避免混合评委。第一轮采用Jev自身31题配对，因此与早先包含DSH的共同28题表数字不同。原始答案/裁判标签与细分分母均在各轮原报告。','',
        *summary_table(data['main']),'',
        '## 各轮具体做了什么、哪些题变化','']
    for r in data['main']:
        a,b=[r['scores'][s] for s in [r['control'],r['candidate']]]
        lines += ['### '+r['id']+' '+r['title'],'',r['change'],'',f"直接对照：`{r['control']}` → `{r['candidate']}`；Jev同{r['tasks']}题；排除题：{ids(r['excluded_task_ids'])}。",'',
            '| 指标 | 该轮基线 | 该轮新版本 | 差值 |','| --- | ---: | ---: | ---: |']
        for k,label in zip(KEYS,LABELS):
            before=f"{a['joint_count']}/{r['tasks']} ({pct(a[k])})" if k=='joint' else val(a[k],k)
            after=f"{b['joint_count']}/{r['tasks']} ({pct(b[k])})" if k=='joint' else val(b[k],k)
            lines.append('| '+label+' | '+before+' | '+after+' | '+delta(r['deltas'][k],k)+' |')
        lines += ['', '**各维度具体变化题号**（不适用分母的变化不判升降；完整题目见末尾目录）：','',
            '| 维度 | 提高 | 下降 | 有/无适用分母的变化 |','| --- | --- | --- | --- |']
        for k,label in zip(KEYS,LABELS):
            v=r['directions'][k];lines.append('| '+label+' | '+ids(v['up'])+' | '+ids(v['down'])+' | '+ids(v['not_comparable'])+' |')
        lines+=['','**原因与证据边界**：','',*['- '+s for s in r['diagnosis']],'',
            '以下是发生指标变化的逐题数值。事实/引用比例按各自实际陈述和引用计数，分母改变时不等于准确率变化；原计数保存在机器可读总账。','',
            '| 题号 | 要点 | 事实支持 | 单引 | 引用组 | 边界/2 | 联合达标0/1 |','| --- | --- | --- | --- | --- | --- | --- |']
        for q in r['changed_questions']:
            lines.append('| '+str(int(q['task_id'].split('-')[-1]))+' | '+' | '.join(val(q['before'][k],k)+'→'+val(q['after'][k],k) for k in KEYS)+' |')
        lines+=['',f"全部维度数值未变题：{ids(r['unchanged_questions'])}。",'',f"[该轮全部原回答与评分]({link(r)})。",'']
    lines+=['## 早期Luna独立结果','',*summary_table(data['luna_supplement']),'']
    for r in data['luna_supplement']:
        lines+=[f"{r['title']}：要点提高{ids(r['directions']['point']['up'])}；下降{ids(r['directions']['point']['down'])}；排除{ids(r['excluded_task_ids'])}。",'']
    lines+=['第03轮Luna与Jev方向相反；Luna第10题遗漏单位的理由与已写nm的回答矛盾，原分保留，不借总账修正。','',
        '## 对同一PyMuPDF81块历史基线的补充比较','',
        '以下均为各轮原报告已有的同题配对，不是新的共同全集。即使对照版本相同，排除题不同也不能直接比较行间绝对数。','',*summary_table(data['pymupdf_anchor']),'',
        '## 重排的重复验证','',
        '固定六个版本×轮次都有效的30题，统一排除23、24。第1轮是历史首次实验；第2、3轮为新增独立运行，不是修改重排算法。','',*summary_table(data['stability_rounds']),'']
    for r in data['stability_rounds']:
        lines += [r['title']+'：要点提高'+ids(r['directions']['point']['up'])+'；下降'+ids(r['directions']['point']['down'])+'；新增联合达标'+ids(r['directions']['joint']['up'])+'；失去联合达标'+ids(r['directions']['joint']['down'])+'。','']
    lines += ['三轮要点均值：纯向量93.98%，重排93.43%，差值-0.56个百分点；重排较高1轮、较低2轮。引用组完整均值96.13%→97.38%，联合达标率均值65.56%→67.78%，但轮间波动较大。','',
        '第32题重排三轮都漏摘要冲突、要点均83.33%，纯向量三轮100%；第25题重排第3轮为引用校验失败后的拒答。第11题首轮数值反例被宽评疑点仍在，统一去掉11后要点三轮平均差值为-3.45个百分点。重复证明首轮收益不稳，没有证明某个组件的统计显著效应。','',
        '[重复验证完整报告](../data/literature/qa-evaluation/reports/rerank-stability-20261031/comparison.html)。','',
        '## 其他已做工作：为何不混入上述得分','',
        '- 模型/High配置阶段：同29题，旧协议Luna要点89.08%→89.08%，Jev88.51%→89.37%；旧模型别名可能已经指向同一远端服务，且执行超时和调度有变化，不能称纯模型升级收益。早期评分协议与后续统一五维不同，逐题五维变化不强行拼接。详见[原配置报告](QA_FLASH1017_HIGH_REPORT_20261028.md)。',
        '- 检索诊断：保存/重放候选50、前8及最终证据，定位第11题表格与第32题摘要遗漏；诊断没有重答或评分，因此没有独立答案质量增分。它为后续重排提供了依据。',
        '- 解析质量检查、局部复核和修正账本首先是来源保全与可追溯能力；“19区域检查完成、18处修正、120表格数值不变”不能直接换算成问答质量分。问答收益已单独在第04轮列出。',
        '- 评测集、Jev/Luna接入、评分标准统一、费用/历史/封存/失败保存是评测基础设施；它们改善可测量性，不代表作答模型自动提高。早期37题/注入任务、DSH系统对照不是本表32题主链的算法优化轮。',
        '- MinerU路线和PyMuPDF路线互为替代，不会把两份解析文本简单一起入库。图像一般理解、曲线取数、混合检索、query改写等尚未完成的功能不算“已有优化”。','',
        '## 原因归纳与采用状态','',
        '可以确认的失败阶段：第11题有些轮次关键表未到生成器，有些轮次虽已到却没用；第32题多次重排后丢摘要冲突；第20/25题有引用校验拒答；第13题丢失可能措辞；第22题个别轮次漏单位。它们分别属于取证、使用证据、输出校验和表达完整性问题。','',
        '只能提出机制解释、不能确认单组件因果：重切块会改变向量表示和邻块组合；重排按单块相关性选前8不保证跨章节覆盖；更长提示可能增加额外陈述和引用要求。需固定其他组件的消融及重复/新论文验证后才能量化各自贡献。','',
        '采用状态：较好的PyMuPDF结构版仍是网站默认；MinerU、重排和指引作为实验候选保留。曾有局部或单轮提升，但后续复杂组合没有稳定全面超过基线。未据此次总结修改配置或新增付费调用。','',
        '## 32道题目录','', '| 题号 | 原题 |','| --- | --- |']
    for tid,q in sorted(data['questions'].items()):lines.append('| '+str(int(tid.split('-')[-1]))+' | '+q.replace('|','\\|')+' |')
    lines += ['','## 数据与核验','',
        '[机器可读总账及逐题原计数](../data/literature/qa-evaluation/reports/optimization-history-20261031/summary.json)。各轮compare与JSONL原文件SHA-256写入总账，程序逐项复算同题均值、比率和升降题号并与原汇总核对；没有重新语义评分。',
        '本次0答题调用、0裁判调用；所有原始答案和分数保留。缺失不计零、事实分母不包括纯范围声明、联合通过仍检查范围声明；比例分母与陈述颗粒不同，不应机械作总体正确率解释。','']
    return '\n'.join(lines)


def publish(root=ROOT):
    root=Path(root);data=build(root);dest=root/DEST;dest.mkdir(parents=True,exist_ok=True)
    save=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    save(dest/'summary.json',data);doc=root/DOC;doc.write_text(render(data),encoding='utf-8',newline='\n')
    save(dest/'publication.json',dict(summary_sha256=digest(dest/'summary.json'),document_sha256=digest(doc),script_sha256=digest(Path(__file__)),provider_calls=0))
    return dict(main_comparisons=len(data['main']),luna_comparisons=len(data['luna_supplement']),anchor_comparisons=len(data['pymupdf_anchor']),repeat_rounds=3,questions=len(data['questions']),provider_calls=0)


if __name__=='__main__':print(json.dumps(publish(),ensure_ascii=False))
