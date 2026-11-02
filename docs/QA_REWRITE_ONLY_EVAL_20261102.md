# MinerU仅改写检索与重排：同期对照评测

2026-11-02。两组各32次新答题：对照用原问题检索和重排，试验只用改写检索和重排。最终均回答原问题。只由Jev沿用原五维协议评分，回答指引关闭。

| 版本 | 共同题 | 必答要点 | 事实完全支持 | 单引有效 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 原问题检索与重排 | 32 | 94.01% | 99.24% | 98.53% | 96.97% | 1.844 | 20/32 |
| 仅改写检索与重排 | 32 | 94.79% | 98.31% | 97.64% | 98.31% | 1.844 | 19/32 |

有效评分：{'original': 32, 'rewrite': 32}；共同题排除：[]。无效不记零，不计算加权总分。

**结论：本轮没有表现出整体优势。** 必答要点约上升0.78个百分点，引用组完整率上升；事实支持与单引有效率下降，边界均分相同，全达标题数20→19。先保留实验开关，不切换网站默认配置。

32题中有0题首次生成输入完全一致，30题原文块集合变化；改写相对独立对照新增候选累计212题次/块，进入主命中的独有块为5题次/块。输入不同只能证明策略改变了材料或排列，仍不能排除回答生成和裁判随机性。

## 逐题变化

- point_wins：PFI2-011, PFI2-015, PFI2-018
- point_losses：PFI2-016, PFI2-024
- joint_wins：PFI2-011, PFI2-014, PFI2-025
- joint_losses：PFI2-016, PFI2-020, PFI2-024, PFI2-029

## 重点题核对

以下为评分后的代码、原文和答案核对，不是Jev生成的文字理由，也没有修改原分。

- PFI2-011：Jev把P1由0.5判为1；两版均给出非单调数值反例，具体要点边界可人工复核，不能直接称为新增证据带来的提升。
- PFI2-015：两版均已拿到3.33/1.77 N/mm与作者可能解释；Jev把混杂限制P3由0判为0.5，试验仍未完整说明不能全归因于浆种。
- PFI2-018：试验明确写出相对峰面积不是绝对含量，P3由0变1；两组原文块集合相同，属于组织/回答表达差异，未增加新的原文块。
- PFI2-016：试验列出纸页改善与零距抗张信息，但未明确完成不必同步提高的推断，P3由1变0.5；相关事实已在回答和证据中，不能归为原文完全未检索到。
- PFI2-024：试验漏答哪个因素贡献最大，以及论文没有独立贡献排序的限制，P3由1变0；需区分证据组织、生成遗漏和输入信息覆盖，不能只按分数确定原因。
- PFI2-013：改写擅自扩展到综述相关文献和多种机制，两条References文献条目进入主命中；新增主命中不必然是有效补证。
- PFI2-032：两组均未把含0.888的摘要送入最终证据，仍未指出摘要/正文冲突；该问题本轮没有修复。

## 无效评分

64份Jev评分全部首次有效，无无效评分、补评或排除题。

## 检索实际变化

```json
{
  "rewrite_statuses": {
    "rewritten": 32
  },
  "same_candidate_set": 0,
  "same_primary_order": 0,
  "same_final_sources": 2,
  "same_initial_generation_input": 0,
  "shared_candidate_occurrences": 1388,
  "rewrite_only_candidate_occurrences": 212,
  "rewrite_only_primary_occurrences": 5,
  "added_final_source_occurrences": 118,
  "removed_final_source_occurrences": 200,
  "changed_final_source_questions": [
    "PFI2-001",
    "PFI2-002",
    "PFI2-003",
    "PFI2-004",
    "PFI2-005",
    "PFI2-006",
    "PFI2-008",
    "PFI2-009",
    "PFI2-010",
    "PFI2-011",
    "PFI2-012",
    "PFI2-013",
    "PFI2-014",
    "PFI2-015",
    "PFI2-016",
    "PFI2-017",
    "PFI2-019",
    "PFI2-020",
    "PFI2-021",
    "PFI2-022",
    "PFI2-023",
    "PFI2-024",
    "PFI2-025",
    "PFI2-026",
    "PFI2-027",
    "PFI2-028",
    "PFI2-029",
    "PFI2-030",
    "PFI2-031",
    "PFI2-032"
  ],
  "note": "Counts are question/source occurrences, not paper chunks deleted or proof that required evidence improved.",
  "point_changes_with_same_initial_generation_input": []
}
```

