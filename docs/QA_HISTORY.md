# 问答历史、用户评价与评测素材

## 使用

文献问答页提供公开的“问答历史”。服务端接收问题后先保存处理中记录，再在后台生成回答。
页面轮询记录；刷新自动恢复最近一次问答，离开页面停止轮询，后台继续处理到完成或90秒总时限。
历史可搜索、分页、打开详情、重新提问。重新提问生成新记录，原记录保留；不把旧回答作为新问题上下文。
原提交浏览器可在回答下方标记“有帮助”或“不准确”，选择问题标签、填写说明和修改评价；其他访问者可查看已保存反馈。
“导出全部记录”下载JSONL，包括所有访问者的全部记录和评价，不受当前列表搜索/分页限制。

## 存储与会话

记录库为`LITERATURE_DATA_DIR/qa_history.sqlite3`，默认项目根目录`.rag-data/qa_history.sqlite3`。
首次访问历史或提问时自动建表，版本为1；只写此记录库，不修改实验PostgreSQL、文献元数据、PDF或向量索引内容。
SQLite使用WAL和短事务；一个Uvicorn进程使用一个后台线程执行问答、每次一个90秒有界子进程。
`.qa-history.lock`阻止多个API进程同时使用此记录库，避免错误地将另一进程的任务标成中断。
重启后首次访问时，将上次遗留的处理中记录标为interrupted。未接收的422/403/429请求不建立问答记录。

服务端签发256位随机会话标识，数据库仅保存其SHA-256。Cookie为HttpOnly、SameSite=Lax，限定路径
`/api/v1/literature`，有效期180天；HTTPS请求设置Secure。本地HTTP可用于开发。
列表、详情及导出公开可读，包含已有和新增记录；详情的can_feedback表示当前浏览器是否为原提交者。评价写入仍检查记录所属会话，他人的记录返回403，不存在的记录返回404。伪造未注册Cookie只会创建新会话。
所有历史响应为Cache-Control: no-store。列表不返回会话标识，JSONL也不包含会话标识或提交幂等键。
这不是账号体系。清除Cookie、换浏览器、换设备或分享域名变化不影响查看及导出，只会失去修改原有评价的权限。
记录长期保存在服务器数据目录，没有按Cookie到期清理记录的机制。历史问题、回答、引用及反馈对所有能访问本站的人可见；提交前页面明确说明公开保存。

POST检查Origin/浏览器站点信息以防跨站操作。Vite代理覆盖X-Forwarded-Host为浏览器访问的Host；
其他反向代理也必须覆盖而不是信任外部传入的此头，透传正确的HTTPS协议，并保持后端仅供可信代理访问。
前后端跨源部署须显式配置可信CORS域名并调整浏览器credentials/Cookie策略；本版本使用同源部署。

## 保存内容

- questions：问题、状态、UTC时间、端到端耗时、失败原因和结果快照。
- result：回答、最终引用、逐条结论与引用编号；全部通过筛选并交给模型的检索片段（最多top_k条），包括未使用的片段和分数。
- configuration：Embedding/LLM provider和模型、维度、top_k、min_score、提示词与流程代码SHA-256、文献ID/文件SHA-256。
- generation_calls：每次应用层生成调用的usage和是否生成结构化结果；Embedding usage单独保存。
- feedback：用户评分、标签、说明、最后更新时间。它不等同于专家审核或参考答案。

密钥、provider服务地址、数据库密码、原始供应商错误、磁盘路径不进入快照。
Token用量只保存供应商实际提供的整数；未提供或子进程超时未返回时为未知，不据此推算费用。
应用层生成调用次数不包含SDK内部网络重试次数。分数为向量相似度，不是正确率。
无证据为no_evidence，空库为empty_library，引用校验失败为citation_validation_failed，
生成格式失败为provider_response_error，模型调用失败为provider_error，检索失败为retrieval_error；
总时限为timeout，其他子进程/配置失败为worker_error，重启中断为service_restarted。
子进程被强制终止时无法回传尚未返回的片段或用量；保留接收时配置、问题和失败状态，不补造证据。
接收记录写入失败则不启动模型；完成写入失败返回明确保存失败提示，客户端不显示“已保存”。

## API（前缀/api/v1/literature）

| 方法/路径 | 契约 |
|---|---|
| POST /ask | `{"question":"问题","request_id":"UUID"}`；question 2—2000字符；request_id可省略，前端总是提供 |
| GET /history | page默认1，page_size默认10最多100，q字面子串搜索最多200字符；固定时间倒序+ID倒序 |
| GET /history/{id} | 公开的完整结果、配置和反馈，含can_feedback；处理中也可读取 |
| POST /history/{id}/feedback | 原提交浏览器写入；rating=helpful/inaccurate、tags最多5个、note最多2000字符；仅answered/refused可评价 |
| GET /history/export | 流式JSONL，所有会话全部记录，包括失败记录；读取事务提供一致快照 |

POST /ask已从同步答案改为记录响应：首次接收202，包含id/status=processing；随后轮询GET /history/{id}。
相同会话+相同request_id重复提交不会再次调用模型；完成后重放返回200及同一记录。
相同编号不同问题返回409，另一个问答占用槽位返回429。模型失败/超时通过历史status=failed返回，
error_status保留503/504；status还包含answered/refused/interrupted。
记录有result（可为null）、feedback（可为null）、configuration、created_at/completed_at、latency_ms、reason_code。
result内部保留原回答的answer/citations。客户端等待请求超时时应先查看历史或沿用原提交编号重试。

## 管理导出与备份

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/manage_qa_history.py export
.\.venv\Scripts\python.exe scripts/manage_qa_history.py backup
```

默认写入已忽略的`backups/qa_history_UTC时间戳.jsonl`或`.sqlite3`；已有文件拒绝覆盖。
可用`--database`指定记录库、`--output`指定新文件。网站也提供公开全量JSONL导出；本地脚本用于备份及管理导出。
备份使用SQLite在线backup，包含已提交的WAL数据，并执行integrity_check；不要在运行期间只复制主.sqlite3文件。
恢复时先停止API，保存现有记录库，将备份放入新的数据目录并指定LITERATURE_DATA_DIR（需完整文献快照），
或在确认保留原库后替换记录库。不要让旧库的-wal/-shm文件和恢复库混用。
恢复后所有浏览器均可查看旧记录；修改旧评价仍依赖原Cookie。
PostgreSQL备份不包含此库；`.rag-data`、备份、真实导出均不进入Git。

## eval边界

JSONL schema_version=1，是评测素材。先人工标注参考答案及应命中的证据，再分离调参集和验收集。
可以比较检索召回、回答正确性、结论与引用一致性、拒答能力及延迟；不把用户“有帮助”直接当标准答案。
本次没有执行Ragas评分，也没有建立正式文献问答质量基准。
