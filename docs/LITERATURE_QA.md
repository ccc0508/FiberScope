# 文献问答接入说明

## 已完成范围

访问 `/literature`，或点击左侧“科研助手 → 文献问答”。

- 展示已完成导入的文献、页数和片段数；支持单轮中文提问。
- 支持MinerU章节组织、文字/表格行/图片检索、双路查询、文字候选重排、结构化回答与引用校验。
- 点击回答中的引用编号定位原文片段；点击“查看原文”打开PDF对应页。
- 图文模式将命中证据关联的原PDF区域图片交给DeepSeek，引用卡片显示可点击的原图，并为历史记录独立缓存图片。
- 提供等待、拒答、失败重试和手机布局；页面以纯文本渲染答案和文献片段。
- 文献库为独立快照，不读取旧实验SQLite，也不改变当前PostgreSQL或原始Excel。
- 服务端长期保存问答历史及全部检索证据，所有访问者可查看与导出；用户评价仍限原提交浏览器修改。支持JSONL导出和独立备份，见[问答记录说明](QA_HISTORY.md)。
- 文献数据页可直接解析上传的PDF并保存候选数据，支持原文对照、修改/确认/驳回、审核版本和已确认数据导出，不经过向量检索；见[提取与审核说明](LITERATURE_EXTRACTION.md)。

当前本机默认配置（2026-11-02）：1篇论文、14页、113个MinerU原文块、20条表格行及11组图像（Figure 1—9、Table 1—2）；Embedding为Qwen3-VL-Embedding、2560维，DeepSeek Flash High接收文字与原图。正文/表格/公式小节补全、表格关联、原问题+改写双路查询、BGE文字重排均启用；回答指引关闭。已增加一次DeepSeek证据审校，记录原稿及有依据的最小修订；失败或时间不足时保留原稿，不能将审校视为准确性保证。原BGE与Qwen纯文本库保留，历史评测不覆盖。详见[证据审校结果与开销](QA_EVIDENCE_REVIEW_RESULT_20261102.md)、[默认图文启用记录](QA_VISUAL_ACTIVATION_20261102.md)和[图片链路实现](QA_VISUAL_INTEGRATION_20261102.md)。

文献覆盖范围以页面列出的文件为准。引用可追溯不等于结论已通过独立语义审查。本机私有配置与服务器独立，Git推送不会自动更新服务器的索引和模型配置。

## 本机运行

本机已完成依赖安装、文献快照和配置迁移，直接沿用项目原有启动命令。旧项目保持不变，无需同时运行旧Streamlit服务。

新的完整后端环境可安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-literature-lock.txt
```

已有基本后端环境时可只增加可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-literature.txt
```

配置文件：`backend/.env.literature`，模板为`backend/.env.literature.example`。该配置与PostgreSQL的`backend/.env`分开。API密钥只在服务端读取，不返回浏览器。

| 配置 | 说明 |
|---|---|
| LITERATURE_ENABLED | 显式启用文献问答；默认false |
| LITERATURE_DATA_DIR | 历史、提取和图片缓存的数据根目录，相对路径以backend目录为基准 |
| LITERATURE_LIBRARY_DIR | 可选独立检索库目录；不改变历史和提取数据目录 |
| LITERATURE_TIMEOUT_SECONDS | 单次子进程总时限，5—300秒，默认90秒；当前本机300秒 |
| RAG_EMBEDDING_* | 与索引一致的provider、模型、维度、密钥和服务地址 |
| RAG_LLM_* | 回答模型及服务配置，支持已有openai/deepseek适配器 |
| RAG_EVIDENCE_REVIEW_ENABLED | 可选DeepSeek一次证据审校，代码默认false，本地当前已启用；不重新检索 |
| RAG_EVIDENCE_REVIEW_TIMEOUT_SECONDS | 审校请求时间上限，默认120秒；剩余整次请求预算不足则跳过并保留原稿 |
| RAG_EVIDENCE_REVIEW_MAX_OUTPUT_TOKENS | 审校输出上限，默认16384；截断、无效结果或编辑校验失败均保留原稿并记录原因 |
| RAG_TOP_K / RAG_MIN_SCORE | 检索上限与相似度阈值，沿用原RAG规则 |
| RAG_VISUAL_RETRIEVAL_ENABLED | 开启同空间的Qwen图像召回和原图输入，要求已建好图像库及匹配的DeepSeek配置 |
| RAG_VISUAL_MAX_IMAGES / RAG_VISUAL_MAX_TOTAL_BYTES | 原图数量和字节预算，默认4张、12 MiB |

