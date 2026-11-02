# MinerU查询改写：同期对照评测

2026-11-02。两组各32次新答题，分别使用原问题检索与原问题加一条改写。只由Jev沿用原五维协议评分，回答指引关闭。

| 版本 | 共同题 | 必答要点 | 事实完全支持 | 单引有效 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 原问题检索 | 30 | 95.83% | 98.26% | 95.93% | 98.26% | 1.900 | 21/30 |
| 原问题＋改写双路检索 | 30 | 96.11% | 99.14% | 100.00% | 100.00% | 1.867 | 25/30 |

有效评分：{'original': 31, 'rewrite': 31}；共同题排除：['PFI2-026', 'PFI2-027']。无效不记零，不计算加权总分。

32题中有27题首次生成输入完全一致；改写新增独有候选累计218题次/块，但进入主命中的独有块仅0题次/块。输入一致题的要点变化为['PFI2-004', 'PFI2-011', 'PFI2-015', 'PFI2-022']，这些变化不能归因于改写补到新证据。

## 逐题变化

- point_wins：PFI2-004, PFI2-011
- point_losses：PFI2-015, PFI2-022
- joint_wins：PFI2-004, PFI2-011, PFI2-024, PFI2-029
- joint_losses：无

## 无效评分

```json
[
  {
    "arm": "original",
    "task_id": "PFI2-027",
    "attempts": [
      {
        "attempt": 1,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "6990c429ca549e5ef152c8dca94d933352bca33493a2081c4b669baaa72ca03f",
        "response_sha256": "22958565db2f0bce8f9c6dfe59c85afc47e1b5d65040d1590cf4dfc49e6b7db4",
        "record_sha256": "081029b431442d103891673f2811b755681ef72ce726514c207d6cba825cb593",
        "usage": {
          "input_tokens": 76463,
          "output_tokens": 5268,
          "total_tokens": 81731,
          "reported_cost_usd": 0.003211446
        }
      },
      {
        "attempt": 2,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "6990c429ca549e5ef152c8dca94d933352bca33493a2081c4b669baaa72ca03f",
        "response_sha256": "ceb0a1cead2cb5441db828a2d1c3881ef0d7db029831db9f45da9366a7ef7b04",
        "record_sha256": "9789899da32b605b3aebc0182356c609fc2b1e63392d236842c3520b41625092",
        "usage": {
          "input_tokens": 76463,
          "output_tokens": 5268,
          "total_tokens": 81731,
          "reported_cost_usd": 0.003211446
        }
      },
      {
        "attempt": 3,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "6990c429ca549e5ef152c8dca94d933352bca33493a2081c4b669baaa72ca03f",
        "response_sha256": "d4db60edc713d62f8197df4c3071b3da794deb4aa42e8d96a2df258807afba0c",
        "record_sha256": "4a5f1a80fa718fc0914baeb40ada4806298b83d608069e06e5c1630c70fd5f17",
        "usage": {
          "input_tokens": 76463,
          "output_tokens": 5268,
          "total_tokens": 81731,
          "reported_cost_usd": 0.003211446
        }
      }
    ],
    "score": null
  },
  {
    "arm": "rewrite",
    "task_id": "PFI2-026",
    "attempts": [
      {
        "attempt": 1,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "54957a75c4bcfdfc4bf1b9a7f3e925543d8904714a4d7047435ce52c50e5d320",
        "response_sha256": "1725bcc0db8bd18094b1a4ffbee9314289528025b7d478f93feb2ef1e4e5ec67",
        "record_sha256": "9c8d78ac97d3092710634c76c100805ee708bbd72b8a8b114d00ff601ce066b6",
        "usage": {
          "input_tokens": 70597,
          "output_tokens": 3590,
          "total_tokens": 74187,
          "reported_cost_usd": 0.002965074
        }
      },
      {
        "attempt": 2,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "54957a75c4bcfdfc4bf1b9a7f3e925543d8904714a4d7047435ce52c50e5d320",
        "response_sha256": "9573c6b71cd91659e95478724a1324fb1009fd2b46f072dac20072b03158da52",
        "record_sha256": "dd6cc494f67ae9331a623732276e53d877aa804dabd0a9b219271a39ee202f45",
        "usage": {
          "input_tokens": 70597,
          "output_tokens": 3593,
          "total_tokens": 74190,
          "reported_cost_usd": 0.002965074
        }
      },
      {
        "attempt": 3,
        "status": "invalid_scorecard",
        "validation_message": "Group and citation decisions disagree",
        "request_sha256": "54957a75c4bcfdfc4bf1b9a7f3e925543d8904714a4d7047435ce52c50e5d320",
        "response_sha256": "874e1eede2e446d7e27f015bae36d2ca9f55f64e7238cf419e28c46324fe0a81",
        "record_sha256": "bd9020d517cb7e9dc7f189f5afce3f21875126537b90ccb09443335acc8fbcf6",
        "usage": {
          "input_tokens": 70597,
          "output_tokens": 3590,
          "total_tokens": 74187,
          "reported_cost_usd": 0.002965074
        }
      }
    ],
    "score": null
  }
]
```
单引与引用组判定矛盾属于裁判输出未通过一致性校验，不代表回答得零分。每份无效评分已尝试3次并封存，不改裁判原判；这些题的两组回答仍完整列出。

