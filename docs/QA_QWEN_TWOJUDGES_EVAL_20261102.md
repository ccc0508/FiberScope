# Qwen文字版重跑：Jev与Luna双裁判

2026-11-02。MinerU 113块、Qwen3-VL-Embedding、双路查询、原问题重排与统一补全；图片和回答指引关闭。32题全部重新回答一次，同一份最终回答由Jev与Luna独立评分，旧答案不覆盖。

共同有效且无标准疑点的题目：32/32。有效评分：{"jev": 32, "luna": 32}。

| 裁判 | 共同题 | 必答要点 | 事实支持 | 单引有效 | 引用组完整 | 边界/2 | 全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Jev | 32 | 90.89% | 98.46% | 97.79% | 98.46% | 1.812 | 17/32 |
| Luna | 32 | 90.62% | 97.71% | 99.28% | 96.18% | 1.625 | 18/32 |

不计算加权总分；比例分母随实际陈述/引用数量变化。主表使用同一组共同有效题，缺失不记零；每位裁判各自全量有效题另保存在JSON中。

## 结果解读

以下为对已保存回答、诊断及裁判原判的报告解读，不是新的评分，未修改任何裁判标签。

- 两位裁判的要点均约91%，但全达标仅17/32和18/32。事实有依据与完整回答所有要求并不是一回事；不据此合成总分。
- 第16题两位都认为缺少或仅部分表达“纸页变强不等于单根纤维必然变强”的限制；首次生成输入与上轮相同。
- 第28题只总结了PFI论文，没有明确声明另一篇Non-Wood Fibers论文未在库中、无法做两篇比较，两位都判必答要点0、边界0；首次输入与上轮相同。
- 第32题仍漏摘要0.888与正文0.912的冲突，两位对该必答点均给部分覆盖；本轮正常返回不代表该问题已解决。
- 第22题氢键相对含量23.56/34.92没有写百分号；Jev给数值要点部分覆盖、Luna给完整，但Luna对回答边界更严格。这是评分分歧，报告不代替裁判改分。
- 第25题本轮明确说所给证据缺8000转BET值。Jev给完整要点，Luna只给部分覆盖；原判与Luna理由均保留。
- 第10题第一次草稿的claims已带引用，但未展示的answer摘要缺引用标记，触发missing_answer_reference；第二次成功。该诊断定位了格式问题，不是检索证据不足。

本轮重新答题并重新评分；与上轮的涨跌包含生成、重排及裁判变化。新增诊断本身未改变校验规则，不把分数变化归因于诊断功能。

## 与上轮Qwen的Jev比较

| 版本 | 共同题 | 必答要点 | 事实支持 | 单引有效 | 引用组完整 | 边界/2 | 全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| previous_jev | 31 | 92.74% | 99.24% | 99.28% | 97.71% | 1.839 | 22/31 |
| current_jev | 31 | 91.13% | 98.43% | 97.74% | 98.43% | 1.839 | 17/31 |

Previous Qwen and new Qwen with newly generated answers and new Jev judgments, not an embedding change or a controlled judge-repeat-only test.

```json
{
  "point_wins": [
    "PFI2-025"
  ],
  "point_losses": [
    "PFI2-016",
    "PFI2-022",
    "PFI2-028"
  ],
  "joint_wins": [
    "PFI2-025",
    "PFI2-027"
  ],
  "joint_losses": [
    "PFI2-010",
    "PFI2-014",
    "PFI2-016",
    "PFI2-022",
    "PFI2-024",
    "PFI2-028",
    "PFI2-030"
  ]
}
```

32题中27题首次生成输入与上轮完全相同。改写沿用封存结果，无新增改写API费用。

## 两裁判分歧

```json
{
  "tasks": {
    "key_points": [
      "PFI2-007",
      "PFI2-011",
      "PFI2-016",
      "PFI2-020",
      "PFI2-022",
      "PFI2-024",
      "PFI2-025",
      "PFI2-031"
    ],
    "claim_support": [
      "PFI2-024",
      "PFI2-030",
      "PFI2-032"
    ],
    "citation_support": [
      "PFI2-010",
      "PFI2-026",
      "PFI2-030"
    ],
    "citation_group_coverage": [
      "PFI2-014",
      "PFI2-024",
      "PFI2-026",
      "PFI2-029",
      "PFI2-030"
    ],
    "answerability": [
      "PFI2-004",
      "PFI2-015",
      "PFI2-022",
      "PFI2-024",
      "PFI2-025",
      "PFI2-029"
    ]
  },
  "counts": {
    "key_points": 9,
    "claim_support": 3,
    "citation_support": 3,
    "citation_group_coverage": 5,
    "answerability": 6
  }
}
```

上述为原生标签分歧计数，包含纯范围陈述中最终可能不计入事实引用指标的原生选择，不等于最终分数差。完整逐项原判和Luna理由见HTML。分歧不自动由报告作者裁决，不取两裁判较高分。

## 引用校验诊断

共33次引用校验，1次失败。
规则计数：{"missing_answer_reference": 1}

每次只记录首先触发的规则。失败草稿与最终回答分开保存，不送进裁判上下文；旧第27/32题草稿仍不可恢复，本轮是新的独立生成。

## 用量和耗时

答题：{"cached_rewrite_replays": 32, "generation": {"calls": 33, "known_tokens": {"input_tokens": 237853, "output_tokens": 34946, "total_tokens": 272799}, "total_token_unknown_calls": 0}, "image_tokens": 0, "median_end_to_end_seconds": 14.891, "median_question_embedding_seconds": 0.52, "monetary_costs": {"embedding": null, "generation": null, "rerank": null}, "outcomes": {"answered": 32}, "question_embedding": {"calls": 64, "known_tokens": {"input_tokens": 4472, "total_tokens": 4472}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 450107, "output_tokens": 0}, "total_token_unknown_calls": 32}, "rewrite_api_calls_during_answers": 0, "timing_note": "End-to-end excludes offline shared-query preparation; not comparable to live-rewrite historical timing."}
- Jev：{"calls": 32, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2416251, "output_tokens": 118024, "total_tokens": 2534275}, "reported_cost_usd": "0.101482542", "request_time_ms": 110472, "usage_unknown_calls": 0}
- Luna：{"calls": 34, "cost_unknown_calls": 1, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2086666, "output_tokens": 64397, "total_tokens": 2151063}, "reported_cost_usd": "0.293029275", "request_time_ms": 822632, "usage_unknown_calls": 1}

端到端时间不含上轮已生成的改写；推理Token已包含在生成Token，不重复相加。供应商未返回的金额记未知，裁判费用包含无效尝试。

## 排除与范围

```json
{
  "exclusions": [],
  "failed_grades": []
}
```

仅一篇论文的开发题；本轮验证诊断记录并比较两裁判，不据此宣称Embedding稳定提升。网站默认配置和服务器均未切换。

[逐题HTML、两裁判原判及失败草稿](../data/literature/qa-evaluation/reports/qwen-twojudges-20261102-r2/comparison.html)
[方法](QA_QWEN_TWOJUDGES_METHOD_20261102.md)
