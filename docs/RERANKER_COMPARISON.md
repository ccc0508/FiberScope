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
