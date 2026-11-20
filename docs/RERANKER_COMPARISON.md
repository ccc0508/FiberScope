# 固定候选池重排实验

该脚本用于比较当前 BGE、阿里云百炼 `qwen3-rerank` 和 OpenRouter `typesafe/jev-1.14` 的排序行为，不改变线上重排配置。

## 实验边界

- 使用八篇论文评测集的 24 道论文题（16 单篇、8 跨篇），不运行 6 道无需论文的问题。
- 每题只用原始问题搜索一次整个论文库，沿用 Qwen3-VL Embedding、表格行及图片关联父块的候选检索；阈值沿用本地配置。最多 50 条，去重后保存正文和顺序。
- 三种模型使用完全相同的 query 和候选正文，均取前 8 条。不截断正文，不把标准答案、参考页码或其他模型的分数发给重排模型。
- BGE 和 Qwen 一次请求处理整个候选池；Jev 使用 Score 对每条候选独立打 0—3 分，再除以 3 排序。Jev 的评分准则写在脚本 `LEVELS` 中，不能把它的分数当成正确概率。
- 不运行 Planner、后续补查、章节补全、生成或复核。本实验不能代替 30 题端到端回归，也不代表完整 Agent 的回答分数。
- 三个服务采用各自协议，BGE 保持既有参数；Jev 不作为本轮排序效果的裁判。

## 指标口径

现有 gold 提供的是“论文＋参考页码”，不是每个块的精细相关性标签。因此脚本只计算以下位置代理指标：

1. **参考页覆盖率@8**：前 8 条覆盖的标准参考位置数 / 全部标准参考位置数，每题计算后取平均。
2. **候选中可用参考页保留率@8**：只对前 50 条里已经出现的标准参考位置计算保留比例，区分候选缺失与排序损失。候选中一个参考位置也没有时记为不适用，不计为满分。
3. **参考页 nDCG@8**：与任一标准参考位置重叠的块暂标为 1，其他标为 0。位置越靠前权重越大；按候选池内理想排序归一化。
4. **目标论文覆盖率@8**：前 8 条涉及了多少题目所需论文。这只能描述来源覆盖，不保证该论文的具体证据充分。

同页的无关段落可能被代理指标误判为相关，其他页的有效证据可能漏记。正式比较 Recall@8、Precision@8 或 nDCG@8，需要独立标注候选块与必答项的语义关系。解释性原文样例另存 `manual-probes.json`，不是完整的人工标注集。

耗时有两种：常规调用记录保存每次请求耗时；`timing` 另对 001、011、019 三题重新请求，测量完整候选池的墙钟耗时。Jev 的 50 次请求并发度固定为 16，不能将其逐条请求耗时直接与 BGE/Qwen 的整批请求耗时对比。

