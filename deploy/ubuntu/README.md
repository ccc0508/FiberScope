# Ubuntu单机部署

部署结构：Nginx提供`/fiberscope/`，后端仅监听`127.0.0.1:8010`，PostgreSQL仅本机访问。
同机原有网站可继续使用根路径；服务保持一个worker，与SQLite记录库的单实例锁匹配。

## 目录

| 路径 | 内容 |
| --- | --- |
| `/opt/fiberscope/releases/<version>` | 版本代码和前端构建 |
| `/opt/fiberscope/current` | 当前版本软链接 |
| `/opt/fiberscope/venv` | 在Linux重新安装的Python环境 |
| `/etc/fiberscope/backend.env` | 数据库连接配置，root:fiberscope，0640 |
| `/etc/fiberscope/literature.env` | 私有模型配置，root:fiberscope，0640 |
| `/var/lib/fiberscope/rag-data` | 文献索引、PDF、问答、提取与审核记录 |
| `/var/www/fiberscope-public/fiberscope` | 指向当前版本的frontend/dist |

将版本内`.rag-data`链接到持久数据目录，并将`backend/.env`、`backend/.env.literature`
分别链接到上述私有配置。私有配置和实际业务数据不得进入代码包或Git。

## 前端与反向代理

```sh
npm ci
npm run build -- --base=/fiberscope/
```

`BASE_URL`同时作用于路由、接口、PDF、下载和图标。根路径构建继续使用默认`/`。
将`fiberscope.nginx.conf`包含在所选server块中；应先备份原配置，再执行`nginx -t`并reload。
Cookie路径必须随代理改写，才能在子路径下保存提交会话、幂等状态和问答评价权限。
代理覆盖Host及转发头，保证Origin检查正确；后端端口不得直接开放公网。

本配置复用已有HTTP入口。HTTPS需要域名和可用TLS入口；若443已有服务，应另行协调，不能直接覆盖。

## 数据迁移与验收

1. 保存原服务器配置和应用状态，准备独立的用户、版本及数据目录。
2. 使用PostgreSQL 18的逻辑备份恢复实验库，先创建所需角色；应用使用独立随机密码及只读角色。
3. SQLite使用在线备份，包含WAL中已提交内容；同时迁移PDF、Chroma索引和提取检查点。
   迁移前后确认没有处理中任务，文件指纹一致；不能只复制Git代码。
4. 从源库只读导出八个视图的行数及内容指纹，与目标库逐项比较；执行V012并检查只读权限。
5. 启用`fiberscope.service`，验证健康、筛选、分页、PDF、页图、导出、Origin和Cookie。
6. 运行后端测试及实际浏览器检查，检查原网站仍可访问、内存及磁盘占用，并完成持久数据备份。

部署后通过systemd开机启动及故障重启。当前问答、提取各只能并行处理一个任务；增加worker之前需调整任务与记录协调。
容量以实际监测为准：2GB机器还运行其他应用时，应限制数值库线程、并发和服务内存，避免影响原服务。
