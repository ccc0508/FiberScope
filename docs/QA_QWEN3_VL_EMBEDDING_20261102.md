# MinerU候选版切换阿里云Qwen3-VL Embedding

2026-11-02。按用户要求，将MinerU候选版的问题向量、原文块向量及表格行向量统一切换为阿里云百炼`qwen3-vl-embedding`，2560维。原问题与一条改写分别检索、合并去重后使用原问题BGE重排的策略保持不变。

## 实现

- 使用百炼原生Multimodal Embedding HTTP API，不走OpenAI兼容的文本向量接口。模型支持文本、图片与图文融合；默认关闭融合，只有显式图文输入才请求融合向量。
- 独立适配器支持文本分批（最多20条）、图片批次及图文融合，按返回index恢复顺序，校验数量、维度、有限数值和非零向量；失败不退回BGE、不自动重试，不保存密钥或原始供应商错误。
- 用量保留供应商原始口径：该模型的input_tokens是文本，image_tokens是图片，total_tokens已包含二者。缺失金额记未知，不把多模态Token再重复加到total_tokens。
- 新增独立重建工具，不重新解析或切块。保持块ID、原文、页码、章节、内容分类和表格关联一致，同时重算全部原文及表格行向量。每批保存结果与用量，可显式恢复失败批次；已完成批次复用缓存，未确认是否完成的付费请求禁止自动重放。

原生接口与维度依据：[阿里云API文档](https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference)、[模型说明](https://help.aliyun.com/zh/model-studio/qwen3-vl-embedding)。

## 索引与配置

新索引：`.rag-data/index-versions/mineru-qwen3-vl-20261102`。113个原文块、20条表格行、10条正文表格关联，向量均为Qwen3-VL 2560维。旧BGE库、历史实验库及评测材料保留，不能将新旧向量混在同一个Chroma集合中，即使选择相同维度也不兼容。

私有配置为`backend/.env.aliyun`，已被Git忽略；无密钥示例为`backend/.env.aliyun.example`。验证通过后，当前MinerU候选配置`.rag-data/configs/mineru-body-tables-v1-20261031.env`指向新库及新模型。

```powershell
.\.venv\Scripts\python.exe scripts\reembed_literature.py --source-dir .rag-data\index-versions\mineru-body-tables-v1-20261031 --output .rag-data\index-versions\mineru-qwen3-vl-20261102 --env-file backend\.env.aliyun --embed
```

命令使用新目录。中途明确失败后，可在核对账单/检查点后使用`--resume`，不应删除目录重复付费。若已完成，校验后返回现有结果。重建清单和向量缓存均位于私有索引目录。

## 实际验证

- 文本接口：真实调用返回2560维。
- 图片接口：论文图9原始裁图真实调用返回2560维。
- 图文融合：同一原图与图注真实调用，开启enable_fusion后返回一个2560维向量。
- 重建：7批完成113个原文块及20条表格行，共28601个报告Token；旧库指纹保持一致，原文、块编号、章节及关联均核对。
- 完整问答：第8题和第32题均成功回答；各自执行原问题、改写两路Qwen查询及原问题BGE重排，最终送原问题给DeepSeek。仅作流程验证，没有调用Jev或Luna评分。第32题仍没有收到摘要0.888，不能声称已解决该问题。
- 自动化：192项相关测试通过，包括供应商协议、错误处理、图文输入、模型隔离、断点恢复及实际worker入口组合测试。

机器可读验证及用量见`data/literature/embedding-migrations/qwen3-vl-20261102/summary.json`；原始请求诊断、运行源码快照与问答结果位于已忽略的`.rag-data/evaluations/qwen3-vl-embedding-20261102`。

## 当前边界

本轮完成的是Embedding模型替换：新的原文索引仍由文字与表格行构成，图片输入与融合接口已支持并真实验证，**图片尚未加入主检索库，原图尚未送给回答模型**。若要回答“图中曲线如何变化”，仍需接入图像索引、来源映射与DeepSeek视觉输入；多模态Embedding本身不会自动完成看图回答。

为保持可比较，本轮保留0.35候选阈值、原BGE重排、最多50候选/8主命中、小节补全和8000/24000字符预算。0.35继承旧模型，尚未针对Qwen分数校准，不是正确概率；正式优劣需要另跑固定评测，不能由两题验证断定提升。

此处切换的是MinerU候选配置。`backend/.env.literature`和服务器部署本轮未切换；密钥、新向量库和私有问答记录均未上传GitHub。
