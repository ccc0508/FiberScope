# 答题模型关闭思考模式（2026-11-13）

按用户要求，当前 DeepSeek Flash 答题模型改为非思考模式。Planner、SQL 子 Agent、文献子 Agent 与最终综合作答均沿用同一模型配置。

- 本地私有配置：`backend/.env.literature`。
- 服务器私有配置：`/etc/fiberscope/literature-agent-20261111.env`。
- 设置 `RAG_LLM_THINKING_ENABLED=false`，不再指定推理强度。
- 服务器服务已重新加载配置。

通过服务器实际使用的 `ChatAgentAdapter` 执行了一次最小真实请求，确认请求携带 `thinking.type=disabled`，正常返回 `2`，结束原因为 `stop`，输出用量为 1 Token，未返回思考内容。

本次仅验证配置和最小调用，未重新评测综合题、未覆盖旧失败记录，也不能据此声称原先的两道网页失败已经通过端到端复测。

私有配置修改前已备份，配置及备份均不纳入 Git。此次不改变模型名称、检索链路或各项调用预算。
