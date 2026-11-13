<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Info, RefreshCw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  type Metadata,
  type ListResult,
  type Sample,
  type SampleType,
} from "../api";
import { niceTicks } from "../beating";
import { isGarden } from "../mode";
import { vSeg, vTilt } from "../motion";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import PageHeader from "../components/PageHeader.vue";

/*
 * 复配分析：一个模板服务两种显示模式。
 *  偏光（v1）：指标卡（纤维 / 纸张两组单选芯片）→ 趋势图（HUD 十字准星）| 配比阶梯 → 明细表
 *  花园（v4）：控制瓦片（常用分段 + 全部指标下拉）→ 趋势图 | 端点与条件 + 复配样本范围 → 明细表
 * 两套装饰 / 侧栏都渲染，按 :root[data-mode=…] 显隐；不 remount，选择与悬停状态跨模式保留。
 */
interface BlendRow {
  canonical_code: string;
  sw_proportion_pct: number;
  hw_proportion_pct: number;
  sw_beating_revolutions: number | null;
  hw_beating_revolutions: number | null;
  sw_beating_degree_sr: number | null;
  hw_beating_degree_sr: number | null;
  [key: string]: string | number | null;
}
type Indicator = Metadata["indicators"][number];
const route = useRoute(),
  router = useRouter();
const rows = ref<BlendRow[]>([]),
  samples = ref<Sample[]>([]);
const metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const selected = ref<Sample | null>(null),
  focused = ref<BlendRow | null>(null);
const defaultMetric: Indicator = {
  key: "tensile_index",
  name: "抗张指数",
  unit: "N·m/g",
  group: "paper",
  scope: ["core"],
  unit_status: "confirmed",
};
const metrics = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("core")) ?? [
      defaultMetric,
    ],
);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ?? defaultMetric,
);
const unitFlagged = (i: Indicator) => i.unit_status !== "confirmed";
const metricOptions = computed(() =>
  metrics.value.map((i) => ({
    value: i.key,
    label: unitFlagged(i) ? `${i.name}（单位待复核）` : i.name,
  })),
);
// 偏光：按指标组排成两组单选芯片（v1 mswitch）
const GROUP_TITLES: Record<string, string> = {
  fiber: "纤维特性",
  paper: "纸张性能",
};
const metricGroups = computed(() => {
  const groups: { key: string; title: string; items: Indicator[] }[] = [];
  for (const i of metrics.value) {
    let g = groups.find((x) => x.key === i.group);
    if (!g) {
      g = { key: i.group, title: GROUP_TITLES[i.group] ?? i.group, items: [] };
      groups.push(g);
    }
    g.items.push(i);
  }
  return groups;
});
// 花园：常用指标分段（v4 QUICK），其余从下拉中选
const QUICK = [
  "tensile_index",
  "burst_index",
  "tear_index",
  "fiber_length_weighted_mm",
];
const quickMetrics = computed(() =>
  QUICK.map((k) => metrics.value.find((i) => i.key === k)).filter(
    (i): i is Indicator => !!i,
  ),
);

const visible = computed(() =>
  [...rows.value].sort(
    (a, b) =>
      a.sw_proportion_pct - b.sw_proportion_pct ||
      a.canonical_code.localeCompare(b.canonical_code),
  ),
);
/** 端点复用纯浆样本：针叶木 0%（纯阔叶木）或 100%（纯针叶木） */
const role = (r: BlendRow): SampleType =>
  r.sw_proportion_pct === 0
    ? "hardwood"
    : r.sw_proportion_pct === 100
      ? "softwood"
      : "blend";
const ROLE_NAMES: Record<SampleType, string> = {
  hardwood: "纯阔叶木端点",
  blend: "复配样本",
  softwood: "纯针叶木端点",
};
const LEGEND: SampleType[] = ["hardwood", "blend", "softwood"];
const pointName = (r: BlendRow) => ROLE_NAMES[role(r)];
const nEnds = computed(
  () => visible.value.filter((r) => role(r) !== "blend").length,
);
const nBlend = computed(() => visible.value.length - nEnds.value);
const valueOf = (r: BlendRow, key: string): number | null => {
  const v = r[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};
const value = (r: BlendRow) => valueOf(r, metric.value.key);
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const unit = computed(() => metric.value.unit ?? "单位未确认");
// 紧凑读数（阶梯、准星、范围）：≥1 保留两位，小数指标保留四位；表格与提示沿用四位
const digits = computed(() => {
  const m = Math.max(0, ...valid.value.map((r) => Math.abs(value(r)!)));
  return m >= 1 ? 2 : 4;
});
const short = (v: number | null) => number(v, digits.value);
const ratio = (r: BlendRow) =>
  `${number(r.sw_proportion_pct)}/${number(r.hw_proportion_pct)}`;

/* ---------- 端点与条件（花园）：复配样本的组分打浆条件，取实测的不同取值 ---------- */
function spread(values: (number | null)[], d: number) {
  const v = [...new Set(values.filter((x): x is number => x !== null))];
  if (!v.length) return "—";
  const lo = Math.min(...v),
    hi = Math.max(...v);
  return lo === hi ? number(lo, d) : `${number(lo, d)}–${number(hi, d)}`;
}
const blendRows = computed(() =>
  visible.value.filter((r) => role(r) === "blend"),
);
const conditions = computed(() => ({
  sw: {
    rev: spread(
      blendRows.value.map((r) => r.sw_beating_revolutions),
      0,
    ),
    sr: spread(
      blendRows.value.map((r) => r.sw_beating_degree_sr),
      1,
    ),
  },
  hw: {
    rev: spread(
      blendRows.value.map((r) => r.hw_beating_revolutions),
      0,
    ),
    sr: spread(
      blendRows.value.map((r) => r.hw_beating_degree_sr),
      1,
    ),
  },
}));
// 复配样本范围（只描述实测值）
const extremes = computed(() => {
  const b = blendRows.value.filter((r) => value(r) !== null);
  if (!b.length) return null;
  const hi = b.reduce((a, r) => (value(r)! > value(a)! ? r : a));
  const lo = b.reduce((a, r) => (value(r)! < value(a)! ? r : a));
  return { hi, lo };
});

/* ---------- 配比阶梯（偏光） ---------- */
const ladder = computed(() => {
  const vals = valid.value.map((r) => value(r)!);
  const lo = Math.min(...vals),
    hi = Math.max(...vals);
  return visible.value.map((r) => {
    const v = value(r);
    return {
      r,
      w: v === null ? 0 : 12 + ((v - lo) / (hi - lo || 1)) * 88,
    };
  });
});

/* ---------- 趋势图：按容器实际宽度绘制，文字不随缩放变形 ---------- */
const plotBox = ref<HTMLElement>();
const plotSvg = ref<SVGSVGElement>();
const plotWidth = ref(760);
let sizeObserver: ResizeObserver | undefined;
onMounted(() => {
  sizeObserver = new ResizeObserver(([entry]) => {
    if (entry) plotWidth.value = Math.max(260, Math.round(entry.contentRect.width));
  });
  watch(
    plotBox,
    (el, old) => {
      if (old) sizeObserver?.unobserve(old);
      if (el) sizeObserver?.observe(el);
    },
    { immediate: true },
  );
});
const narrow = computed(() => plotWidth.value < 520);
const plotH = computed(() => (narrow.value ? 300 : 400));
const X_PAD = 14;
const margin = computed(() => ({
  t: 38,
  r: narrow.value ? 10 : 22,
  // 花园在横轴下方画针阔配比色带
  b: isGarden.value ? 70 : 50,
  l: narrow.value ? 48 : 62,
}));
const plotRight = computed(() => plotWidth.value - margin.value.r);
const plotBottom = computed(() => plotH.value - margin.value.b);
const px = (sw: number) =>
  margin.value.l +
  X_PAD +
  (sw / 100) * (plotRight.value - margin.value.l - 2 * X_PAD);
const yTicks = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values);
  const pad = (max - min || Math.abs(max) || 1) * 0.06;
  return niceTicks(
    min >= 0 ? Math.max(0, min - pad) : min - pad,
    max + pad,
    narrow.value ? 4 : 5,
  );
});
const yMin = computed(() => yTicks.value[0]!),
  yMax = computed(() => yTicks.value[yTicks.value.length - 1]!);
