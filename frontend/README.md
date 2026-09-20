# FiberScope 数据总览前端

Vue 3 + TypeScript + Vite。当前实现一个真实数据总览页面；其他分析页面只展示禁用的导航项，并标注“后续开放”。

## 启动

先在项目根目录启动后端，读取现有原数据库连接配置：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --env-file backend/.env --host 127.0.0.1 --port 8000
```

在另一个终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173/>。Vite将 `/api` 代理到本机8000端口。
前端没有数据库账号、密码或伪造的演示数据；后端不可用时显示错误和重试按钮。

```powershell
npm run build
npm run preview
```

build先执行严格TypeScript检查，再生成dist；preview在4173端口预览构建结果，也代理本机后端。
部署到其他服务器时，需要为 `/api` 配置反向代理；dist本身不包含后端服务。

## 功能与数据口径

- 全库统计：物理样本、核心展示点、循环观测、已收录指标。
- 样本组成：点击类型筛选表格，可再次点击取消；统计图保持全库口径。
- 记录配对率：fiber-paper视图行数 / 样本数，不代表所有指标非空。
- 表格：编码/名称搜索、类型筛选、10/25/50条分页，按后端固定编码顺序显示。
- URL保存q/type/page/size，刷新后保留筛选和分页。
- 点击样本编码打开详情抽屉，显示原料比例、打浆条件、Excel文件、工作表及行号。
- NULL显示为“—”；零仍显示0；复配条件按针叶木/阔叶木分别列出。
- 请求取消和超时处理；加载骨架、空结果、错误编号和重试；手机端折叠左侧导航和表格横向滚动。

## 文件组织

| 文件 | 职责 |
|---|---|
| src/App.vue | 左侧导航、顶部路径、数据说明弹窗 |
| src/pages/Overview.vue | 全库统计、筛选分页、样本表格 |
| src/pages/Association.vue | 纤维与纸张指标散点图、分组相关系数及配对明细 |
| src/analysis.ts | Pearson系数和坐标范围计算 |
| src/pages/Blends.vue | 复配分析、配比趋势、端点说明与实验条件 |
| src/pages/Beating.vue | 打浆分析、指标筛选、趋势图、实验明细 |
| src/components/SampleDetail.vue | 样本详情和来源追溯抽屉 |
| src/api.ts | 请求、超时、取消、错误和数据类型 |
| src/style.css | 统一配色、字号、间距、组件和响应式规则 |
| src/main.ts | Vue和路由入口 |

## 设计参考

参考 [Metabase官方探索教程](https://www.metabase.com/learn/metabase-basics/getting-started/explore-data)
中的卡片分组、图表筛选、数据表格与逐条查看的交互方式。
使用浅色背景、白色卡片、蓝色强调色、清晰的标题层级；固定导航放在左侧。
采用自有FiberScope标识和实现，没有复制Metabase源码或品牌资产。

验证结果见 [前端验收记录](../docs/FRONTEND_VALIDATION.md)。

## 打浆分析

访问 `/beating`。原料可选全部、针叶木、阔叶木；支持打浆度及接口目录中21项核心指标。筛选条件保存在URL中。曲线按打浆转数排序，缺失值断开，零值保留。悬停或键盘聚焦数据点查看数值，点击或Enter/空格打开样本来源抽屉。明细表展示全部筛选记录；手机端图表与表格分别横向滚动。

## 复配分析

访问 `/blends`，默认抗张指数，可切换21项核心指标。横轴为针叶木比例0—100%，阔叶木比例为其余部分。11个展示点包括9个复配样本及2个复用的纯浆端点；明细显示两种原料的打浆转数和打浆度。点击图表或表格可追溯样本来源；筛选保存在URL中。

## 纤维—纸张关联

访问 `/association`，默认长度加权纤维长度与抗张指数。横轴支持12项纤维特性，纵轴支持9项纸张指标；类型和指标选择保存在URL中。每个点代表一个唯一样本，点击或键盘Enter/空格打开来源抽屉。配对明细保留缺失值，统计仅使用成对有限数值，不补零。

Pearson r按当前筛选及样本类型分别计算。少于3对有效数据或任一指标无变化时不显示系数；合并类型可能受实验条件影响，不提供因果或显著性结论。运行 `npm test` 检查相关系数及坐标范围计算。
