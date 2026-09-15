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
| src/pages/Overview.vue | 全库统计、筛选分页、样本表格及质量记录 |
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