const tickDigits = computed(() => {
  const step = Math.abs((yTicks.value[1] ?? 1) - (yTicks.value[0] ?? 0)) || 1;
  for (let d = 0; d < 6; d++)
    if (Math.abs(step * 10 ** d - Math.round(step * 10 ** d)) < 1e-6) return d;
  return 6;
});
const py = (v: number) =>
  margin.value.t +
  (1 - (v - yMin.value) / (yMax.value - yMin.value || 1)) *
    (plotBottom.value - margin.value.t);
const xTicks = computed(() =>
  Array.from({ length: 11 }, (_, i) => i * 10).filter(
    (t) => !narrow.value || t % 20 === 0,
  ),
);
// 线段仅连接相邻有效观测，缺失值处断开
const linePath = computed(() => {
  let connected = false;
  return visible.value
    .map((r) => {
      const v = value(r);
      if (v === null) {
        connected = false;
        return "";
      }
      const seg = `${connected ? "L" : "M"}${px(r.sw_proportion_pct).toFixed(1)},${py(v).toFixed(1)}`;
      connected = true;
      return seg;
    })
    .join("");
});

/** 形状标记：针叶木圆、阔叶木圆角方、复配三角 */
function shapePath(type: SampleType, x: number, y: number, r: number) {
  const f = (n: number) => n.toFixed(2);
  if (type === "hardwood") {
    const s = r * 0.9,
      c = Math.min(2, s * 0.45),
      l = 2 * s - 2 * c;
    return `M${f(x - s + c)},${f(y - s)}h${f(l)}a${c},${c} 0 0 1 ${c},${c}v${f(l)}a${c},${c} 0 0 1 ${-c},${c}h${f(-l)}a${c},${c} 0 0 1 ${-c},${-c}v${f(-l)}a${c},${c} 0 0 1 ${c},${-c}Z`;
  }
  if (type === "blend")
    return `M${f(x)},${f(y - r * 1.2)}L${f(x + r * 1.12)},${f(y + r * 0.8)}L${f(x - r * 1.12)},${f(y + r * 0.8)}Z`;
  return `M${f(x - r)},${f(y)}a${f(r)},${f(r)} 0 1 0 ${f(2 * r)},0a${f(r)},${f(r)} 0 1 0 ${f(-2 * r)},0Z`;
}
const markSize = (r: BlendRow, hot = false) =>
  (role(r) === "blend" ? 5 : 6.2) * (hot ? 1.3 : 1);

const hoverPoint = computed(() => {
  const r = focused.value;
  const v = r ? value(r) : null;
  if (!r || v === null) return null;
  return { row: r, v, x: px(r.sw_proportion_pct), y: py(v) };
});
// 偏光 HUD：准星两端钉在坐标轴上的读数框（宽度按字符估算，免去测量）
const textWidth = (s: string) =>
  [...s].reduce((w, ch) => w + (/[　-鿿＀-￯]/.test(ch) ? 10.5 : 6.4), 0);
const hud = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  const xl = `针 ${number(p.row.sw_proportion_pct)}%`,
    yl = short(p.v);
  const xw = textWidth(xl) + 12,
    yw = textWidth(yl) + 12;
  const cx = Math.max(
    margin.value.l + xw / 2,
    Math.min(plotRight.value - xw / 2, p.x),
  );
  return { xl, yl, xw, yw, cx };
});
const tip = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  return {
    style: { "--x": `${p.x}px`, "--y": `${p.y}px` },
    left: p.x + 16 + 236 > plotWidth.value,
    below: p.y < 128,
  };
});
// 直接标注两个端点（偏光 v1 ref-lbl）
const endLabels = computed(() =>
  (["hardwood", "softwood"] as SampleType[])
    .map((t) => {
      const r = valid.value.find((x) => role(x) === t);
      if (!r) return null;
      const x = px(r.sw_proportion_pct),
        y = py(value(r)!);
      return {
        t,
        x: t === "hardwood" ? x + 10 : x - 10,
        y: y < margin.value.t + 24 ? y + 24 : y - 14,
        anchor: t === "hardwood" ? "start" : "end",
      };
    })
    .filter((x): x is NonNullable<typeof x> => !!x),
);

