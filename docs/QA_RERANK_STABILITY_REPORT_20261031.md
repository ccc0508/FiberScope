# RAG候选重排稳定性：两版各三轮

保留历史第1轮，两版各新增2轮。原32题中，六个版本×轮次组合固定共同有效题30题。

本次重复没有证明重排稳定优于纯向量：固定30题，重排要点分较高1轮、较低2轮、相同0轮；三轮平均差值-0.56个百分点。

本次三轮中，重排版在第32题持续漏掉摘要与正文的数值冲突，三轮要点均为83.33%；纯向量版该题三轮要点均满分。第25题重排版新增两轮要点分别为0与0.5，其中第3轮是引用校验失败后的程序拒答。

重排版在第11题三轮要点均被Jev判为满分，纯向量版均明显失分；但第1轮的数值反例要点可能被高估。统一排除第11题后，三轮平均要点差值进一步转为重排低3.45个百分点，不能据该单题宣称整体收益。

保留重排功能为可选实验开关，当前不切换默认网站配置。下一步应检查重排是否挤掉冲突证据，以及回答遗漏要点和引用校验失败；本轮不修改这些环节。

主比较使用固定共同题；缺失不记零，不计算加权总分。三轮等权均值与样本SD是描述统计，不是置信区间。

| 指标 | 纯向量均值±样本SD；范围 | 重排均值±样本SD；范围 | 逐轮差值均值±样本SD；范围 |
| --- | --- | --- | --- |
| 必答要点 | 93.98% ± 0.98%；93.06%—95.00%（3轮） | 93.43% ± 4.18%；89.44%—97.78%（3轮） | -0.56% ± 5.14%；-5.56%—4.72%（3轮） |
| 事实完全支持 | 98.53% ± 0.46%；98.25%—99.06%（3轮） | 98.84% ± 0.54%；98.21%—99.21%（3轮） | 0.31% ± 0.44%；-0.03%—0.82%（3轮） |
| 单条引用有效 | 97.85% ± 0.45%；97.50%—98.36%（3轮） | 98.15% ± 0.57%；97.50%—98.56%（3轮） | 0.29% ± 0.67%；-0.19%—1.06%（3轮） |
| 引用组完整 | 96.13% ± 0.48%；95.61%—96.55%（3轮） | 97.38% ± 1.60%；95.54%—98.43%（3轮） | 1.25% ± 1.19%；-0.08%—2.20%（3轮） |
| 边界 / 2 | 1.878 ± 0.038；1.833—1.900（3轮） | 1.844 ± 0.107；1.767—1.967（3轮） | -0.033 ± 0.145；-0.133—0.133（3轮） |
| 五项全部达标率 | 65.56% ± 1.92%；63.33%—66.67%（3轮） | 67.78% ± 7.70%；63.33%—76.67%（3轮） | 2.22% ± 6.94%；-3.33%—10.00%（3轮） |

百分比指标的SD与差值以“百分点”理解。

## 同一固定题集的逐轮结果

| 轮次 | 纯向量要点 | 重排要点 | 差值/百分点 | 纯向量全达标 | 重排全达标 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 93.06% | 97.78% | +4.72 | 20/30 | 23/30 |
| 2 | 95.00% | 89.44% | -5.56 | 20/30 | 19/30 |
| 3 | 93.89% | 93.06% | -0.83 | 19/30 | 19/30 |

各轮最大配对仅作补充，不用其不同题集计算波动。

## 第1轮最大配对

共同有效30题。

| 版本 | 题数 | 必答要点 | 事实支持 | 单条引用 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 85块纯向量排序 | 30 | 93.06% | 98.25% | 98.36% | 95.61% | 1.833 | 20/30 (66.67%) |
| 85块＋候选重排 | 30 | 97.78% | 98.21% | 98.37% | 95.54% | 1.967 | 23/30 (76.67%) |

排除：[{"task_id": "PFI2-023", "excluded_cells": [{"system": "rerank", "round": 1, "reason": "invalid_scorecard"}]}, {"task_id": "PFI2-024", "excluded_cells": [{"system": "content", "round": 1, "reason": "invalid_scorecard"}]}]。

## 第2轮最大配对

共同有效32题。

| 版本 | 题数 | 必答要点 | 事实支持 | 单条引用 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 85块纯向量排序 | 32 | 94.79% | 99.12% | 96.92% | 95.61% | 1.844 | 20/32 (62.50%) |
| 85块＋候选重排 | 32 | 89.06% | 99.27% | 98.67% | 98.54% | 1.781 | 20/32 (62.50%) |

