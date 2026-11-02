# 引用校验失败规则与草稿记录

2026-11-02。为后续文献问答和新建评测记录具体失败原因；不重写历史答案或评分，不重新调用模型补造旧草稿。

## 保存在哪里

新worker结果增加`citation_validation`，原有最终`answer/claims/citations`和`generation_calls`字段保持原用途：

- 在线问答：完整结果随原有`result_json`保存到问答历史SQLite，无需数据库迁移；历史详情与JSONL导出保留诊断。
- 新建评测：`results/<题号>.json`的`response.citation_validation`保留诊断，源文件仍按原流程封存。
- 旧评测使用自己的封存源码，不会被本次修改覆盖；要使用新记录功能，需用当前源码准备新的运行目录。
- 诊断草稿与普通问答历史沿用现有访问范围；当前平台历史公开可读。草稿只作诊断，不作为最终回答展示，也不进入裁判的候选答案字段。

## 每次校验包含什么

| 字段 | 含义 |
| --- | --- |
| `version` | `citation-validation-trace-v1` |
| `scope` | 仅检查引用结构，不能解释为原文支持度评分 |
| `first_failure_only` | `true`；原校验器遇到第一处问题即抛错，每次记录首先触发的规则 |
| `attempts[].attempt` | 第几次生成，从1开始；与`generation_calls[].attempt`对应 |
| `status` | `failed`或`passed` |
| `rule_code/message` | 稳定规则编码与固定中文说明；通过时为空 |
| `field` | 失败字段，如`claims[1].citation_refs` |
| `claim_index` | 出错陈述的下标，从0开始；非陈述问题为空 |
| `supplied_refs` | 本次实际提供给模型的引用编号 |
| `draft` | 失败的完整结构化草稿，保留`answer`及各条`claims.text/citation_refs` |
| `draft_sha256` | 草稿规范JSON的SHA-256，便于检查报告是否改变了草稿 |

结构化草稿中的文字与引用原样保留，没有自动修正；它不是供应商原始HTTP响应，也不包含模型思考过程。程序不将请求头、配置密钥或供应商错误正文加入该记录；程序日志继续不打印草稿和原始错误。

成功校验只记录`passed`，不重复保存成功草稿。第一次失败、第二次成功时仍保存第一次失败的草稿；两次失败时两份都留存。若生成阶段没有得到有效结构化结果，就没有可记录的校验草稿，也不会编造一份：例如第一轮生成异常、第二轮校验失败时，仅有`attempt=2`的校验记录。后续模型请求失败时，此前已收集的校验诊断仍随worker的失败结果返回。

## 规则编码

| 编码 | 问题 |
| --- | --- |
| `evidence_reference_sequence` | 输入证据编号不唯一、不连续或顺序不正确 |
| `empty_answer_or_claims` | 回答或陈述列表为空 |
| `empty_claim_text` | 陈述正文为空 |
| `multiline_claim_text` | 单条陈述包含换行 |
| `inline_claim_reference` | 陈述正文直接带引用标记 |
| `missing_claim_reference` | 陈述没有引用 |
| `non_string_claim_reference` | 陈述引用编号不是字符串 |
| `duplicate_claim_reference` | 同一陈述重复引用 |
| `unknown_claim_reference` | 陈述引用编号不存在 |
| `duplicate_claim` | 陈述内容重复 |
| `noncanonical_answer_reference` | 回答中的引用不是标准`[n]`格式 |
| `missing_answer_reference` | 回答没有引用标记 |
| `unknown_answer_reference` | 回答使用不存在的编号 |
| `undeclared_answer_reference` | 回答使用了陈述列表未声明的编号 |

原有规则、先后顺序、错误文字、一次重试、重试提示词、最终拒答策略及最终陈述渲染均未调整。本次不用于证明回答质量提升，只补诊断信息。

## 离线查看报告

在项目根目录执行，可读取新旧评测运行目录、单个worker JSON，或问答历史JSONL导出：

```powershell
.\.venv\Scripts\python.exe scripts\report_qa_citation_failures.py --input .rag-data\evaluations\某次运行 --output .rag-data\diagnostics\某次运行
```

输出`report.html`、`records.jsonl`和文件校验清单。HTML分开呈现最终返回与“未经校验”的失败草稿，并转义草稿中的HTML。工具不调用模型、不重新评分，不覆盖已有报告；输入缺少诊断时明确标注无法还原。原始结果与草稿指纹保留，草稿被改动时拒绝导出。

第27、32题的旧BGE运行没有记录失败草稿，本次功能不能恢复它们。若后续对它们重跑，应建立新的实验记录，不替换原有评测结果。
