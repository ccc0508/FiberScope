<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ArrowDownAZ,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Layers3,
  ListFilter,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-vue-next";
import {
  ApiError,
  get,
  number,
  typeKeys,
  typeNames,
  type ListResult,
  type Metadata,
  type Sample,
  type SampleType,
} from "../api";
import SampleDetail from "../components/SampleDetail.vue";
import FilterSelect from "../components/FilterSelect.vue";
import OverviewDials from "../components/OverviewDials.vue";
import PageHeader from "../components/PageHeader.vue";
import { materialColors } from "../palette";
import { isGarden, reducedMotion } from "../mode";
import { useCountUp, vTilt } from "../motion";

const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null);
const typeCounts = ref<Record<SampleType, number>>({
  softwood: 0,
  hardwood: 0,
  blend: 0,
});
const summaryLoading = ref(true),
  summaryError = ref(""),
  lastRead = ref("");
const rows = ref<Sample[]>([]),
  total = ref(0),
  totalPages = ref(0);
const loading = ref(true),
  error = ref(""),
  requestId = ref("");
const selected = ref<Sample | null>(null);
const page = computed(() => {
  const value = Number(route.query.page);
  return Number.isInteger(value) && value >= 1 && value <= 100000 ? value : 1;
});
const size = computed(() =>
  [10, 25, 50].includes(Number(route.query.size))
    ? Number(route.query.size)
    : 10,
);
const kind = computed(() =>
  typeKeys.includes(route.query.type as SampleType)
    ? (route.query.type as SampleType)
    : "",
);
const query = computed(() => String(route.query.q ?? "").slice(0, 100));
const search = ref(query.value);
const filterCount = computed(
  () => Number(!!query.value) + Number(!!kind.value),
);
const counts = computed(() => metadata.value?.counts);
const filterOptions = computed(() => [
  { value: "", label: "全部样本类型", count: counts.value?.samples },
  ...typeKeys.map((type) => ({
    value: type,
    label: typeNames[type],
    count: counts.value ? typeCounts.value[type] : undefined,
    color: materialColors[type],
  })),
]);

/* ---------------------------------------------------------------- 全库统计（metadata 实时计数） */
const count = (key: string) => {
  const value = counts.value?.[key];
  return typeof value === "number" ? value : null;
};
const GROUP_LABEL: Record<string, string> = {
  fiber: "纤维",
  paper: "纸张",
  distribution: "长度分布",
  strength: "强度",
};
const indicatorGroups = computed(() => {
  const list = metadata.value?.indicators;
  if (!list) return [];
  const byGroup = new Map<string, number>();
  for (const item of list)
    byGroup.set(item.group, (byGroup.get(item.group) ?? 0) + 1);
  return [...byGroup].map(([key, n]) => ({
    key,
    n,
    label: GROUP_LABEL[key] ?? key,
  }));
});
/** tone: a material, or n1–n4 (neutral ramp, light → dark) for encodings that are not sample type */
interface KpiSegment {
  key: string;
  n: number;
  tone: string;
}
interface Kpi {
  key: string;
  kicker: string;
  label: string;
  value: number | null;
  unit: string;
  /** caption parts, joined with " · "; each part never breaks inside */
  note: string[];
  segments: KpiSegment[];
  /** spoken summary of the bar; empty when the note already says it */
  barLabel: string;
}
const kpis = computed<Kpi[]>(() => {
  const meta = metadata.value;
  const beating = count("beating"),
    blends = count("blends"),
    cycles = count("recycled/cycles");
  const display = beating != null && blends != null ? beating + blends : null;
  // 复配展示点中复用的纯浆端点 = 复配展示点 − 复配样本
  const reused = blends != null && meta ? blends - typeCounts.value.blend : null;
  const groups = indicatorGroups.value;
  return [
    {
      key: "samples",
      kicker: "Samples",
      label: "唯一物理样本",
      value: count("samples"),
      unit: "个",
      note: ["针叶木、阔叶木与针阔复配"],
      segments: meta
        ? typeKeys.map((t) => ({ key: t, n: typeCounts.value[t], tone: t }))
        : [],
      barLabel: meta
        ? typeKeys.map((t) => `${typeNames[t]} ${typeCounts.value[t]}`).join("，")
        : "",
    },
    {
      key: "display",
      kicker: "Display points",
      label: "核心实验展示点",
      value: display,
      unit: "个",
      note:
        display == null
          ? ["复配端点复用已有纯浆样本"]
          : [
              `打浆 ${beating} + 复配 ${blends}`,
              ...(reused != null && reused >= 0
                ? [`含 ${reused} 个复用端点`]
                : []),
            ],
      segments:
        beating != null && blends != null
          ? [
              { key: "beating", n: beating, tone: "n2" },
              { key: "blends", n: blends, tone: "n4" },
            ]
          : [],
      barLabel: "",
    },
    {
      key: "recycled",
      kicker: "Recycled obs.",
      label: "再生纸浆原始观测",
      value: count("recycled/details"),
      unit: "条",
      note: meta
        ? [`${meta.blocks.length} 个数据块`, `${number(cycles)} 个循环汇总点`]
        : ["数据块与循环汇总点"],
      segments: meta
        ? meta.blocks.map((b) => ({ key: b.block_code, n: 1, tone: "n2" }))
        : [],
      barLabel: "",
    },
    {
      key: "indicators",
      kicker: "Indicators",
      label: "已收录指标",
      value: meta ? meta.indicators.length : null,
      unit: "项",
      note: groups.length
        ? groups.map((g) => `${g.label} ${g.n}`)
        : ["纤维特性、纸张性能、长度分布"],
      segments: groups.map((g, i) => ({
        key: g.key,
        n: g.n,
        tone: `n${4 - Math.min(i, 3)}`,
      })),
      barLabel: "",
    },
  ];
});
// a caption part with a count ("强度 3") stays on one line; plain prose may wrap
const hasDigits = (text: string) => /\d/.test(text);
// polarized: each neutral segment shows its own slice of one interference gradient
function segmentStyle(k: Kpi, s: KpiSegment) {
  const sum = k.segments.reduce((a, x) => a + x.n, 0);
  let start = 0;
  for (const x of k.segments) {
    if (x === s) break;
    start += x.n;
  }
  return {
    flex: `${s.n} 1 0`,
    "--bs": `${sum && s.n ? (sum / s.n) * 100 : 100}% 100%`,
    "--bp": `${sum > s.n ? (start / (sum - s.n)) * 100 : 0}% 0`,
  };
}
const kpiEls: Ref<HTMLElement | undefined>[] = [ref(), ref(), ref(), ref()];
function setKpiEl(index: number, el: unknown) {
  const target = kpiEls[index];
  if (target) target.value = el instanceof HTMLElement ? el : undefined;
}
const kpiShown = kpiEls.map((el, index) =>
  useCountUp(() => kpis.value[index]?.value ?? null, { el }),
);

