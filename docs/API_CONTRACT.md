# 植物纤维平台 API v1

首版采用 FastAPI + PostgreSQL、Vue 3 + TypeScript + ECharts。浏览器仅访问 `/api/v1`。
首版提供只读展示和探索；模型预测、Agent交互、用户管理与数据编辑不在本次实现范围。

## 接口

| GET 路径 | 数据视图 | 基线 | 筛选参数 |
|---|---|---:|---|
| /health | 实际探测数据库连接 | — | 无 |
| /metadata | 指标、单位状态、字段清单、枚举、实时数量与数据块 | — | 无 |
| /samples | v_sample_overview | 61 | sample_type、q、canonical_code |
| /beating | v_beating_analysis | 52 | material_code、min_revolutions、max_revolutions |
| /blends | v_blend_analysis | 11 | 无 |
| /fiber-paper | v_fiber_paper_analysis | 61 | sample_type、canonical_code |
| /recycled/cycles | v_recycled_cycle_summary | 47 | block_code、cycle_no |
| /recycled/details | v_recycled_cycle_detail | 131 | block_code、cycle_no |
| /quality | v_recycled_data_quality | 4 | block_code |
| /lineage | v_data_lineage | 257 | canonical_code、usage_type、file_name |

列表统一使用 `page`（默认1）、`page_size`（默认50，最多500）。越界页返回空数组且保留正确total。
多选数据块使用重复参数，如 `?block_code=G01&block_code=G11`。样本类型为softwood/hardwood/blend，原料为SW/HW。
`q`对样本编码和名称做不区分大小写的字面子串搜索；百分号、下划线不作为通配符。
不支持的筛选、任意排序字段、无效枚举及超限参数返回422。排序固定为catalog中定义的稳定多字段顺序。

```json
{"data":[],"pagination":{"page":1,"page_size":50,"total":0,"total_pages":0},"meta":{"view":"fiber.v_sample_overview","indicators":[],"notes":[]}}
```

返回记录保留对应视图的全部字段，具体清单见 `/metadata` 的 `views.*.columns`。
字段名为snake_case；对外样本标识使用canonical_code，实验内标签使用display_code。
NUMERIC序列化为JSON数值，不预先舍入；浏览器浮点数不能承担任意精度计算，精确存储以PostgreSQL为准。
NULL返回null；百分比为0—100。时间为含时区的ISO 8601。前端仅在显示层控制小数位。

## 指标与科学口径

`metadata.indicators`提供key、name、unit、group、scope、unit_status。
核心数据使用12项fiber与9项paper指标；再生纸浆使用12项fiber、10档distribution和3项strength指标。
透气度unit_status=tentative，单位暂定μm/(Pa·s)；耐折度unit_status=unconfirmed、unit=null。
14个数据块保持处理条件未知；4条质量记录对应Excel行5、6、13、60，保留原值。
复配端点zk010/zk100复用HW_R08000/SW_R14000。强度和指数分开，不做因果、评分或预测结论。

## 错误与连接

错误格式为 `{"error":{"code":"INVALID_QUERY","message":"...","request_id":"..."}}`。
422=INVALID_QUERY，503=DATABASE_UNAVAILABLE，500=INTERNAL_ERROR，其余HTTP错误=HTTP_ERROR。
响应头X-Request-ID与错误编号一致。错误不返回数据库连接信息、密码或SQL。
应用账号仅接受fiber_app或fiber_reader；所有查询强制只读、参数化并设置超时。
接口当前无用户登录，部署时仅限可信网络或在反向代理增加访问控制。
