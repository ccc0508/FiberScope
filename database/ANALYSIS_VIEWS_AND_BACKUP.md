# 正式数据备份与分析视图实施说明

当前前提：V005 已显示 `PASS`，正式库包含61个唯一样本、63个实验展示点、70条样本组分、61条纤维测量、61条纸张测量和178条来源记录。

## 一、先制作正式数据基线备份

在 PowerShell 中运行：

```powershell
Set-Location 'C:\path\to\project'
.\database\backup\create_baseline_backup.ps1
```

默认使用管理员账号 `postgres`，PostgreSQL需要时会提示输入密码。备份保存到项目的 `backups/` 文件夹，同时生成：

- PostgreSQL自定义格式 `.dump` 归档；
- `.restore-list.txt` 归档目录，用于确认 `pg_restore` 能读取备份；
- `.sha256.txt` 完整性指纹。

该备份包含当前数据库结构和数据，但不保存登录角色的密码。角色和权限仍由环境脚本及版本迁移管理。

## 二、创建五个分析视图

退出当前交互式 `psql` 后，在 PowerShell 中运行：

```powershell
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
$dir = 'C:\path\to\project\database\migrations'

& $psql -X -W -v ON_ERROR_STOP=1 -U postgres -d plant_fiber_db `
  -f "$dir\V006__create_analysis_views.sql"

& $psql -X -W -v ON_ERROR_STOP=1 -U postgres -d plant_fiber_db `
  -f "$dir\V007__grant_and_verify_analysis_views.sql"
```

V006是一次性迁移，不要重复执行。V007只调整并检查权限，可以重复执行。

V007成功时应显示：

| 项目 | 预期值 |
|---|---:|
| verification_status | PASS |
| analysis_view_count | 5 |
| sample_overview_rows | 61 |
| wide_analysis_rows | 61 |
| beating_rows | 52 |
| blend_rows | 11 |
| lineage_rows | 257 |
| covered_source_rows | 178 |

## 三、五个视图的作用

| 视图 | 粒度 | 行数 | 用途 |
|---|---|---:|---|
| `fiber.v_sample_overview` | 每个唯一样本一行 | 61 | 查询样本类型、SW/HW比例和打浆条件 |
| `fiber.v_fiber_paper_analysis` | 每个唯一样本一行 | 61 | 同时分析12项纤维特性和9项纸张性能 |
| `fiber.v_beating_analysis` | 每个纯浆实验展示点一行 | 52 | 绘制打浆转数、打浆度与性能变化曲线 |
| `fiber.v_blend_analysis` | 每个复配展示点一行 | 11 | 绘制针阔比例与纤维、纸张性能关系 |
| `fiber.v_data_lineage` | 每个来源用途一行 | 257 | 追溯到文件、Sheet1和Excel原始行 |

数据库视图本身不保证显示顺序。可视化查询必须显式使用 `ORDER BY display_order` 或 `ORDER BY beating_revolutions`。

## 四、使用只读账号验证查询

以 `fiber_reader` 登录：

```powershell
& $psql -X -W -U fiber_reader -d plant_fiber_db
```

在 `psql` 中可以执行：

```sql
SELECT *
FROM fiber.v_beating_analysis
WHERE experiment_code = 'SW_BEATING'
ORDER BY display_order;

SELECT *
FROM fiber.v_blend_analysis
ORDER BY display_order;
```

`fiber_reader`可以读取分析视图，但不能插入、修改或删除正式数据。为保持V004的既有权限基线，它仍保留对基础表的只读查询权；后端和可视化平台应统一通过这五个视图访问分析数据。

## 五、单位状态

- `air_permeability`：数值原样保留，设计暂定单位为 `μm/(Pa·s)`；可视化界面应标记“单位待复核”。
- `folding_endurance_raw`：耐折度原始值，单位待确认；确认前不要自动换算。

视图和权限通过后，下一阶段是建立后端只读查询接口，并以 `fiber_reader` 作为数据库连接账号。
