# 文献工具与调用轨迹

这里记录文献 Agent 使用的工具协议和持久化轨迹。

## 工具

| 名称 | 行为 | 边界 |
| --- | --- | --- |
| search_literature | 调用现有检索完整流程，包括查询改写、融合去重、重排、上下文补全；返回原文、来源块、章节标识、图片标识 | 返回run内统一编号，并保留本次局部编号到统一编号的映射 |
| list_sections | 单篇传document_id，或用document_ids一次查最多四篇的目录 | 批量输出每篇的章节ID、标题、页码和独立的分页游标；继续翻页时单篇调用。目录不产生引用。 |
| read_section | 保留单篇单章节写法；用targets一次读取最多三个document_id与section_id组合 | 整批共用max_chars，默认12000、最多24000；逐项返回状态和分页游标，正文只返回一份，保留页码、字符范围和独立的引用。 |
| read_table | 按文献和原始表格chunk_id返回完整存储表格及关联原图标识 | 不猜测缺失单元格/单位；不新生成结构化行列，也不自动读取所有讨论段落 |
| view_image | 按asset_id交付已有PDF原图裁剪的PNG像素及图号、页码、bbox、哈希 | 不是只有图注；核对原文件路径、大小和哈希。不执行视觉理解，不新增局部放大/子图裁剪 |

计算变化和单位换算工具已下线。需要简单计算时，由模型根据可引用的已查数据推导，并区分推导值与原文数值；旧记录仍可回查。

所有工具必须填写reason。Agent一轮最多执行一个工具；独立的目录或章节请求可以在该次调用中批量完成。

## 轨迹

默认位置：`.rag-data/tool-traces.sqlite3`，随`.rag-data`忽略，不上传GitHub。

- 每个调用包含run_id、独立call_id、可选parent_call_id、输入、调用理由、开始/结束时间和耗时。
- 先持久化started再执行，成功/失败后更新；异常中断的started记录保留，不假装已完成。
- 保存实际返回的文字、页码、块/章节/图片标识和结果哈希。图片保存身份与哈希，返回给调用方的是base64像素；轨迹不重复保存base64。
- 检索保存候选、主命中、补全诊断、改写/重排/embedding调用和供应商返回用量。未知Token或费用为null，不估算为零。
- worker调用保存非敏感配置快照和文献身份。API密钥不进入协议；未知输入字段会被拒绝且不保存其值。上游原始异常文本不保存。
- 记录完整调用轨迹不等于保存模型隐藏推理，也不等于保证检索或答案正确。
- 本地入口只用于可信开发环境；尚无多用户访问授权接口。公开接入前应添加访问控制和轨迹保留策略。

## 使用

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/literature_tools.py schemas
.\.venv\Scripts\python.exe -X utf8 scripts/literature_tools.py call --library <现有文献库目录> --request <请求JSON文件> --run-id example --output .rag-data/tool-result.json
.\.venv\Scripts\python.exe -X utf8 scripts/literature_tools.py trace --run-id example --output .rag-data/tool-trace.json
.\.venv\Scripts\python.exe -X utf8 scripts/literature_tools.py evidence --run-id example --output .rag-data/evidence-ledger.json
```

检索请求示例：

```json
{"tool":"search_literature","query":"PFI打浆为什么提高WRV？","reason":"寻找机制及条件依据"}
```

章节读取请求示例（标识需替换成实际检索结果）：

```json
{"tool":"read_section","document_id":"doc_x","section_id":"sec_x","offset":0,"max_chars":12000,"exclude_chunk_ids":[],"reason":"补读机制解释及条件"}
```

批量读取示例（每项也可带自己的offset与exclude_chunk_ids）：

```json
{"tool":"read_section","targets":[{"document_id":"doc_x","section_id":"sec_x"},{"document_id":"doc_y","section_id":"sec_y"}],"max_chars":12000,"reason":"比较两篇论文的验证方法"}
```

原图输出可能很大，建议使用`--output`保存，不直接将base64打印到终端。

## 验证

自动测试覆盖原有检索调用、轨迹保存、目录与章节批量读取、部分失败、字符预算、章节分页与去重、文献归属、参数拒绝、原图篡改检测和跨run来源隔离。

已用当前MinerU/Qwen论文库完成五种工具的实际调用，私有记录run_id为`tool-smoke-20261104`。检索执行真实改写/向量化/重排；读取和计算未调用答题或审校模型。

## 单次问答证据清单

已实现：同一个run_id代表一次问答，工具返回的ref共用一套递增编号。下一次独立提问必须换run_id；run_id不是用户身份或访问凭证。

- 检索返回统一ref及local_to_run_refs；内部检索诊断仍保留局部编号，不能直接拿它当最终引用。
- 章节分页中的每个原文片段、完整表格和实际读取的原图均获得ref。旧的calculation记录可继续读取，不能冒充论文原文。
- 按内容及出处精确去重：原文、文献身份/可用的文件哈希、页码、原始块、字符范围、附带图片共同确定快照。不按语义相似合并，也不因同一个chunk_id就覆盖不同内容。
- 相同的完整原文通过检索/章节/表格接口取得时，若实际快照一致，可复用编号；不同分页范围、补全窗口或图片附件视为不同证据。原图单独读取也独立编号，避免把仅获得图片标识说成已查看像素。
- 重复获取时追加来源call_id，不修改原快照。单个ref可追溯到多个工具调用。
- SQLite事务内完成编号分配、快照和最终调用记录保存，并发下无重复编号。重启不重置；失败调用不分配编号。进程提交后、响应送达前中断时，记录表示执行完成，不表示调用方已收到。
- `ToolTraceStore.evidence(run_id, refs)`可解析指定引用；不存在或格式非法的编号明确失败，不借用其他run的同名编号。
- 历史工具记录不自动回填或改写。新调用才进入证据清单；图片base64仍不写入SQLite。

实际论文同表两次读取会复用编号，图像得到独立编号。回答和复核使用这份证据清单。
