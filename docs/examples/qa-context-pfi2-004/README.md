# 第四题：评委实际收到的上下文

本例对应 PFI2-004，使用 qa-scoring-v3 标准。导出时间：2026-10-27。本次只读取历史数据，没有调用模型，没有新增费用。

## 先看这些文件

| 文件 | 内容 |
| --- | --- |
| [luna-initial.context.json](luna-initial.context.json) | 最适合阅读：初评 user 消息中的 JSON 已展开，所有证据和论文文本完整保留 |
| [luna-initial.system.txt](luna-initial.system.txt) | Luna 初评的完整 system 指令 |
| [luna-initial.request.json](luna-initial.request.json) | 初评完整请求体；user.content 是 JSON 字符串，所以有转义符 |
| [luna-final-repair.context.json](luna-final-repair.context.json) | 最终采用的补评所对应的上下文，含协议校验反馈 |
| [luna-final-repair.system.txt](luna-final-repair.system.txt) | 最终补评的完整 system 指令 |
| [luna-final-repair.request.json](luna-final-repair.request.json) | 最终补评完整请求体 |
| [jev.request.json](jev.request.json) | Jev 保存的请求体，包含共享 state 和 28 个 questions |
| [provenance.json](provenance.json) | 原始运行标识、请求 SHA256、还原方式 |

Luna 当时保存了输入快照、配置和请求校验值，没有单独保存完整请求体。此处使用源码还原，两个请求的规范化 SHA256 均与历史任务记录完全一致；system 文本也与历史指纹一致。Jev 文件来自已保存的请求体。文件经过 JSON 缩进排版，不宣称与原 HTTP 字节序列相同。没有导出认证请求头或密钥。

## 题目与实际回答

题目：PFI打到12000转的时候，针叶木浆和阔叶木浆的打浆度各是多少？那我们以后想要63 °SR左右的浆，是不是直接打12000转就行了？

实际回答：

```text
该研究中PFI打浆转数设置为0、4000、8000、12000和16000转。 [1]
按文中对应关系，针叶木浆在12000转时打浆度为63 °SR。 [7]
按文中对应关系，阔叶木浆在12000转时打浆度为57 °SR。 [7]
打浆度会随PFI打浆转数增加而显著提高，并与纤维润胀和WRV增加有关。 [4]
本研究中12000转仅使针叶木浆达到63 °SR，而阔叶木浆为57 °SR，故不能直接把12000转套用于所有目标约63 °SR的浆。 [7]
```

## 每部分装了什么

| 字段 | 第四题的实际内容 | 用途 |
| --- | --- | --- |
| reference_case | 题目、参考答案、P1/P2/P3、关键错误规则 | 判断要点是否回答完整 |
| candidate.answer | 上述原始回答 | 评分对象 |
| candidate.claims | 5 条陈述及各自 citation_refs | 逐句核查，检查额外陈述 |
| candidate.retrieved_evidence | 本次回答实际检索到的 8 个片段，包含原文、编号、页码和检索分数 | 检查检索是否充分，以及引用是否真的支持陈述 |
| candidate.citations | 原回答返回的引用信息 | 来源对应 |
| reference_evidence | 固定评测集的 28 条参考证据 | 核对科学事实；并非回答模型本次检索到的内容 |
| paper_texts | 1 篇论文、40045 个字符的全文文本 | 核查事实和条件；不包含 PDF 页面图像 |
| source_documents | 论文标识、文件指纹、页数等 | 确认材料身份 |
| rubric、scoring_policy | 评分规则与统一语义边界 | 决定 0/0.5/1、完整/部分/缺失等如何判断 |
| task | 测试模式、能力、检索适用性 | 确定哪些维度适用 |
| output_shape | 预填陈述与编号、尚未填分的结果模板 | 约束 Luna 输出格式，不是旧评委的评分 |

P1 是针叶木 63 °SR；P2 是阔叶木 57 °SR；P3 是不能跨浆种、跨条件套用，并指出作用力也是不同条件。

这次单论文评测的实现会把整份参考证据集和该论文全文放入每题上下文，并没有逐题只挑 P1/P2/P3 引用的几条参考证据。它也没有为每个评分维度重新发送一次全文。

例如，C5 是“不能直接把 12000 转套用于所有目标约 63 °SR 的浆”。检查这句话是否符合论文事实，可以核查全文；检查其附带的 [7] 是否充分，只能使用 candidate.retrieved_evidence 中 [7] 的真实文本。该片段从 `8000, 12,000...` 开始，保留原始截断，不能拿全文替它补齐。

## 对应源代码

1. [judge_qa_eval.py](../../../scripts/judge_qa_eval.py) 的 `source_context()`（第 86 行）加载固定参考证据和全文。
2. 同文件 `packet()`（第 132 行）合并题目、规则、科学材料、实际回答和结果模板。
3. 同文件 `request_body()`（第 260 行）组装 Luna 的两条消息：

```python
messages = [{'role': 'system', 'content': protocol.SYSTEM}, {'role': 'user', 'content': encode(data)}]
```

4. [qa_judge_prompt.py](../../../scripts/qa_judge_prompt.py) 的 `SYSTEM`（第 6 行）是完整评分指令。
5. [judge_qa_eval.py](../../../scripts/judge_qa_eval.py) 第 392 行在每题循环里组装一次，第 422 行发送请求。
6. [qa_jev_prompt.py](../../../scripts/qa_jev_prompt.py) 的 `build_request()`（第 65 行）复用科学材料，删除 Luna 专用的输出模板，增加证据定位池，并构造原生 Jev 请求。

Jev 的实际结构是 `model + state + questions + provider`，不是 system/user 消息。共享 state 中另有 86 个可定位证据条目；questions 包含 3 个要点判断，以及每条陈述的分类、事实支持、证据定位、引用组覆盖和单条引用贡献：3 + 5 × 5 = 28。它们随一次应用层 HTTP 请求发送；不据此推断供应商内部执行次数。

## 初评与最终补评的区别

已发布的第四题 Luna 分数采用第二次协议补评结果经零调用规范化后的记录，不是初评记录。最终请求的 `runtime_validation_feedback` 提示：

```text
Citation group and individual contribution labels are inconsistent
```

这是校验反馈，要求重新产生一致的评分结构，并附有允许使用的检索标签。此次没有传入旧分数、旧语义评语或另一个评委的结论。不能把有校验反馈的补评说成与初评完全相同的上下文。

## 论文来源

Li、Zhao、He（2020），*Probing Effect of Papirindustriens Forskningsinstitut (PFI) Refining on Aggregation Structure of Cellulose: Crystal Packing and Hydrogen-Bonding Network*，Polymers 12, 2912。DOI：[10.3390/polym12122912](https://doi.org/10.3390/polym12122912)。论文采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)；这里保留评测时使用的文本提取版本，排版与原 PDF 不同。
