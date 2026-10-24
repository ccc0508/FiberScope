# 文献问答评测起点：qa-v1-20261024

2026-10-24已完成第一步：固定现有问答代码、配置、论文、文本片段和向量索引。
本步骤没有编写评测题、生成问答或计算质量分数；离线检索验证不是问答效果评测。

## 固定内容

| 项目 | 内容 |
| --- | --- |
| 产品代码提交 | `d6a391ee8febcc58a4d0e1b59551d92403082f48` |
| Git版本标记 | `qa-baseline-20261024`，指向上述原始提交 |
| 本地快照 | `.rag-data/baselines/qa-v1-20261024/` |
| 文献 | Li-2020-PFI-refining-aggregation-structure-cellulose.pdf |
| 覆盖 | 1篇、14页、44个文本片段与44个向量 |
| 回答模型 | `deepseek-v4-flash`，provider为`deepseek` |
| 向量模型 | `BAAI/bge-m3`，1024维，provider为`openai`兼容接口 |
| 检索 | 最多50个向量候选，相似度阈值0.35，最终最多8段证据 |
| 生成 | 现有提示词、引用校验、最多2次应用层生成尝试，问答总时限90秒 |
| 配置与环境 | 脱敏配置、供应商地址指纹、Python与实际安装依赖版本清单 |

设置中的chunk_size/chunk_overlap只记录当前设置，不推断旧索引如何切块；实际冻结的44个片段是评测依据。
temperature、top_p和seed在当前生成器中没有显式设置，快照如实记录为供应商默认行为。
现有历史问答不作为标准答案，不包含在此快照中；实验PostgreSQL和提取记录库也不在范围内。

## 文件与公开范围

```text
.rag-data/baselines/qa-v1-20261024/
  code.zip                  # 原提交中backend、frontend、scripts、docs等已跟踪代码
  configuration.json        # 不包含密钥或原始供应商地址
  environment.json          # Python、系统与实际依赖版本
  manifest.json             # 文件SHA-256、论文指纹、原提交和离线验证结果
  library/
    metadata.sqlite3        # 在线备份；论文路径调整为快照内相对路径
    chroma/                 # SQLite在线备份及原向量索引文件
    papers/                 # 原始PDF，按内容SHA-256命名
```

完整快照位于Git忽略目录，只保存在本机。GitHub只保存脚本、测试、本说明和
`data/literature/qa-baselines/qa-v1-20261024.json`脱敏清单，不包含PDF、向量或密钥。
该公开清单与本地manifest内容相同，可用于比对文件指纹。

密钥和供应商地址仍由本机私有配置提供，不写入快照。供应商地址仅保存指纹以核对是否换过服务。
远端模型升级、供应商默认参数和随机输出不能靠本地快照冻结，因此不能承诺逐字复现回答。
Git标签标记的是被评测的原产品代码；之后新增的保存工具与说明属于另外的提交。

## 校验已有快照

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/freeze_qa_baseline.py verify .rag-data/baselines/qa-v1-20261024 --check-index
```

校验包括完整文件集合、SHA-256、SQLite完整性、论文内容指纹、44个片段与向量ID的一致性、
1024维向量及一次本地近邻查询。Chroma在临时副本上打开，避免校验过程修改冻结快照。
使用已有向量作为查询，不调用Embedding或大模型接口，不产生模型费用。

不要直接用Chroma打开冻结目录，或把网页服务的数据目录指向冻结快照。后续评测应复制到独立运行目录，
使用code.zip中的原始代码及匹配的私有服务配置，再写入单独的结果目录。
当前版本的worker从其backend/.env.literature读取模型配置，不能只改数据目录就认为配置已冻结。

## 后续创建另一个快照

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/freeze_qa_baseline.py snapshot .rag-data/baselines/新的唯一编号
```

工具要求产品代码已提交，拒绝覆盖目录；对SQLite使用在线备份，包含已提交的WAL数据。
复制前后核对文献库和配置是否发生变化；若失败，不会写出最终manifest，不得使用该未完成目录。
该工具不是云备份或自动备份计划。迁移机器时需另外保留完整本地快照及私有服务配置。

## 本次验证

- 7项保存工具测试通过：WAL数据、源库不变、文件校验、篡改与额外文件识别、目标目录限制、禁止覆盖和配置脱敏。
- 实际快照校验：10个文件、1篇PDF、44个文本片段。
- 实际索引副本：44个向量，1024维，本地检索通过，供应商调用数为0。
- 下一步：依据冻结论文整理带原文证据的评测题和参考答案，再运行未优化版本获取首份质量基线报告。
