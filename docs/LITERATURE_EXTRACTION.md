# 文献数据提取与审核

第一版提供可复制文字的 PDF 表格提取、异步任务保存、原文证据查询和 JSONL 导出。复用 `backend/.env.literature` 中的 `RAG_LLM_*` 配置，不依赖向量检索，也不读取提取基准作为模型输入。

网站左侧“科研助手 → 文献数据”进入 `/literature-data`，提供上传、任务搜索、原文对照、数据修改、确认/驳回、审核版本和已确认数据导出。OCR、曲线图读数、论文全文批量识别和预测模型尚未实现。

原始提取快照保持待审核状态，人工审核另存版本。确认原文抄录不等于确认建模适用性；只有明确确认并标记适合建模的记录，审核结果中的 `approved_for_training` 才为true。这是访客的人工标记，不代表专家评审或已执行模型训练。

## 运行

安装新增解析依赖，沿用现有后端启动方式：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-literature.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

`LITERATURE_ENABLED=true` 启用文献模块。`LITERATURE_EXTRACTION_TIMEOUT_SECONDS` 控制单次提取子进程总时限，默认 180 秒，范围 10—300 秒。模型客户端每次调用超时 75 秒，不做网络自动重试；仅在输出校验失败时允许一次完整修正。

已有基本环境也可以安装完整的 `backend/requirements-literature-lock.txt`。模型服务地址及 API 密钥仅在隔离工作进程中读取，不返回前端。

## 接口契约

接口前缀为 `/api/v1/literature/extractions`。

| 方法与路径 | 用途 |
| --- | --- |
| POST `/extractions` | 提交 PDF 原始字节，接受任务后返回记录，处理中为 202，已完成的幂等重放为 200 |
| GET `/extractions` | 当前浏览器的任务摘要列表，固定按时间、ID倒序；支持 `page`、`page_size`、文件名/表格字面搜索`q` |
| GET `/extractions/{id}` | 处理状态、来源与完整证据/结果快照 |
| GET `/extractions/{id}/pdf` | 当前访问者的原文 PDF |
| GET `/extractions/{id}/export` | 当前访问者该任务的单行 JSONL 快照 |
| GET `/extractions/{id}/page` | 受限工作进程渲染的原文页PNG，按原始PDF点坐标定位数值 |
| POST `/extractions/{id}/reviews/{record_id}` | 保存该候选数据的新审核版本 |
| GET `/extractions/{id}/reviews/{record_id}/events` | 修改前后内容、审核决定与时间，按版本倒序 |
| GET `/extractions/{id}/confirmed?format=jsonl` | 仅导出当前已确认记录；`format=csv`导出UTF-8 BOM CSV |

POST 使用 `Content-Type: application/pdf`，请求体是 PDF 文件本身，不是 multipart 表单。查询参数：

| 参数 | 说明 |
| --- | --- |
| `page` | 必填，PDF物理页码，1—200 |
| `table` | 必填，例如 `Table 3`；所选区域必须出现该表标题 |
| `request_id` | UUID，省略时生成；网络重试应复用同一编号 |
| `filename` | 显示文件名，默认 `paper.pdf`，不参与磁盘路径构造 |
| `crop` | 可选，`x0,top,x1,bottom`，PDF点坐标；页左上角为参照 |

文件最多 12MB，最多 200 页；第一版一次处理一页/区域。所选区域最多 4,000 个文字单元、40,000 个字符。加密、损坏、没有可提取文字或过于复杂的页面会记录为失败，保留已得到的证据和诊断。

同一会话、同一 `request_id` 的相同文件和参数只执行一次；不同参数返回 409。单实例一次执行一个提取任务，忙时返回 429。接受的任务在后台继续执行，刷新页面不会取消。重启后未结束任务标记 `interrupted`，恢复已写入的检查点。

客户端可先调用列表建立会话，再提交/轮询。会话由随机 HttpOnly Cookie `fiber_extraction_session` 标识，数据库仅存其 SHA-256。列表、详情、PDF和导出均检查归属，其他访问者返回404；修改请求检查 Origin，响应禁止缓存。这是浏览器隔离，不是账号登录；清除 Cookie 或换域名/设备后无法直接找回原会话。提取会话与问答历史会话独立。

## 提取流程与证据

1. 上传内容按 SHA-256 命名，保存原文与处理参数。
2. 在有总时限的独立子进程中解析 PDF，生成每个文字单元的编号、文字和位置；失败及超时均不回传原始供应商错误。
3. 模型识别行名、指标表头、单位及测量状态，将每个单元格映射到 PDF 文字编号。PDF内容只作为证据，不能覆盖系统提取规则。
4. 程序检查编号存在、行名来源、单元格位置、数值格式、单位和状态引用、重复行/列及重复数值编号。
5. 数值由程序直接从引用的 PDF 文字复制；模型不会直接写入它生成的数字。保留 `raw_value`、`raw_unit`、页码、表格、坐标及表头/单位/状态来源。
6. 完成后保存候选记录；缺失单元格保存为缺失提示，不补零、不猜测条件或单位。保存失败时明确返回不可用，不能显示为已保存。

