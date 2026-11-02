# 新Embedding模型：BGE与Qwen控制变量评测

2026-11-02。只比较文字Embedding，图片关闭；两组复用相同检索改写，各新答32题，Jev沿用原五维协议。

| 版本 | 共同题 | 必答要点 | 事实支持 | 单引有效 | 引用组完整 | 边界/2 | 全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BGE-M3 · 1024维 | 31 | 89.25% | 96.75% | 98.46% | 95.93% | 1.806 | 22/31 |
| Qwen3-VL · 2560维（文字输入） | 31 | 92.74% | 99.24% | 99.28% | 97.71% | 1.839 | 22/31 |

有效评分：{'bge': 32, 'qwen': 31}；共同题排除['PFI2-023']。无效评分不记零，不算加权总分。

## 结果解读

共同31题，要点提高3.49个百分点；五项全达标BGE为22题，Qwen为22题。本轮略好，但未证明文字检索稳定领先。

以下为报告对保存的回答、运行诊断及Jev原判的解读，不是Jev生成的文字理由，也不更改模型分数。

- PFI2-004：首次输入完全相同。两版均给63/57 °SR并列作用力条件；Jev把Qwen的条件限制要点评为部分覆盖。属于措辞/裁判敏感性，不能归因于新检索。
- PFI2-015：两版都找到纤维长度变化及较低作用力的解释，但都未明确说不能全部归因于浆种；Jev对这项限制分别判缺失/部分。没有证明补到了新的关键事实。
- PFI2-020：首次输入完全相同，要点均全覆盖。Qwen回答的陈述及引用组获全支持；BGE多写的一项free OH解释被判部分支持。
- PFI2-024：首次输入完全相同，要点均全覆盖。BGE有一条额外机制陈述被判部分支持；Qwen的表达全部获支持，属于生成表述差异。
- PFI2-025：两版都拿到补充表线索。Qwen列了Table S1与定性趋势，却没有明确说明当前证据缺少8000转的精确BET值，必答点从1降为0；并非提供了错误数值。
- PFI2-026：两版均无逐次重复实验数据。Qwen明确限定为所给证据未提供，获得完整要点；BGE措辞与引用组获部分支持。未证明原始数据召回增加。
- PFI2-027：首次输入完全相同。BGE两次生成后引用校验失败并返回统一拒答；Qwen回答可答部分并声明耐破/撕裂数据缺失。不能把此增分算作召回收益。
- PFI2-032：BGE两次生成后引用校验失败；Qwen纠正0.919/0.925的对象并给正文0.912/0.889，但仍漏摘要0.888及冲突，只获部分要点。不能视为已解决冲突检索。

要点差异的算术分解：{"baseline_citation_failure_questions_percentage_points": 5.913978494623656, "note": "Arithmetic decomposition, not causal attribution; keep all these questions in the primary paired result.", "other_questions_percentage_points": -2.4193548387096806, "total_percentage_points": 3.4946236559139754}
第27/32题对总差异贡献较大，但含生成/校验失败，不能据此认定检索能力提高。主表仍保留这两题，没有事后删题抬分。

保留候选，不据此替换网站默认版本。先补图像题单独核验多模态收益；文字部分优先定位引用校验拒答、缺数据声明及摘要/正文冲突漏检。

## 逐题变化

- point_wins：PFI2-015, PFI2-026, PFI2-027, PFI2-032
- point_losses：PFI2-004, PFI2-025
- joint_wins：PFI2-020, PFI2-024
- joint_losses：PFI2-004, PFI2-025

32题中20题首次生成输入完全相同，这类题的分数变化不能归因于Embedding补到了新材料。

## 检索变化与参考原文覆盖

```json
{
  "retrieval": {
    "shared_queries_identical": true,
    "same_primary_order": 20,
    "same_initial_generation_input": 20,
    "stage_changes": {
      "candidates": {
        "same_set": 0,
        "added_occurrences": 391,
        "removed_occurrences": 391
      },
      "primary": {
        "same_set": 24,
        "added_occurrences": 8,
        "removed_occurrences": 8
      },
      "final": {
        "same_set": 22,
        "added_occurrences": 23,
        "removed_occurrences": 33
      }
    },
    "point_changes_with_same_initial_input": [
      "PFI2-004",
      "PFI2-027"
    ]
  },
  "reference_coverage": {
    "bge": {
      "exact_reference_occurrences": 23,
      "stages": {
        "candidates": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        },
        "primary": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        },
        "final": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        }
      },
      "excluded_occurrences": 24,
      "scope": "Exact aligned reference source-interval coverage, not semantic evidence sufficiency or whole-benchmark recall."
    },
    "qwen": {
      "exact_reference_occurrences": 23,
      "stages": {
        "candidates": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        },
        "primary": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        },
        "final": {
          "numerator": 22,
          "denominator": 23,
          "value": 0.9565217391304348
        }
      },
      "excluded_occurrences": 24,
      "scope": "Exact aligned reference source-interval coverage, not semantic evidence sufficiency or whole-benchmark recall."
    }
  },
  "alignment_statuses": {
    "located": 11,
    "review_required": 15,
    "unresolved": 2
  }
}
```

