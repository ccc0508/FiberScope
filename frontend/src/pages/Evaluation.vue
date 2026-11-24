<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Activity, ArrowLeft, BookOpen, Database, FlaskConical, History, Layers, MessageSquare, Play, Search } from "lucide-vue-next";
import { apiPath } from "../urls";

type Group = "literature" | "sql" | "mixed" | "non_paper";
type Case = { id: string; group: Group; category: string; question: string };
type Row = {
  id: string; group: Group; status: string; score: number | null; calibrated_score: number | null;
  duration_ms: number | null; error: string | null; metrics: Record<string, unknown>;
};
type Manifest = {
  commit: string | null; architecture: string; cases_hash?: string; runtime_hash: string;
  configuration: Record<string, string | null>; rubrics: Record<Group, string>;
  budget: { models: number; tools: number; seconds: number }; library: Record<string, string>; judge: string;
};
type Run = {
  id: string; created_at: string; parent: string | null; manifest: Manifest; cases: Row[];
  database_fingerprint: string | null; deepseek_usage: { total_tokens: number; incomplete: boolean };
};
type Grade = { score: number; model: string; metrics: Record<string, unknown>; review: Record<string, unknown>; decisions: Record<string, unknown>; usage: Record<string, number>; duration_ms?: number };
type Answer = {
  answer: string; langfuse?: { url?: string }; tool_calls: unknown[];
  model_calls: Array<{ stage: string; usage?: Record<string, number> }>;
  evidence_check?: Record<string, unknown>; evidence_supplement_planning?: Record<string, unknown>;
};
type Detail = Row & { question: string; reference: Record<string, unknown>; reference_results: unknown[];
  answer: Answer | null; grade: Grade | null; calibrations: Array<{ timestamp: string; score: number; reason: string }> };

const suites = [
  { key: "literature", name: "文献题", desc: "论文证据与引用", icon: BookOpen },
  { key: "sql", name: "SQL 题", desc: "实验数据与口径", icon: Database },
  { key: "mixed", name: "综合题", desc: "文献与数据整合", icon: Layers },
  { key: "non_paper", name: "日常题", desc: "直接作答与格式", icon: MessageSquare },
] as const;
const label: Record<string, string> = {
  queued: "排队", answering: "作答中", scoring: "Jev 评分中", scored: "已评分",
  answer_failed: "作答失败", score_failed: "评分失败", setup_failed: "准备失败", interrupted: "已中断",
};
const metricLabels: Record<string, string> = {
  point_score: "要点分", fact_support: "事实充分支持率（%）", citation_precision: "单条引用有效率（%）",
  citation_coverage: "引用组完整覆盖率（%）", boundary: "证据边界（满分 2）", strict_pass: "严格通过",
  sql_attempts: "SQL 调用", sql_completed: "SQL 成功", exact_reference_matches: "参考行集精确匹配",
  covered_reference_results: "参考行已覆盖", reference_checks: "可对照查询数",
  tool_accuracy: "工具调用评分", passed: "日常题通过",
};