let pointerActive = false;
function pointer(e: PointerEvent) {
  if (e.pointerType === "touch") return;
  const svg = e.currentTarget as SVGSVGElement;
  const box = svg.getBoundingClientRect();
  const mx = e.clientX - box.left,
    my = e.clientY - box.top;
  const inside =
    mx >= margin.value.l - 6 &&
    mx <= plotRight.value + 6 &&
    my >= margin.value.t - 14 &&
    my <= plotBottom.value + 10;
  if (!inside) {
    if (pointerActive) focused.value = null;
    pointerActive = false;
    return;
  }
  let best: BlendRow | null = null,
    d = Infinity;
  for (const r of valid.value) {
    const dist = Math.abs(px(r.sw_proportion_pct) - mx);
    if (dist < d) {
      d = dist;
      best = r;
    }
  }
  pointerActive = true;
  focused.value = best;
}
function pointerLeave() {
  if (pointerActive) focused.value = null;
  pointerActive = false;
}
function pointKey(e: KeyboardEvent, r: BlendRow) {
  const list = valid.value,
    i = list.indexOf(r);
  let next: BlendRow | undefined;
  if (e.key === "ArrowRight" || e.key === "ArrowUp") next = list[i + 1];
  else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = list[i - 1];
  else if (e.key === "Home") next = list[0];
  else if (e.key === "End") next = list[list.length - 1];
  else return;
  e.preventDefault();
  if (next)
    plotSvg.value
      ?.querySelector<SVGGElement>(`[data-point="${next.canonical_code}"]`)
      ?.focus();
}

/* ---------- 页头签名（花园）：抗张指数沿配比梯度，端点按原料形状标记 ---------- */
const SIG_KEY = "tensile_index";
const sigName = computed(
  () =>
    metadata.value?.indicators.find((i) => i.key === SIG_KEY)?.name ??
    defaultMetric.name,
);
const sig = computed(() => {
  const pts = visible.value
    .map((r) => ({ r, v: valueOf(r, SIG_KEY) }))
    .filter((p): p is { r: BlendRow; v: number } => p.v !== null);
  if (pts.length < 2) return null;
  const vs = pts.map((p) => p.v),
    lo = Math.min(...vs),
    hi = Math.max(...vs),
    pad = (hi - lo) * 0.18 || 1;
  const X = (sw: number) => 26 + (sw / 100) * (420 - 52),
    Y = (v: number) => 104 - ((v - (lo - pad)) / (hi + pad - (lo - pad))) * 90;
  const marks = pts.map((p) => ({
    code: p.r.canonical_code,
    t: role(p.r),
    d: shapePath(role(p.r), X(p.r.sw_proportion_pct), Y(p.v), role(p.r) === "blend" ? 4.2 : 5.2),
  }));
  const a = pts[0]!,
    b = pts[pts.length - 1]!;
  return {
    path: pts
      .map((p, i) => `${i ? "L" : "M"}${X(p.r.sw_proportion_pct).toFixed(1)},${Y(p.v).toFixed(1)}`)
      .join(""),
    marks,
    x0: X(0),
    x1: X(100),
    first: { x: X(a.r.sw_proportion_pct) + 2, y: Y(a.v) - 11, text: number(a.v, 2) },
    last: { x: X(b.r.sw_proportion_pct) - 2, y: Y(b.v) - 11, text: number(b.v, 2) },
    n: pts.length,
    ends: pts.filter((p) => role(p.r) !== "blend").length,
  };
});