Embedding模型、provider或维度变化时，应创建新索引；不能直接把新配置套到原索引上。

## 一次性迁移工具

```powershell
.\.venv\Scripts\python.exe scripts/setup_literature.py --source-root C:\path\to\legacy-project
```

迁移工具获取旧导入器使用的文件锁，备份文献元数据库和向量库，复制已完成文献并校验PDF的SHA-256，然后将PDF路径改为快照内的相对路径。它仅复制指定RAG配置项，不读取或复制旧实验数据库，不重新生成embedding。目标`.rag-data`或配置文件已存在时拒绝覆盖。

目录结构：

```text
.rag-data/
  metadata.sqlite3
  qa_history.sqlite3
  chroma/
  papers/
backend/.env.literature
```

文献库、密钥、真实问答结果均不进入Git。部署时需要另行传输这份完整文献快照及服务端配置；仅克隆代码不会自动获得文献。当前为一次性快照，不会自动同步旧项目后续导入的新文献。

## 接口

| 方法与路径（前缀/api/v1） | 用途 |
|---|---|
| GET /literature/documents | enabled、文献列表、说明；不返回磁盘路径或密钥 |
| POST /literature/ask | JSON请求`{"question":"研究问题","request_id":"UUID"}`；去除首尾空白后2—2000字符，返回202及记录编号 |
| GET /literature/documents/{document_id}/pdf | 按文献ID读取允许目录内的PDF，支持浏览器`#page=N`跳页 |
| GET /literature/history | 公开历史、搜索和分页 |
| GET /literature/history/{id} | 记录进度、结果、证据、配置和评价 |
| POST /literature/history/{id}/feedback | 保存或修改当前会话的用户评价 |
| GET /literature/history/export | 全部公开记录的JSONL导出 |
| GET /literature/images/{checksum} | 读取历史缓存中校验通过的原图PNG |

提问返回记录（首次202/processing），前端轮询历史详情；完成后从`result`读取`status`（answered/refused）、`answer`、`citations`和模型流程耗时。记录顶层`latency_ms`为端到端耗时。引用包含`ref`、`document_id`、`filename`、`page_start`、`page_end`、`chunk_id`、`excerpt`。

无足够证据或引用纠错仍失败时记录为refused；忙碌返回429；模型/配置失败或超时记录为failed并保留error_status=503/504；无效问题返回422。请求错误沿用统一错误对象和请求编号，worker的原始报错不会返回客户端。

## 执行与并发

每次问答在独立Python子进程中运行，强制UTF-8；主服务不加载Chroma及模型SDK。超时由subprocess终止并回收子进程。单个API进程同时只接受一个问答，其余返回429；上线初期使用一个Uvicorn worker，多worker或多实例部署前需要共享限流。

前端提交及每次轮询最多等待15秒，仅展示校验后的完整回答，不提前流式输出尚未校验的生成文本。离开页面会停止轮询；已接收任务继续处理并保存结果，刷新后恢复最近记录。每次问题仍独立处理；未实现文献上传/删除界面、实验数据问答或文献与实验联合分析。历史同源会话、接口变更和部署约束见[问答记录说明](QA_HISTORY.md)。

## 验证

继承94项RAG检索/回答/引用测试，并新增11项文献HTTP接口、问题校验、空库/禁用状态、PDF目录边界、并发槽位、超时、CORS及错误脱敏检查。连同原后端32项集成测试，共137项通过；TypeScript检查、生产构建和依赖一致性检查通过。

2026-10-05问答历史阶段：增加10项记录/隔离/幂等/Origin/失败与备份恢复检查，并更新异步提问契约测试；完整后端147项通过，前端6项计算/来源测试及生产构建通过。真实模型、刷新恢复、评价、导出和手机视口验证见[前端验收记录](FRONTEND_VALIDATION.md)。

真实模型已通过浏览器完成中文问题“PFI 打浆如何影响纤维素的聚集结构？”，返回5条可追溯引用。PDF接口返回200及application/pdf，引用支持第1、6、7、12页等页码链接。390px手机布局、加载状态、引用定位、拒答、503重试及HTML文本转义检查通过；模拟响应已恢复。

此前一次真实调用发现Windows子进程默认编码不能可靠传递中文，已改为`-X utf8`并加入回归断言。完整浏览器回归脚本不自动调用收费模型。
