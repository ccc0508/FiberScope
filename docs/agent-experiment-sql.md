# Agent 实验数据 SQL 工具

新增 `describe_experiment_data`（真实字段目录、单位、统计粒度）与 `query_experiment_data`（受限 SQL）。模型生成 SQL，程序解析、校验后重新生成 PostgreSQL SQL，再交给数据库执行。

第一版限定为 catalog.py 中八个 fiber 分析视图之一的单条 SELECT。支持筛选、排序、GROUP BY/HAVING，以及 COUNT、SUM、AVG、MIN、MAX、ROUND、ABS、COALESCE、NULLIF。暂不支持连接、子查询、CTE、类型转换或任意函数。采用语法树节点白名单，解析成功本身不代表允许执行。

沿用应用专用只读连接，事务只读，查询超时 5 秒、锁等待 1 秒；search_path 限定 pg_catalog。服务端游标最多读取 101 行，返回最多 100 行、约 24000 字符的行数据；截断时明确返回 truncated。统计全体数据应使用数据库聚合，不可根据截断结果推算全体。

SQL、列名、行数据、查询时间、视图及限制说明保存为 experiment_query 证据快照，分配当前回答内统一引用编号。网页显示实验数据库来源，不生成论文页码或 PDF 链接。来源追溯可另查 v_data_lineage；该视图一行是一项来源用途，不能把行数当作样本数。

验证：SQL 拦截、成功查询、证据与网页结果适配及既有 Agent 测试；真实 PostgreSQL 分组查询；真实模型自然语言调用。文献 30 题完整回归尚未执行，不能据本次功能验证宣称文献能力没有退化。