/* ---------- 交互 ---------- */
function update(key: string, next: string) {
  void router.replace({ query: { ...route.query, [key]: next } });
}
// 偏光指标芯片：单选组，方向键在组内移动并选中
function chipKey(e: KeyboardEvent, items: Indicator[], i: number) {
  let n = -1;
  if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % items.length;
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
    n = (i - 1 + items.length) % items.length;
  else if (e.key === "Home") n = 0;
  else if (e.key === "End") n = items.length - 1;
  else return;
  e.preventDefault();
  const next = items[n]!;
  update("metric", next.key);
  const group = (e.currentTarget as HTMLElement).parentElement;
  group?.querySelectorAll<HTMLButtonElement>("button")[n]?.focus();
}
const chipTabbable = (items: Indicator[], i: number) => {
  const sel = items.findIndex((x) => x.key === metric.value.key);
  return sel === -1 ? i === 0 : sel === i;
};
function detail(row: BlendRow) {
  selected.value =
    samples.value.find((s) => s.canonical_code === row.canonical_code) ?? null;
}
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  focused.value = null;
  try {
    const [data, meta, sampleData] = await Promise.all([
      get<ListResult<BlendRow>>("blends", { page_size: 500 }, current.signal),
      get<Metadata>("metadata", {}, current.signal),
      get<ListResult<Sample>>("samples", { page_size: 500 }, current.signal),
    ]);
    if (current.signal.aborted) return;
    rows.value = data.data;
    metadata.value = meta;
    samples.value = sampleData.data;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据读取失败";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
watch(
  () => [metric.value.key],
  () => {
    focused.value = null;
  },
);
void load();
onBeforeUnmount(() => {
  controller?.abort();
  sizeObserver?.disconnect();
});
</script>

<template>
  <div class="overview blend-page">
    <PageHeader description="观察针阔配比变化下的纤维特性与纸张性能。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <figure class="blend-sig">
          <svg
            v-if="sig"
            viewBox="0 0 420 132"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              <linearGradient id="blend-sig-grad" x1="0" x2="1">
                <stop offset="0" class="stop-hw" />
                <stop offset=".5" class="stop-bl" />
                <stop offset="1" class="stop-sw" />
              </linearGradient>
            </defs>
            <rect
              class="sg-band"
              :x="sig.x0"
              y="116"
              :width="sig.x1 - sig.x0"
              height="4"
              rx="2"
            />
            <text class="sg-m" :x="sig.x0" y="131" text-anchor="middle">0%</text>
            <text class="sg-m" :x="sig.x1" y="131" text-anchor="middle">100%</text>
            <path class="sg-line" :d="sig.path" />
            <path
              v-for="m in sig.marks"
              :key="m.code"
              class="sg-pt"
              :class="m.t"
              :d="m.d"
            />
            <text class="sg-v" :x="sig.first.x" :y="sig.first.y">{{ sig.first.text }}</text>
            <text class="sg-v" :x="sig.last.x" :y="sig.last.y" text-anchor="end">
              {{ sig.last.text }}
            </text>
          </svg>
          <div v-else class="blend-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            {{ sigName }} · 针叶木比例 0→100% ·
            <b>{{ sig ? sig.n : "—" }}</b> 个展示点（两端
            {{ sig ? sig.ends : "—" }} 个复用纯浆）
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <div v-if="error" class="card blend-state blend-status" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card blend-state blend-status" role="status">
      正在读取复配实验数据…
    </div>
    <template v-else>
      <!-- 指标：偏光为两组单选芯片，花园为常用分段 + 全部指标下拉；同一路由参数 metric -->
      <section class="card blend-controls" aria-label="复配分析筛选">
        <h2 class="ctl-title">分析指标</h2>
        <p class="blend-count" role="status">
          <span class="nw">{{ visible.length }} 个展示点</span>（含
          <span class="nw">{{ nEnds }} 个纯浆端点</span>）<span
            class="sep"
            aria-hidden="true"
            >·</span
          ><span class="nw">{{ valid.length }} 个有效数据点</span>
        </p>
        <div class="ctl-groups">
          <div v-for="g in metricGroups" :key="g.key" class="ctl-group">
            <span :id="`blend-group-${g.key}`" class="field-label"
              >{{ g.title }} · {{ g.items.length }} 项</span
            >
            <div
              class="seg blend-chips"
              role="radiogroup"
              :aria-labelledby="`blend-group-${g.key}`"
            >
              <button
                v-for="(i, k) in g.items"
                :key="i.key"
                type="button"
                role="radio"
                :aria-checked="i.key === metric.key"
                :tabindex="chipTabbable(g.items, k) ? 0 : -1"
                @click="update('metric', i.key)"
                @keydown="chipKey($event, g.items, k)"
              >
                {{ i.name }}
              </button>
            </div>
          </div>
        </div>
        <div class="ctl-row">
          <div class="ctl">
            <span id="blend-quick-label" class="field-label">分析指标 · 常用</span>
            <div
              v-seg
              class="seg blend-quick"
              role="group"
              aria-labelledby="blend-quick-label"
            >
              <button
                v-for="i in quickMetrics"
                :key="i.key"
                type="button"
                :aria-pressed="i.key === metric.key"
                @click="update('metric', i.key)"
              >
                {{ i.name }}
              </button>
            </div>
          </div>
          <div class="ctl ctl-all">
            <span class="field-label">全部 {{ metrics.length }} 项指标</span
            ><FilterSelect
              id="blend-metric"
              label="分析指标"
              :model-value="metric.key"
              :options="metricOptions"
              @update:model-value="update('metric', $event)"
            />
          </div>
        </div>
      </section>

      <section class="card blend-chart" aria-labelledby="blend-chart-title">
        <div class="chart-head">
          <h2 id="blend-chart-title">{{ metric.name }}随针叶木比例的变化</h2>
          <p>
            纵轴：{{ metric.name }}（{{ unit }}）<span
              v-if="unitFlagged(metric)"
              class="unit-flag"
              >{{ metric.unit_status === "tentative" ? "单位暂定" : "单位未确认" }}</span
            >
          </p>
        </div>
        <ul class="blend-legend" aria-label="图例">
          <li v-for="t in LEGEND" :key="t">
            <i class="mk" :class="t" aria-hidden="true"></i>{{ ROLE_NAMES[t] }}
          </li>
        </ul>
        <p v-if="unitFlagged(metric)" class="unit-note">
          {{ metric.name }}的单位{{
            metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
          }}，数值保留原始口径。
        </p>
        <div v-if="!valid.length" class="blend-state blend-plot-state" role="status">
          当前没有该指标的有效数据，请切换指标。
        </div>
        <div v-else ref="plotBox" class="blend-plot-box">
          <svg
            ref="plotSvg"
            class="blend-plot"
            role="group"
            :width="plotWidth"
            :height="plotH"
            :viewBox="`0 0 ${plotWidth} ${plotH}`"
            :aria-label="`${metric.name}随针叶木比例的变化图；可用Tab定位数据点，方向键切换，Enter查看样本详情`"
            @pointermove="pointer"
            @pointerleave="pointerLeave"
          >
            <defs>
              <linearGradient id="blend-ratio-grad" x1="0" x2="1">
                <stop offset="0" class="stop-hw" />
                <stop offset=".5" class="stop-bl" />
                <stop offset="1" class="stop-sw" />
              </linearGradient>
            </defs>
            <!-- 偏光：两个端点所在的竖带 -->
            <g class="end-bands" aria-hidden="true">
              <rect
                class="band hardwood"
                :x="px(0) - 14"
                :y="margin.t"
                width="28"
                :height="plotBottom - margin.t"
              />
              <rect
                class="band softwood"
                :x="px(100) - 14"
                :y="margin.t"
                width="28"
                :height="plotBottom - margin.t"
              />
            </g>
            <g class="grid" aria-hidden="true">
              <line
                v-for="t in yTicks"
                :key="`gy${t}`"
                :x1="margin.l"
                :x2="plotRight"
                :y1="py(t)"
                :y2="py(t)"
              />
            </g>
            <g class="axis" aria-hidden="true">
              <line :x1="margin.l" :x2="plotRight" :y1="plotBottom" :y2="plotBottom" />
              <text
                v-for="t in yTicks"
                :key="`ty${t}`"
                :x="margin.l - 10"
                :y="py(t) + 4"
                text-anchor="end"
              >
                {{ number(t, tickDigits) }}
              </text>
              <g v-for="t in xTicks" :key="`tx${t}`">
                <line :x1="px(t)" :x2="px(t)" :y1="plotBottom" :y2="plotBottom + 5" />
                <text :x="px(t)" :y="plotBottom + 20" text-anchor="middle">{{ t }}%</text>
              </g>
              <text class="axis-title" x="4" :y="margin.t - 18">
                <tspan class="garden-only">↑ </tspan>{{ metric.name }} / {{ unit }}
              </text>
              <text
                class="axis-title x-title"
                :x="plotRight"
                :y="plotH - 8"
                text-anchor="end"
              >
                {{
                  narrow
                    ? "针叶木比例 / %"
                    : "针叶木比例 / %（阔叶木比例 = 100% − 针叶木比例）"
                }}
              </text>
            </g>
            <!-- 花园：横轴下方的阔 → 复配 → 针色带 -->
            <g class="ratio-band" aria-hidden="true">
              <rect
                :x="px(0)"
                :y="plotBottom + 32"
                :width="px(100) - px(0)"
                height="5"
                rx="2.5"
              />
              <text :x="px(0)" :y="plotBottom + 54">← 阔叶木比例</text>
              <text
                v-if="!narrow"
                class="ratio-mid"
                :x="(px(0) + px(100)) / 2"
                :y="plotBottom + 54"
                text-anchor="middle"
              >
                阔叶木比例 = 100% − 针叶木比例
              </text>
              <text :x="px(100)" :y="plotBottom + 54" text-anchor="end">针叶木比例 →</text>
            </g>
            <path class="blend-line" :d="linePath" />
            <g
              v-for="r in valid"
              :key="r.canonical_code"
              class="plot-point"
              :class="[role(r), { on: focused?.canonical_code === r.canonical_code }]"
              :data-point="r.canonical_code"
              role="button"
              tabindex="0"
              :aria-label="`${r.canonical_code}，针叶木${r.sw_proportion_pct}%，阔叶木${r.hw_proportion_pct}%，${pointName(r)}，${metric.name}${value(r)} ${unit}，查看详情`"
              @focus="focused = r"
              @blur="focused = null"
              @click="detail(r)"
              @keydown="pointKey($event, r)"
              @keydown.enter.prevent="detail(r)"
              @keydown.space.prevent="detail(r)"
            >
              <circle
                class="hit"
                :cx="px(r.sw_proportion_pct)"
                :cy="py(value(r)!)"
                r="14"
              />
              <path
                class="mark"
                :d="
                  shapePath(
                    role(r),
                    px(r.sw_proportion_pct),
                    py(value(r)!),
                    markSize(r, focused?.canonical_code === r.canonical_code),
                  )
                "
              />
              <title>
                {{ r.canonical_code }} · 针叶木
                {{ number(r.sw_proportion_pct) }}% / 阔叶木
                {{ number(r.hw_proportion_pct) }}% · {{ metric.name }}
                {{ number(value(r), 4) }} {{ unit }}
              </title>
            </g>
            <!-- 端点名称画在曲线之上，纸色描边保证穿线时可读 -->
            <g v-if="!narrow" class="end-labels" aria-hidden="true">
              <text
                v-for="l in endLabels"
                :key="l.t"
                :x="l.x"
                :y="l.y"
                :text-anchor="l.anchor"
              >
                {{ ROLE_NAMES[l.t] }}
              </text>
            </g>
            <!-- 花园：竖向引导线 + 焦点圈 -->
            <g v-if="hoverPoint" class="guide" aria-hidden="true">
              <line
                class="guide-l"
                :x1="hoverPoint.x"
                :x2="hoverPoint.x"
                :y1="margin.t"
                :y2="plotBottom"
              />
              <circle class="guide-focus" :cx="hoverPoint.x" :cy="hoverPoint.y" r="13" />
            </g>
            <!-- 偏光：显微镜 HUD 十字准星，读数钉在两条坐标轴上 -->
            <g v-if="hoverPoint && hud" class="hud" aria-hidden="true">
              <line
                class="hud-l"
                :x1="hoverPoint.x"
                :x2="hoverPoint.x"
                :y1="margin.t"
                :y2="plotBottom"
              />
              <line
                class="hud-l"
                :x1="margin.l"
                :x2="plotRight"
                :y1="hoverPoint.y"
                :y2="hoverPoint.y"
              />
              <path
                class="hud-tk"
                :d="`M${hoverPoint.x - 6},${hoverPoint.y}h12M${hoverPoint.x},${hoverPoint.y - 6}v12`"
              />
              <circle class="hud-ring" :cx="hoverPoint.x" :cy="hoverPoint.y" r="10" />
              <rect
                class="hud-box"
                :x="hud.cx - hud.xw / 2"
                :y="plotBottom + 4"
                :width="hud.xw"
                height="17"
                rx="3"
              />
              <text class="hud-t" :x="hud.cx" :y="plotBottom + 16.5" text-anchor="middle">
                {{ hud.xl }}
              </text>
              <rect
                class="hud-box"
                :x="margin.l - 4 - hud.yw"
                :y="hoverPoint.y - 8.5"
                :width="hud.yw"
                height="17"
                rx="3"
              />
              <text
                class="hud-t"
                :x="margin.l - 10"
                :y="hoverPoint.y + 4"
                text-anchor="end"
              >
                {{ hud.yl }}
              </text>
            </g>
          </svg>
          <div
            class="blend-tip"
            :class="{ on: tip, left: tip?.left, below: tip?.below }"
            :style="tip?.style"
            role="status"
            aria-live="polite"
          >
            <template v-if="hoverPoint">
              <div class="tip-head">
                <i class="mk" :class="role(hoverPoint.row)" aria-hidden="true"></i
                ><b>{{ pointName(hoverPoint.row) }}</b>
              </div>
              <div class="tip-code">{{ hoverPoint.row.canonical_code }}</div>
              <div class="tip-row">
                <span>配比 针 / 阔</span
                ><b
                  >{{ number(hoverPoint.row.sw_proportion_pct) }} /
                  {{ number(hoverPoint.row.hw_proportion_pct) }}</b
                >
              </div>
              <div class="tip-row">
                <span>{{ metric.name }}</span><b>{{ number(hoverPoint.v, 4) }}</b>
              </div>
              <div class="tip-foot">{{ unit }}</div>
            </template>
          </div>
        </div>
        <p class="blend-hint">
          悬停或聚焦查看数值，点击数据点查看样本详情与来源。方向键在数据点间移动。
        </p>
        <p class="caveat blend-caveat">
          <Info :size="16" aria-hidden="true" /><span
            >线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。</span
          >
        </p>
      </section>

      <div class="blend-side">
        <!-- 偏光：配比阶梯（v1 Ratio ladder） -->
        <aside class="card blend-ladder" aria-labelledby="blend-ladder-title">
          <span class="ladder-k" aria-hidden="true">Ratio ladder</span>
          <h2 id="blend-ladder-title">配比阶梯</h2>
          <p class="side-note">
            {{ nBlend }}个复配样本与{{ nEnds }}个复用纯浆端点；端点不计为新增样本。具体打浆条件见下方明细。
          </p>
          <ol class="ladder" :aria-label="`各配比（针 / 阔）的${metric.name}`">
            <li
              v-for="l in ladder"
              :key="l.r.canonical_code"
              :class="{ on: focused?.canonical_code === l.r.canonical_code }"
            >
              <span class="lad-ratio" aria-hidden="true"
                ><i :style="{ width: `${l.r.sw_proportion_pct}%` }"></i
              ></span>
              <span class="lad-r">{{ ratio(l.r) }}</span>
              <span class="lad-v" aria-hidden="true"
                ><i :class="role(l.r)" :style="{ width: `${l.w}%` }"></i
              ></span>
              <span class="lad-n">{{ short(value(l.r)) }}</span>
            </li>
          </ol>
        </aside>
        <!-- 花园：端点与条件 + 复配样本范围（v4 stack） -->
        <section v-tilt class="card blend-cond" aria-labelledby="blend-cond-title">
          <h2 id="blend-cond-title">端点与条件</h2>
          <p class="side-note">
            {{ nBlend }} 个复配样本与 {{ nEnds }} 个复用纯浆端点；端点不计为新增样本。
          </p>
          <div class="facts">
            <div class="fact">
              <span class="l"><i class="mk softwood" aria-hidden="true"></i>针叶木组分</span>
              <span class="v">{{ conditions.sw.rev }} r · {{ conditions.sw.sr }} °SR</span>
            </div>
            <div class="fact">
              <span class="l"><i class="mk hardwood" aria-hidden="true"></i>阔叶木组分</span>
              <span class="v">{{ conditions.hw.rev }} r · {{ conditions.hw.sr }} °SR</span>
            </div>
          </div>
          <p class="side-note">具体打浆条件见下方明细。</p>
        </section>
        <section v-tilt class="card blend-range" aria-labelledby="blend-range-title">
          <h2 id="blend-range-title">复配样本范围</h2>
          <p class="side-note">{{ metric.name }} · {{ unit }}</p>
          <div class="facts">
            <div class="fact">
              <span class="l"
                >最高 · {{ extremes ? ratio(extremes.hi) : "—" }}</span
              >
              <span class="v big">{{ extremes ? short(value(extremes.hi)) : "—" }}</span>
            </div>
            <div class="fact">
              <span class="l"
                >最低 · {{ extremes ? ratio(extremes.lo) : "—" }}</span
              >
              <span class="v big">{{ extremes ? short(value(extremes.lo)) : "—" }}</span>
            </div>
          </div>
          <p class="side-note">仅描述实测值，不代表配比与性能之间的因果关系。</p>
        </section>
      </div>

      <section class="card blend-table" aria-labelledby="blend-table-title">
        <div class="table-head">
          <h2 id="blend-table-title">
            实验明细 <span class="quiet-tag">{{ visible.length }}</span>
          </h2>
          <p>
            按针叶木比例升序排列；条件按针叶木 / 阔叶木显示，“—”表示无对应值。
          </p>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="复配实验明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th>样本编码</th>
                <th>类型</th>
                <th class="numeric">配比 / %</th>
                <th class="numeric">打浆转数 / r</th>
                <th class="numeric">打浆度 / °SR</th>
                <th class="numeric">{{ metric.name }} / {{ unit }}</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in visible"
                :key="r.canonical_code"
                :class="{ on: focused?.canonical_code === r.canonical_code }"
              >
                <td>
                  <button class="sample-code" @click="detail(r)">
                    {{ r.canonical_code }}
                  </button>
                </td>
                <td>
                  <span class="type-tag" :class="role(r)"><i></i>{{ pointName(r) }}</span>
                </td>
                <td class="numeric">
                  <span class="ratio-wrap"
                    ><span class="ratio-bar" aria-hidden="true"
                      ><i :style="{ width: `${r.sw_proportion_pct}%` }"></i></span
                    >{{ number(r.sw_proportion_pct) }} /
                    {{ number(r.hw_proportion_pct) }}</span
                  >
                </td>
                <td class="numeric">
                  {{ number(r.sw_beating_revolutions) }} /
                  {{ number(r.hw_beating_revolutions) }}
                </td>
                <td class="numeric">
                  {{ number(r.sw_beating_degree_sr, 1) }} /
                  {{ number(r.hw_beating_degree_sr, 1) }}
                </td>
                <td class="numeric">{{ number(value(r), 4) }}</td>
                <td>
                  <button
                    class="text-button"
                    :aria-label="`查看 ${r.canonical_code} 详情`"
                    @click="detail(r)"
                  >
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!visible.length" class="blend-state">暂无匹配数据。</p>
      </section>
    </template>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
/* ================================================================ page grid
   DOM order: header · controls · chart · side panel · table.
   Dense auto-flow pairs the chart with the side panel (v1 bl-grid / v4 s-8 + s-4). */
.blend-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  grid-auto-flow: row dense;
  gap: 18px;
  align-items: start;
}
.blend-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.blend-page > .page-header {
  margin-bottom: 0;
}
.blend-page > .blend-chart {
  grid-column: 1;
}
.blend-page > .blend-side {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .blend-page {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}
:root[data-mode="garden"] .blend-page > .blend-chart {
  align-self: stretch;
}

.nw {
  white-space: nowrap;
}
/* material markers: softwood circle, hardwood 2px square, blend triangle */
.mk {
  display: inline-block;
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--sw);
}
.mk.hardwood {
  border-radius: 2px;
  background: var(--hw);
  transform: scale(0.92);
}
.mk.blend {
  border-radius: 0;
  background: var(--bl);
  clip-path: polygon(50% 4%, 98% 92%, 2% 92%);
  transform: scale(1.18);
}

