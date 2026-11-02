# 原PDF图片入库与DeepSeek视觉问答

2026-11-02。按用户要求，已接入MinerU候选版的图片向量入库、检索来源映射、原图发送、引用展示与历史图片保存。

## 已实现的流程

1. 校验MinerU原生JSON与原PDF的指纹，使用其页面、区域框和图号定位。将同页连续子图按共同编号图注组织，不把页眉标志、无编号装饰图片直接作为科研图入库。
2. 根据原PDF区域以180 DPI渲染PNG，保留完整图组。每组记录文献ID、原图注/表格父块ID、图号、物理页码、区域框、源子图编号、尺寸和内容哈希。本论文得到Figure 1—9及Table 1—2，共11组原图，约1.56 MB。
3. 使用阿里云Qwen3-VL-Embedding生成11组图像向量，2560维。保留原113块文本向量、20条表格行和10条明确关联，新建独立索引，不再次切块或重算已有文本向量。文字与图片使用完全相同的模型空间。
4. 原问题与一条改写分别向量化。每路同时检索文字、表格行与图像。图像命中映射回原图注/表格父块，按父块取最大余弦分数，合并去重后仍最多50候选，再按既有RRF双路融合规则处理。
5. BGE继续使用**原问题与文字候选**重排，最多8个主命中；本轮没有增加多模态重排模型。按原小节、明确表格关联和正文续句规则补全，仍受8000/24000字符预算约束。
6. 只为最终证据中实际存在的图注/表格源块附加原图。优先问题明确提及的图号，再按主命中顺序补充。每次最多4张、总计12 MiB，按图片ID去重；超限跳过并记录原因，不因有图就加载整篇PDF。
7. DeepSeek接收原问题、文字证据及真实Base64图片数据，使用标准image_url块和original细节选项。每张图旁明确标注引用编号、图号与页码。额外视觉说明要求区分实际看到的像素与仅有图注、区分估读与精确数值，保持既有JSON陈述和引用格式。回答High思考设置沿用原值。
8. 引用保存图片定位元数据；页面引用卡片显示原图缩略图、图号和页码，可点击查看。历史记录按内容哈希另存所有输入原图，包含最终没有引用的图，避免删除或切换检索索引后丢失当时模型看到的材料。图片二进制和Base64不写进问答JSON。

[DeepSeek官方视觉输入说明](https://api-docs.deepseek.com/guides/vision/)。

## 当前配置与建库

当前MinerU候选配置为`.rag-data/configs/mineru-body-tables-v1-20261031.env`，私有阿里云配置为`backend/.env.aliyun`；两者选用新库`.rag-data/index-versions/mineru-qwen3-vl-images-20261102`并开启`RAG_VISUAL_RETRIEVAL_ENABLED=true`。旧BGE库、Qwen纯文本库及封存实验配置保留。

```powershell
.\.venv\Scripts\python.exe scripts\index_literature_images.py --source-dir .rag-data\index-versions\mineru-qwen3-vl-20261102 --native data\literature\parsing-comparisons\mineru-vs-pymupdf-20261029\mineru-content-list.json --output .rag-data\index-versions\mineru-qwen3-vl-images-20261102 --env-file backend\.env.aliyun --embed
```

工具每次处理一篇指纹一致的文献，不硬编码本论文图号或科学数值。跨页子图、无明确图注、源定位不一致等复杂情况需要后续处理；不会声称任意PDF都已自动识别。已有目标目录需要显式`--resume`，有效图像向量复用，未确认是否完成的付费请求禁止自动重放。

## 真实验证

在独立HTTP服务与独立历史库中完成两道需要原图信息的问题，每题使用独立问答进程，未提供标准答案或旧答案：

| 问题 | 观察结果 |
| --- | --- |
| Figure 9中间与两侧的区域标注、蓝线排列差异 | 正确识别Crystalline region与Amorphous region；描述结晶区蓝线平直平行、非晶区弯曲交错；引用图9 |
| Figure 2橙色/绿色柱分别表示什么、左右轴如何区分 | 区分Drainability（°SR，左轴）与WRV（%，右轴），给出大致变化趋势并提示不能直接比较双轴柱高；引用图2 |

两题均真实发送4张原图给DeepSeek；保存的模型输入诊断包含图片ID、引用号、图号、哈希与尺寸。两题各生成一次，HTTP端到端约14.47秒、23.17秒。引用PNG端点返回200，下载字节的SHA256与实际输入图片相同。上述观察是功能核对，不是裁判评分或正式准确率。

- 新图像入库11次Embedding请求，报告6295 Token（文本242、图片6053）；文本Token含模型模板，图片Token不在total_tokens之外重复相加。
- 后端293项相关测试通过，覆盖图像协议、原文映射、预算、路径与哈希校验、历史缓存、图片备份、旧文字流程、引用及基线工具。
- 前端TypeScript检查与生产构建通过；ego-browser确认历史回答中的图9原图加载成功，图号/页码与来源一致。
- 原文、章节分类、原113块及表格行向量保持不变。基线封存工具已纳入图像清单、向量与原PNG，后续评测可复现实际图片输入。

原始运行材料在已忽略的`.rag-data/evaluations/visual-integration-20261102`。公开摘要与两道示例答案见`data/literature/visual-integration/20261102`，不含密钥或图片二进制。

## 历史与备份

历史原图保存在问答数据根目录的`qa-images`下，与检索索引独立。`scripts/manage_qa_history.py backup`先备份SQLite，再按该快照中的实际图片引用复制图片，输出`<备份数据库文件>.assets/qa-images`及图片清单。恢复时需要将备份数据库与该目录中的qa-images一起恢复到问答数据根目录。JSONL导出只包含定位和哈希，不内嵌图片二进制。

## 范围与限制

现在是Qwen多模态召回、BGE文字重排与DeepSeek视觉回答的组合。图像可能被文字重排或图片预算排除，不保证每次问题需要的图一定进入模型；这些阶段均有诊断。

本轮没有调用Jev/Luna，也未重跑32题。旧文字评测不能直接衡量新增的纯视觉事实；正式图片评测需要包含图例、曲线、示意图及数值估读问题，并确保裁判或人工金标准能够核对原图。不能用两题验证宣称整体质量提升。

本轮切换MinerU候选配置，网站`backend/.env.literature`及远端服务器部署保持原状态。密钥、原图、向量与私有历史不会上传GitHub。
