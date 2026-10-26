# 独立裁判三轮评分稳定性：阶段记录

2026-10-26。按用户要求，对同一批已保存的32条回答再独立评分两轮。**64次初次评分请求均已处理，但补评期间第三方服务返回余额不足，正式有效评分尚未齐全，暂不发布三轮总分或完整稳定性结论。**

## 独立上下文与控制

- 每题为全新的system+user请求，store=false，无conversation或previous_response_id；不提供上轮分数、理由或回答模型身份。
- 三轮固定同样32题、相同原版RAG回答、论文、原文证据、评分标准、裁判提示词和模型参数；每题初始请求指纹一致。新两轮没有重跑RAG或Embedding。
- 使用用户指定第三方服务的gpt-6.1-sol，沿用原采样默认值；没有额外设置temperature/top_p/seed。模型身份由网关报告，客户端无法独立认证其内部实现。
- 三轮初评返回的89个响应编号互不重复。上下文隔离得到核对，但不能据此证明供应商内部随机过程完全独立。

## 当前有效进度

| 轮次 | 初始请求已处理 | 初始有效 | 初始拒收 | 初始接口失败 | 补评后有效评分 | 待补齐 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 第2轮 | 32/32 | 18 | 12 | 2 | 27/32 | 5 |
| 第3轮 | 32/32 | 19 | 11 | 2 | 24/32 | 8 |

第二轮待补：PFI2-024、PFI2-026、PFI2-027、PFI2-028、PFI2-031。
第三轮待补：PFI2-024、PFI2-025、PFI2-026、PFI2-027、PFI2-028、PFI2-030、PFI2-031、PFI2-032。

初始拒收主要涉及结构字段、引句不匹配、检索适用性和缺陷关联。不是回答本身的0分；程序不手工补写模型语义评分。有效低分不重试，也不从两个有效分数中挑选高分。
第一轮完整历史结果仍为必答要点平均90.10%、严格达标24/32，见[原报告](QA_BASELINE_V2_REPORT_20261026.md)；其他两轮不以部分题目均分冒充完整32题得分。

## 余额不足与恢复

一次403后，模型列表查询200且另一轮仍获得有效推理结果，因此保留记录后做了一次有上限的显式网络补试。后续403明确返回`insufficient balance`、`billing_error`，两轮均已停止新增评分请求。
私有研究目录保存初始评分、全部补评、失败记录、来源指纹、恢复状态和余额不足时的检查点；没有修改原回答或已有效的评分。充值后仅继续未补齐的任务。
程序最多允许每题2次协议修正和2次显式网络补试；重试保持相同模型、题目、证据及请求内容，格式反馈不含旧语义分值。已实现保留格式反馈的网络补试修复，并通过回归测试。

## 当前调用与用量

新增两轮目前合计84次应用层评分请求（含失败和补评）；76次有用量，8次用量未知。已知输入3,072,161、输出155,604、合计3,227,765 Token。
新增RAG生成0次、Embedding查询0次。实际扣费账单未取得，金额未知；超时及拒绝请求的未知上游用量不能视为0。

## 后续稳定性比较

补齐后，使用同一组32题比较三轮必答要点均分、逐要点一致率、平均绝对差、二次加权κ、严格达标翻转、关键错误有无翻转以及引用/证据边界判定一致性。
纯初次输出的数值另列：目前三轮都有完整数值的共同题目为25题，其中可能包含未通过原文/格式校验的输出。这仅是初始数值诊断，不是正式质量得分，不用于宣布总体稳定。缺失值从不按0分计算。
这项实验衡量固定回答的评分器重复性，不等于RAG重新生成的稳定性，也不证明裁判与领域专家一致。后续仍需要专家校准分歧题。

## 保存与校验

[第二轮进度](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/round-2-progress.json)、[第三轮进度](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/round-3-progress.json)、[已知用量](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/cost.json)、[来源指纹](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/publication.json)。
[第二轮有效逐项评分](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/round-2-review-scores.jsonl)、[第三轮有效逐项评分](../data/literature/qa-evaluation/reports/judge-repeatability-20261026/checkpoint/round-3-review-scores.jsonl)。公开副本省略候选claim全文，完整原件和证据保存在私有`.rag-data/evaluations/`；密钥不进入Git。
Windows与Ubuntu服务器各123项相关测试通过；两轮检查点在服务器与本机独立复核原API输出和失败链，逐项评分及用量统计一致。比较工具不调用模型，缺题或标准疑点会阻止生成完整比较。
评测方法参考[OpenAI官方评测指南](https://developers.openai.com/api/docs/guides/evaluation-best-practices)，自动裁判仍需要人工校准。