## 检索实际变化

```json
{
  "rewrite_statuses": {
    "rewritten": 32
  },
  "original_candidates_unchanged": 30,
  "same_primary_order": 21,
  "same_final_sources": 27,
  "same_initial_generation_input": 27,
  "shared_candidate_occurrences": 1382,
  "rewrite_only_candidate_occurrences": 218,
  "rewrite_only_primary_occurrences": 0,
  "added_final_source_occurrences": 7,
  "removed_final_source_occurrences": 24,
  "changed_final_source_questions": [
    "PFI2-006",
    "PFI2-017",
    "PFI2-021",
    "PFI2-029",
    "PFI2-032"
  ],
  "note": "Counts are question/source occurrences, not paper chunks deleted or proof that required evidence improved.",
  "point_changes_with_same_initial_generation_input": [
    "PFI2-004",
    "PFI2-011",
    "PFI2-015",
    "PFI2-022"
  ]
}
```

候选、主命中和最终原文是三个阶段；新增候选不等于补到必需证据。不同原文块的数量按题累计，同一块在多题出现会重复计数。完整两路query、候选预算、增减块和逐题回答在HTML与JSONL。

## 耗时和用量

- 原问题检索：端到端中位14.30秒/题。
  - 各环节：{"currency_costs": {"generation": null, "query_rewrite": null, "question_embedding": null, "rerank": null}, "generation": {"calls": 33, "known_tokens": {"input_tokens": 249090, "output_tokens": 33401, "total_tokens": 282491}, "total_token_unknown_calls": 0}, "median_end_to_end_seconds": 14.305, "outcomes": {"answered": 32}, "query_rewrite": {"calls": 0, "known_tokens": {}, "total_token_unknown_calls": 0}, "question_embedding": {"calls": 32, "known_tokens": {"input_tokens": 1011, "output_tokens": 0, "total_tokens": 1011}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 473744, "output_tokens": 0}, "total_token_unknown_calls": 32}, "returned_generation_models": {"deepseek-flash": 33}, "returned_rewrite_models": {}, "sum_end_to_end_seconds": 498.504}
  - Jev：{"calls": 34, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2569757, "output_tokens": 124434, "total_tokens": 2694191}, "reported_cost_usd": "0.107929794", "request_time_ms": 123935, "usage_unknown_calls": 0}
- 原问题＋改写双路检索：端到端中位17.76秒/题。
  - 各环节：{"currency_costs": {"generation": null, "query_rewrite": null, "question_embedding": null, "rerank": null}, "generation": {"calls": 33, "known_tokens": {"input_tokens": 239649, "output_tokens": 34519, "total_tokens": 274168}, "total_token_unknown_calls": 0}, "median_end_to_end_seconds": 17.759, "outcomes": {"answered": 32}, "query_rewrite": {"calls": 32, "known_tokens": {"input_tokens": 8054, "output_tokens": 2073, "total_tokens": 10127}, "total_token_unknown_calls": 0}, "question_embedding": {"calls": 64, "known_tokens": {"input_tokens": 3229, "output_tokens": 0, "total_tokens": 3229}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 470921, "output_tokens": 0}, "total_token_unknown_calls": 32}, "returned_generation_models": {"deepseek-flash": 33}, "returned_rewrite_models": {"deepseek-flash": 32}, "sum_end_to_end_seconds": 572.453}
  - Jev：{"calls": 34, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2549727, "output_tokens": 121984, "total_tokens": 2671711}, "reported_cost_usd": "0.107088534", "request_time_ms": 124467, "usage_unknown_calls": 0}
- 额外接口探测：{"calls": 2, "known_tokens": {"input_tokens": 500, "output_tokens": 113, "total_tokens": 613}, "total_token_unknown_calls": 0}。首次手工探测的中文被Shell编码损坏，原始请求保留、不计入正式题目。
- 推理Token已包含在生成Token内；两次问题Embedding逐次计数。未返回的供应商货币费用为未知，不能当成免费。

## 控制变量与限制

答题源提交946b1cfa1c5fd448b05f5a8ac88e4620c2baca15，两组同代码、同113块索引及原PDF，唯一配置差异为查询改写开关。两组新答题，不复用历史答案。每题独立进程，仅输入问题与论文库，不包含标准答案；每个Jev请求独立组装，不包含另一组答案或旧评分。

两组并行启动、各自按题序执行；网络和远端模型随机性无法冻结。一轮开发集结果不能证明稳定性或新论文泛化。单题变化还需结合候选/最终证据和重复实验判断，不能只看得分归因。原DSH答案仅为兼容旧导入格式而复制，本轮没有新DSH/Luna调用。网站默认配置与服务器未切换。

[方法](QA_QUERY_REWRITE_METHOD_20261102.md)
[32题两组答案、Jev原判与检索变化](../data/literature/qa-evaluation/reports/query-rewrite-20261102/comparison.html)