/* ================================================================ states */
.blend-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.blend-state p {
  margin: 14px 0;
}
.blend-status {
  display: grid;
  justify-items: center;
}

/* ================================================================ signature (garden hero) */
.blend-sig {
  position: relative;
  margin: 0;
  min-width: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.blend-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.blend-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 132;
}
.blend-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.blend-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.stop-hw {
  stop-color: var(--hw);
}
.stop-bl {
  stop-color: var(--bl);
}
.stop-sw {
  stop-color: var(--sw);
}
.sg-band {
  fill: url(#blend-sig-grad);
  opacity: 0.6;
}
.sg-m {
  font-family: var(--font-mono);
  font-size: 10.5px;
  fill: var(--text-2);
}
.sg-v {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 500;
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--surface);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.sg-line {
  fill: none;
  stroke: color-mix(in oklab, var(--bl) 50%, var(--rc));
  stroke-width: 2.1;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.sg-pt {
  fill: var(--sw);
  stroke: var(--surface);
  stroke-width: 1.6;
  paint-order: stroke;
}
.sg-pt.hardwood {
  fill: var(--hw);
}
.sg-pt.blend {
  fill: var(--bl);
}

/* ================================================================ controls */
.blend-controls {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "title count"
    "groups groups";
  align-items: baseline;
  gap: 14px 14px;
  padding: 20px 22px;
}
.ctl-title {
  grid-area: title;
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}
.blend-count {
  grid-area: count;
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.6;
}
.blend-count .sep {
  margin: 0 8px;
  color: var(--text-3);
}
.ctl-groups {
  grid-area: groups;
  display: grid;
  gap: 14px;
}
.ctl-group .field-label {
  margin-bottom: 8px;
}
.blend-chips > button {
  min-height: 32px;
  font-size: 13px;
}
.ctl-row {
  grid-area: row;
  display: none;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 18px 28px;
  min-width: 0;
}
.ctl {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ctl-all {
  min-width: 240px;
}

/* ================================================================ chart card */
.blend-chart {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "head head"
    "note note"
    "plot plot"
    "legend hint"
    "caveat caveat";
  align-items: start;
  column-gap: 20px;
  padding: 22px 24px;
}
.chart-head {
  grid-area: head;
  min-width: 0;
}
.chart-head h2 {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--text);
}
.chart-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-2);
}
.unit-flag {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--warn);
  color: var(--warn);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.unit-note {
  grid-area: note;
  margin-top: 10px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--warn);
}
.blend-legend {
  grid-area: legend;
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 12.5px;
  color: var(--text-2);
}
.blend-legend li {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.blend-plot-box,
.blend-plot-state {
  grid-area: plot;
}
.blend-plot-box {
  position: relative;
  width: 100%;
  min-width: 0;
  margin-top: 14px;
  /* the svg is sized from this box; clip a resize frame instead of scrolling the page */
  overflow-x: clip;
}
.blend-plot {
  display: block;
  touch-action: pan-y;
}
.blend-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--chart-text);
}
.blend-plot .axis-title {
  font-family: var(--font-body);
  font-size: 12px;
}
.garden-only {
  display: none;
}
.grid line {
  stroke: var(--chart-grid);
  shape-rendering: crispEdges;
}
.axis line {
  stroke: var(--chart-axis);
  shape-rendering: crispEdges;
}
.band {
  fill-opacity: 0.07;
}
.band.hardwood {
  fill: var(--hw);
}
.band.softwood {
  fill: var(--sw);
}
.ratio-band {
  display: none;
}
.ratio-band rect {
  fill: url(#blend-ratio-grad);
  opacity: 0.7;
}
.blend-plot .ratio-band text {
  font: 400 11.5px var(--font-body);
  fill: var(--text-2);
}
.blend-line {
  fill: none;
  stroke: var(--bl);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.85;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.hit {
  fill: transparent;
}
.plot-point:focus-visible .hit {
  stroke: var(--focus);
  stroke-width: 2.5;
}
.mark {
  fill: var(--sw);
  stroke: var(--chart-paper);
  stroke-width: 2;
  stroke-linejoin: round;
  paint-order: stroke;
}
.plot-point.hardwood .mark {
  fill: var(--hw);
}
.plot-point.blend .mark {
  fill: var(--bl);
}
.blend-plot .end-labels text {
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--chart-paper);
  stroke-width: 4px;
  stroke-linejoin: round;
}
/* hover layers: garden guide and polarized HUD are both rendered, one shows per mode */
.guide,
.hud {
  display: none;
  pointer-events: none;
}
.hud-l {
  stroke: var(--text-2);
  stroke-opacity: 0.55;
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.hud-tk {
  stroke: var(--text);
  stroke-width: 1;
  fill: none;
}
.hud-ring {
  fill: none;
  stroke: var(--text);
  stroke-width: 1.5;
}
.hud-box {
  fill: var(--surface);
  stroke: var(--line-strong);
  stroke-width: 1;
}
.blend-plot .hud-t {
  font-size: 10.5px;
  fill: var(--text);
}
.guide-l {
  stroke: var(--text);
  stroke-opacity: 0.35;
  stroke-dasharray: 3 4;
}
.guide-focus {
  fill: none;
  stroke: var(--text);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}
/* floating tooltip (also the polite live region for the readout) */
.blend-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 5;
  min-width: 168px;
  max-width: 236px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  box-shadow: var(--shadow-pop);
  pointer-events: none;
  opacity: 0;
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) - 100% - 12px));
  transition: opacity 0.12s;
}
.blend-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) - 100% - 12px));
}
.blend-tip.below {
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) + 16px));
}
.blend-tip.left.below {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) + 16px));
}
.blend-tip.on {
  opacity: 1;
}
.tip-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tip-head b {
  font-weight: 500;
}
.tip-code {
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-2);
}
.tip-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 14px;
}
.tip-row span {
  color: var(--text-2);
}
.tip-row b {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
  white-space: nowrap;
}
.tip-foot {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}
.blend-hint {
  grid-area: hint;
  margin-top: 12px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-3);
  text-align: right;
}
.blend-caveat {
  grid-area: caveat;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 14px;
}
.blend-caveat svg {
  flex: none;
  margin-top: 3px;
  color: var(--text-3);
}

