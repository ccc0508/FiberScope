# GPT-6 Luna评分准备

2026-10-26，用户指定将原GPT-6.1 Sol评分服务替换为OpenRouter上的GPT-6 Luna，与Jev继续独立双评。已从OpenRouter公开模型目录确认准确标识为`openai/gpt-6-luna`；不使用Pro、Batch或其他模型别名。

## 配置与凭证

模板：[backend/.env.luna.example](../backend/.env.luna.example)。本机私有配置为`backend/.env.luna`，服务器为`/etc/fiberscope/luna.env`。实际配置被Git忽略，服务器文件仅root可读。

```dotenv
QA_LUNA_BASE_URL=https://openrouter.ai/api/v1
QA_LUNA_MODEL=openai/gpt-6-luna
QA_LUNA_API=chat_completions
QA_LUNA_API_KEY=
QA_LUNA_TIMEOUT_SECONDS=180
QA_LUNA_MAX_OUTPUT_TOKENS=16000
```

使用独立的`QA_LUNA_*`命名空间，不继承`QA_JUDGE_API_KEY`、`QA_JEV_API_KEY`或通用`OPENROUTER_API_KEY`。密钥未配置时，实际评分在发送请求前停止；不会自动拿已有Jev密钥调用。

## 评分契约

[judge_qa_luna.py](../scripts/judge_qa_luna.py)复用现有评分引擎和[统一评分标准v3](QA_SCORING_V3.md)，通过OpenRouter的`/chat/completions`发送独立system+user请求。接口模式已显式配置，不在失败后自动换接口、模型或重复调用。

保持同一批32份原始回答、评分要点和证据。Luna需要独立重评完整32题，不能将Luna的分数补进旧Sol结果后合成一个裁判。此前Jev的v3结果在源回答、规则及输入指纹一致时可以复用，省去重复Jev调用。

新输出使用全新的目录，例如`judge-luna-openrouter-scoring-v3-core-20261026-r1-initial`。旧Sol、Jev记录和旧失败链继续保留。默认不覆盖推理参数，提供商默认值会通过原始请求指纹与模型公开配置记录。

## 未提供Key也能做的验证

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/judge_qa_luna.py --run-dir .rag-data/evaluations/pfi-v2-core-20261026-r1 --dry-run
```

`--dry-run`校验冻结题集、源回答、模型标识、接口配置，构造32题请求及指纹；不调用模型、不新建评分结果目录、不修改原回答。当前已完成此离线准备，凭证为空，尚未进行付费接口验证。

提供Key后，先限制一次调用验证完整评分：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/judge_qa_luna.py --run-dir .rag-data/evaluations/pfi-v2-core-20261026-r1 --output-dir .rag-data/evaluations/judge-luna-openrouter-scoring-v3-core-20261026-r1-initial --limit 1
```

首题成功时保留为本轮正式评分，后续同目录仅继续余下31题；失败时保留原始响应，不自动重放。程序继续校验原文引句、要点、事实/范围、引用贡献及引用组完整性，不由开发助手填正式语义分数。

## 用量与费用

原始OpenRouter响应、Token及请求耗时继续由现有评分引擎保存。额外的`openrouter-costs.json`逐请求读取API返回的`usage.cost`，以十进制累计已知美元费用，并单列未知费用的调用数。API未返回金额、网络失败或超时均不当作免费，实际充值账单另计。

当前未对新模型宣称速度、评分质量或账户可用性；这些需要Key后的实际调用验证。公开模型目录可用，不等于用户账户具备调用权限或余额。

依据：[OpenRouter模型页](https://openrouter.ai/openai/gpt-6-luna)、[OpenRouter Chat接口](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion)、[OpenAI Docs模型说明](https://developers.openai.com/api/docs/models/gpt-6-luna)。