覆盖率只统计在MinerU源文本中精确对齐的参考原文区间，按每题所需参考片段计数。近似/待复核和未定位片段排除且不记零。这是原文位置覆盖诊断，不等于证据已足够回答，也不代表全部题目的语义召回率。新增/删除块按题累计，不是删改数据库原文。

## 用量与耗时

共享改写准备：{"cache_sha256": "4c393104465899f3c20bea3f936172657d4240f747a77ef588aa66edf7d589e0", "currency_cost": null, "median_request_seconds": 1.236, "statuses": {"completed": 32}, "sum_request_seconds": 39.017, "usage": {"calls": 32, "known_tokens": {"input_tokens": 8054, "output_tokens": 2240, "total_tokens": 10294}, "total_token_unknown_calls": 0}}
- BGE-M3 · 1024维：端到端中位13.84秒/题，问题Embedding合计中位1.327秒/题。
  - 运行用量：{"cached_rewrite_replays": 32, "generation": {"calls": 36, "known_tokens": {"input_tokens": 260848, "output_tokens": 36365, "total_tokens": 297213}, "total_token_unknown_calls": 0}, "image_tokens": 0, "median_end_to_end_seconds": 13.842500000000001, "median_question_embedding_seconds": 1.3265, "monetary_costs": {"embedding": null, "generation": null, "rerank": null}, "outcomes": {"answered": 30, "refused": 2}, "question_embedding": {"calls": 64, "known_tokens": {"input_tokens": 3428, "output_tokens": 0, "total_tokens": 3428}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 470379, "output_tokens": 0}, "total_token_unknown_calls": 32}, "rewrite_api_calls_during_answers": 0, "timing_note": "End-to-end excludes offline shared-query preparation; not comparable to live-rewrite historical timing."}
  - Jev评分：{"calls": 32, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2378601, "output_tokens": 113942, "total_tokens": 2492543}, "reported_cost_usd": "0.099901242", "request_time_ms": 117875, "usage_unknown_calls": 0}
- Qwen3-VL · 2560维（文字输入）：端到端中位15.46秒/题，问题Embedding合计中位0.556秒/题。
  - 运行用量：{"cached_rewrite_replays": 32, "generation": {"calls": 33, "known_tokens": {"input_tokens": 242408, "output_tokens": 35661, "total_tokens": 278069}, "total_token_unknown_calls": 0}, "image_tokens": 0, "median_end_to_end_seconds": 15.4575, "median_question_embedding_seconds": 0.556, "monetary_costs": {"embedding": null, "generation": null, "rerank": null}, "outcomes": {"answered": 32}, "question_embedding": {"calls": 64, "known_tokens": {"input_tokens": 4472, "total_tokens": 4472}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 450107, "output_tokens": 0}, "total_token_unknown_calls": 32}, "rewrite_api_calls_during_answers": 0, "timing_note": "End-to-end excludes offline shared-query preparation; not comparable to live-rewrite historical timing."}
  - Jev评分：{"calls": 34, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2606832, "output_tokens": 129886, "total_tokens": 2736718}, "reported_cost_usd": "0.109486944", "request_time_ms": 127956, "usage_unknown_calls": 0}

端到端不含预先生成改写的耗时；改写一次计费、两组回放不再计费。不要与之前实时改写的耗时直接比较。推理Token已含在生成Token内，未返回金额保持未知。

## 无效评分

```json
[
  {
    "arm": "qwen",
    "task_id": "PFI2-023",
    "attempts": [
      {
        "attempt": 1,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "record_sha256": "bfea0a9f12668b97443e2e6833f5add3dbdd1a3551ac9d9ce25c302dee07da6b",
        "usage": {
          "input_tokens": 70127,
          "output_tokens": 2741,
          "total_tokens": 72868,
          "reported_cost_usd": 0.002945334
        }
      },
      {
        "attempt": 2,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "record_sha256": "e19cc77dccea6f8d09df4c7230135858893a00e6870f84eca1c86670d43ea7e7",
        "usage": {
          "input_tokens": 70127,
          "output_tokens": 2741,
          "total_tokens": 72868,
          "reported_cost_usd": 0.002945334
        }
      },
      {
        "attempt": 3,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "record_sha256": "0c56db70299b08243e08c27e925f7cd78bfd1aa266b1ef0f694714688c73601e",
        "usage": {
          "input_tokens": 70127,
          "output_tokens": 2741,
          "total_tokens": 72868,
          "reported_cost_usd": 0.002945334
        }
      }
    ],
    "score": null
  }
]
```

本轮未重复入库Embedding；这里的Token仅统计新问题与本轮运行。此前索引重建的用量不混入本轮答题成本。

## 结论的适用范围

本轮比较同一113块、20条表格行、相同query和原BGE重排下的模型替换，不包含图片。仅一轮开发集结果，不证明稳定性或新论文泛化；0.35未针对Qwen校准，不代表两模型最佳能力。两组均新答、独立进程，裁判不看另一组答案、模型身份或旧分数。网站和启用图片的MinerU候选配置均未切换。

[方法](QA_EMBEDDING_METHOD_20261102.md)
[32题逐题回答、Jev原判与检索对照](../data/literature/qa-evaluation/reports/embedding-20261102/comparison.html)