// garden KPI decoration (v4 kpiDeco): two stain strands and a plum hairline per tile
const decoPaths = (i: number) => [
  `M10 ${70 + i * 4}C40 ${20 + i * 6} 70 ${110 - i * 5} 112 ${40 + i * 3}`,
  `M18 ${100 - i * 3}C46 ${60 + i * 2} 64 ${30 + i * 4} 108 ${78 - i * 2}`,
  "M30 20C52 40 70 60 100 108",
];

/* ---------------------------------------------------------------- 核心数据覆盖 */
const coverage = computed(() => {
  const paired = count("fiber-paper"),
    samples = count("samples");
  const list = metadata.value?.indicators;
  return {
    paired,
    samples,
    pct:
      paired != null && samples ? Math.round((paired / samples) * 100) : null,
    fiber: list ? list.filter((i) => i.group === "fiber").length : null,
    paper: list ? list.filter((i) => i.group === "paper").length : null,
    sources: count("sources"),
  };
});
const coverageEl = ref<HTMLElement>();
const pctShown = useCountUp(() => coverage.value.pct, { el: coverageEl });
const RING = 2 * Math.PI * 42;
const ringOffset = computed(() =>
  (RING * (1 - Math.min(100, coverage.value.pct ?? 0) / 100)).toFixed(1),
);

/* ---------------------------------------------------------------- garden hero signature: 1 根纤维 = 1 个样本 */
const strip = computed(() => {
  if (!metadata.value) return null;
  const comp = typeKeys.map((type) => ({ type, n: typeCounts.value[type] }));
  const sum = comp.reduce((a, c) => a + c.n, 0);
  const W = 420,
    gap = 20,
    dx = sum ? (W - 8 - gap * (comp.length - 1)) / sum : 0;
  let seed = 61 >>> 0;
  const R = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  let x = 4,
    k = 0;
  const groups = comp.map((c) => {
    const x0 = x;
    const strands: { d: string; delay: string }[] = [];
    for (let i = 0; i < c.n; i++, k++) {
      const sx = x + dx * i + dx / 2,
        a = (R() - 0.5) * 10,
        b = (R() - 0.5) * 12,
        top = 40 + R() * 8;
      strands.push({
        d: `M${sx.toFixed(1)},126 C${(sx + a).toFixed(1)},104 ${(sx - a * 0.8).toFixed(1)},72 ${(sx + b).toFixed(1)},${top.toFixed(1)}`,
        delay: `${(-k * 0.37).toFixed(2)}s`,
      });
    }
    x += dx * c.n + gap;
    return { ...c, x0, label: typeNames[c.type], strands };
  });
  return { groups, sum };
});

