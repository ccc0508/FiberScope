# 数据库恢复与验收

## 独立恢复演练

在项目根目录运行：

```powershell
python scripts/restore_drill.py --backup backups/plant_fiber_db_baseline_20260901_171451.dump
```

脚本使用本机PostgreSQL 18工具，默认端口55432；可通过 `--pg-bin`、`--port` 覆盖。
端口5432被明确拒绝，目标目录始终是新建的 `tmp/restore_UTC时间戳/cluster`，不会复用既有数据库目录。
如备份有 `.sha256.txt` 记录，脚本先校验其散列；不匹配立即退出。

执行流程：

1. 以随机密码、SCRAM认证初始化全新的实例，仅监听127.0.0.1。
2. 创建owner/importer/reader角色和空的plant_fiber_db。
3. 在单一事务中恢复备份，保留对象所有者和归档权限。
4. 执行V005、V010，新增V011应用角色，再执行V012完整验收。
5. 为应用角色设置随机密码，输出不含密码的result.json。

`app.env`和`admin.env`仅保存在被Git忽略的演练目录中。
实例成功后保留运行，供接口验证；出错时尝试停止该实例，保留文件便于排查。
Windows启动阶段使用文件日志和关闭的标准输入，避免后台PostgreSQL继承管道导致等待不退出。

验收后可停止指定的演练实例（替换为脚本实际返回的目录）：

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'C:\path\to\project\tmp\restore_时间戳\cluster' -m fast -w stop
```

需要继续使用时，在相同目录与端口启动：

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'C:\path\to\project\tmp\restore_时间戳\cluster' -l 'C:\path\to\project\tmp\restore_时间戳\server.log' -o '-h 127.0.0.1 -p 55432' -w start
```

## 验收版本

- V004、V007属于早期核心结构阶段，分别严格要求8张表、5个视图。扩展完成后不应原样重跑。
- V007包含授权变更，不是只读检查。
- V005和V010分别验证核心与再生纸浆数据。
- V011是一次性新增应用角色迁移，不修改实验数据；不应重复执行。
- V012使用只读事务，验证11张表、114个字段、8个视图、行数、主外键数量、已验证约束、
  延迟组分触发器、所有者、应用读取边界、复配端点和质量复核行。

V012需要能够读取系统目录和全部业务表的管理员连接。应用只读角色本身不能读取底层表。

## 从源文件初始化（不同于备份恢复）

`database/bootstrap/V000__roles.sql` 和 `V000__database.sql` 用于全新实例。
先连接postgres执行roles文件，再执行database文件；它包含独立CREATE DATABASE和连接切换。
不要在既有正式实例中运行这两个一次性脚本，也不要在备份恢复前创建fiber Schema。

从源文件建库的顺序为：V000 → V001/V002/V003 → V004 → 核心导入 → V005 → V006/V007
→ V008/V009 → 再生纸浆导入 → V010 → V011 → V012。
密码通过本地交互设置，脚本没有硬编码密码。完整从Excel重建流程本阶段尚未做新的全程演练；
本阶段实际验收的是最新dump恢复流程和后端接口。
