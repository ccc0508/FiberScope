# FiberScope 纤维视界

将植物纤维实验Excel整理为PostgreSQL数据库，提供可追溯的只读分析API。

当前已实现：11张数据库表、8个分析视图、两套数据导入流程、独立备份恢复演练、
FastAPI实验数据只读后端与自动化集成测试，以及数据总览、打浆、复配、纤维—纸张关联、再生纸浆循环、数据来源、文献问答和文献数据八个页面。
数据来源支持9个已入库Excel文件、309条来源行的筛选与分页，将一行的多种用途合并展示，并关联样本、原始观测及循环分析。

| 入口 | 内容 |
|---|---|
| [后端运行说明](backend/README.md) | 安装、配置、启动与测试 |
| [前端运行说明](frontend/README.md) | 八个页面的启动地址、功能和数据口径说明 |
| [文献问答](docs/LITERATURE_QA.md) | 文献快照、模型配置、引用原文、接口与验收 |
| [问答评测起点](docs/QA_BASELINE.md) | qa-v1-20261024未优化代码、配置、文献索引快照与校验 |
| [问答评测题集](docs/QA_EVALUATION.md) | 30题、78个评分要点、参考答案和原文证据，含拒答/部分可答/原文冲突 |
| [首轮问答基线报告](docs/QA_BASELINE_REPORT_20261025.md) | 原版30题真实运行、AI来源初评和逐题依据；要点均分94.17%，严格达标20/30，待独立专家复核 |
| [v2评测修正与注入测试](docs/QA_EVALUATION_V2.md) | 文本32题、正常/攻击对照、图像边界分组；3道跨文献题延期，含强校验与可选要点评分 |
| [独立模型评分](docs/QA_INDEPENDENT_JUDGE.md) | GPT-6.1 Sol独立评分、原文校验、失败补评和分组汇总，保留完整依据与用量 |
| [v2完整文本评测报告](docs/QA_BASELINE_V2_REPORT_20261026.md) | 原版32题全部完成独立评分，要点均分90.10%，严格达标24/32；含8道错题及评测自身的稳定性问题 |
| [三轮评分稳定性报告](docs/QA_JUDGE_STABILITY_20261026.md) | 新两轮有效31/32和32/32；共同31题均分89.78%/90.32%/90.59%，6题严格判定翻转，含失败项与用量 |
| [Jev独立评分接入](docs/QA_JEV_JUDGE.md) | OpenRouter原生Decisions接口、逐项判断、原文编号定位、独立上下文与费用记录 |
| [Jev三轮实测与效率对照](docs/QA_JEV_EVALUATION_20261026.md) | 96次调用，三轮均分88.02%/88.02%/88.54%；API报告费用约0.26866美元，中位请求耗时约0.9秒 |
| [GPT与Jev评分分歧复核](docs/QA_JUDGE_DISAGREEMENT_REVIEW_20261026.md) | 对照原回答、检索片段与PDF核对16题，区分裁判误判与规则歧义；不覆盖历史分数 |
| [统一评分标准v3](docs/QA_SCORING_V3.md) | 统一半分边界、全文与检索范围、联合引用完整性；GPT/Jev共用规则与指纹，旧评分保留 |
| [同一回答独立双评](docs/QA_DUAL_JUDGE.md) | 同一批32份回答按v3规则由GPT/Jev分别评分；单轮对照、分歧清单和一致项抽查 |
| [GPT-6 Luna评分接入](docs/QA_LUNA_JUDGE.md) | OpenRouter独立凭证、v3评分、32题输入与API费用记录；32题评分完成 |
| [Luna与Jev正式对照](docs/QA_LUNA_JEV_V3_REPORT_20261027.md) | 同32题必答均分89.06%/88.02%，要点一致率93.90%；13题分歧、源文抽查和全部补评费用 |
| [完整题目答案与双评理由](docs/QA_FULL_QUESTIONS_AND_REVIEWS_20261027.md) | 32题原回答、参考答案、逐项分数与原始评语；附其余5题状态及原文证据，另有可搜索打印的[浏览器版](docs/QA_FULL_QUESTIONS_AND_REVIEWS_20261027.html) |
| [服务器部署说明](deploy/ubuntu/README.md) | 通用部署结构、数据迁移、服务自启与定时备份 |
| [文献提取与审核](docs/LITERATURE_EXTRACTION.md) | 整篇自动发现表格与正文数据、原文对照、审核版本、导出及基准评测 |
| [前端验收记录](docs/FRONTEND_VALIDATION.md) | 构建、真实浏览器交互和响应式检查 |
| [全站验收记录](docs/FULL_SITE_VALIDATION.md) | 六个页面的数据核对、完整流程、异常状态和响应式回归 |
| [API契约](docs/API_CONTRACT.md) | 10个实验数据接口、7个文献及问答记录接口、9个提取与审核接口 |
| [恢复与验收](docs/RECOVERY.md) | 独立恢复实例与验收脚本适用阶段 |
| [本阶段验收记录](docs/VALIDATION_REPORT.md) | 实际完成范围、数量与限制 |
| [数据库迁移](database/migrations/) | V001—V012 |
| [仓库内容管理](docs/REPOSITORY_CONTENTS.md) | 开发资料、私有研究材料和生成产物的存放边界 |

数据基线：61个物理样本、63个实验展示点；再生纸浆131条观测、47个循环汇总点、4条质量复核。
全部12项纤维特性和9项核心纸张性能保留。原始Excel不修改，未知单位和处理条件不推断。

`data/`中保留建库和回归测试所需的来源及评测资料，仅用于本项目授权用途。
个人汇报、项目分工、历史交接、生成文档和重复材料包保存在仓库外的私有归档中。
`output/`、`backups/`、`tmp/`、真实环境文件和依赖目录不进入Git；详见[仓库内容管理](docs/REPOSITORY_CONTENTS.md)。
2026-09-13已完成原数据库验收，创建fiber_app，并将本机API接入原数据库5432端口；
10个接口实际HTTP检查通过，8个数据接口与原数据库逐行对照一致。实验数据未修改。
支持Ubuntu单机部署，通过`/fiberscope/`挂载；API仅监听本机，由Nginx提供入口，见[部署说明](deploy/ubuntu/README.md)。

文献问答与提取记录长期保存在服务端，所有访问者可查看和导出，并可修改文献审核；问答评价保留原提交浏览器权限。
记录保存在独立的`.rag-data/qa_history.sqlite3`，不写入实验数据库；备份及全量导出见[问答记录说明](docs/QA_HISTORY.md)。