排除：[]。

## 第3轮最大配对

共同有效32题。

| 版本 | 题数 | 必答要点 | 事实支持 | 单条引用 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 85块纯向量排序 | 32 | 93.23% | 97.64% | 97.89% | 96.06% | 1.875 | 19/32 (59.38%) |
| 85块＋候选重排 | 32 | 93.49% | 99.18% | 97.01% | 98.36% | 1.781 | 20/32 (62.50%) |

排除：[]。

## 第11题敏感性分析

从固定共同题统一移除第11题后剩29题。原分不改，不替换主比较。

要点逐轮差值：{"values": [0.014367816091954033, -0.08333333333333337, -0.034482758620689724], "n": 3, "mean": -0.03448275862068969, "sample_sd": 0.0488505747126437, "minimum": -0.08333333333333337, "maximum": 0.014367816091954033, "range": 0.0977011494252874}。

## 耗时与费用

| 版本 | 第1轮中位秒 | 第2轮中位秒 | 第3轮中位秒 | 三轮中位数的平均/秒 |
| --- | ---: | ---: | ---: | ---: |
| 85块纯向量排序 | 13.23 | 15.83 | 15.20 | 14.75 |
| 85块＋候选重排 | 19.92 | 16.74 | 16.77 | 17.81 |

新增Jev请求129次，API报告费用$0.370381284，费用未知0次。历史请求未重做，历史费用另存。

延迟使用每轮全部题，质量使用固定共同题。未知费用保留未知；输入/输出用量按原记录，不推测货币价格。

## 解释边界

主比较在六个版本×轮次组合均有有效、无参考答案疑问的固定共同题上计算。各轮最大配对另列，不用于计算跨轮波动。

均值为三轮指标等权平均，SD为轮次间样本标准差；这是重复运行的描述统计，不是置信区间、统计显著性或新论文泛化证明。

同一32题为开发集；重复生成和一次首个有效Jev判定混合了回答与裁判波动，没有单独识别两者贡献。

第一轮为历史运行；新增两轮采用按题近同时运行两版，调度、缓存、网络和远端服务变化会影响延迟与用量。

未知费用不记零；推理Token已包含于生成Token，不再重复相加。所有语义分数保留Jev原判定，不生成新的裁判理由。

原轮1第11题未明确列出所要求的4000→8000转数值反例却被Jev判为满分，存在高估可能；原分不改。统一移除第11题的敏感性分析不替换主比较，也不能替代专家核验。

历史第1轮85块纯向量排序的PFI2-024无有效评分，继续保留为缺失，不重评、不记零。

历史第1轮85块＋候选重排的PFI2-023无有效评分，继续保留为缺失，不重评、不记零。

Only Jev original, first-valid judgments are used; invalid/missing grades remain null, never zero. No weighted grand score is calculated.

Historical round 1 content PFI2-024 and rerank PFI2-023 have no valid Jev judgment; these answers are not regraded.

Historical rerank PFI2-011 may be overestimated by Jev: the answer does not explicitly give the required 4000→8000 revolution numeric counterexample. Original labels are retained.

Round 1 consists of separate sequential historical runs started on 2026-10-30. New rounds run the two systems concurrently for each question in independent processes, waiting for each pair, round 2 before round 3.

Dates, scheduling, provider caching, network and remote service state can affect runtime and token usage. Summed question seconds are not elapsed experiment wall time.

Remote model aliases and identical settings do not prove unchanged provider weights or bitwise reproducibility.

Three rounds on the same 32 development questions give descriptive variation only; no statistical significance or new-paper generalization is claimed. Answer and judge variability are not separately identified.

API-reported judge costs are not invoices. Failed requests and missing usage/cost remain unknown; answering, embedding and rerank actual money costs are unknown. Reasoning tokens are already included in generation tokens.

Offline collection compares sealed configuration probes; it does not read credentials or rerun the live configuration probe.

Round 3 rerank PFI2-025 returned a production refusal after citation validation failure. The original answer/status is preserved and graded, not regenerated; a reader-only adapter accepts the existing refused status without changing the judge harness.

[全部32题、六份回答与原Jev判定](../data/literature/qa-evaluation/reports/rerank-stability-20261031/comparison.html)。
[完整计算、用量、控制变量与来源指纹](../data/literature/qa-evaluation/reports/rerank-stability-20261031/comparison.json)。
[实验方法与独立上下文说明](QA_RERANK_STABILITY_METHOD_20261031.md)。