/* ================================================================ side panels */
.blend-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}
.blend-cond,
.blend-range {
  display: none;
}
.blend-ladder {
  flex: 1;
  padding: 22px;
}
.ladder-k {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-3);
}
.blend-ladder h2 {
  margin: 4px 0 6px;
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}
.side-note {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.ladder {
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
  display: grid;
  gap: 7px;
}
.ladder li {
  display: grid;
  grid-template-columns: 44px 52px minmax(0, 1fr) 62px;
  align-items: center;
  gap: 8px;
  padding: 2px 4px;
  margin: 0 -4px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  transition: background 0.15s;
}
.ladder li.on {
  background: var(--surface-hover);
}
.lad-ratio {
  display: block;
  height: 8px;
  border-radius: 2px;
  overflow: hidden;
  background: var(--hw);
}
.lad-ratio i {
  display: block;
  height: 100%;
  background: var(--sw);
}
.lad-r {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.lad-v {
  display: block;
  height: 4px;
  border-radius: 2px;
  background: var(--line-soft);
}
.lad-v i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--sw);
}
.lad-v i.hardwood {
  background: var(--hw);
}
.lad-v i.blend {
  background: var(--bl);
}
.lad-n {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--text);
}
.facts {
  display: grid;
  gap: 8px;
  margin: 12px 0 10px;
}
.fact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  font-size: 14px;
}
.fact .l {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: var(--text-2);
}
.fact .v {
  font-family: var(--font-mono);
  color: var(--text);
  white-space: nowrap;
}