结果快照包含 `configuration`、`evidence`、`diagnostics`、`result`。配置保存模型名称、提示词及流程指纹；诊断保存模型实际返回的 Token 用量和校验失败原因。供应商未返回的用量不估算。硬超时若尚未返回调用结果，该次 Token 用量仍未知。

**位置和格式检查不能证明指标语义正确。** 例如某个真实数值可能被模型归到错误指标；这类问题需要提取评测与原文对照审核解决。不得把“引用了真实数字”当成“实验条件全部对应正确”。

## 在网站中核对

1. 上传可复制文字的PDF，填写物理页码与表格编号，提交后自动轮询。URL保留任务编号，刷新恢复同一会话的任务。
2. 左侧显示原文页，可放大/缩小及打开完整PDF；右侧按原文原料分组查看指标。点击候选值，原文高亮该数值及对应原料、表头、单位和状态。
3. 核对原料、指标、测量状态、数值和单位；需要补充实验条件时记录原文来源。修改数据必须填写说明，不覆盖原始提取证据。
4. 选择待核对、确认抄录或驳回，再单独选择建模适用性。驳回和建模评估需要说明，未确认的数据不能直接标记适合建模。
5. 保存后可查看每个版本的修改前后内容及时间。未保存的修改会阻止记录切换，离开页面时有提示；可取消修改，或重新读取服务端版本。
6. 导出CSV或JSONL仅包含当前已确认记录，附原值、审核值、单位、实验条件与来源、页码、坐标、版本和建模适用性。待核对、已驳回记录不进入该导出；适用性未评估的已确认记录仍可导出，但不得把它们默认当成训练数据。

审核POST必须包含 `expected_revision`（首次为0），以及 `raw_material`、`metric`、`measurement_state`、`raw_value`、`raw_unit`、`status`；可补充 `experiment_condition`、`condition_source`、`suitability`、`note`。数值用原始字符串保留精度，程序检查有限数值。服务器对版本进行原子检查：过期版本返回409，不覆盖另一个页面的更新。取消本地修改后重新读取，再决定是否提交。

审核存储新增 `extraction_reviews` 与 `extraction_review_events` 两张表，记录库从版本1升级到2，保留原有任务。原始 `snapshot_json` 不更新，审核记录按候选ID关联。没有登录体系，因此审核记录不能冒充实名专家审核。

CSV文本字段会防止被Excel解释为公式；JSONL保存原始文本。真实数值字符串（含负数）不添加防公式前缀。

## 本地提取和评测

使用已经整理的 Table 3 基准：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/extract_literature.py `
  --pdf tmp/pdfs/nonwood_fibers_2021.pdf `
  --page 5 --table "Table 3" `
  --benchmark data/literature/benchmarks/ferdous_2021_table3
```

默认脚本等待最多330秒，结果和评测报告保存在被忽略的 `tmp/literature-extraction`。等待结束不会撤销服务端已接受的任务；Cookie仅在此脚本进程中保留，结果文件不包含会话令牌。脚本会话与浏览器会话独立，因此脚本生成的任务不会自动出现在另一个浏览器中；网站审核请从页面上传。

比较基准前先检查 PDF SHA-256、页码与表格一致，避免拿不同排版的坐标比较。以“原文原料名、指标、测量状态”为键，同时比较原始数字写法、数值、单位与原文坐标，并报告缺失、意外记录和重复项。仅全部匹配的记录计为正确。

基准本身保留原文疑点，详情见[表3整理说明](../data/literature/benchmarks/ferdous_2021_table3/README.md)。对该表的高分证明的是指定样例的忠实提取，不证明原文科学数据正确，也不证明其他论文上同样准确。

## 存储与备份

```text
.rag-data/extraction/
  records.sqlite3          # 会话、任务、证据和结果快照，WAL模式
  pdfs/<sha256>.pdf        # 上传原文，以内容指纹去重
  jobs/<task-id>/          # 原子写入的配置、证据、诊断和结果检查点
  .process.lock           # 同一记录库只允许一个提取服务实例
```

SQLite记录库独立于实验PostgreSQL和问答历史，整个目录均被Git忽略。实验数据库备份不会覆盖它。备份时使用SQLite在线备份接口备份记录库，并保存 `pdfs/`；活动任务的 `jobs/` 检查点需一并保留。不要在任务运行时只复制SQLite主文件而遗漏WAL。最简单的完整目录备份方式是在服务正常退出后复制整个 `extraction/` 目录。

## 验证记录

提取后端的初始模型结果见[提取验证记录](LITERATURE_EXTRACTION_VALIDATION.md)；页面、审核版本和导出的完整流程见[审核页面验证记录](LITERATURE_REVIEW_VALIDATION.md)。
