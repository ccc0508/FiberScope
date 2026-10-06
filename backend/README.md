# 植物纤维只读 API

FastAPI + Psycopg连接池。全部业务查询仅使用8个数据库分析视图。
接口契约见 [API_CONTRACT.md](../docs/API_CONTRACT.md)。

实验数据库连接保持只读；文献问答的历史、评价写入独立SQLite记录库，见[问答记录说明](../docs/QA_HISTORY.md)。
文献表格提取任务、原文证据和候选结果保存于另一个独立SQLite记录库，接口和使用脚本见[表格提取说明](../docs/LITERATURE_EXTRACTION.md)。

## 安装

在项目根目录的PowerShell中执行（本次验证环境为Python 3.14.2）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
Copy-Item backend/.env.example backend/.env
```

编辑本地 `backend/.env`，填写只读账号连接信息。该文件已被Git忽略。
不要使用postgres或fiber_importer；程序只接受fiber_app或fiber_reader。
新环境的fiber_app需要管理员执行一次V011并通过psql的 `\password fiber_app` 设置密码。
本机原数据库已于2026-09-13通过接入脚本应用V011、配置随机密码并完成V012和后端测试。
现有backend/.env已经连接127.0.0.1:5432，不要覆盖它或重复创建账号。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

- 交互文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>

也可以显式使用恢复演练生成的环境文件，不需要复制为backend/.env：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --env-file tmp/restore_时间戳/app.env --host 127.0.0.1 --port 8000
```

环境变量优先于.env文件。不要把环境文件内容复制到日志或提交到Git。

## 验证

集成测试必须显式提供环境文件；未设置时数据库集成用例跳过，不应据此宣称通过完整验收。
优先使用独立恢复实例，测试不会执行正式导入或修改业务数据。

```powershell
$env:TEST_DB_ENV = 'D:\develop\srp2.0\tmp\restore_时间戳\app.env'
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
```

测试包含全部视图逐行逐字段对照、基线数量、稳定分页、筛选、搜索通配符转义、参数注入、
错误编号、CORS、只读权限、空值、两端样本复用、4条质量异常、单位和数据块未知状态。

## 原数据库首次接入

`scripts/connect_original_database.py`用于本机5432端口原数据库首次接入；在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/connect_original_database.py
```

管理员密码通过终端隐藏输入，不保存。脚本先以只读事务运行V005和V010；
若fiber_app不存在，先备份并校验归档，再在事务中创建账号并运行V012。
已有fiber_app时只核验账号和输入的密码，不重置密码或更改权限。
应用配置写入被Git忽略的backend/.env，之后自动运行后端测试。
脚本拒绝覆盖既有backend/.env。本机已接入完成，不需要再次运行。
如测试阶段失败，账号和配置可能已创建，需查看tmp中的无密码结果报告后再处理。

## 当前边界

实验数据接口仅允许GET只读访问；文献问答新增POST提问及GET文献/PDF接口，配置与实验数据库分开，见[文献问答接入说明](../docs/LITERATURE_QA.md)。没有用户登录、实验数据写入或预测接口。
默认仅监听本机。公网使用前需要反向代理访问控制、HTTPS和独立部署验收。
数据库不可用时返回503，不向客户端暴露连接信息。服务不会自动执行迁移或导入。
前端已提供七个页面，运行方式见[前端说明](../frontend/README.md)。