const savedToken = "fiberscope:evaluation:access";
const token = ref(sessionStorage.getItem(savedToken) ?? "");
const unlocked = ref(false);
const manifest = ref<Manifest>();
const catalog = ref<Case[]>([]);
const chosen = ref(new Set<string>());
const filter = ref<Group | "all">("all");
const search = ref("");
const tab = ref<"new" | "history">("new");
const history = ref<Run[]>([]);
const historySearch = ref("");
const historyGroup = ref<Group | "all">("all");
const current = ref<Run>();
const baselineId = ref("");
const detail = ref<Detail>();
const busy = ref(false);
const error = ref("");
const calibrated = ref<number>();
const calibrationReason = ref("");
let timer: number | undefined;

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase();
  return catalog.value.filter(item => (filter.value === "all" || filter.value === item.group) &&
    (!query || (item.id + " " + item.question + " " + item.category).toLowerCase().includes(query)));
});
const active = (status: string) => ["queued", "answering", "scoring"].includes(status);
const score = (row: Row) => row.calibrated_score ?? row.score;
const stats = (run: Run) => {
  const values = run.cases.flatMap(row => score(row) == null ? [] : [score(row)!]);
  const settled = run.cases.filter(row => !active(row.status)).length;
  return { values: values.length, settled, mean: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null };
};
const progress = computed(() => current.value ? stats(current.value) : undefined);
const baseline = computed(() => history.value.find(run => run.id === baselineId.value));
const filteredHistory = computed(() => {
  const query = historySearch.value.trim().toLowerCase();
  return history.value.filter(run => (historyGroup.value === "all" || run.cases.some(row => row.group === historyGroup.value)) &&
    (!query || (date(run.created_at) + " " + (run.manifest.commit ?? "")).toLowerCase().includes(query)));
});
const pairs = computed(() => {
  const old = new Map(baseline.value?.cases.map(row => [row.id, row]));
  return (current.value?.cases ?? []).flatMap(row => {
    const other = old.get(row.id);
    const left = other ? score(other) : null;
    const right = score(row);
    return left == null || right == null ? [] : [{ id: row.id, left, right, delta: right - left }];
  });
});
const compared = computed(() => pairs.value.length ? pairs.value.reduce((total, item) => total + item.delta, 0) / pairs.value.length : null);
const configDifferences = computed(() => {
  if (!baseline.value || !current.value) return [];
  const a = baseline.value.manifest;
  const b = current.value.manifest;
  return [
    ["Agent", a.runtime_hash, b.runtime_hash],
    ["模型或配置", JSON.stringify(a.configuration), JSON.stringify(b.configuration)],
    ["文献索引", JSON.stringify(a.library), JSON.stringify(b.library)],
    ["数据库", baseline.value.database_fingerprint, current.value.database_fingerprint],
    ["评分规则", JSON.stringify(a.rubrics), JSON.stringify(b.rubrics)],
    ["运行预算", JSON.stringify(a.budget), JSON.stringify(b.budget)],
  ].filter(([, left, right]) => left !== right).map(([name]) => name);
});
const display = (value: number | null | undefined) => value == null ? "—" : Number(value.toFixed(2)).toString();
const tokenCount = (usage: Run["deepseek_usage"]) => usage.incomplete && !usage.total_tokens ? "未知" : usage.total_tokens.toLocaleString("zh-CN");
const date = (value: string) => new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
const json = (value: unknown) => JSON.stringify(value, null, 2);
const safeTrace = computed(() => {
  const url = detail.value?.answer?.langfuse?.url;
  return url?.startsWith("https://") ? url : undefined;
});

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiPath("evaluation" + path), {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: "Bearer " + token.value.trim(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) unlocked.value = false;
    throw new Error(data.error?.message ?? data.detail ?? ("请求失败（" + response.status + "）"));
  }
  return data as T;
}

async function useRequest(action: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  try { await action(); }
  catch (problem) { error.value = problem instanceof Error ? problem.message : "操作未完成。"; }
  finally { busy.value = false; }
}

async function refresh() {
  const { runs } = await request<{ runs: Run[] }>("/runs");
  history.value = runs;
  if (current.value) {
    const refreshed = runs.find(run => run.id === current.value?.id);
    if (refreshed) {
      current.value = refreshed;
      const opened = detail.value;
      if (opened && refreshed.cases.find(row => row.id === opened.id)?.status !== opened.status) {
        const updated = await request<Detail>("/runs/" + refreshed.id + "/cases/" + opened.id);
        if (current.value?.id === refreshed.id && detail.value === opened) {
          detail.value = updated;
          calibrated.value = score(updated) ?? undefined;
        }
      }
    }
  }
}

async function unlock() {
  await useRequest(async () => {
    const data = await request<{ cases: Case[]; manifest: Manifest }>("/cases");
    catalog.value = data.cases;
    manifest.value = data.manifest;
    sessionStorage.setItem(savedToken, token.value.trim());
    unlocked.value = true;
    await refresh();
  });
}