费用区分供应商返回金额、公开单价估算和未知。BGE 原生 usage 位于 `meta.tokens`；Qwen 返回 `usage.total_tokens`；Jev 返回 `usage.cost`（美元）。缺失金额不表示免费。百炼北京 `qwen3-rerank` [公开价](https://help.aliyun.com/zh/model-studio/qwen3-rerank)为每百万输入 Token 0.5 元；免费额度、优惠及实际账单另算。

## 本地运行

在项目根目录用 PowerShell 执行；私有配置读取 `backend/.env.literature` 和 `backend/.env.jev`，密钥不输出、不写入报告。

```powershell
$common = @(
  '--source', 'D:/develop/srp2.0',
  '--library', 'D:/develop/srp2.0/.rag-data/index-versions/paper-collection-definitions-20261106',
  '--output', 'D:/develop/srp2.0/output/reranker-comparison-20261119'
)
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py prepare @common
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py run @common --workers 16
# 只补一次连接/读取失败、429 或 5xx，原失败另存 attempts。
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py run @common --workers 4 --retry-transient
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py timing @common --workers 16
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py report @common
```

已有成功结果直接复用。输入 fingerprint 改变时拒绝复用旧结果。401/402/403 会停止提交新任务；已经发出的请求仍会落盘。失败不会静默替换为其他模型或向量排序。

## 输出

- `pools.json`：冻结问题、候选正文、顺序、参考位置、输入哈希；必须保留供回放。
- `prepared/`：逐题检索与 Embedding 用量断点。
- `calls/<model>/`：每次原生响应、请求哈希、状态、耗时和用量；可由冻结输入与脚本重建请求。
- `attempts/`：一次有限补试前的原始失败记录，汇总请求量和耗时时包含它们。
- `timing/`：另行测量三组完整候选池的原始请求及墙钟耗时。
- `summary.json`、`details.json`、`comparison.html`：汇总、每题前八条原文与完整块编号排序。
- `manual-probes.json`、`manual-probe-results.json`：人工对照原文后的解释性定位与排序名次。

包含论文原文的输出位于 Git 忽略的 `output/`，不随代码推送。只有脚本、测试、方法与不含论文正文的汇总可以进入仓库。

接口依据：[百炼重排 API](https://help.aliyun.com/zh/model-studio/text-rerank-api)、[TypeSafe Score](https://docs.typesafe.ai/primitives/score)。

## 逐要点语义核对

页码指标之后，使用 `audit_reranker_evidence.py` 核对前 8 块是否包含每个必答要点所需的事实。本次由 Codex 阅读原文作内容判断，单独保存“要点—子事实—可支持该事实的块”映射；程序只检查块是否已被选出并汇总。没有新增 Jev 或其他 API 裁判调用，也没有再次生成答案。这不是独立盲评，映射与判断说明均可展开复查。

映射以 `semantic-audit-annotations.json` 保存，绑定冻结候选池和 gold 的 SHA256，防止旧编号应用到其他论文内容。每个子事实可由多个等价块之一支持；一个要点可需要多个子事实，也可由多个块共同支持。允许基于原文事实作合理推论，不要求原文逐字复述参考答案。仅包含关键词、位于同页或引用另一项研究，不算目标事实证据。

- 完整：所有必要子事实均有依据，1 分。
- 部分：具有实质证据，但缺少必要数值、对象、条件或某个子事实，0.5 分。
- 缺失：没有实质支持，0 分。
- 不适用：纯回答行为、题目给定数值的换算或没有具体论文事实断言的数据管理建议，不要求从论文中检索，单独列明，不计分母。

完整覆盖率为完整要点数除以适用要点数；加权覆盖率为“完整数＋0.5×部分数”除以适用要点数。另按每题平均给出宏平均口径，避免混淆两种分母。它们均是证据可用性，不是生成答案的要点得分或准确率。

同时用全部冻结候选作检查：如果 50 块中能支持、前 8 块不能，则记录重排漏选；如果 50 块也只有部分或没有证据，记录候选池缺口。这个结论仅针对本次原问题检索得到的候选池，不能代替整个 Agent 多次补查后的召回评估。

本地复跑仅汇总已有材料，不发送请求：

```powershell
& ./.venv/Scripts/python.exe -X utf8 scripts/audit_reranker_evidence.py `
  --output 'D:/develop/srp2.0/output/reranker-comparison-20261119' `
  --gold 'D:/develop/srp2.0/fiberscope-eval-8papers-v1/gold.jsonl'
```

结果为 `semantic-audit.html`、`semantic-audit-details.json`、`semantic-audit-summary.json`，分别提供逐题原文、明细和汇总。涉及图像的要点只按实际传给这三个文本重排器的文字检查；不会把未提供的 PDF 图片视为已召回证据。可由领域人员复查并修订映射，重新汇总时保留新的注释文件哈希。

## Qwen3.7 补测

支持 `--model qwen37`，对应百炼 `qwen3.7-text-rerank`，使用已有百炼密钥和同一个原生端点。主对照保持原始问题、候选正文、候选顺序及默认问答排序指令，仅更换请求中的模型名称。不额外设置 `instruct`，避免把模型更新和提示词调整混在一起。

默认运行仍为原来的 BGE/Qwen/Jev 三模型；不会因增加此选项意外多发付费请求。报告发现 `calls/qwen37` 后才增加新版结果，旧的三模型输出仍可复算。逐要点汇总会识别新增模型，验证它排序的仍是同一组候选编号。

补测使用独立的 `output/reranker-qwen37-20261119`，复制并复用原实验的冻结池及三模型响应，不改原实验目录。这里只新增24次重排请求及3次独立计时请求。新命中的原文逐条复查；可补录它们对既有子事实的等价支持，但不更换要点、评分规则和不适用项，并验证旧三模型的全部汇总分数保持不变。新增支持映射与原注释文件均保留，便于复查。

```powershell
# 独立目录须先备好与原实验完全相同的pools.json、证据注释和复用响应。
$extra = @(
  '--source', 'D:/develop/srp2.0',
  '--library', 'D:/develop/srp2.0/.rag-data/index-versions/paper-collection-definitions-20261106',
  '--output', 'D:/develop/srp2.0/output/reranker-qwen37-20261119'
)
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py run @extra --model qwen37 --workers 3
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py timing @extra --model qwen37 --workers 1
& ./.venv/Scripts/python.exe -X utf8 scripts/compare_rerankers.py report @extra
& ./.venv/Scripts/python.exe -X utf8 scripts/audit_reranker_evidence.py `
  --output 'D:/develop/srp2.0/output/reranker-qwen37-20261119' `
  --gold 'D:/develop/srp2.0/fiberscope-eval-8papers-v1/gold.jsonl'
```

2026-11-19这次补测的逐要点加权覆盖率：旧Qwen为67.03%，Qwen3.7为93.96%，BGE为80.77%，Jev为93.96%。Qwen3.7完整/部分/缺失为84/3/4（91项），19/24题证据齐全；Jev为83/5/3，20/24题证据齐全。因此总加权分相同，不代表每题或每种缺陷相同，也不是最终生成答案准确率。三题独立计时中Qwen3.7的整批耗时为0.698、0.720、2.026秒；需要更多样本才能评价线上延迟。

## 24题端到端对照

`benchmark_reranker_e2e.py` 支持对当前24道论文题分别运行Qwen3.7和Jev配置。`prepare`复制当前本地工作版本（含尚未提交的源码改动）和私有运行配置到Git忽略的实验目录，记录文件哈希；仅在快照中增加原生重排适配器。实际网站配置不切换。两组使用同一快照、库、问题文件、DeepSeek回答模型与预算，所有题目独立新会话，保留首次答案和失败，不选择最佳答案。

实验使用Planner＋文献子Agent架构，每题20次模型调用、12次工具调用、2次搜索、360秒，全局预算共享；上下文160000字符，收尾预留16384字符，普通输出8192 Token，综合输出16384 Token。两组重排仍用同一60秒批次上限，无自动模型降级/向量回退。Jev以16并发逐候选独立评分，规则与固定池对照相同；Qwen3.7仍用默认问答排序指令。

这次没有强制Agent搜索：它可直接查目录、读章节、定位表格或看图。只有实际调用 `search_literature` 的题目才暴露于重排器，报告另列这些题目与重排原生请求数。两次独立执行的计划、查询和回答会存在随机差异；不能把未调用重排器的题目差异归因于重排器。

端到端评分沿用原24题必答要点、事实充分支持、单引有效、引用组完整覆盖、边界与严格通过的口径，排除此前用户已确认不强求的FS8-002 K4。Jev原始决定保留，Codex另行对照原文及图像校准，不在原始评分文件上覆盖。Jev同时用于重排和裁判，存在相关偏好的可能；Codex校准也不是独立人类专家审核。总结可承接已明确对应的上下文引用，实质错误仍扣分，不报告六维加权“总准确率”。

```powershell
$e2e = @(
  '--source', 'D:/develop/srp2.0',
  '--library', 'D:/develop/srp2.0/.rag-data/index-versions/paper-collection-definitions-20261106',
  '--output', 'D:/develop/srp2.0/output/reranker-e2e-20261120'
)
& ./.venv/Scripts/python.exe -X utf8 scripts/benchmark_reranker_e2e.py prepare @e2e
& ./.venv/Scripts/python.exe -X utf8 scripts/benchmark_reranker_e2e.py answers @e2e --workers 2
& ./.venv/Scripts/python.exe -X utf8 scripts/benchmark_reranker_e2e.py judge @e2e
# 完成人工/领域复核映射后，再由程序应用calibration.json并汇总。
& ./.venv/Scripts/python.exe -X utf8 scripts/report_reranker_e2e.py `
  --source 'D:/develop/srp2.0' --output 'D:/develop/srp2.0/output/reranker-e2e-20261120'
```

也可独立启动 `watch-judge` 在已保存回答出现后评分；该进程只读取完整落盘结果，存在未完成的付费裁判请求时拒绝静默重跑。实验快照的 `.rag-data/agent-runs/<run-id>/state.json` 与 `tool-traces.sqlite3` 是本轮原始轨迹；逐题结果内保存对应Langfuse链接。`report_reranker_e2e.py`生成 `comparison.html`、`summary.json` 与完整 `results.json`；尚未校准的已完成回答显式记为待校准，不填假分数。

2026-11-20这轮48份首次答案全部完成，48次Jev评分全部首调有效，随后逐题做Codex原文校准。冻结代码、文献库与网站模型私有配置的完整性检查均通过。结果保存在本地 `output/reranker-e2e-20261120/comparison.html`，完整原文快照、私有配置和生成报告仍按仓库规则不上传Git。

| 校准后指标 | Qwen3.7重排配置 | Jev重排配置 |
| --- | --- | --- |
| 端到端完成 | 24/24 | 24/24 |
| 平均必答要点分 | 97.92 | 96.88 |
| 事实充分支持 | 91.09%（92/101） | 94.17%（97/103） |
| 单引有效 | 98.87%（263/266） | 99.22%（254/256） |
| 引用组完整覆盖 | 90.10%（91/101） | 95.15%（98/103） |
| 严格通过 | 14/24 | 16/24 |
| 16道单篇题要点分 | 100.00 | 100.00 |
| 8道跨篇题要点分 | 93.75 | 90.63 |

Qwen的要点失分在17题（75）和24题（75）；Jev在17、22、24题（均75）。17题两组均被Planner路由到直接回答，算术正确但未核对两篇原文单位；24题两组均未交代Li的损伤D与T0关系；Jev22题还未给CLSM孔隙率误差范围。其他差异主要是额外数值、材料归属与引用问题，原始判分和逐项校准理由均保留在HTML。

Qwen只有12/24题实际触发重排，共14批、14次API请求；Jev只有5/24题触发，共5批、250次独立候选评分请求。重排批次耗时中位数为0.743秒与3.304秒；整题耗时中位数为76.97秒与75.57秒。两组工具路径不同，不能把整题耗时差直接归因于重排器。Jev重排接口实际返回费用合计0.006741294美元；Qwen接口未返回金额，不能记作免费。两组Jev裁判费用分别为0.044222514和0.037696680美元，均与重排费用分开记录。

这一轮Qwen的要点分略高、Jev的事实与引用指标较高，但不是固定候选池或固定工具轨迹实验。每组每题仅运行一次，证据核查单元是Markdown语义段而非等长原子事实，且Jev同时参与排序与原始评判；不能据此宣称统计显著的总体优劣，也不能把这些指标合成一个“整体准确率”。网站仍使用原配置，本次没有部署或切换线上重排器。

与2026-11-09的v7全量回归核对后，修正了本轮Qwen第17题K3的口径不一致：沿用此前不强求固定字段设计清单的规则，恢复K3由0.5为1；该题总分62.5→75，本轮Qwen24题要点均分97.40→97.92。没有重新生成答案或调用裁判，原始Jev评分与答案保持不变，校准文件记录了更正前后数值。此前v7的30题要点分99.58，筛选相同24题为99.48；v7第17/22/24题分别100/100/87.5，本轮Qwen为75/100/75，Jev为75/75/75。题目和必答要点文本相同，但代码与独立运行路径不同，不能单凭这组结果把下降归因于重排器。
