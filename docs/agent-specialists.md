# 一层调度＋SQL／文献子Agent v1

实现入口：`backend/literature_rag/application/specialist_agent.py`。复用现有工具执行器、只读SQL、EXPLAIN、AgentLoop、证据账本和引用校验，不使用新Agent框架。没有递归子Agent或动态重规划。

## 路由与职责

主Agent通过原生Function Calling输出唯一route_task，程序用Pydantic验证，route为direct/clarify/sql/literature/both。直接回答或澄清不创建子任务、不虚称完成研究复核。需要实际字段知识的歧义交给SQL子Agent先读目录。

- SQL子Agent仅可调用describe_experiment_data、query_experiment_data、calculate_change，没有论文目录上下文。要求先读真实字段、单位和统计粒度；缺条件时返回needs_clarification。权限不仅由提示词约束，工具schema和执行端都检查。
- 文献子Agent只得到文献工具与现有论文目录，不能调用数据库工具。保留检索、目录/章节、表格、原图和计算能力。
- 混合任务先SQL后文献，顺序执行。SQL需要澄清时不继续执行文献任务。两者返回status、summary、missing_choices、limitations的JSON。格式处理见下节；子任务执行未完成不会伪装成格式问题重试。
- 主Agent统一核对证据并组织最终回答，不把数据库观测与论文机理混成因果证明。子Agent不做完整答案复核，避免每层重复审校。父Agent仅获得实际送达子Agent、且在父上下文预算内的工具结果；图片结论明确为子Agent的视觉解释，父Agent没有重新看原图，不得声称直接查看。

## 共享预算

### 结构化输出容错（2026-11-07）

路由结果与每个子Agent交接结果先清理首尾空白、BOM以及完整包裹JSON的代码围栏，然后执行原有严格字段校验。不会从解释文字中猜测截取JSON，也不会自动丢弃未知字段或补造必填值。

空参数、损坏JSON、额外字段等校验失败时，每个交接边界最多发起一次格式纠正。纠正不提供业务工具，只提供原始输出、对应任务、结构定义和校验错误，要求保留事实、缺口、引用与原任务意图。再次失败就停止；纠正成功只代表格式可解析，不代表事实正确，仍进入父Agent复核和引用校验。

纠正调用计入全局模型次数与时间，不重置子任务预算；路由纠正预留两次后续调用，子结果纠正至少预留一次父Agent整理调用，同时保留原有收尾时间。剩余预算或上下文容量不足时明确记录跳过原因。

`format_checks`保存原始输出、初始校验错误、是否清理包装、是否尝试纠正、纠正输出和最终状态。全局模型轨迹增加原始`raw_message`，保留供应商原生参数字符串，避免损坏参数解析成空字典后丢失原文。子轨迹中的原答案不被纠正结果覆盖。

本次46项相关测试通过（包含18项调度测试）。旧失败原文离线回放中，SQL08、SQL14仅去掉围栏即可通过结构校验，其余12个格式失败仍需要模型纠正。尚未对这批题进行真实模型重跑，不将模拟测试结果当作真实完成率提升；旧基线记录保持不变。

网站开启新架构时总上限12次模型调用（包括路由、两个子任务、最终整理和引用纠正），8次实际工具调用，2次检索，通常240秒。旧单Agent仍为10次模型调用。新架构的12是显式增加总上限，不是每个子Agent各12；尚未验证最优预算。

子任务按剩余数量分配局部调用额度；共享截止时间不重置，为父整理预留时间和2次模型调用。子Agent仍受现有单次上下文/图片预算约束。工具共享run_id且顺序执行，证据编号由同一SQLite账本分配；子任务轨迹有独立child_id。主Agent最终引用只允许实际收到的证据编号，必要时在剩余预算内纠正一次。

记录包含plan、children（任务、结构化结果、完整子轨迹）、全局model_calls/tool_calls、budget_usage、citation_validation及最终状态。工具失败与模型失败均留痕，不产生虚假引用。

## 启用与回退

CLI独立试跑：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/run_literature_agent.py --architecture specialists --question "当前规范样本有多少个？" --library .rag-data/index-versions/paper-collection-definitions-20261106 --run-id specialists-smoke-unique
```

网站配置`backend/.env.literature`中`LITERATURE_AGENT_ARCHITECTURE=specialists`，重启后生效。设为single回到当前单Agent。默认single保持不变，现有评测脚本不传architecture时仍跑原版，不污染冻结基线。旧提示词对照文件只能用于single模式。

## 当前验证与限制

121项后端相关测试通过，包括直接路由、两种工具隔离、越权请求拒绝、澄清中止后续任务、共享预算/截止时间、父级引用修正、上下文未送达证据不可引用、旧架构兼容。Fake模型测试用于验证调度程序行为，不代表真实模型路由/答题准确率。

本轮最小DeepSeek请求仍返回HTTP500，因此尚未完成真实新架构问答或30题文献、20题SQL回归。代码部署为可选入口，网站默认不切换。模型恢复后先测直接/SQL/文献/混合/澄清五条路径，再做同题回归。尚未解决的模型语义错误不能宣称靠架构拆分已经消失。

v1不包含：多轮持久会话、跨任务记忆、递归委派、自动多次重规划、子任务失败后自动回退旧流程、成本美元硬上限。子Agent需要澄清是结构化协议与模型判断，不是通过题目关键词强制拦截。