/* ================================================================ table */
.blend-table {
  overflow: hidden;
}
.table-head {
  padding: 22px 24px 14px;
}
.table-head h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}
.table-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-2);
}
.blend-table .table-scroll:focus-visible {
  outline-offset: -2px;
}
.blend-table tbody tr.on td {
  background: var(--surface-hover);
}
.ratio-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.ratio-bar {
  display: none;
  width: 54px;
  height: 6px;
  border-radius: 9px;
  overflow: hidden;
  background: color-mix(in oklab, var(--hw) 40%, var(--surface));
}
.ratio-bar i {
  display: block;
  height: 100%;
  border-radius: 9px;
  background: color-mix(in oklab, var(--sw) 75%, var(--surface));
}

/* ================================================================ polarized (v1) */
:root[data-mode="polarized"] .blend-chart {
  grid-template-columns: auto minmax(0, 1fr);
}
:root[data-mode="polarized"] .blend-legend li {
  white-space: nowrap;
}
:root[data-mode="polarized"] .hud {
  display: inline;
}
:root[data-mode="polarized"] .blend-tip {
  background: var(--surface-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
:root[data-mode="polarized"] .tip-head b {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--text-2);
}
:root[data-mode="polarized"] .tip-row b {
  font-size: 15px;
  font-weight: 400;
}
:root[data-mode="polarized"] .blend-table th {
  font-family: var(--font-mono);
}
:root[data-mode="polarized"] .blend-table td.numeric {
  font-family: var(--font-mono);
  font-size: 13px;
}
:root[data-mode="polarized"] .blend-table .text-button {
  color: var(--accent-ink);
}

/* ================================================================ garden (v4) */
:root[data-mode="garden"] .blend-controls {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas: "row count";
  align-items: end;
  padding: 22px 24px;
}
:root[data-mode="garden"] .ctl-title,
:root[data-mode="garden"] .ctl-groups {
  display: none;
}
:root[data-mode="garden"] .ctl-row {
  display: flex;
}
:root[data-mode="garden"] .blend-count {
  text-align: right;
  padding-bottom: 8px;
}
:root[data-mode="garden"] .blend-chart {
  grid-template-areas:
    "head legend"
    "note note"
    "plot plot"
    "hint hint"
    "caveat caveat";
}
:root[data-mode="garden"] .chart-head h2,
:root[data-mode="garden"] .table-head h2 {
  font-size: 19px;
  font-weight: 500;
}
:root[data-mode="garden"] .chart-head p {
  margin-top: 2px;
}
:root[data-mode="garden"] .blend-legend {
  margin: 4px 0 0;
  justify-content: flex-end;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .blend-plot .axis-title {
  font-size: 11.5px;
  fill: var(--text-2);
}
:root[data-mode="garden"] .garden-only,
:root[data-mode="garden"] .ratio-band,
:root[data-mode="garden"] .guide {
  display: inline;
}
:root[data-mode="garden"] .x-title,
:root[data-mode="garden"] .end-bands,
:root[data-mode="garden"] .end-labels {
  display: none;
}
:root[data-mode="garden"] .blend-line {
  stroke: color-mix(in oklab, var(--bl) 50%, var(--rc));
  stroke-width: 2.2;
  opacity: 1;
}
:root[data-mode="garden"] .mark {
  stroke: var(--surface);
}
:root[data-mode="garden"] .blend-tip {
  padding: 10px 13px;
  border: 0;
  border-radius: 16px;
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow);
  transition:
    opacity 0.18s,
    transform 0.18s var(--ease);
}
:root[data-mode="garden"] .blend-hint {
  text-align: left;
  font-size: 13px;
  color: var(--text-2);
}
:root[data-mode="garden"] .blend-caveat svg {
  color: var(--accent);
}
:root[data-mode="garden"] .blend-ladder {
  display: none;
}
:root[data-mode="garden"] .blend-cond,
:root[data-mode="garden"] .blend-range {
  display: block;
  padding: 22px 24px;
}
:root[data-mode="garden"] .blend-cond {
  background: linear-gradient(
    160deg,
    color-mix(in oklab, var(--surface) 94%, transparent),
    color-mix(in oklab, var(--bl-tint) 90%, transparent)
  );
}
:root[data-mode="garden"] .blend-side h2 {
  font-size: 18px;
  font-weight: 500;
  line-height: 1.35;
  margin-bottom: 10px;
  color: var(--text);
}
:root[data-mode="garden"] .fact {
  border-radius: 16px;
  background: color-mix(in oklab, var(--surface) 62%, transparent);
}
:root[data-mode="garden"] .fact .v.big {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-weight: 400;
  font-size: 24px;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.02em;
}
:root[data-mode="garden"] .ratio-bar {
  display: inline-block;
}
:root[data-mode="garden"] .blend-table .text-button {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  background: color-mix(in oklab, var(--surface) 80%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .blend-table .text-button:hover {
  text-decoration: none;
  background: var(--surface);
}

/* ================================================================ responsive */
@media (max-width: 1279px) {
  :root[data-mode="polarized"] .blend-chart {
    grid-template-areas:
      "head head"
      "note note"
      "plot plot"
      "legend legend"
      "hint hint"
      "caveat caveat";
  }
  :root[data-mode="polarized"] .blend-hint {
    text-align: left;
    margin-top: 8px;
  }
}
@media (max-width: 1100px) {
  .blend-page {
    grid-template-columns: minmax(0, 1fr) 280px;
  }
  .ladder li {
    grid-template-columns: 36px 48px minmax(0, 1fr) 56px;
  }
}
@media (max-width: 900px) {
  .blend-page,
  :root[data-mode="garden"] .blend-page {
    grid-template-columns: minmax(0, 1fr);
  }
  .blend-page > .blend-chart,
  .blend-page > .blend-side {
    grid-column: 1;
  }
  :root[data-mode="garden"] .blend-side {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .blend-controls,
  :root[data-mode="garden"] .blend-controls {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "title"
      "count"
      "groups";
    padding: 16px;
  }
  :root[data-mode="garden"] .blend-controls {
    grid-template-areas:
      "row"
      "count";
  }
  :root[data-mode="garden"] .blend-count {
    text-align: left;
    padding-bottom: 0;
  }
  .ctl,
  .ctl-all {
    width: 100%;
    min-width: 0;
  }
  .blend-chips {
    flex-wrap: wrap;
  }
  .blend-chart,
  :root[data-mode="garden"] .blend-chart {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "head"
      "legend"
      "note"
      "plot"
      "hint"
      "caveat";
    padding: 16px;
  }
  :root[data-mode="garden"] .blend-legend {
    justify-content: flex-start;
    margin-top: 10px;
  }
  .blend-hint {
    text-align: left;
  }
  :root[data-mode="garden"] .blend-side {
    grid-template-columns: minmax(0, 1fr);
  }
  .blend-ladder,
  :root[data-mode="garden"] .blend-cond,
  :root[data-mode="garden"] .blend-range {
    padding: 18px 16px;
  }
  .table-head {
    padding: 18px 16px 12px;
  }
  .fact {
    font-size: 13px;
    padding: 10px 12px;
  }
}
</style>
