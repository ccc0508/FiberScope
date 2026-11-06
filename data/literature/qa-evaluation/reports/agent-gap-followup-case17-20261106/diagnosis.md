# 第17题：Morais表1证据获取诊断

核查对象：agent-gap-followup-case17-20261106，冻结八篇论文库。仅离线核查保存轨迹和读取工具，不重新调用答题、Embedding或重排API。

## 已验证链路

| 环节 | 核查结果 |
|---|---|
| 原PDF | 第4页Table 1，X3明确为Coarseness (mg/100m)；已渲染页面检查。 |
| MinerU原始输出 | imports/doc_cec3e2f8b5abaa89.json的native_blocks保留完整HTML表及该单位。 |
| 整理后的块 | chk_c6b4ded04cbe28c9627f，1033字符，table类型，单位完整。 |
| 向量库 | Chroma的chunks_a2bfead5f9a9集合对应embedding记录存在。 |
| 两轮候选 | 两次重排输入各50个候选，均不含目标表块；并非进入重排后被剔除。 |
| 表格行索引 | table-retrieval.json与table-row-vectors.json均没有此表；table_rows直接调用返回No fully labelled numeric data rows found。 |
| 上下文补全 | 第二次命中的方法段属于2.2 Methods，表1属于3.1 MLR；不同小节，且没有明确表号关联，未自动补入。 |
| 读取能力 | 直接使用正确document_id和chunk_id调用read_table，返回完整表；正确section_id调用read_section，返回5块且包含单位。 |
| 模型可见参数 | 目标表chunk_id与所属section_id均未出现在模型输入中。 |

## 原因

1. 主要丢失位置是候选召回：目标表已经解析、入库，但未进入两轮前50候选。两轮均有50候选进入重排，不是0.35阈值导致候选不满。不能凭此给出目标表精确向量排名；此次未重新做全库向量排序。
2. 表格行检索存在覆盖盲点：scripts/index_table_evidence.py的table_rows要求数据行各单元格均为数值；X3 / Coarseness (mg/100m)这种变量定义表不满足条件，缺少行级召回路径。整表向量仍存在，不能说整表未入库。
3. 查询含作者年份且未限定文献。前50候选里，Morais第11—12页条目第一轮14个、第二轮13个；参考文献占用候选名额是观察到的现象，不足以单独证明移除它们就一定召回目标表。
4. 第二轮上下文确有预算限制，但目标表此前已不在候选，故不是这张表丢失的起点。
5. 工具可调用不等于目标可定位：read_table需要document_id+chunk_id，read_section需要document_id+section_id。没有find_table、章节目录或按页读取入口，模型不能仅凭论文身份直接取得表1。当前search_literature也不暴露document_id过滤参数。

## 对此前归因的修正

不能简单归为模型有read_table却不使用。人工从SQLite找到正确ID后能成功读取，只证明底层读取有效，并不证明模型当时拥有调用所需定位信息。模型也没有穷尽所有可能路径的证据，但工具缺少发现入口是已确认的接口缺口。

## 建议优先级

先提供论文＋表号定位及论文目录发现入口；给已确认论文的定向检索提供文献过滤；再让变量定义/单位表生成行级检索表示。随后以同题及其他跨篇题验证。不能把单纯提高重排预算当作本例的直接修复，因为目标未进入重排输入。

本轮没有修改索引、运行逻辑、评分或问答提示词。原始证据与测试输出保存在忽略的.rag-data/case17-diagnosis，PDF截图在.rag-data/case17-table1-page.png。
