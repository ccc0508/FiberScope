# 回答模型对照：GPT-6 Astra 与 DeepSeek Flash

本轮按用户要求测试 GPT-6 Astra，保留当前 MinerU、千问多模态 Embedding、原图输入、查询改写、重排及小节补全。服务端模型目录已确认 `gpt-6-astra`；不使用用户粘贴配置中的另一个型号 `gpt-5.5`。两侧推理档位均为 high；不同厂商的 high 不表示相等计算量。

## 固定条件

- 同一份原始 PDF、同一套 32 道 core_text 题，逐题独立进程，无前题上下文。
- 先以当前含原图的 MinerU＋Qwen3-VL 库检索，复用已冻结的原问题／改写查询。然后让两个回答模型使用完全相同的最终证据文本、顺序、引用编号和原图字节。
- DeepSeek 对照只回放源材料，不读取 GPT 答案、参考答案或评分。回放文件独立封存并记录摘要；不重复支付 Embedding、重排和查询改写调用。
- 查询改写独立使用原有 DeepSeek 配置，更换回答模型不会改变查询模型或向其他厂商发送其密钥。
- 保留每题最多两次生成及原有引用校验；不启用完整性指引，不添加针对题目的提示。
- GPT 使用 Responses API、结构化输出、`store=false`；DeepSeek 使用原有 Chat Completions JSON 输出。接口协议不同，但业务提示、证据和引用校验规则相同；这些适配差异属于本轮模型替换的实际效果。

## 评分和复核

外部评分仅使用 Jev，沿用 `qa-system-five-v1`：必答要点、事实支持、单条引用、引用组覆盖、回答边界。无加权总分。原始评分首个有效结果保留，协议无效／请求失败最多三次，全部尝试保留；失败不计零分。

用户指定最终以 Codex 复核为准。原始 Jev 评分不会覆盖，复核另存：检查参考答案、真实回答、实际引用原文及论文证据；对无法评分的条目补齐，发现过严或过宽之处逐项记录原值、最终值、理由与依据。复核是 Codex 审阅，不称为人工专家金标准。两组均适用相同规则，不能只纠正 GPT 一侧。

原图在本轮回答时真实提供。Jev 当前仍接收原有文字评分包，不直接读取图片像素；若出现仅能由图片判断的陈述，由 Codex 查看相应原图后复核，不能将 Jev 的文字判断冒充图像审核。

## 运行与记录

私有配置 `.rag-data/configs/answer-model-{astra,deepseek}-20261102.env`，全部被 Git 忽略。密钥和鉴权头不写入公开报告。公网网站配置保持原样，本轮为独立实验，不自动部署。

运行入口：`scripts/evaluate_answer_models_20261102.py`，依次 prepare、answers（astra）、seal-replay、answers（deepseek）、prepare-grading、grade。同一结果完成后不自动重跑；被中断的付费请求需先核查。

过程和原始数据保存在 `.rag-data/evaluations/answer-models-20261102` 及两个 `pfi-answer-*-20261102` 目录。正式结果待本轮运行、Jev 评分和复核完成后追加，历史报告保持不变。

接口依据：[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)、[图像输入](https://developers.openai.com/api/docs/guides/images-vision?api-mode=responses)。第三方服务返回的型号与费用仅按实测记录，不据官方标价推算第三方账单，也无法从客户端独立验证其底层路由。
