# MinerU当前采用的检索策略

2026-11-02，按用户选择，MinerU候选版采用**原问题与改写问题分别检索，合并后用原问题重排**。

流程：

1. DeepSeek生成一条检索改写；保留原问题。
2. 原问题和改写分别使用阿里云`qwen3-vl-embedding`（2560维）向量化，各取最多50个候选，分别应用原0.35阈值。新阈值尚未通过正式质量评测校准。
3. 按原文块ID去重，使用RRF（k=60）合并排名，最多保留50个候选。
4. 用**原问题**和完整候选原文进行BGE重排，最多选8个主命中。
5. 按现有MinerU小节、表格关联与正文续句规则补全，预算为单条8000、全部24000字符。
6. 回答模型依据最终证据回答**原问题**，回答指引关闭。

私有候选配置：`.rag-data/configs/mineru-body-tables-v1-20261031.env`。明确设置：

```dotenv
RAG_QUERY_REWRITE_ENABLED=true
RAG_QUERY_REWRITE_MODE=dual
RAG_EMBEDDING_PROVIDER=dashscope
RAG_EMBEDDING_MODEL=qwen3-vl-embedding
RAG_EMBEDDING_DIMENSIONS=2560
```

改写失败会记录状态并使用原问题检索；改写与原问题完全相同时只检索一次。两路命中同一个块时只向重排器提交一份原文，保留来源诊断。表格行检索、113块分类索引、重排模型和上下文补全设置保持原值。

查询策略沿用双路检索。后续模型替换建立了独立的`mineru-qwen3-vl-20261102`索引，保留原113块与20条表格行文本；正文、表格、图注仍以文字参与当前问答。新模型的图片、图文融合接口已经验证，实际图片尚未加入问答检索或生成输入。

配置校验与自动化测试验证双路去重、原问题重排及最终回答原问题。模型替换详情、真实调用与用量见[迁移说明](QA_QWEN3_VL_EMBEDDING_20261102.md)。历史封存实验配置、回答和评分保留。

这份文件记录候选版的当前选择。网站仍读取`backend/.env.literature`；本次未切换该文件或部署服务器。

- [双路方案方法与评测范围](QA_QUERY_REWRITE_METHOD_20261102.md)
- [双路方案评测结果](QA_QUERY_REWRITE_EVAL_20261102.md)
- [仅改写方案对照结果](QA_REWRITE_ONLY_EVAL_20261102.md)
