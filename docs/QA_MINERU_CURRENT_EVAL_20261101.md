# 当前MinerU组合版本：32题Jev评测

2026-11-01。新增32题独立答题，只用Jev原五维规则评分。正文/表格/公式小节补全、表格行检索、BGE重排、主命中候选统一预算全部启用；回答指引关闭。

32题答题状态：{'answered': 32}。首次有效Jev评分32/32；当前无标准答案疑点的有效题32题。无效评分不计零，不计算加权总分。

## 与历史PyMuPDF结构81块比较

| 版本 | 共同题 | 必答要点 | 事实完全支持 | 单条引用有效 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 历史PyMuPDF81块 | 31 | 95.97% | 100.00% | 97.69% | 96.75% | 1.935 | 22/31 |
| 当前MinerU113块组合 | 31 | 95.43% | 97.66% | 98.48% | 98.44% | 1.903 | 22/31 |

此为历史结果复用对比，未为旧版重新答题或评分。共同题排除缺失/参考标准被标记的评分；日期、远端模型别名与随机输出等变化未完全控制，不能把差异归因于单独某项优化，也不能据一轮证明稳定提升。

排除：[{"baseline_reference_concern": null, "baseline_valid": false, "current_reference_concern": false, "current_valid": true, "task_id": "PFI2-023"}]

## 本轮全部有效题

| 版本 | 共同题 | 必答要点 | 事实完全支持 | 单条引用有效 | 引用组完整 | 边界/2 | 五项全达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 当前MinerU组合 | 32 | 94.53% | 97.69% | 98.51% | 98.46% | 1.875 | 22/32 |

上表与共同题对照分母可能不同；事实与引用的分母还会随实际陈述数量变化。五项全达标要求必答点全覆盖、陈述支持、适用引用/引用组达标及边界2分，不是新的加权分数。

## 逐题变化

- point_wins：无
- point_losses：PFI2-032
- joint_wins：PFI2-020, PFI2-024, PFI2-028
- joint_losses：PFI2-014, PFI2-029, PFI2-032

上述变化均取Jev首次有效原判；导出器没有替代模型打分。完整问题、参考标准、两版回答、引用与评分见HTML和JSONL。

## 用量和耗时

- 答题端到端中位耗时：12.90秒/题（含进程、检索、重排、生成）。
- 生成：{"calls": 32, "known_tokens": {"input_tokens": 240172, "output_tokens": 34638, "total_tokens": 274810}, "total_token_unknown_calls": 0}
- 重排：{"calls": 32, "known_tokens": {"input_tokens": 473958, "output_tokens": 0}, "total_token_unknown_calls": 32}
- 问题Embedding：{"calls": 32, "known_tokens": {"input_tokens": 1011, "output_tokens": 0, "total_tokens": 1011}, "total_token_unknown_calls": 0}
- Jev全部评分尝试及费用：{"calls": 32, "cost_unknown_calls": 0, "invoice_cost_usd": null, "known_tokens": {"input_tokens": 2450769, "output_tokens": 120002, "total_tokens": 2570771}, "reported_cost_usd": "0.102932298", "request_time_ms": 128733, "usage_unknown_calls": 0}
- 推理Token已包含在生成Token中，不重复相加。供应商没有返回的货币结算金额记为未知；Jev费用包含无效尝试。

## 封存与范围

答题源提交：`ba540a901089d816a647db5a284d9b957d54fb62`。从独立干净检出冻结代码、113块索引、原PDF、原32题及配置，未修改用户正在编辑的前端文件。每题新进程，不带历史回答、评分或参考答案；裁判使用原协议独立上下文，不接收旧分。

旧导入器的数据格式包含历史DSH答案，仅为兼容导入而复制；本轮只对新RAG答案创建32个Jev任务，没有新增DSH或Luna调用。网站默认配置及服务器均未切换。

[逐题HTML报告](../data/literature/qa-evaluation/reports/mineru-current-20261101/comparison.html)
[机器可读结果](../data/literature/qa-evaluation/reports/mineru-current-20261101/comparison.json)