候选、主命中和最终原文是三个阶段；新增候选不等于补到必需证据。不同原文块的数量按题累计，同一块在多题出现会重复计数。新增/独有块由独立对照组候选与试验组候选比较计算，试验内部没有隐藏的原问题检索。完整改写、候选预算、增减块和逐题回答在HTML与JSONL。

## 耗时和用量

- 原问题检索与重排：端到端中位15.68秒/题。
  - 各环节：{"currency_costs": {"generation": null, "query_rewrite": null, "question_embedding": null, "rerank": null}, "generation": {"calls": 36, "known_tokens": {"input_tokens": 273104, "output_tokens": 37025, "total_tokens": 310129}, "total_token_unknown_calls": 0}, "median_end_to_end_seconds": 15.6805, "outcomes": {"answered": 32}, "query_rewrite": {"calls": 0, "known_tokens": {}, "total_token_unknown_calls": 0}, "question_embedding": {"calls": 32, "known_tokens": {"input_tokens": 1011, "output_tokens": 0, "total_tokens": 1011}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 473958, "output_tokens": 0}, "total_token_unknown_calls": 32}, "returned_generation_models": {"deepseek-flash": 36}, "returned_rewrite_models": {}, "sum_end_to_end_seconds": 521.12}
  - Jev：{"calls": 32, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2441206, "output_tokens": 119690, "total_tokens": 2560896}, "reported_cost_usd": "0.102530652", "request_time_ms": 124338, "usage_unknown_calls": 0}
- 仅改写检索与重排：端到端中位16.87秒/题。
  - 各环节：{"currency_costs": {"generation": null, "query_rewrite": null, "question_embedding": null, "rerank": null}, "generation": {"calls": 32, "known_tokens": {"input_tokens": 208049, "output_tokens": 31733, "total_tokens": 239782}, "total_token_unknown_calls": 0}, "median_end_to_end_seconds": 16.872999999999998, "outcomes": {"answered": 32}, "query_rewrite": {"calls": 32, "known_tokens": {"input_tokens": 8054, "output_tokens": 2305, "total_tokens": 10359}, "total_token_unknown_calls": 0}, "question_embedding": {"calls": 32, "known_tokens": {"input_tokens": 2476, "output_tokens": 0, "total_tokens": 2476}, "total_token_unknown_calls": 0}, "questions": 32, "rerank": {"calls": 32, "known_tokens": {"input_tokens": 541867, "output_tokens": 0}, "total_token_unknown_calls": 32}, "returned_generation_models": {"deepseek-flash": 32}, "returned_rewrite_models": {"deepseek-flash": 32}, "sum_end_to_end_seconds": 566.169}
  - Jev：{"calls": 32, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2321161, "output_tokens": 109022, "total_tokens": 2430183}, "reported_cost_usd": "0.097488762", "request_time_ms": 120194, "usage_unknown_calls": 0}
- 本轮无额外付费接口探测。推理Token已包含在生成Token内；每组每题各一次问题Embedding。未返回的供应商货币费用为未知，不能当成免费。

## 控制变量与限制

答题源提交97866ec512107e505de8f802be62dd8448350d4b，两组同代码、同113块索引及原PDF，唯一配置策略差异为是否启用仅改写检索和重排。两组新答题，不复用历史答案。本轮同时改变检索和重排输入，不能区分两项各自贡献。每题独立进程，仅输入问题与论文库，不包含标准答案；每个Jev请求独立组装，不包含另一组答案或旧评分。

两组并行启动、各自按题序执行；网络和远端模型随机性无法冻结。一轮开发集结果不能证明稳定性或新论文泛化。单题变化还需结合候选/最终证据和重复实验判断，不能只看得分归因。原DSH答案仅为兼容旧导入格式而复制，本轮没有新DSH/Luna调用。网站默认配置与服务器未切换。

[方法](QA_REWRITE_ONLY_METHOD_20261102.md)
[32题两组答案、Jev原判与检索变化](../data/literature/qa-evaluation/reports/rewrite-only-20261102/comparison.html)