let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
let summaryController: AbortController | undefined;
async function loadSummary() {
  summaryController?.abort();
  const current = new AbortController();
  summaryController = current;
  summaryLoading.value = true;
  summaryError.value = "";
  metadata.value = null;
  try {
    const [meta, ...groups] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      ...typeKeys.map((type) =>
        get<ListResult<Sample>>(
          "samples",
          { sample_type: type, page_size: 1 },
          current.signal,
        ),
      ),
    ]);
    if (current.signal.aborted) return;
    groups.forEach((group, i) => {
      typeCounts.value[typeKeys[i]!] = group.pagination.total;
    });
    metadata.value = meta;
    lastRead.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch (e) {
    if (!current.signal.aborted)
      summaryError.value =
        e instanceof Error ? e.message : "统计信息读取失败。";
  } finally {
    if (!current.signal.aborted) summaryLoading.value = false;
  }
}
async function loadRows() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  requestId.value = "";
  try {
    const result = await get<ListResult<Sample>>(
      "samples",
      {
        q: query.value,
        sample_type: kind.value,
        page: page.value,
        page_size: size.value,
      },
      current.signal,
    );
    if (current.signal.aborted) return;
    rows.value = result.data;
    total.value = result.pagination.total;
    totalPages.value = result.pagination.total_pages;
    if (page.value > Math.max(1, totalPages.value)) update({ page: 1 });
  } catch (e) {
    if (!current.signal.aborted) {
      rows.value = [];
      error.value = e instanceof Error ? e.message : "样本读取失败。";
      requestId.value = e instanceof ApiError ? (e.requestId ?? "") : "";
    }
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
function update(values: {
  q?: string;
  type?: string;
  page?: number;
  size?: number;
}) {
  const next = {
    q: query.value,
    type: kind.value,
    page: page.value,
    size: size.value,
    ...values,
  };
  void router.replace({
    query: {
      ...(next.q ? { q: next.q } : {}),
      ...(next.type ? { type: next.type } : {}),
      ...(next.page > 1 ? { page: next.page } : {}),
      ...(next.size !== 10 ? { size: next.size } : {}),
    },
  });
}
function chooseType(type: string) {
  clearTimeout(timer);
  update({ type, q: search.value.trim(), page: 1 });
}
function submitSearch() {
  clearTimeout(timer);
  update({ q: search.value.trim(), page: 1 });
}
function queueSearch() {
  clearTimeout(timer);
  timer = setTimeout(submitSearch, 350);
}
function clearFilters() {
  clearTimeout(timer);
  search.value = "";
  update({ q: "", type: "", page: 1 });
}
// 样本盘清单的类型行：筛选下方样本库，再次点击取消；样本库不在视野里时滚动过去
const library = ref<HTMLElement>();
function pickType(type: SampleType) {
  chooseType(kind.value === type ? "" : type);
  const el = library.value;
  if (!el) return;
  const box = el.getBoundingClientRect();
  if (box.top > window.innerHeight * 0.7 || box.bottom < 0)
    el.scrollIntoView({
      behavior: reducedMotion.value ? "auto" : "smooth",
      block: "start",
    });
}
const dials = ref<InstanceType<typeof OverviewDials>>();
function refresh() {
  void loadSummary();
  void dials.value?.load();
  void loadRows();
}
watch(
  () => route.query,
  () => {
    search.value = query.value;
    void loadRows();
  },
  { immediate: true },
);
void loadSummary();
onBeforeUnmount(() => {
  clearTimeout(timer);
  controller?.abort();
  summaryController?.abort();
});
</script>

<template>
  <div class="overview ov">
    <PageHeader description="选一组数据查看刻度盘，悬停清单行在盘上定位。">
      <template #actions>
        <span
          class="connection"
          :class="{ offline: summaryError }"
          role="status"
          ><span></span
          >{{
            summaryLoading
              ? "正在读取"
              : summaryError
                ? "连接待检查"
                : "数据已连接"
          }}</span
        ><button
          class="button"
          :disabled="summaryLoading || loading"
          @click="refresh"
        >
          <RefreshCw :size="15" :class="{ spinning: summaryLoading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <figure class="ov-sig">
          <svg
            v-if="strip"
            viewBox="0 0 420 132"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <g v-for="g in strip.groups" :key="g.type" :class="`sg-${g.type}`">
              <text class="sg-n" :x="g.x0" y="24">{{ g.n }}</text>
              <text class="sg-t" :x="g.x0 + (g.n >= 10 ? 30 : 17)" y="23">
                {{ g.label }}
              </text>
              <g class="sg-strands">
                <path
                  v-for="(s, i) in g.strands"
                  :key="i"
                  :d="s.d"
                  :style="{ animationDelay: s.delay }"
                />
              </g>
            </g>
          </svg>
          <div v-else class="ov-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            1 根纤维 = 1 个唯一物理样本 · 共
            <b>{{ strip ? strip.sum : "—" }}</b> 个
          </figcaption>
        </figure>
      </template>
    </PageHeader>
    <div v-if="summaryError" class="error-banner" role="alert">
      <TriangleAlert :size="18" /><span>{{ summaryError }}</span
      ><button class="text-button" @click="loadSummary">重新读取统计</button>
    </div>

    <section class="card ov-kpis" aria-label="全库统计" :aria-busy="summaryLoading">
      <article
        v-for="(k, i) in kpis"
        :key="k.key"
        v-tilt
        class="metric ov-kpi"
        :class="`ov-kpi--${k.key}`"
      >
        <span class="ov-kpi-kicker" aria-hidden="true">{{ k.kicker }}</span>
        <span class="ov-kpi-label">{{ k.label }}</span>
        <div
          :ref="(el) => setKpiEl(i, el)"
          class="ov-kpi-num"
          :class="{ skeleton: summaryLoading && k.value == null }"
        >
          <span class="ov-kpi-value" aria-hidden="true">{{
            kpiShown[i]!.value == null ? "—" : number(kpiShown[i]!.value)
          }}</span
          ><span class="sr-only">{{ k.value == null ? "—" : number(k.value) }}</span
          ><small>{{ k.unit }}</small>
        </div>
        <div
          class="ov-kpi-bar"
          :role="k.barLabel ? 'img' : undefined"
          :aria-label="k.barLabel || undefined"
          :aria-hidden="k.barLabel ? undefined : 'true'"
        >
          <i
            v-for="s in k.segments"
            :key="s.key"
            :class="`tone-${s.tone}`"
            :style="segmentStyle(k, s)"
          ></i>
        </div>
        <p class="ov-kpi-note" :title="k.note.join(' · ')">
          <template v-for="(part, j) in k.note" :key="j"
            ><template v-if="j"> · </template
            ><span :class="{ 'ov-nw': hasDigits(part) }">{{ part }}</span></template
          >
        </p>
        <svg
          class="ov-kpi-deco"
          viewBox="0 0 120 120"
          fill="none"
          stroke-linecap="round"
          aria-hidden="true"
          focusable="false"
        >
          <path
            v-for="(d, j) in decoPaths(i)"
            :key="j"
            :d="d"
            :class="`d${j + 1}`"
          />
        </svg>
        <span class="ov-kpi-fov" aria-hidden="true"></span>
      </article>
    </section>

    <OverviewDials ref="dials" :active-type="kind" @pick-type="pickType" />

    <section
      ref="coverageEl"
      class="card ov-cov"
      aria-labelledby="coverage-title"
    >
      <div
        class="ov-ring"
        role="img"
        :aria-label="`纤维与纸张测量记录配对率 ${coverage.pct ?? '—'}%`"
      >
        <svg class="ov-ring-gd" viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            <linearGradient id="ov-ring-grad" x1="0" x2="1">
              <stop class="ov-ring-stop1" offset="0" />
              <stop class="ov-ring-stop2" offset="1" />
            </linearGradient>
          </defs>
          <circle class="ov-ring-track" cx="50" cy="50" r="42" />
          <circle
            class="ov-ring-arc"
            cx="50"
            cy="50"
            r="42"
            :stroke-dasharray="RING.toFixed(1)"
            :stroke-dashoffset="ringOffset"
          />
        </svg>
        <span class="ov-ring-pz" aria-hidden="true">
          <i class="ov-ring-pz-track"></i
          ><i
            class="ov-ring-pz-arc"
            :style="{ '--p': String(coverage.pct ?? 0) }"
          ></i>
        </span>
        <div class="ov-ring-value" aria-hidden="true">
          <p>
            <span>{{ pctShown == null ? "—" : pctShown }}</span
            ><small>%</small>
          </p>
        </div>
      </div>
      <div class="ov-cov-text">
        <p class="ov-cov-kicker" aria-hidden="true">Coverage · fibre × paper</p>
        <h2 id="coverage-title">核心数据覆盖</h2>
        <p class="ov-cov-sub">按测量记录配对统计，不代表每项指标均有值</p>
        <p class="ov-cov-line">
          纤维与纸张测量记录配对率
          <b class="mono"
            >{{ coverage.paired == null ? "—" : number(coverage.paired) }} /
            {{ coverage.samples == null ? "—" : number(coverage.samples) }}</b
          >
          个样本
        </p>
      </div>
      <ul class="ov-cov-stats">
        <li>
          <span class="ov-stat">{{
            coverage.fiber == null ? "—" : number(coverage.fiber)
          }}</span
          ><span>项纤维特性</span>
        </li>
        <li>
          <span class="ov-stat">{{
            coverage.paper == null ? "—" : number(coverage.paper)
          }}</span
          ><span>项纸张性能</span>
        </li>
        <li>
          <span class="ov-stat">{{
            coverage.sources == null ? "—" : number(coverage.sources)
          }}</span
          ><span>条核心来源</span>
        </li>
      </ul>
      <div class="ov-cov-links">
        <RouterLink class="button" to="/association"
          >查看纤维—纸张关联<ArrowRight :size="14"
        /></RouterLink>
        <RouterLink class="button" to="/sources"
          >查看数据来源<ArrowRight :size="14"
        /></RouterLink>
      </div>
    </section>

    <section
      ref="library"
      class="card sample-card ov-library"
      aria-labelledby="samples-title"
    >
      <div class="sample-title">
        <div>
          <h2 id="samples-title">
            <span class="table-symbol"><Layers3 :size="18" /></span>样本库
            <span class="count-badge">{{
              error || loading ? "…" : total
            }}</span>
          </h2>
          <p>每行代表一个唯一物理样本，点击编码查看详情与来源。</p>
        </div>
        <span class="sort-note"><ArrowDownAZ :size="15" />按样本编码排序</span>
      </div>
      <div class="table-toolbar">
        <form class="search-field" role="search" @submit.prevent="submitSearch">
          <Search :size="17" /><input
            v-model="search"
            aria-label="搜索样本编码或名称"
            placeholder="搜索样本编码或名称…"
            maxlength="100"
            @input="queueSearch"
          /><button
            v-if="search"
            type="button"
            class="icon-button clear-search"
            aria-label="清空搜索"
            @click="
              search = '';
              submitSearch();
            "
          >
            <X :size="14" />
          </button>
        </form>
        <FilterSelect
          id="sample-type"
          label="样本类型"
          :model-value="kind"
          :options="filterOptions"
          @update:model-value="chooseType"
        />
        <span class="toolbar-spacer"></span
        ><span class="result-label"
          ><ListFilter :size="15" />{{
            filterCount ? `已应用 ${filterCount} 项筛选` : "全部样本"
          }}</span
        >
      </div>
      <div v-if="filterCount" class="filter-chips">
        <span>筛选条件</span
        ><button v-if="kind" @click="chooseType('')">
          {{ typeNames[kind] }}<X :size="12" /></button
        ><button
          v-if="query"
          @click="
            search = '';
            update({ q: '', page: 1 });
          "
        >
          关键词：{{ query }}<X :size="12" /></button
        ><button class="clear-all" @click="clearFilters">清除全部</button>
      </div>
      <div v-if="error" class="table-state" role="alert">
        <TriangleAlert :size="30" />
        <h3>暂时无法读取样本</h3>
        <p>{{ error }}</p>
        <small v-if="requestId">请求编号：{{ requestId }}</small
        ><button class="button primary" @click="loadRows">重新加载</button>
      </div>
      <div
        v-else-if="!loading && !rows.length"
        class="table-state"
        role="status"
      >
        <Search :size="32" />
        <h3>没有找到匹配的样本</h3>
        <p>试试其他编码、名称，或清除筛选条件。</p>
        <button class="button" @click="clearFilters">清除筛选</button>
      </div>
      <div
        v-else
        class="table-scroll"
        role="region"
        aria-label="样本数据表，可横向滚动"
        tabindex="0"
        :aria-busy="loading"
      >
        <table>
          <thead>
            <tr>
              <th class="row-index">#</th>
              <th>样本编码</th>
              <th>样本名称</th>
              <th>样本类型</th>
              <th class="numeric">针叶木 / 阔叶木</th>
              <th class="numeric">打浆转数 <small>r</small></th>
              <th class="numeric">打浆度 <small>°SR</small></th>
              <th><span class="sr-only">查看详情</span></th>
            </tr>
          </thead>
          <tbody v-if="loading && !rows.length">
            <tr v-for="i in 6" :key="i">
              <td v-for="j in 8" :key="j">
                <span class="skeleton cell-skeleton"></span>
              </td>
            </tr>
          </tbody>
          <tbody v-else :class="{ 'table-refreshing': loading }">
            <tr v-for="(sample, index) in rows" :key="sample.canonical_code">
              <td class="row-index">{{ (page - 1) * size + index + 1 }}</td>
              <td>
                <button
                  class="sample-code"
                  :disabled="loading"
                  @click="selected = sample"
                >
                  {{ sample.canonical_code }}
                </button>
              </td>
              <td class="sample-name">{{ sample.display_name }}</td>
              <td>
                <span class="type-tag" :class="sample.sample_type"
                  ><i></i>{{ typeNames[sample.sample_type] }}</span
                >
              </td>
              <td class="numeric ratio-cell">
                <span class="ov-ratio" aria-hidden="true"
                  ><i
                    :style="{
                      width: `${Math.max(0, Math.min(100, sample.sw_proportion_pct ?? 0))}%`,
                    }"
                  ></i></span
                >{{ number(sample.sw_proportion_pct) }}% <span>/</span>
                {{ number(sample.hw_proportion_pct) }}%
              </td>
              <td class="numeric">
                <template v-if="sample.sample_type === 'blend'"
                  ><span title="针叶木 / 阔叶木"
                    >{{ number(sample.sw_beating_revolutions) }} /
                    {{ number(sample.hw_beating_revolutions) }}</span
                  ></template
                ><template v-else>{{
                  number(
                    sample.sample_type === "softwood"
                      ? sample.sw_beating_revolutions
                      : sample.hw_beating_revolutions,
                  )
                }}</template>
              </td>
              <td class="numeric">
                <template v-if="sample.sample_type === 'blend'"
                  >{{ number(sample.sw_beating_degree_sr, 1) }} /
                  {{ number(sample.hw_beating_degree_sr, 1) }}</template
                ><template v-else>{{
                  number(
                    sample.sample_type === "softwood"
                      ? sample.sw_beating_degree_sr
                      : sample.hw_beating_degree_sr,
                    1,
                  )
                }}</template>
              </td>
              <td>
                <button
                  class="icon-button row-detail"
                  :disabled="loading"
                  :aria-label="`查看${sample.canonical_code}详情`"
                  @click="selected = sample"
                >
                  <ChevronRight :size="16" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-footer">
        <span role="status" aria-live="polite">{{
          loading
            ? "正在读取样本…"
            : error
              ? "读取失败"
              : total === 0
                ? "共 0 个样本"
                : `显示 ${(page - 1) * size + 1}–${Math.min(page * size, total)}，共 ${total} 个样本`
        }}</span>
        <div class="pagination">
          <label
            >每页
            <select
              aria-label="每页条数"
              :value="size"
              @change="
                update({
                  size: Number(($event.target as HTMLSelectElement).value),
                  page: 1,
                })
              "
            >
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
            </select>
            条</label
          >
          <div class="page-buttons">
            <button
              class="icon-button"
              aria-label="上一页"
              :disabled="loading || !!error || page <= 1"
              @click="update({ page: page - 1 })"
            >
              <ChevronLeft :size="17" /></button
            ><span
              >{{ page }} <span>/ {{ Math.max(1, totalPages) }}</span></span
            ><button
              class="icon-button"
              aria-label="下一页"
              :disabled="loading || !!error || page >= totalPages"
              @click="update({ page: page + 1 })"
            >
              <ChevronRight :size="17" />
            </button>
          </div>
        </div>
      </div>
    </section>
    <footer class="page-foot">
      <span
        ><CircleHelp :size="14" />复配样本的打浆条件按“针叶木 /
        阔叶木”显示；“—”表示无对应记录。</span
      ><span>{{ lastRead ? `最近读取 ${lastRead}` : "等待读取数据" }}</span>
    </footer>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
