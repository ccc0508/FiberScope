# 《数据汇总(1).xlsx》增量入库说明

## 1. 本次扩展的定位

`数据汇总(1).xlsx`记录的是再生纸浆循环回用实验的逐行观测，不是原有针叶木、阔叶木和针阔复配实验的最终均值。它包含：

- 10档纤维长度分布；
- 12项纤维特性；
- 抗张强度（kN/m）、耐破强度（kPa）、撕裂强度（mN）；
- 循环次数和重复观测。

因此，本次新增3张独立表和3个分析视图，不把这些数据强行写入原来的`fiber_measurement`或`paper_measurement`。原有8张核心表、5个分析视图和61个样本均保持不变。

## 2. 已确认的数据结构

- 工作表：`Sheet1`，范围`A1:Z135`；
- 131行完整数值观测，无公式、缺失值或非数值项；
- 共14个连续数据块，按源表顺序编码为`G01`—`G14`，显示为“数据块01”—“数据块14”；
- 共47个“数据块×循环”分析点；
- 第113行“陈莉”为第二段数据的分隔标记；
- 第118—121行黄色数据按工作簿批注映射为美废13#；
- 其余数据根据工作簿批注及同项目实验说明映射为美废12#；
- 4行的10档长度分布合计偏离100%超过1个百分点。原值保留，并通过质量视图标记，不做自动归一化。

工作簿没有提供14个数据块的正式实验条件。这14个数据块不代表14种已确认的处理方式。数据库用`metadata_status='unknown'`明确记录这一状态，`condition_label`保持`NULL`，不根据数值推测名称。将来如获得可靠实验记录，可以补充`recycled_data_block.condition_label`，不需要重导131行观测。

## 3. 新增对象

### 3.1 三张表

| 表 | 作用 |
|---|---|
| `fiber.recycled_dataset` | 保存来源文件、版本、SHA-256和工作簿元数据 |
| `fiber.recycled_data_block` | 保存G01—G14数据块、显示名称、原料、循环数、重复数和实验条件确认状态 |
| `fiber.recycled_cycle_observation` | 逐行保存131条原始观测和Excel源行号 |

### 3.2 三个视图

| 视图 | 预期行数 | 用途 |
|---|---:|---|
| `fiber.v_recycled_cycle_detail` | 131 | 查询逐行原始明细 |
| `fiber.v_recycled_cycle_summary` | 47 | 绘制各数据块随循环次数变化的曲线；条件未知时不用于解释处理条件差异 |
| `fiber.v_recycled_data_quality` | 4 | 复核长度分布合计异常的源行 |

## 4. 正式执行顺序

在PowerShell中进入项目目录：

```powershell
Set-Location 'D:\develop\srp2.0'
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
```

### 第一步：再次只读预检

```powershell
python .\database\importer\precheck_recycled_summary.py
```

也可以运行：

```powershell
.\database\importer\run_recycled_summary_precheck.ps1
```

预期显示：

```text
预检状态：PASS
数量：dataset=1, data_block=14, observation=131, summary_point=47, review_row=4
```

### 第二步：以管理员建立3张表和3个视图

```powershell
& $psql -X -W -v ON_ERROR_STOP=1 -U postgres -d plant_fiber_db `
  -f '.\database\migrations\V008__create_recycled_pulp_tables.sql'

& $psql -X -W -v ON_ERROR_STOP=1 -U postgres -d plant_fiber_db `
  -f '.\database\migrations\V009__create_recycled_pulp_views.sql'
```

`V008`和`V009`是一次性迁移。成功后不要重复执行。

三个迁移脚本首行均显式设置了`UTF8`客户端编码，以避免中文Windows环境下`psql`把UTF-8脚本误读为GBK。

### 第三步：正式导入131行数据

```powershell
python .\database\importer\import_recycled_summary.py --apply
```

也可以运行：

```powershell
.\database\importer\run_recycled_summary_import.ps1
```

程序会：

1. 重新执行完整预检；
2. 要求输入大写确认词`IMPORT_RECYCLED`；
3. 要求输入`fiber_importer`密码；
4. 在单个事务中写入1个数据集、14个数据块和131条观测；
5. 发生任何错误时整批回滚；
6. 发现目标表已有数据时拒绝覆盖或重复导入。

### 第四步：以只读账号验收

```powershell
& $psql -X -W -v ON_ERROR_STOP=1 -U fiber_reader -d plant_fiber_db `
  -f '.\database\migrations\V010__verify_recycled_pulp_import.sql'
```

预期结果：

```text
verification_status = PASS
dataset_count        = 1
block_count          = 14
observation_count    = 131
summary_point_count  = 47
review_row_count     = 4
original_sample_count= 61
```

只有出现`PASS`才算正式完成。

## 5. 入库后的查询示例

查询循环汇总数据：

```sql
SELECT *
FROM fiber.v_recycled_cycle_summary
ORDER BY block_order, cycle_no;
```

查询需要人工复核的4行：

```sql
SELECT *
FROM fiber.v_recycled_data_quality
ORDER BY source_row;
```

查询正式实验条件仍未知的数据块：

```sql
SELECT
    block_code,
    block_name,
    source_start_row,
    source_end_row,
    raw_material_grade,
    condition_label,
    metadata_status
FROM fiber.recycled_data_block
WHERE metadata_status = 'unknown'
ORDER BY block_order;
```

## 6. 后续需要补充的信息

如能找到实验原始记录，最有价值的补充内容是G01—G14各数据块的正式实验条件，例如老化时间、处理方式或样品批次。补充时只更新数据块表，不改动原始观测值和Excel源行映射。找不到记录时，继续使用“数据块01”—“数据块14”和`unknown`状态即可。
