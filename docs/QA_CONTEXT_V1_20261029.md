# 文献问答第一轮优化：结构切块与上下文补全

2026-10-29。本轮完成正文与单页表格重切块、同页邻块补全、精确重叠去重、来源快照和字符预算控制。答题模型继续使用当前DeepSeek Flash / High，检索仍为一次向量查询、top_k=8、min_score=0.35。

## 结果

- 新索引独立构建在本机私有`.rag-data/index-versions/structure-v1-20261029`。原库44块保留；新库81块，其中79个句段块、2个表格块。
- 表1、表2的两类浆数据、列名和表注按原文保留；新块由现有已抽取文本的原文子串组成，没有用模型重写或补造单元格。新旧块、页面偏移与文本指纹保存在`structure.json`及`source-pages.json`。
- 对旧32题的已保存检索命中进行离线重放，未新增模型或Embedding调用。所有补全结果在同文献、同页范围内；单条证据不超过8,000字符，总证据不超过24,000字符。
- 使用独立本地HTTP服务及隔离的问答记录库，真实访问文献列表、PDF、提问、状态轮询和历史详情。第21、10题各一次生成成功，引用原文与模型收到的证据一致。
- 分组回归覆盖206项相关测试，全部通过；前端生产构建通过。

| 开发验证题 | 原回答缺口 | 新请求观察 |
| --- | --- | --- |
| PFI2-021 | 原证据只有33.06%，没有12000转的29.28%，无法计算 | 回答给出33.06%→29.28%，下降3.78个百分点，相对下降约11.43%；引用包含完整表格依据 |
| PFI2-010 | 未给出两类浆(200)晶粒尺寸的端点数值 | 回答列出两类浆各5个转数的尺寸，端点均为4.5→4.7 nm |

这是证据完整性及数值出现检查，不是新一轮Luna/Jev质量评分。两道真实请求同时使用新索引和上下文补全；不能据此宣称全部32题分数已经提高，也不能单独归因于其中一个改动。第10题仍有“软木/硬木”的术语表述，领域术语与完整回答检查留待生成阶段优化。

公开验证记录：[开发检查摘要](../data/literature/qa-evaluation/reports/context-v1-20261029/smoke.json)、[两道真实回答及引用快照](../data/literature/qa-evaluation/reports/context-v1-20261029/answers.jsonl)。原始HTTP记录与32题检索重放保存在本地忽略目录，不写入原问答历史。

## 处理流程

1. 向量检索得到原始主命中，保留其原始分数。
2. 从只读SQLite元数据读取同一文献、同一页、前后各一块；完整表格主命中直接保留。
3. 重叠窗口合并，按原文顺序拼接，只去除可精确匹配的旧文本重叠。非连续原文明确分隔，结构化表格/句段不会按相似文字删行。
4. 先为主命中保留预算，再添加上下文；超预算时退回完整原块，记录预算限制和未纳入的主命中。不会在数字行中途截断。
5. 生成与引用使用同一份最终证据。历史同时保存原始命中、补全诊断、最终文本、全部组成块和配置指纹。页面可展开查看多段引用的原文组成。

程序校验引用编号、结构及来源映射，不把这种校验当作科学事实正确性的证明。

## 配置与版本切换

```dotenv
LITERATURE_DATA_DIR=../.rag-data
LITERATURE_LIBRARY_DIR=../.rag-data/index-versions/structure-v1-20261029
RAG_CONTEXT_EXPANSION_ENABLED=true
RAG_CONTEXT_NEIGHBOR_RADIUS=1
RAG_CONTEXT_MAX_EVIDENCE_CHARS=8000
RAG_CONTEXT_MAX_TOTAL_CHARS=24000
```

`LITERATURE_LIBRARY_DIR`只选择文献索引和PDF，问答历史及文献提取任务继续存放在`LITERATURE_DATA_DIR`，避免切换索引后原记录消失。历史保存证据快照，旧记录不会根据新索引重新解释。

回退时移除`LITERATURE_LIBRARY_DIR`并设置`RAG_CONTEXT_EXPANSION_ENABLED=false`。原库、旧基线和旧评分均未覆盖。新配置加载需要重启后端。

建立新版本先预览，无模型调用：

```powershell
.\.venv\Scripts\python.exe scripts\reindex_literature_structure.py --source-dir .rag-data
```

显式调用既有Embedding服务并构建独立索引：

```powershell
.\.venv\Scripts\python.exe scripts\reindex_literature_structure.py --source-dir .rag-data --output .rag-data\index-versions\structure-v1-20261029 --embed
```

脚本拒绝覆盖已有目录；失败的构建标记为failed，不能作为已完成索引使用。本轮Embedding两批共81块，服务报告11,716 Token；两个真实问题的查询Embedding共75 Token。答题生成用量随真实响应保存，未取得实际账单，不估算货币费用。上述为应用层调用记录，SDK内部网络重试未单独计数。

冻结工具已支持复制结构清单及页面来源；评测运行工具按配置中的完整源文件清单校验新流程，同时兼容旧版六文件指纹。

## 范围与限制

- 当前对已入库文字做结构整理，沿用既有PDF文本抽取结果；不提供OCR、图片理解或原始PDF错列修复。
- 表格识别基于文本标题、数值行和章节边界，是保守的单页处理。到达页末会记录跨页完整性尚未核验，不自动连接下一页的表格。
- 超长表格明确拒绝构建，后续需实现经核验的按行分组及重复表头；本轮不会为了满足预算删除数据行。
- 未找到正确结果附近的检索问题仍需后续排序与混合检索解决；补邻块不会保证所有问题的完整证据都能找到。
- 未执行新的32题生成或128份双评，旧DSH对照报告仍对应旧回答。
- 服务器SSH连接持续被关闭，当前不能把本轮本地修改宣称为线上已部署。

实现：[上下文补全](../backend/literature_rag/application/context.py)、[结构重切](../backend/literature_rag/application/structure.py)、[独立索引构建](../scripts/reindex_literature_structure.py)。