.ov {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.ov > .page-header,
.ov > .error-banner {
  margin-bottom: 0;
}
.ov > .page-foot {
  margin-top: -6px;
}

/* ================================================================ garden hero signature */
.ov-sig {
  position: relative;
  margin: 0;
  min-width: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ov-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.ov-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 132;
}
.ov-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.ov-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
}
.sg-n {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-size: 22px;
  font-weight: 420;
  letter-spacing: -0.02em;
  fill: var(--text);
}
.sg-t {
  font-family: var(--font-body);
  font-size: 11.5px;
  fill: var(--text-2);
}
.sg-strands path {
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-opacity: 0.85;
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: ov-sway 7s ease-in-out infinite alternate;
}
.sg-softwood path {
  stroke: var(--sw);
}
.sg-hardwood path {
  stroke: var(--hw);
}
.sg-blend path {
  stroke: var(--bl);
}
@keyframes ov-sway {
  from {
    rotate: -3deg;
  }
  to {
    rotate: 3deg;
  }
}

/* ================================================================ KPI row */
.ov-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.ov-kpi {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.ov-kpi-kicker,
.ov-kpi-deco,
.ov-kpi-fov {
  display: none;
}
.ov-kpi-label {
  color: var(--text-2);
}
.ov-kpi-num {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: fit-content;
  min-width: 2ch;
  color: var(--text);
}
.ov-kpi-value {
  font-family: var(--font-display);
  font-variant-numeric: lining-nums tabular-nums;
  line-height: 1;
}
.ov-kpi-num small {
  font-size: 15px;
  color: var(--text-2);
}
.ov-kpi-bar {
  display: flex;
  gap: 2px;
  overflow: hidden;
}
.ov-kpi-bar i {
  display: block;
  min-width: 2px;
  height: 100%;
}
.tone-softwood {
  background: var(--sw);
}
.tone-hardwood {
  background: var(--hw);
}
.tone-blend {
  background: var(--bl);
}
.ov-kpi-note {
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ov-nw {
  white-space: nowrap;
}

/* ---------------------------------------------------------------- polarized: one HUD strip (v1 .kpi-strip) */
:root[data-mode="polarized"] .ov-kpis {
  padding: 0;
}
:root[data-mode="polarized"] .ov-kpi {
  background: none;
  box-shadow: none;
  border-radius: 0;
  padding: 24px 24px 22px;
  border-right: 1px solid var(--line-soft);
  position: relative;
}
:root[data-mode="polarized"] .ov-kpi:last-child {
  border-right: 0;
}
:root[data-mode="polarized"] .ov-kpi::before {
  display: none;
}
:root[data-mode="polarized"] .ov-kpi-kicker {
  display: block;
  order: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-3);
}
:root[data-mode="polarized"] .ov-kpi-num {
  order: 1;
  margin: 12px 0 12px;
}
:root[data-mode="polarized"] .ov-kpi-value {
  font-weight: 200;
  font-size: clamp(48px, 5.6vw, 84px);
  letter-spacing: -0.05em;
}
:root[data-mode="polarized"] .ov-kpi-num small {
  font-weight: 300;
  margin-left: 2px;
}
/* interference bar: every neutral segment is a slice of one --ifl gradient */
:root[data-mode="polarized"] .ov-kpi-bar {
  order: 2;
  height: 3px;
  margin-bottom: 16px;
  border-radius: 2px;
  overflow: visible;
}
:root[data-mode="polarized"] .ov-kpi-bar i {
  border-radius: 2px;
}
:root[data-mode="polarized"] .ov-kpi-bar i[class*="tone-n"] {
  background: var(--ifl);
  background-size: var(--bs);
  background-position: var(--bp);
  opacity: 0.85;
}
:root[data-mode="polarized"] .ov-kpi-bar .tone-softwood {
  box-shadow: 0 0 10px var(--sw);
}
:root[data-mode="polarized"] .ov-kpi-bar .tone-hardwood {
  box-shadow: 0 0 10px var(--hw);
}
:root[data-mode="polarized"] .ov-kpi-bar .tone-blend {
  box-shadow: 0 0 10px var(--bl);
}
:root[data-mode="polarized"] .ov-kpi-label {
  order: 3;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
:root[data-mode="polarized"] .ov-kpi-note {
  order: 4;
  margin-top: 4px;
  white-space: normal;
  overflow: visible;
  line-height: 1.6;
}
/* field-of-view reticle in the corner of each readout */
:root[data-mode="polarized"] .ov-kpi-fov {
  display: block;
  position: absolute;
  top: 18px;
  right: 18px;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  background:
    linear-gradient(var(--line-strong), var(--line-strong)) center / 1px 100% no-repeat,
    linear-gradient(var(--line-strong), var(--line-strong)) center / 100% 1px no-repeat;
  opacity: 0.8;
}
:root[data-mode="polarized"] .ov-kpi-fov::after {
  content: "";
  position: absolute;
  inset: 9px;
  border-radius: 50%;
  border: 1px solid var(--accent);
  opacity: 0.55;
}

/* ---------------------------------------------------------------- garden: four glass KPI tiles (v4 .kpi) */
:root[data-mode="garden"] .ov-kpis {
  gap: 18px;
  padding: 0;
  background: none;
  box-shadow: none;
  border-radius: 0;
  animation: none;
}
:root[data-mode="garden"] .ov-kpi {
  gap: 10px;
  min-height: 200px;
  padding: 22px 24px;
}
:root[data-mode="garden"] .ov-kpi-label {
  font-size: 14px;
  padding-right: 64px;
}
:root[data-mode="garden"] .ov-kpi-num {
  margin-top: auto;
}
:root[data-mode="garden"] .ov-kpi-value {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-size: clamp(64px, 5.8vw, 84px);
  letter-spacing: -0.035em;
  line-height: 0.9;
}
:root[data-mode="garden"] .ov-kpi-num small {
  font-size: 16px;
}
:root[data-mode="garden"] .ov-kpi-bar {
  height: 8px;
  border-radius: 9px;
}
:root[data-mode="garden"] .ov-kpi-bar i {
  border-radius: 9px;
}
/* neutral plum ramp for encodings that are not sample type (marks stay ≥ 3:1) */
:root[data-mode="garden"] .tone-n1 {
  background: color-mix(in oklab, var(--accent) 58%, var(--surface));
}
:root[data-mode="garden"] .tone-n2 {
  background: color-mix(in oklab, var(--accent) 66%, var(--surface));
}
:root[data-mode="garden"] .tone-n3 {
  background: color-mix(in oklab, var(--accent) 82%, var(--surface));
}
:root[data-mode="garden"] .tone-n4 {
  background: var(--accent);
}
:root[data-mode="garden"] .ov-kpi-deco {
  display: block;
  position: absolute;
  right: -18px;
  top: -14px;
  width: 120px;
  height: 120px;
  opacity: 0.9;
  pointer-events: none;
}
.ov-kpi-deco path {
  stroke-width: 2;
  stroke-opacity: 0.5;
}
.ov-kpi-deco .d1 {
  stroke-width: 3;
  stroke-opacity: 0.55;
  stroke: color-mix(in oklab, var(--accent) 46%, var(--surface));
}
.ov-kpi-deco .d2 {
  stroke: color-mix(in oklab, var(--accent) 66%, var(--surface));
}
.ov-kpi-deco .d3 {
  stroke-width: 0.8;
  stroke-opacity: 0.25;
  stroke: var(--accent);
}
/* only the sample tile wears the type hues: it *is* the three types */
.ov-kpi--samples .ov-kpi-deco .d1 {
  stroke: var(--sw);
}
.ov-kpi--samples .ov-kpi-deco .d2 {
  stroke: var(--bl);
}

/* ================================================================ coverage strip */
.ov-cov {
  display: grid;
  grid-template-columns: auto minmax(220px, 1.1fr) minmax(0, 1.4fr) auto;
  align-items: center;
  gap: 18px 30px;
  padding: 22px 26px;
}
.ov-ring {
  position: relative;
  width: 132px;
  height: 132px;
  flex: none;
}
.ov-ring-gd,
.ov-ring-pz {
  display: none;
}
.ov-ring-value {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text);
}
.ov-ring-value span {
  font-family: var(--font-display);
  font-variant-numeric: lining-nums tabular-nums;
  line-height: 1;
  font-size: 40px;
}
.ov-ring-value small {
  font-size: 13px;
  color: var(--text-2);
}
.ov-cov-kicker {
  display: none;
}
.ov-cov-text h2 {
  color: var(--text);
}
.ov-cov-sub {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--text-2);
}
.ov-cov-line {
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-2);
}
.ov-cov-line b {
  margin: 0 4px;
  font-size: 18px;
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
}
.ov-cov-stats {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.ov-cov-stats li {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  min-width: 0;
  font-size: 12.5px;
  color: var(--text-2);
}
.ov-stat {
  font-family: var(--font-display);
  font-variant-numeric: lining-nums tabular-nums;
  font-size: 34px;
  line-height: 1;
  color: var(--text);
}
.ov-cov-links {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.ov-cov-links .button {
  justify-content: space-between;
  min-height: 34px;
  font-size: 12.5px;
}

/* polarized: interference ring gauge + HUD stat cells */
:root[data-mode="polarized"] .ov-ring-pz {
  display: block;
  position: absolute;
  inset: 0;
}
.ov-ring-pz i {
  position: absolute;
  inset: 0;
  border-radius: 50%;
}
.ov-ring-pz-track {
  border: 1px solid var(--line);
}
.ov-ring-pz-arc {
  background: var(--ifc);
  -webkit-mask:
    radial-gradient(closest-side, transparent calc(100% - 5px), var(--text) calc(100% - 4.5px)),
    conic-gradient(var(--text) calc(var(--p) * 1%), transparent 0);
  -webkit-mask-composite: source-in;
  mask:
    radial-gradient(closest-side, transparent calc(100% - 5px), var(--text) calc(100% - 4.5px)),
    conic-gradient(var(--text) calc(var(--p) * 1%), transparent 0);
  mask-composite: intersect;
  filter: drop-shadow(0 0 6px var(--accent-tint));
}
:root[data-mode="polarized"] .ov-ring::after {
  content: "";
  position: absolute;
  inset: 16px;
  border-radius: 50%;
  border: 1px dashed var(--line);
}
:root[data-mode="polarized"] .ov-ring-value span {
  font-weight: 200;
  letter-spacing: -0.05em;
}
:root[data-mode="polarized"] .ov-cov-kicker {
  display: block;
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-3);
}
:root[data-mode="polarized"] .ov-cov-text h2 {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .ov-cov-stats {
  gap: 0;
}
:root[data-mode="polarized"] .ov-cov-stats li {
  border-left: 1px solid var(--line-soft);
  padding: 4px 18px;
}
:root[data-mode="polarized"] .ov-stat {
  font-weight: 200;
  font-size: 40px;
  letter-spacing: -0.05em;
}

/* garden: v4 ring tile with soft stat pills */
:root[data-mode="garden"] .ov-cov {
  padding: 24px 28px;
}
:root[data-mode="garden"] .ov-ring {
  width: 150px;
  height: 150px;
}
:root[data-mode="garden"] .ov-ring-gd {
  display: block;
  width: 100%;
  height: 100%;
  rotate: -90deg;
}
.ov-ring-track {
  fill: none;
  stroke: var(--line);
  stroke-width: 9;
}
.ov-ring-arc {
  fill: none;
  stroke: url(#ov-ring-grad);
  stroke-width: 9;
  stroke-linecap: round;
  transition: stroke-dashoffset 1.2s var(--ease);
}
.ov-ring-stop1 {
  stop-color: color-mix(in oklab, var(--accent) 58%, var(--surface));
}
.ov-ring-stop2 {
  stop-color: var(--accent);
}
:root[data-mode="garden"] .ov-ring-value span {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-size: 46px;
  letter-spacing: -0.035em;
}
:root[data-mode="garden"] .ov-cov-text h2 {
  font-size: 19px;
  font-weight: 500;
}
:root[data-mode="garden"] .ov-cov-line b {
  font-family: var(--font-mono);
  font-size: 20px;
  font-weight: 400;
}
:root[data-mode="garden"] .ov-cov-stats li {
  border-radius: 18px;
  background: color-mix(in oklab, var(--surface) 60%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .ov-stat {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  letter-spacing: -0.03em;
}

/* ================================================================ sample library */
.ov-library .sample-title h2 {
  color: var(--text);
}
.ov-ratio {
  display: inline-block;
  vertical-align: middle;
  width: 44px;
  height: 5px;
  margin-right: 10px;
  border-radius: 9px;
  overflow: hidden;
  background: var(--hw);
  opacity: 0.85;
}
.ov-ratio i {
  display: block;
  height: 100%;
  background: var(--sw);
}
:root[data-mode="polarized"] .ov-library .sample-title h2 {
  font-size: 17px;
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .ov-ratio {
  height: 3px;
  border-radius: 0;
}
:root[data-mode="garden"] .ov-library .sample-title {
  padding: 24px 26px 18px;
}
:root[data-mode="garden"] .ov-library .sample-title h2 {
  font-size: 19px;
  font-weight: 500;
}
:root[data-mode="garden"] .ov-library .table-toolbar {
  padding: 0 26px 18px;
}
:root[data-mode="garden"] .ov-library .table-scroll {
  margin: 0 10px;
}
:root[data-mode="garden"] .ov-library .table-footer {
  padding: 14px 26px;
}
:root[data-mode="garden"] .ov-ratio {
  background: color-mix(in oklab, var(--hw) 55%, var(--surface));
}
:root[data-mode="garden"] .ov-ratio i {
  background: var(--sw);
  border-radius: 9px;
}

/* ================================================================ responsive */
@media (max-width: 1180px) {
  .ov-cov {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .ov-cov-stats,
  .ov-cov-links {
    grid-column: 1 / -1;
  }
  .ov-cov-links {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
@media (max-width: 1100px) {
  .ov-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  :root[data-mode="polarized"] .ov-kpi:nth-child(2) {
    border-right: 0;
  }
  :root[data-mode="polarized"] .ov-kpi:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line-soft);
  }
}
@media (max-width: 720px) {
  .ov {
    gap: 14px;
  }
  :root[data-mode="polarized"] .ov-kpi {
    padding: 18px 16px;
  }
  :root[data-mode="polarized"] .ov-kpi-value {
    font-size: 46px;
  }
  :root[data-mode="polarized"] .ov-kpi-fov {
    display: none;
  }
  :root[data-mode="polarized"] .ov-kpi-note {
    white-space: normal;
  }
  :root[data-mode="garden"] .ov-kpis {
    gap: 14px;
  }
  :root[data-mode="garden"] .ov-kpi {
    min-height: 0;
    padding: 18px 18px;
  }
  :root[data-mode="garden"] .ov-kpi-value {
    font-size: 54px;
  }
  :root[data-mode="garden"] .ov-kpi-deco {
    width: 80px;
    height: 80px;
  }
  .ov-cov {
    padding: 18px 16px;
    gap: 16px 18px;
  }
  .ov-ring,
  :root[data-mode="garden"] .ov-ring {
    width: 112px;
    height: 112px;
  }
  .ov-ring-value span,
  :root[data-mode="garden"] .ov-ring-value span {
    font-size: 32px;
  }
  .ov-cov-stats li,
  :root[data-mode="polarized"] .ov-cov-stats li {
    padding: 10px 10px;
  }
  .ov-stat,
  :root[data-mode="polarized"] .ov-stat {
    font-size: 28px;
  }
  :root[data-mode="garden"] .ov-library .sample-title {
    padding: 19px 16px 16px;
  }
  :root[data-mode="garden"] .ov-library .table-toolbar {
    padding: 0 16px 16px;
  }
  :root[data-mode="garden"] .ov-library .table-scroll {
    margin: 0;
  }
  :root[data-mode="garden"] .ov-library .table-footer {
    padding: 12px 16px;
  }
}
@media (max-width: 560px) {
  :root[data-mode="garden"] .ov-kpis {
    grid-template-columns: minmax(0, 1fr);
  }
  .ov-cov {
    grid-template-columns: minmax(0, 1fr);
    justify-items: start;
  }
  .ov-cov-stats {
    width: 100%;
  }
}
</style>
