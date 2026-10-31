# 植物纤维数据库：数据预检与正式入库说明

本目录用于把 `data/` 中已经确认的8份正式 Excel 导入 PostgreSQL。程序不会读取旧复配版，也不会读取或移动 `数据汇总(1).xlsx`。

## 1. 文件作用

- `precheck_data.py`：只读检查8份 Excel，生成预检报告，不连接数据库。
- `import_data.py`：重新执行同样的预检，生成正式入库 SQL；只有添加 `--apply` 才会连接数据库。
- `etl_core.py`：集中保存文件白名单、字段映射、样品编码、复配端点和数量规则。
- `reports/`：运行后生成预检报告和可审计的正式入库 SQL。
- `../migrations/V005__verify_imported_data.sql`：入库后的只读验收脚本。

## 2. 固定入库规则

- 只读取8份正式来源，复配只使用文件名含 `0110` 的两份文件。
- `zk010` 复用 `HW_R08000`，`zk100` 复用 `SW_R14000`。
- 仅9个中间复配点创建新的 `blend` 样本。
- 复配针叶木浆固定为 14000 r、41.0°SR；阔叶木浆固定为 8000 r、40.6°SR。
- 12项纤维特性和9项纸张性能全部保留。
- 透气度数值原样保存，单位状态暂定为 `μm/(Pa·s)`。
- 耐折度数值原样保存到 `folding_endurance_raw`，单位待确认。
- 纸张性能按最终均值接收，`replicate_count=3`。

## 3. 第一步：只读预检

请在 PowerShell 中进入项目目录：

```powershell
Set-Location 'C:\path\to\project'
python .\database\importer\precheck_data.py
```

也可以双击前先在 PowerShell 运行简化入口：

```powershell
.\database\importer\run_precheck.ps1
```

预期结果包括：

- 状态 `PASS`
- 61个唯一样本
- 63个实验展示点
- 70条样本组分
- 61条纤维测量
- 61条纸张测量
- 178条来源记录

预检会在 `database/importer/reports/` 生成 JSON 和 Markdown 两种报告。该步骤完全不连接 PostgreSQL。

## 4. 第二步：生成SQL预览

```powershell
python .\database\importer\import_data.py
```

不带 `--apply` 时只生成 `formal_import_generated.sql`，不会修改数据库。可以先查看该文件，再决定是否正式导入。

## 5. 第三步：正式入库

确保8张表已建立且 V004 显示 `PASS`，然后在 PowerShell 中运行：

```powershell
python .\database\importer\import_data.py --apply
```

也可使用：

```powershell
.\database\importer\run_import.ps1
```

程序会依次要求：

1. 输入大写 `IMPORT` 确认写入；
2. 输入 `fiber_importer` 的 PostgreSQL 密码。

密码只交给 PostgreSQL 客户端，不会写入程序、报告或 SQL 文件。程序默认连接：

- 主机：`localhost`
- 端口：`5432`
- 数据库：`plant_fiber_db`
- 用户：`fiber_importer`

如果 PostgreSQL 安装位置不同，可以指定：

```powershell
python .\database\importer\import_data.py --apply `
  --psql 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
```

## 6. 安全机制

- 预检失败时不会连接数据库。
- 正式写入位于一个事务中；写入或约束检查失败时整批回滚。
- 程序强制使用 `fiber_importer`，不使用管理员账号导入业务数据。
- 6张业务表必须为空；发现已有正式数据时程序拒绝覆盖。
- 导入完成后自动运行 V005，只显示 `PASS` 才算完成。

如果已经成功导入，不要再次执行正式入库。需要复核时只运行：

```powershell
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
& $psql -X -W -v ON_ERROR_STOP=1 -U fiber_importer -d plant_fiber_db `
  -f '.\database\migrations\V005__verify_imported_data.sql'
```

若需要清空后重新导入，应先制定受控清理和备份方案，不要手工逐表删除。

## 7. 数据汇总工作簿的增量导入

`数据汇总(1).xlsx`现已作为独立的再生纸浆循环实验数据集纳入设计。它不会混入原来的61个最终均值样本，而是写入3张扩展表，并通过3个扩展视图查询。源表中的14个连续块统一称为“数据块”，不称为“处理组”；正式实验条件未知时保持`NULL`和`unknown`状态。

完整说明、执行顺序和验收标准见：

- `../RECYCLED_SUMMARY_IMPORT.md`
- `../migrations/V008__create_recycled_pulp_tables.sql`
- `../migrations/V009__create_recycled_pulp_views.sql`
- `../migrations/V010__verify_recycled_pulp_import.sql`
- `precheck_recycled_summary.py`
- `import_recycled_summary.py`
