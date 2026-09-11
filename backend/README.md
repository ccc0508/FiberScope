# 植物纤维只读 API

FastAPI + Psycopg连接池。全部业务查询仅使用8个数据库分析视图。
接口契约见 [API_CONTRACT.md](../docs/API_CONTRACT.md)。

## 安装

在项目根目录的PowerShell中执行（本次验证环境为Python 3.14.2）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
Copy-Item backend/.env.example backend/.env
```

编辑本地 `backend/.env`，填写只读账号连接信息。该文件已被Git忽略。
不要使用postgres或fiber_importer；程序只接受fiber_app或fiber_reader。
fiber_app需要管理员执行一次V011并通过psql的 `\password fiber_app` 设置密码。
现有正式库尚未应用V011，本阶段只在独立恢复实例中验证了它。

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

## 当前边界

API只有GET数据服务，没有用户登录、写入、预测或Agent接口。
默认仅监听本机。公网使用前需要反向代理访问控制、HTTPS和独立部署验收。
数据库不可用时返回503，不向客户端暴露连接信息。服务不会自动执行迁移或导入。
此阶段尚无前端页面。
