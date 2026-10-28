# DSH全文问答对照材料包

固定平台：DSH；用户选择的模型：DeepSeek-V4.1-Flash-1017；推理档位：High。
这是整套系统的对照，不要求DSH复用RAG的8段证据，也不限制其只调用模型一次。

## 你实际给DSH什么

每道题新建一个独立会话，只提供：
1. `paper.pdf`：与原RAG评测完全相同的原始PDF。
2. `tasks/PFI2-xxx.md`：该题原始问题、统一作答说明和输出约定。

把对应md的正文粘贴进新会话，并附上paper.pdf。不要只给一个文件路径却没有上传文件。
`questions.md`和`questions.jsonl`是操作者核对目录，不建议把32题一次性丢进同一个会话。
每题会话中不要提供其他题目的回答。可共享同一个静态文档库，但不要共享问答历史、记忆或笔记。

建议先做001题检查PDF能否读取和JSON能否保存；不要给答案质量反馈。格式确认后做其余31题，保留首题结果。
JSON输出按题号保存为`answers/PFI2-001.json`至`answers/PFI2-032.json`，也可汇总成每行一个对象的answers.jsonl。
`OUTPUT_EXAMPLE.json`只演示结构，尖括号内容必须换成真实回答与引文，不得作为已完成结果。

## 保持公平的执行方式

- 先将本包解压到项目仓库以外的独立目录；不要给作答Agent访问FiberScope项目、评测报告或历史会话的权限。
- 每题固定模型和High档位，使用同一份统一说明。无需人为挑选更优答案；若重试，保留首次输出及全部重试记录。
- 仅使用本PDF。允许自主搜索、解析、阅读全文和计算；关闭联网及其他论文来源，避免改变题目的语料范围。
- 不附带参考答案、评分要点、旧RAG回答或裁判意见。本包的题目文件没有这些内容。
- 如平台实际启用了联网、历史记忆、外部材料或视觉能力，记录真实情况，不能把有偏差的运行写成严格同条件。
- 若DSH无法提供逐题独立上下文，应说明限制，不能把连续32轮聊天标成独立32题。

## 输出与后续评分

每题使用`output.schema.json`规定的四个字段：task_id、answer、claims、citations。
需保存答案的全部陈述、引用对应的PDF页码和原文短引，不要求输出隐藏推理。
请保留原始回复。若平台支持，另导出对话和工具记录，供核对实际时间、费用及异常使用的资料。
`RUN_INFO_TEMPLATE.json`由操作者补充，不能观察到的调用次数、Token和费用保留null。

作答结束后，将32份答案、填好的运行信息，以及已有的平台日志一起打包交回。
我们先核对格式、题号、来源与引文，再导入独立结果目录，使用Luna和Jev盲评。

共同评分只有五项：要点完整性、事实支持、单条引用有效性、引用组完整性、证据边界。
不把原RAG的“检索充分性”作为DSH的共同评分指标，也不因缺少检索日志把它记0。
不能核对的引文不视为已验证。引用的粒度可能不同，比较时保留分母、陈述数量和回答长度。

## 解释比较结果

本轮RAG显式请求官方deepseek-flash（当前文档对应V4.1-Flash-1017）、thinking enabled、High。
DSH选择V4.1-Flash-1017和High；仍需记录平台实际返回版本、隐藏系统提示词和工具预算差异。
结果用于比较这两套实际系统配置，不能据此把效果差异唯一归因于RAG架构。
32题为已有开发基线，本轮不证明对新论文或未见题目的泛化。

## 论文来源

Li、Zhao、He（2020），Probing Effect of Papirindustriens Forskningsinstitut (PFI) Refining on Aggregation Structure of Cellulose: Crystal Packing and Hydrogen-Bonding Network，Polymers 12, 2912。
DOI：https://doi.org/10.3390/polym12122912 。许可：CC BY 4.0（https://creativecommons.org/licenses/by/4.0/）。本包原样复制原PDF，未修改。