function choose(group: Group | "all") {
  filter.value = group;
  search.value = "";
  chosen.value = new Set(catalog.value.filter(item => group === "all" || item.group === group).map(item => item.id));
}
function toggle(id: string) {
  const next = new Set(chosen.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  chosen.value = next;
}
function openRun(run: Run) {
  current.value = run;
  baselineId.value = run.parent ?? "";
  detail.value = undefined;
  tab.value = "history";
}
async function openHistory() {
  tab.value = "history";
  await useRequest(refresh);
}
async function start(path: string, body: unknown) {
  await useRequest(async () => {
    const { id } = await request<{ id: string }>(path, body);
    openRun(await request<Run>("/runs/" + id));
    await refresh();
  });
}
async function openCase(id: string) {
  const run = current.value;
  if (!run) return;
  await useRequest(async () => {
    const next = await request<Detail>("/runs/" + run.id + "/cases/" + id);
    if (current.value?.id !== run.id) return;
    detail.value = next;
    calibrated.value = score(next) ?? undefined;
    calibrationReason.value = "";
  });
}
async function saveCalibration() {
  if (!current.value || !detail.value || calibrated.value == null || !calibrationReason.value.trim()) return;
  const path = "/runs/" + current.value.id + "/cases/" + detail.value.id;
  await useRequest(async () => {
    detail.value = await request<Detail>(path + "/calibration", { score: calibrated.value, reason: calibrationReason.value.trim() });
    calibrationReason.value = "";
    await refresh();
  });
}
function usage(calls: Array<{ usage?: Record<string, number> }> = []) {
  const values = calls.flatMap(call => typeof call.usage?.total_tokens === "number" ? [call.usage.total_tokens] : []);
  if (!calls.length) return "未调用";
  if (!values.length) return "未知";
  return values.reduce((a, b) => a + b, 0).toLocaleString("zh-CN") + (values.length !== calls.length ? "（部分记录）" : "");
}

onMounted(() => {
  if (token.value) void unlock();
  timer = window.setInterval(() => {
    if (unlocked.value && !busy.value && history.value.some(run => run.cases.some(row => active(row.status)))) {
      void refresh().catch(problem => { error.value = problem instanceof Error ? problem.message : "进度同步失败。"; });
    }
  }, 2500);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <div class="evaluation">
    <header class="top">
      <div class="identity"><FlaskConical :size="22" /><span>FiberScope</span><span class="separator"></span><span>评测工作台</span></div>
      <RouterLink to="/"><ArrowLeft :size="15" /> 返回平台</RouterLink>
    </header>

    <main class="workspace">
      <section class="intro">
        <div>
          <p class="intro-label"><Activity :size="16" /> Agent 回归评测</p>
          <h1>评测工作台</h1>
          <p>运行固定题库，检查答案、证据和 Jev 评分。</p>
        </div>
        <div v-if="manifest && unlocked" class="runtime">
          <span>当前执行版本</span>
          <strong>{{ manifest.commit?.slice(0, 7) ?? "部署版本" }}</strong>
          <small>{{ manifest.configuration.RAG_LLM_MODEL ?? manifest.architecture }} · {{ catalog.length }} 道题</small>
        </div>
      </section>

      <p v-if="error" class="notice" role="alert">{{ error }}</p>
      <form v-if="!unlocked" class="unlock panel" @submit.prevent="unlock">
        <h2>进入工作台</h2>
        <label for="eval-token">访问令牌</label>
        <div class="unlock-row">
          <input id="eval-token" v-model="token" type="password" autocomplete="current-password" required />
          <button class="primary" :disabled="busy">进入</button>
        </div>
      </form>

      <template v-else>
        <div class="tabs" aria-label="评测视图">
          <button :aria-pressed="tab === 'new'" @click="tab = 'new'"><Play :size="15" /> 新建评测</button>
          <button :aria-pressed="tab === 'history'" @click="openHistory"><History :size="16" /> 评测历史 <span>{{ history.length }}</span></button>
        </div>

        <div v-if="tab === 'new'" class="setup">
          <section class="panel selection">
            <div class="panel-title"><h2>选择题目</h2><button class="secondary" @click="choose('all')">选择全部 {{ catalog.length }} 题</button></div>
            <div class="suites">
              <button v-for="suite in suites" :key="suite.key" :class="{ selected: filter === suite.key }" @click="choose(suite.key)">
                <component :is="suite.icon" :size="18" />
                <strong>{{ suite.name }}</strong>
                <span class="count">{{ catalog.filter(item => item.group === suite.key).length }}</span>
                <small>{{ suite.desc }}</small>
              </button>
            </div>
            <div class="toolbar">
              <label class="query"><Search :size="16" /><input v-model="search" placeholder="搜索题号或题目" aria-label="搜索题号或题目" /></label>
              <select v-model="filter" aria-label="按题组筛选">
                <option value="all">全部题组</option>
                <option v-for="suite in suites" :key="suite.key" :value="suite.key">{{ suite.name }}</option>
              </select>
              <button class="plain" @click="chosen = new Set()">清空选择</button>
            </div>
            <div class="question-list">
              <label v-for="item in filtered" :key="item.id" class="question">
                <input type="checkbox" :checked="chosen.has(item.id)" @change="toggle(item.id)" />
                <code>{{ item.id }}</code><span>{{ item.question }}</span>
              </label>
              <p v-if="!filtered.length" class="empty">没有匹配的题目。</p>
            </div>
          </section>
          <aside class="panel launch">
            <h2>本次运行</h2>
            <div class="tally"><strong>{{ chosen.size }}</strong><span>道已选题目</span></div>
            <dl>
              <div><dt>答题方式</dt><dd>每题独立上下文</dd></div>
              <div><dt>评分模型</dt><dd>Jev</dd></div>
              <div v-if="manifest"><dt>单题预算</dt><dd>{{ manifest.budget.models }} 次模型 · {{ manifest.budget.tools }} 次工具</dd></div>
              <div><dt>执行方式</dt><dd>后台逐题运行</dd></div>
            </dl>
            <button class="primary start" :disabled="busy || !chosen.size" @click="start('/runs', { ids: [...chosen] })">
              <Play :size="16" /> 开始评测
            </button>
            <p class="hint">运行会产生模型调用费用。离开页面后可从历史继续查看。</p>
          </aside>
        </div>

        <div v-else class="history-layout">
          <aside class="panel archive">
            <h2>历史批次</h2>
            <div v-if="history.length" class="archive-filter">
              <input v-model="historySearch" placeholder="日期或提交号" aria-label="搜索评测历史" />
              <select v-model="historyGroup" aria-label="筛选评测历史题组">
                <option value="all">全部题组</option>
                <option v-for="suite in suites" :key="suite.key" :value="suite.key">{{ suite.name }}</option>
              </select>
            </div>
            <p v-if="!filteredHistory.length" class="empty">{{ history.length ? "没有匹配的评测。" : "还没有评测记录。" }}</p>
            <button v-for="run in filteredHistory" :key="run.id" :aria-pressed="current?.id === run.id" @click="openRun(run)">
              <strong>{{ date(run.created_at) }}</strong>
              <small>{{ run.cases.length }} 题 · {{ stats(run).settled }}/{{ run.cases.length }} 完成 · {{ run.manifest.commit?.slice(0, 7) ?? "部署版" }}</small>
              <small>DeepSeek {{ tokenCount(run.deepseek_usage) }} Token{{ run.deepseek_usage.incomplete ? " · 记录不全" : "" }}</small>
              <span>{{ display(stats(run).mean) }}</span>
            </button>
          </aside>

          <section v-if="current && progress" class="panel report">
            <div class="panel-title"><div><h2>本轮结果</h2><p class="hint">{{ date(current.created_at) }} · {{ current.manifest.commit?.slice(0, 7) ?? "部署版" }}</p></div>
              <button v-if="current.cases.some(row => ['answer_failed', 'setup_failed', 'interrupted'].includes(row.status))"
                class="secondary" :disabled="busy || progress.settled !== current.cases.length" @click="start('/runs/' + current.id + '/retry', {})">补跑失败题</button>
            </div>
            <div class="summary">
              <div><small>已结束／计划</small><strong>{{ progress.settled }}/{{ current.cases.length }}</strong></div>
              <div><small>已评分</small><strong>{{ progress.values }}</strong></div>
              <div><small>已评分均分</small><strong>{{ display(progress.mean) }}</strong></div>
              <div><small>DeepSeek Token 总量</small><strong>{{ tokenCount(current.deepseek_usage) }}</strong>
                <small v-if="current.deepseek_usage.incomplete">记录不全</small></div>
            </div>
            <progress :value="progress.settled" :max="current.cases.length" aria-label="评测进度"></progress>
            <div class="group-summary">
              <div v-for="suite in suites.filter(s => current?.cases.some(row => row.group === s.key))" :key="suite.key">
                <span>{{ suite.name }}</span>
                <b>{{ display(stats({ ...current, cases: current.cases.filter(row => row.group === suite.key) }).mean) }}</b>
              </div>
            </div>
            <div class="toolbar compare">
              <label>对照批次 <select v-model="baselineId">
                <option value="">请选择</option>
                <option v-for="run in history.filter(run => run.id !== current?.id)" :key="run.id" :value="run.id">{{ date(run.created_at) }}</option>
              </select></label>
              <span v-if="baseline">{{ pairs.length }} 道共同已评分题 · 平均变化 {{ display(compared) }}</span>
            </div>
            <p v-if="configDifferences.length" class="hint">配置有差异：{{ configDifferences.join("、") }}</p>
            <div class="results">
              <table>
                <thead><tr><th>题号</th><th>状态</th><th>Jev</th><th>校准</th><th v-if="baseline">分数变化</th><th>作答耗时</th></tr></thead>
                <tbody><tr v-for="row in current.cases" :key="row.id" :class="{ focused: row.id === detail?.id }">
                  <td><button class="text-link" @click="openCase(row.id)">{{ row.id }}</button></td>
                  <td>{{ label[row.status] ?? row.status }}</td><td>{{ display(row.score) }}</td><td>{{ display(row.calibrated_score) }}</td>
                  <td v-if="baseline">{{ display(pairs.find(pair => pair.id === row.id)?.delta) }}</td>
                  <td>{{ row.duration_ms == null ? "—" : display(row.duration_ms / 1000) + " s" }}</td>
                </tr></tbody>
              </table>
            </div>

            <template v-if="detail">
              <article class="case-detail">
                <div class="panel-title"><h2>{{ detail.id }} 逐题详情</h2>
                  <button v-if="detail.answer?.answer" class="secondary" :disabled="busy || progress.settled !== current.cases.length"
                    @click="start('/runs/' + current.id + '/rescore', { ids: [detail.id] })">只重跑评分</button>
                </div>
                <p>{{ detail.question }}</p>
                <p v-if="detail.error" class="notice">{{ detail.error }}</p>
                <div v-if="detail.grade" class="group-summary">
                  <div><span>Jev 要点或综合分</span><b>{{ display(detail.grade.score) }}</b></div>
                  <div v-for="(value, key) in detail.grade.metrics" v-show="metricLabels[key]" :key="key">
                    <span>{{ metricLabels[key] }}</span><b>{{ typeof value === "number" ? display(value) : value === true ? "是" : value === false ? "否" : "—" }}</b>
                  </div>
                </div>
                <p v-if="detail.answer" class="hint">
                  答题 Token {{ usage(detail.answer.model_calls.filter(call => call.stage !== 'evidence_check')) }} ·
                  运行时验收 {{ usage(detail.answer.model_calls.filter(call => call.stage === 'evidence_check')) }} ·
                  离线评分 {{ usage(detail.grade ? [{ usage: detail.grade.usage }] : []) }} ·
                  工具 {{ detail.answer.tool_calls.length }} 次
                  <span v-if="detail.grade?.duration_ms != null"> · 评分 {{ display(detail.grade.duration_ms / 1000) }} s</span>
                  <a v-if="safeTrace" :href="safeTrace" target="_blank" rel="noopener noreferrer">Langfuse</a>
                </p>
                <details open><summary>Agent 回答</summary><pre>{{ detail.answer?.answer || "暂无回答" }}</pre></details>
                <details><summary>参考答案与参考 SQL</summary><pre>{{ json(detail.reference) }}</pre><pre v-if="detail.reference_results.length">{{ json(detail.reference_results) }}</pre></details>
                <details v-if="detail.grade"><summary>Jev 各维度评分与置信度</summary><pre>{{ json({ review: detail.grade.review, decisions: detail.grade.decisions, metrics: detail.grade.metrics }) }}</pre></details>
                <details v-if="detail.answer"><summary>工具调用、逐任务证据与补查</summary><pre>{{ json({ tools: detail.answer.tool_calls, acceptance: detail.answer.evidence_check, supplement: detail.answer.evidence_supplement_planning }) }}</pre></details>
                <details v-if="detail.grade"><summary>人工校准 {{ detail.calibrations.length ? '（' + detail.calibrations.length + '）' : '' }}</summary>
                  <ul v-if="detail.calibrations.length"><li v-for="entry in detail.calibrations" :key="entry.timestamp">{{ date(entry.timestamp) }} · {{ display(entry.score) }} · {{ entry.reason }}</li></ul>
                  <form class="calibration" @submit.prevent="saveCalibration">
                    <label>校准分 <input v-model.number="calibrated" type="number" min="0" max="100" step="0.01" required /></label>
                    <label>依据 <textarea v-model="calibrationReason" maxlength="4000" required></textarea></label>
                    <button class="secondary" :disabled="busy">保存校准</button>
                  </form>
                </details>
              </article>
            </template>
          </section>
          <section v-else class="panel idle"><History :size="24" /><h2>选择一轮评测</h2><p>选择历史批次，查看进度和逐题评分。</p></section>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.evaluation { background:#eef3f5; color:#112c3b; min-height:100vh; font:14px/1.6 "Noto Sans SC",sans-serif; --ink:#112c3b; --muted:#526977; --line:#d3dfe4; --accent:#006d64; }
.evaluation :is(button, input, select, textarea) { font:inherit; color:inherit; }
.evaluation button { cursor:pointer; }
.evaluation button:disabled { cursor:default; opacity:.5; }
.evaluation :focus-visible { outline:3px solid #218b80; outline-offset:3px; }
.top { background:#153744; color:#f4fbfa; min-height:63px; padding:12px max(24px,calc((100% - 1280px)/2)); display:flex; align-items:center; justify-content:space-between; gap:12px; }
.identity, .top a, .intro-label, .tabs button, .start { display:flex; align-items:center; gap:9px; }
.identity svg { color:#83dacb; }
.identity { font-weight:700; }
.separator { width:1px; height:18px; background:#66838b; margin:0 6px; }
.top a { color:inherit; text-decoration:none; font-size:13px; white-space:nowrap; }
.workspace { max-width:1280px; margin:auto; padding:0 24px 48px; }
.intro { display:flex; justify-content:space-between; align-items:flex-end; gap:20px; padding:38px 0 24px; }
.intro h1 { font-size:clamp(33px, 5vw, 52px); line-height:1.18; letter-spacing:-.035em; margin:8px 0; }
.intro p { color:var(--muted); margin:0; }
.intro .intro-label { color:var(--accent); font-weight:700; font-size:13px; }
.runtime { border-left:3px solid #6aa89c; min-width:160px; padding:0 0 0 14px; display:grid; gap:1px; }
.runtime strong { font-family:ui-monospace,monospace; font-size:22px; line-height:1.2; }
.runtime :is(span,small), .hint { color:var(--muted); font-size:12px; }
.tabs { display:flex; gap:6px; border-bottom:1px solid var(--line); margin-bottom:18px; }
.tabs button { background:none; border:0; border-bottom:3px solid transparent; padding:10px 14px; color:var(--muted); }
.tabs button[aria-pressed="true"] { border-bottom-color:var(--accent); color:var(--accent); font-weight:700; }
.tabs button span { color:var(--muted); font-size:12px; }
.setup, .history-layout { display:grid; grid-template-columns:minmax(0,1fr) 270px; gap:16px; align-items:start; }
.history-layout { grid-template-columns:230px minmax(0,1fr); }
.panel { background:#fff; border:1px solid var(--line); border-radius:9px; padding:19px; min-width:0; }
.panel h2 { margin:0; color:var(--ink); font-size:19px; line-height:1.35; }
.panel-title { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.panel-title .hint { margin:3px 0 0; }
.suites { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:15px 0; }
.suites button { text-align:left; position:relative; display:grid; gap:3px; background:#f5f9fa; border:1px solid var(--line); border-radius:7px; padding:12px; }
.suites button:is(:hover,.selected) { border-color:var(--accent); background:#e8f4f0; }
.suites button svg { color:var(--accent); margin-bottom:3px; }
.suites small { color:var(--muted); }
.count { position:absolute; inset:8px 11px auto auto; color:var(--accent); font-size:22px; font-weight:700; }
.toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:12px 0; }
.query { display:flex; align-items:center; flex:1; border:1px solid var(--line); border-radius:6px; padding:0 8px; gap:7px; color:var(--muted); min-width:145px; }
.query input { background:none; width:100%; min-width:0; border:0; padding:7px 0; }
.evaluation :is(select, input[type=password], input[type=number], textarea) { background:white; border:1px solid var(--line); border-radius:6px; padding:6px 9px; }
.primary, .secondary, .plain { border-radius:6px; padding:7px 12px; font-weight:700; }
.evaluation .primary { border:1px solid var(--accent); background:var(--accent); color:#fff; }
.secondary { background:#f2f7f8; border:1px solid var(--line); white-space:nowrap; }
.plain,.text-link { background:transparent; border:0; }
.evaluation .text-link { color:#005d55; text-decoration:underline; }
.question-list { max-height:480px; overflow:auto; border-top:1px solid var(--line); }
.question { display:grid; grid-template-columns:17px 76px minmax(0,1fr); align-items:start; gap:8px; border-bottom:1px solid #e7eef0; padding:10px 2px; cursor:pointer; }
.question:hover, .question:has(input:checked), tr.focused { background:#eef8f5; }
.question input { margin-top:4px; accent-color:var(--accent); }
.question code { padding-top:2px; color:var(--accent); font-size:12px; }
.tally { border-bottom:1px solid var(--line); padding:11px 0; display:flex; align-items:baseline; gap:7px; }
.tally strong { color:var(--accent); font-size:44px; line-height:1.15; letter-spacing:-.04em; }
dl { margin:13px 0; }
dl div { display:flex; justify-content:space-between; gap:8px; margin:5px 0; font-size:12px; }
dt { color:var(--muted); } dd { margin:0; text-align:right; }
.start { width:100%; justify-content:center; }
.empty { color:var(--muted); padding:12px 0; }
.archive button { position:relative; display:grid; gap:2px; background:#fff; border:0; border-bottom:1px solid var(--line); padding:11px 27px 11px 4px; width:100%; text-align:left; }
.archive button[aria-pressed=true] { background:#e9f5f1; color:var(--accent); }
.archive button span { position:absolute; right:4px; top:12px; color:var(--accent); font-variant-numeric:tabular-nums; }
.archive button small { color:var(--muted); }
.archive-filter { display:grid; gap:6px; margin-top:10px; }
.archive-filter input { background:#fff; border:1px solid var(--line); border-radius:6px; padding:6px 9px; min-width:0; }
.summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; padding:14px 0 12px; }
.summary div { display:grid; }
.summary strong { font-size:24px; }
.summary small, .group-summary span { color:var(--muted); }
progress { width:100%; height:8px; accent-color:var(--accent); }
.group-summary { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0; }
.group-summary div { display:flex; gap:6px; align-items:center; border:1px solid var(--line); border-radius:4px; padding:4px 8px; font-size:12px; }
.compare { justify-content:space-between; font-size:13px; }
.results { overflow:auto; max-height:470px; }
table { width:100%; border-collapse:collapse; text-align:left; white-space:nowrap; }
th,td { padding:6px 9px; border-bottom:1px solid #e7eef0; }
th { position:sticky; top:0; background:#f0f6f7; color:var(--muted); font-size:12px; z-index:1; }
.case-detail { margin-top:18px; border-top:1px solid var(--line); padding-top:15px; }
details { border-top:1px solid var(--line); padding:8px 0; }
summary { cursor:pointer; font-weight:700; }
pre { white-space:pre-wrap; word-break:break-word; overflow:auto; max-height:400px; background:#f4f7f8; padding:12px; border-radius:5px; font-size:12px; }
.calibration { display:grid; gap:6px; justify-items:start; margin-top:8px; }
.calibration label { display:flex; gap:10px; align-items:baseline; }
.calibration textarea { width:min(420px, 65vw); }
.idle { min-height:220px; display:grid; gap:4px; align-content:center; justify-items:center; }
.idle :is(svg,p) { color:var(--muted); margin:0; }
.unlock { width:min(100%, 430px); } .unlock h2 { margin-bottom:10px; }
.unlock-row { display:flex; gap:8px; margin-top:5px; } .unlock-row input { min-width:0; flex:1; }
.notice { background:#fff0ef; border:1px solid #ecc3bc; color:#94382a; padding:8px 11px; border-radius:5px; }
@media(max-width:830px) { .workspace { padding-inline:15px; } .setup,.history-layout { grid-template-columns:minmax(0,1fr); } .launch { grid-row:1; } .archive { max-height:200px; overflow:auto; } }
@media(max-width:520px) { .suites { grid-template-columns:repeat(2,minmax(0,1fr)); } .intro { align-items:start; flex-direction:column; gap:9px; padding-top:22px; } .runtime { min-width:0; } .top { padding-inline:13px; } .identity { gap:5px; font-size:12px; } .separator { margin:0 2px; } .panel { padding:12px; } }
</style>
