# Agentic RAG 服务器更新记录（2026-11-06）

## 部署结果

- 主机：Ubuntu-wkkw，Ubuntu 24.04，43.108.105.92。
- 应用代码基线：`eaa2350`，加上本次部署配置调整；未包含工作区未提交的设计实验及预测模型文件。
- 当前发布目录：`/opt/fiberscope/releases/agent-eaa2350-20261106`。
- 上一发布目录：`/opt/fiberscope/releases/8c5b51a`，保留用于回滚。
- `/opt/fiberscope/current` 指向新发布目录；前端构建 base 为 `/fiberscope/`。
- 文献库升级为本地当前的八篇论文版本：MinerU 解析、Qwen 多模态索引、Agentic RAG、DeepSeek Flash。原服务器 PostgreSQL、问答历史、提取审核记录保留。
- 新索引目录：`/var/lib/fiberscope/rag-data/index-versions/paper-collection-definitions-20261106`。
- 私有配置：`/etc/fiberscope/literature-agent-20261106.env`，权限 0640；旧配置保留，密钥未入 Git。

已从外部浏览器验证的入口：
https://bidding-sea-tired-committees.trycloudflare.com/fiberscope/

此入口运行在服务器，关闭本地电脑不影响它；仍属于临时隧道地址，重建隧道可能改变地址。服务器本机访问 `http://43.108.105.92/fiberscope/` 返回 200，但本次本地外部直连 IP 超时或空响应，不能据此宣称 IP 入口已对外验收通过。

## 部署配置调整

1. Nginx API 代理超时从 120 秒改为 310 秒，覆盖 Agent 240 秒及后端 300 秒预算。
2. 安装 PyMuPDF 1.28.0 和系统包 poppler-utils，支持 PDF 页面及图片处理。
3. 备份脚本动态发现持久化目录内 SQLite 数据库，并使用 SQLite 在线备份，包含新轨迹库和版本化索引库。

## 验证

- 前端生产构建成功；前端测试 15 项通过。
- Agent answer、loop、context、literature tools 相关测试，本地及 Linux 服务器各 35 项通过。
- 服务器 pip check、nginx 配置检查通过。
- 应用、Nginx、Cloudflare 隧道服务 active；应用切换后重启计数为 0，观测内存峰值约 443 MiB。
- 健康接口和数据库连接正常；文献目录返回八篇论文；原有问答及九条提取任务可查看。
- 真实 HTTP 文献问答完成，返回回答和引用；浏览器查看原图接口返回 200。
- 从公网浏览器提交非论文算术问题成功，回答 40 到 50 增幅为 25%；确认启用 Agent 目录版本、10 次模型调用、8 次工具调用、2 次检索及 240 秒预算。
- 未在本轮重新跑完整评测集，未新增提取任务，也未验证新一次完整图片推理流程。

## 备份与回滚

更新前备份：`/var/backups/fiberscope/20261106T133251Z`。

更新后备份：`/var/backups/fiberscope/20261106T134456Z`，数据库转储、角色及记录/配置归档均已生成。此次确认备份成功，不等同于重新执行完整恢复演练。

部署材料、原 Nginx 配置位于 `/root/fiberscope-update-20261106`。回滚时停止 fiberscope，将 current 链接切回旧发布目录，恢复该目录中的原 Nginx 配置，检查 nginx 配置后启动应用并 reload nginx，再验证健康接口。旧发布配置保持原样。不要仅为回滚代码覆盖持久化用户数据；确需恢复数据时先备份当前数据，再使用更新前备份。

## 运维遗留

安装系统依赖时 needrestart 尝试重启已有的阿里云安全代理 `aegis.service`，该服务启动失败；再次尝试仍失败，原更新进程仍存在。没有终止安全代理进程或修改其配置。此问题需独立排查；当前平台、Nginx 和隧道服务正常。
