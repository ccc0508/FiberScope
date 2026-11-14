<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Info, RefreshCw, RotateCcw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  typeNames,
  typeKeys,
  type Metadata,
  type Sample,
  type SampleType,
  type ListResult,
} from "../api";
import { formatR, pearson, scatterTicks, tickDigits } from "../analysis";
import { isGarden } from "../mode";
import { useCountUp, vSeg } from "../motion";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import PageHeader from "../components/PageHeader.vue";

/*
 * 纤维—纸张关联：一个模板服务两种显示模式。
 *  偏光（v1）：筛选条（类型芯片 + 两个指标）→ 散点图（HUD 十字准星）| Pearson r 列表（细数字 + −1…+1 刻度）→ 明细表
 *  花园（v4）：控制瓦片（类型分段 + 两个指标）→ 散点图（形状标记）| Pearson r 表盘 + 分组行 → 明细表
 * 两套装饰都渲染，按 :root[data-mode=…] 显隐；不 remount，筛选、悬停与焦点跨模式保留。
 */
interface Row extends Sample {
  [key: string]: string | number | null;
}
type Indicator = Metadata["indicators"][number];
type GroupKey = SampleType | "all";
const route = useRoute(),
  router = useRouter();
const rows = ref<Row[]>([]),
  metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const selected = ref<Row | null>(null),
  focused = ref<Row | null>(null);
const xDefault: Indicator = {
  key: "fiber_length_weighted_mm",
  name: "纤维长度（长度加权）",
  unit: "mm",
  group: "fiber",
  scope: ["core"],
  unit_status: "confirmed",
};
const yDefault: Indicator = {
  key: "tensile_index",
  name: "抗张指数",
  unit: "N·m/g",
  group: "paper",
  scope: ["core"],
  unit_status: "confirmed",
};
const xOptions = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) => i.group === "fiber" && i.scope.includes("core"),
    ) ?? [xDefault],
);
const yOptions = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) => i.group === "paper" && i.scope.includes("core"),
    ) ?? [yDefault],
);
const xMetric = computed(
  () => xOptions.value.find((i) => i.key === route.query.x) ?? xDefault,
);
const yMetric = computed(
  () => yOptions.value.find((i) => i.key === route.query.y) ?? yDefault,
);
const kind = computed<GroupKey>(() =>
  typeKeys.includes(route.query.type as SampleType)
    ? (route.query.type as SampleType)
    : "all",
);
const typeOptions: { value: GroupKey; label: string }[] = [
  { value: "all", label: "全部样本类型" },
  ...typeKeys.map((t) => ({ value: t, label: typeNames[t] })),
];
const unitFlagged = (i: Indicator) => i.unit_status !== "confirmed";
const unitFlagText = (i: Indicator) =>
  i.unit_status === "tentative" ? "单位暂定" : "单位未确认";
const options = (items: Indicator[]) =>
  items.map((i) => ({
    value: i.key,
    label: unitFlagged(i) ? `${i.name}（单位待复核）` : i.name,
  }));
const value = (r: Row, i: Indicator): number | null =>
  typeof r[i.key] === "number" && Number.isFinite(r[i.key])
    ? (r[i.key] as number)
    : null;
const unit = (i: Indicator) => i.unit ?? "单位未确认";
const visible = computed(() =>
  rows.value
    .filter((r) => kind.value === "all" || r.sample_type === kind.value)
    .sort((a, b) => a.canonical_code.localeCompare(b.canonical_code)),
);
const valid = computed(() =>
  visible.value.filter(
    (r) => value(r, xMetric.value) !== null && value(r, yMetric.value) !== null,
  ),
);
const legendTypes = computed(() =>
  typeKeys.filter((t) => kind.value === "all" || kind.value === t),
);
const stats = computed(() =>
  [
    ...(kind.value === "all"
      ? [{ key: "all" as GroupKey, name: "全部类型（合并）" }]
      : []),
    ...typeKeys
      .filter((t) => kind.value === "all" || kind.value === t)
      .map((t) => ({ key: t as GroupKey, name: typeNames[t] })),
  ].map((g) => {
    const group = valid.value.filter(
      (r) => g.key === "all" || r.sample_type === g.key,
    );
    return {
      ...g,
      n: group.length,
      r: pearson(
        group.map((row) => [
          value(row, xMetric.value)!,
          value(row, yMetric.value)!,
        ]),
      ),
    };
  }),
);
const whyNoR = (n: number) =>
  n < 3 ? "少于3对数据，暂不计算" : "至少一个指标无变化，无法计算";
/** position on a −1 … +1 track, in % (v1 corr-axis) */
const rPos = (r: number) => ((r + 1) / 2) * 100;

/* ---------- 形状标记：针叶木圆、阔叶木圆角方、复配三角 ---------- */
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
const markSize = (t: SampleType) => (t === "blend" ? 5 : 5.2);

/* ---------- 散点图：按容器实际宽度绘制，文字不随缩放变形 ---------- */
const plotBox = ref<HTMLElement>();
const plotSvg = ref<SVGSVGElement>();
const plotWidth = ref(760),
  plotBoxH = ref(0);
let sizeObserver: ResizeObserver | undefined;
onMounted(() => {
  sizeObserver = new ResizeObserver(([entry]) => {
    if (!entry) return;
    plotWidth.value = Math.max(260, Math.round(entry.contentRect.width));
    plotBoxH.value = Math.round(entry.contentRect.height);
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
const plotMin = computed(() => (narrow.value ? 320 : 420));
// the plot row takes the free height of a stretched chart card (paired with a taller panel)
const plotH = computed(() => Math.min(640, Math.max(plotMin.value, plotBoxH.value)));
const margin = computed(() => ({
  t: 38,
  r: narrow.value ? 12 : 20,
  b: 54,
  l: narrow.value ? 46 : 60,
}));
const plotRight = computed(() => plotWidth.value - margin.value.r);
const plotBottom = computed(() => plotH.value - margin.value.b);
const xTicks = computed(() =>
  scatterTicks(
    valid.value.map((r) => value(r, xMetric.value)!),
    narrow.value ? 4 : 7,
  ),
);
const yTicks = computed(() =>
  scatterTicks(
    valid.value.map((r) => value(r, yMetric.value)!),
    narrow.value ? 4 : 5,
  ),
);
const xDigits = computed(() => tickDigits(xTicks.value)),
  yDigits = computed(() => tickDigits(yTicks.value));
const lo = (t: number[]) => t[0]!,
  hi = (t: number[]) => t[t.length - 1]!;
const px = (v: number) =>
  margin.value.l +
  ((v - lo(xTicks.value)) / (hi(xTicks.value) - lo(xTicks.value) || 1)) *
    (plotRight.value - margin.value.l);
const py = (v: number) =>
  plotBottom.value -
  ((v - lo(yTicks.value)) / (hi(yTicks.value) - lo(yTicks.value) || 1)) *
    (plotBottom.value - margin.value.t);
interface Point {
  r: Row;
  x: number;
  y: number;
}
const points = computed<Point[]>(() =>
  valid.value.map((r) => ({
    r,
    x: px(value(r, xMetric.value)!),
    y: py(value(r, yMetric.value)!),
  })),
);
// 方向键顺序：←/→ 按横轴，↑/↓ 按纵轴（数值由小到大）
const byX = computed(() =>
  [...points.value].sort((a, b) => a.x - b.x || b.y - a.y),
);
const byY = computed(() =>
  [...points.value].sort((a, b) => b.y - a.y || a.x - b.x),
);
const hoverPoint = computed(() => {
  const r = focused.value;
  if (!r) return null;
  return points.value.find((p) => p.r.canonical_code === r.canonical_code) ?? null;
});
// 紧凑读数（HUD 坐标框）：大数保留一位，常规两位，小数四位
const compact = (v: number) =>
  v.toLocaleString("zh-CN", {
    maximumFractionDigits: Math.abs(v) >= 100 ? 1 : Math.abs(v) >= 1 ? 2 : 4,
  });
// 偏光 HUD：准星两端钉在坐标轴上的读数框（宽度按字符估算，免去测量）
const textWidth = (s: string) =>
  [...s].reduce((w, ch) => w + (/[　-鿿＀-￯]/.test(ch) ? 10.5 : 6.4), 0);
const hud = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  const xl = `${compact(value(p.r, xMetric.value)!)} ${unit(xMetric.value)}`,
    yl = compact(value(p.r, yMetric.value)!);
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
    left: p.x + 16 + 250 > plotWidth.value,
    below: p.y < 136,
  };
});

let pointerActive = false;
const pointerOnPoint = ref(false);
function pointer(e: PointerEvent) {
  if (e.pointerType === "touch") return;
  const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
  const mx = e.clientX - box.left,
    my = e.clientY - box.top;
  let best: Row | null = null,
    d = 30 * 30;
  for (const p of points.value) {
    const dist = (p.x - mx) ** 2 + (p.y - my) ** 2;
    if (dist < d) {
      d = dist;
      best = p.r;
    }
  }
  pointerOnPoint.value = !!best;
  if (best) {
    pointerActive = true;
    if (focused.value?.canonical_code !== best.canonical_code) focused.value = best;
  } else if (pointerActive) {
    pointerActive = false;
    focused.value = null;
  }
}
function pointerLeave() {
  pointerOnPoint.value = false;
  if (pointerActive) focused.value = null;
  pointerActive = false;
}
// 指针点击取最近的点（重合点亦然）；读屏的激活事件落在点本身
function plotClick(e: MouseEvent) {
  const el = (e.target as Element | null)?.closest<SVGGElement>("[data-point]");
  const hit = el
    ? valid.value.find((r) => r.canonical_code === el.dataset.point)
    : undefined;
  const r = pointerActive && focused.value ? focused.value : hit;
  if (r) selected.value = r;
}
function pointKey(e: KeyboardEvent, r: Row) {
  let list: Point[] | null = null,
    step = 0;
  if (e.key === "ArrowRight") (list = byX.value), (step = 1);
  else if (e.key === "ArrowLeft") (list = byX.value), (step = -1);
  else if (e.key === "ArrowUp") (list = byY.value), (step = 1);
  else if (e.key === "ArrowDown") (list = byY.value), (step = -1);
  else if (e.key === "Home" || e.key === "End") list = byX.value;
  else if (e.key === "Escape") {
    focused.value = null;
    return;
  } else return;
  e.preventDefault();
  const i = list.findIndex((p) => p.r.canonical_code === r.canonical_code);
  const next =
    e.key === "Home"
      ? list[0]
      : e.key === "End"
        ? list[list.length - 1]
        : list[i + step];
  if (next)
    plotSvg.value
      ?.querySelector<SVGGElement>(`[data-point="${next.r.canonical_code}"]`)
      ?.focus();
}
function pointBlur(r: Row) {
  if (focused.value?.canonical_code === r.canonical_code && !pointerActive)
    focused.value = null;
}

/* ---------- Pearson r 表盘（花园）：−1（左）… +1（右），指针为首组 r，类型标记在外缘 ---------- */
const DIAL = { cx: 180, cy: 176, R: 140 };
const dialAngle = (r: number) => Math.PI * (1 - (r + 1) / 2);
const dialPt = (r: number, rad: number): [number, number] => [
  DIAL.cx + Math.cos(dialAngle(r)) * rad,
  DIAL.cy - Math.sin(dialAngle(r)) * rad,
];
function dialArc(r0: number, r1: number, rad: number) {
  const [x0, y0] = dialPt(r0, rad),
    [x1, y1] = dialPt(r1, rad);
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${rad},${rad} 0 0 ${r1 > r0 ? 1 : 0} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}
const dialTicks = [-1, -0.5, 0, 0.5, 1].map((v) => {
  const [x1, y1] = dialPt(v, DIAL.R - 13),
    [x2, y2] = dialPt(v, DIAL.R - 22),
    [tx, ty] = dialPt(v, DIAL.R - 36);
  return {
    v,
    x1,
    y1,
    x2,
    y2,
    tx,
    ty: ty + 4,
    label: v === 0 ? "0" : `${v < 0 ? "−" : "+"}${Math.abs(v)}`,
  };
});
const dialTrack = dialArc(-1, 1, DIAL.R);
const head = computed(() => stats.value[0] ?? null);
const dial = computed(() => {
  const r = head.value?.r ?? null;
  return {
    fill: r !== null && r !== 0 ? dialArc(0, r, DIAL.R) : null,
    angle: r === null ? null : -(180 * (1 - (r + 1) / 2)),
    marks: stats.value
      .filter((s) => s.key !== "all" && s.r !== null)
      .map((s) => {
        const [x, y] = dialPt(s.r!, DIAL.R + 17);
        return { key: s.key as SampleType, d: shapePath(s.key as SampleType, x, y, 6) };
      }),
  };
});
const dialEl = ref<HTMLElement>();
const dialShown = useCountUp(() => head.value?.r ?? null, {
  el: dialEl,
  decimals: 3,
});

/* ---------- 页头签名（花园）：示例组合的散点与合并 r，数据来自本页已读取的配对数据 ---------- */
const sigX = computed(
  () => metadata.value?.indicators.find((i) => i.key === xDefault.key) ?? xDefault,
);
const sigY = computed(
  () => metadata.value?.indicators.find((i) => i.key === yDefault.key) ?? yDefault,
);
const sig = computed(() => {
  const pts = rows.value
    .map((r) => ({ r, x: value(r, xDefault), y: value(r, yDefault) }))
    .filter((p): p is { r: Row; x: number; y: number } => p.x !== null && p.y !== null);
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p.x),
    ys = pts.map((p) => p.y);
  const x0 = Math.min(...xs),
    x1 = Math.max(...xs),
    y0 = Math.min(...ys),
    y1 = Math.max(...ys);
  const X = (v: number) => 16 + ((v - x0) / (x1 - x0 || 1)) * 234,
    Y = (v: number) => 118 - ((v - y0) / (y1 - y0 || 1)) * 106;
  return {
    marks: pts.map((p) => ({
      code: p.r.canonical_code,
      t: p.r.sample_type,
      d: shapePath(p.r.sample_type, X(p.x), Y(p.y), 3),
    })),
    r: pearson(pts.map((p) => [p.x, p.y])),
    n: pts.length,
  };
});

/* ---------- 交互 ---------- */
function update(key: string, v: string) {
  void router.replace({ query: { ...route.query, [key]: v } });
}
const isDefaultPair = computed(
  () => xMetric.value.key === xDefault.key && yMetric.value.key === yDefault.key,
);
function resetPair() {
  const query = { ...route.query };
  delete query.x;
  delete query.y;
  void router.replace({ query });
}
// 样本类型：单选组，方向键在组内移动并选中
function typeKey(e: KeyboardEvent, i: number) {
  const n = typeOptions.length;
  let k = -1;
  if (e.key === "ArrowRight" || e.key === "ArrowDown") k = (i + 1) % n;
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp") k = (i - 1 + n) % n;
  else if (e.key === "Home") k = 0;
  else if (e.key === "End") k = n - 1;
  else return;
  e.preventDefault();
  update("type", typeOptions[k]!.value);
  const group = (e.currentTarget as HTMLElement).parentElement;
  group?.querySelectorAll<HTMLButtonElement>("button")[k]?.focus();
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
    const [data, meta] = await Promise.all([
      get<ListResult<Row>>("fiber-paper", { page_size: 500 }, current.signal),
      get<Metadata>("metadata", {}, current.signal),
    ]);
    if (current.signal.aborted) return;
    rows.value = data.data;
    metadata.value = meta;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据读取失败";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
watch(
  () => [kind.value, xMetric.value.key, yMetric.value.key],
  () => (focused.value = null),
);
void load();
onBeforeUnmount(() => {
  controller?.abort();
  sizeObserver?.disconnect();
});
</script>

<template>
  <div class="overview association-page">
    <PageHeader description="探索纤维特性与纸张性能的对应关系。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <figure class="as-sig">
          <svg
            v-if="sig"
            viewBox="0 0 420 132"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <line class="sg-base" x1="8" x2="258" y1="126" y2="126" />
            <line class="sg-base" x1="8" x2="8" y1="6" y2="126" />
            <path
              v-for="m in sig.marks"
              :key="m.code"
              class="sg-dot"
              :class="m.t"
              :d="m.d"
            />
            <text class="sg-t" x="418" y="34" text-anchor="end">合并 Pearson r</text>
            <text class="sg-n" x="418" y="84" text-anchor="end">
              {{ formatR(sig.r) }}
            </text>
            <text class="sg-m" x="418" y="106" text-anchor="end">{{ sig.n }} 对</text>
          </svg>
          <div v-else class="as-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            {{ sigX.name }} × {{ sigY.name }} · 合并 r
            <b>{{ sig ? formatR(sig.r) : "—" }}</b> · 相关不等于因果
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <div v-if="error" class="card as-state as-status" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card as-state as-status" role="status">
      正在读取纤维与纸张数据…
    </div>
    <template v-else>
      <section class="card as-controls" aria-label="关联分析筛选">
        <div class="ctl ctl-type">
          <span id="as-type-label" class="field-label">样本类型</span>
          <div
            v-seg
            class="seg as-types"
            role="radiogroup"
            aria-labelledby="as-type-label"
          >
            <button
              v-for="(t, i) in typeOptions"
              :key="t.value"
              type="button"
              role="radio"
              :aria-checked="kind === t.value"
              :tabindex="kind === t.value ? 0 : -1"
              @click="update('type', t.value)"
              @keydown="typeKey($event, i)"
            >
              <i
                v-if="t.value !== 'all'"
                class="mk"
                :class="t.value"
                aria-hidden="true"
              ></i
              >{{ t.label }}
            </button>
          </div>
        </div>
        <div class="ctl ctl-axis">
          <span class="field-label">横轴 · 纤维特性</span
          ><FilterSelect
            id="association-x"
            label="纤维特性"
            :model-value="xMetric.key"
            :options="options(xOptions)"
            @update:model-value="update('x', $event)"
          />
        </div>
        <div class="ctl ctl-axis">
          <span class="field-label">纵轴 · 纸张性能</span
          ><FilterSelect
            id="association-y"
            label="纸张性能"
            :model-value="yMetric.key"
            :options="options(yOptions)"
            @update:model-value="update('y', $event)"
          />
        </div>
        <button
          type="button"
          class="button as-reset"
          :disabled="isDefaultPair"
          @click="resetPair"
        >
          <RotateCcw :size="14" aria-hidden="true" />恢复示例组合
        </button>
      </section>

      <section class="card as-chart" aria-labelledby="as-chart-title">
        <div class="as-chart-head">
          <h2 id="as-chart-title">{{ xMetric.name }}与{{ yMetric.name }}</h2>
          <p class="pair-count" role="status">
            <span class="nw"
              >{{ visible.length }} 个样本<span class="sep" aria-hidden="true">·</span></span
            ><span class="nw"
              >{{ valid.length }} 对有效数据<span class="sep" aria-hidden="true">·</span></span
            ><span class="nw">{{ visible.length - valid.length }} 个缺失配对</span>
          </p>
        </div>
        <ul class="as-legend" aria-label="图例">
          <li v-for="t in legendTypes" :key="t">
            <i class="mk" :class="t" aria-hidden="true"></i>{{ typeNames[t] }}
          </li>
        </ul>
        <p class="axis-caption">
          横轴：{{ xMetric.name }}（{{ unit(xMetric) }}）　纵轴：{{
            yMetric.name
          }}（{{ unit(yMetric) }}）<span v-if="unitFlagged(yMetric)" class="unit-flag">{{
            unitFlagText(yMetric)
          }}</span>
        </p>
        <p v-if="unitFlagged(yMetric)" class="unit-note">
          <Info :size="15" aria-hidden="true" /><span
            >{{ yMetric.name }}单位{{
              yMetric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
            }}，数值保留原始口径。</span
          >
        </p>
        <div v-if="!valid.length" class="as-state as-plot-state" role="status">
          当前没有成对的有效数据，请切换指标或样本类型。
        </div>
        <div
          v-else
          ref="plotBox"
          class="as-plot-box"
          :style="{ '--plot-min': `${plotMin}px` }"
        >
          <svg
            ref="plotSvg"
            class="as-plot"
            :class="{ pointing: pointerOnPoint }"
            role="group"
            :width="plotWidth"
            :height="plotH"
            :viewBox="`0 0 ${plotWidth} ${plotH}`"
            :aria-label="`${xMetric.name}与${yMetric.name}散点图。每点代表一个样本；Tab聚焦，方向键切换，Enter或空格查看详情`"
            @pointermove="pointer"
            @pointerleave="pointerLeave"
            @click="plotClick"
          >
            <!-- 偏光：目镜视场四角 -->
            <g class="reticle" aria-hidden="true">
              <path
                :d="`M${margin.l},${margin.t + 12}V${margin.t}H${margin.l + 12}M${plotRight - 12},${margin.t}H${plotRight}V${margin.t + 12}M${plotRight},${plotBottom - 12}V${plotBottom}H${plotRight - 12}`"
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
                {{ number(t, yDigits) }}
              </text>
              <g v-for="t in xTicks" :key="`tx${t}`">
                <line :x1="px(t)" :x2="px(t)" :y1="plotBottom" :y2="plotBottom + 5" />
                <text :x="px(t)" :y="plotBottom + 20" text-anchor="middle">
                  {{ number(t, xDigits) }}
                </text>
              </g>
              <text class="axis-title" x="2" :y="margin.t - 18">
                <tspan class="garden-only">↑ </tspan>{{ yMetric.name }} / {{ unit(yMetric) }}
              </text>
              <text
                class="axis-title"
                :x="plotRight"
                :y="plotH - 8"
                text-anchor="end"
              >
                {{ xMetric.name }} / {{ unit(xMetric) }}<tspan class="garden-only"> →</tspan>
              </text>
            </g>
            <g
              v-for="p in points"
              :key="p.r.canonical_code"
              class="pt"
              :class="p.r.sample_type"
              :data-point="p.r.canonical_code"
              role="button"
              tabindex="0"
              :aria-label="`${p.r.canonical_code}，${typeNames[p.r.sample_type]}，${xMetric.name}${value(p.r, xMetric)}，${yMetric.name}${value(p.r, yMetric)}，查看详情`"
              @focus="focused = p.r"
              @blur="pointBlur(p.r)"
              @keydown="pointKey($event, p.r)"
              @keydown.enter.prevent="selected = p.r"
              @keydown.space.prevent="selected = p.r"
            >
              <circle class="hit" :cx="p.x" :cy="p.y" r="11" />
              <path class="mark" :d="shapePath(p.r.sample_type, p.x, p.y, markSize(p.r.sample_type))" />
              <title>
                {{ p.r.canonical_code }} · {{ xMetric.name }}
                {{ number(value(p.r, xMetric), 4) }} {{ unit(xMetric) }} ·
                {{ yMetric.name }} {{ number(value(p.r, yMetric), 4) }}
                {{ unit(yMetric) }}
              </title>
            </g>
            <!-- 悬停 / 聚焦的点画在最上层并放大 -->
            <g v-if="hoverPoint" class="hot pt" :class="hoverPoint.r.sample_type" aria-hidden="true">
              <path
                class="mark"
                :d="shapePath(hoverPoint.r.sample_type, hoverPoint.x, hoverPoint.y, markSize(hoverPoint.r.sample_type) * 1.4)"
              />
            </g>
            <!-- 花园：焦点圈 -->
            <g v-if="hoverPoint" class="guide" aria-hidden="true">
              <circle class="guide-focus" :cx="hoverPoint.x" :cy="hoverPoint.y" r="14" />
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
              <circle class="hud-ring" :cx="hoverPoint.x" :cy="hoverPoint.y" r="11" />
              <path
                class="hud-tk"
                :d="`M${hoverPoint.x - 17},${hoverPoint.y}h6M${hoverPoint.x + 11},${hoverPoint.y}h6M${hoverPoint.x},${hoverPoint.y - 17}v6M${hoverPoint.x},${hoverPoint.y + 11}v6`"
              />
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
            class="as-tip"
            :class="{ on: tip, left: tip?.left, below: tip?.below }"
            :style="tip?.style"
            role="status"
            aria-live="polite"
          >
            <template v-if="hoverPoint">
              <div class="tip-head">
                <i class="mk" :class="hoverPoint.r.sample_type" aria-hidden="true"></i
                ><b>{{ typeNames[hoverPoint.r.sample_type] }}</b>
              </div>
              <div class="tip-code">{{ hoverPoint.r.canonical_code }}</div>
              <div class="tip-row">
                <span>{{ xMetric.name }}</span
                ><b>{{ number(value(hoverPoint.r, xMetric), 4) }}<small>{{ unit(xMetric) }}</small></b>
              </div>
              <div class="tip-row">
                <span>{{ yMetric.name }}</span
                ><b>{{ number(value(hoverPoint.r, yMetric), 4) }}<small>{{ unit(yMetric) }}</small></b>
              </div>
            </template>
          </div>
        </div>
        <p class="as-hint">
          悬停或聚焦查看数值，点击查看样本详情与来源。重合的数据点也可通过明细表逐一查看。方向键在数据点间移动。
        </p>
      </section>

      <section class="card as-stats" aria-labelledby="as-stats-title">
        <p class="eyebrow as-eyebrow" aria-hidden="true">
          Pearson r<span class="garden-inline"> · −1 … +1</span>
        </p>
        <h2 id="as-stats-title">线性相关性</h2>
        <p class="as-stats-desc">
          Pearson r 范围为 −1 至 1；正值表示同向变化，负值表示反向变化，接近
          0 表示线性关联较弱。
        </p>
        <div class="as-dial">
          <svg class="dial-svg" viewBox="0 0 360 214" aria-hidden="true" focusable="false">
            <path class="dial-track" :d="dialTrack" />
            <g v-for="t in dialTicks" :key="t.v">
              <line class="dial-tick" :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2" />
              <text class="dial-tl" :x="t.tx" :y="t.ty" text-anchor="middle">{{ t.label }}</text>
            </g>
            <path v-if="dial.fill" class="dial-fill" :d="dial.fill" />
            <path
              v-for="m in dial.marks"
              :key="m.key"
              class="dial-mk"
              :class="m.key"
              :d="m.d"
            />
            <g
              v-if="dial.angle !== null"
              class="dial-needle"
              :style="{ '--a': `${dial.angle}deg` }"
            >
              <line :x1="DIAL.cx" :y1="DIAL.cy" :x2="DIAL.cx + DIAL.R - 30" :y2="DIAL.cy" />
              <circle :cx="DIAL.cx + DIAL.R - 30" :cy="DIAL.cy" r="4.5" />
            </g>
            <circle class="dial-hub" :cx="DIAL.cx" :cy="DIAL.cy" r="9" />
          </svg>
          <div v-if="head" ref="dialEl" class="dial-num">
            <span class="dial-big" aria-hidden="true">{{ formatR(dialShown) }}</span>
            <span class="sr-only">Pearson r {{ formatR(head.r) }}</span>
            <span class="dial-cap"
              ><span class="nw">{{ head.name }}</span> ·
              <span class="nw">{{ head.n }} 对有效数据</span></span
            >
            <small v-if="head.r === null" class="why">{{ whyNoR(head.n) }}</small>
          </div>
        </div>
        <ul class="corr-list" aria-label="各组 Pearson r">
          <li
            v-for="(s, i) in stats"
            :key="s.key"
            class="corr-row"
            :class="[s.key, { first: i === 0 }]"
          >
            <span class="corr-l"
              ><i v-if="s.key !== 'all'" class="mk" :class="s.key" aria-hidden="true"></i
              ><i v-else class="mk-all" aria-hidden="true"></i>{{ s.name }}</span
            >
            <strong class="corr-n" :data-group="s.key">{{ formatR(s.r) }}</strong>
            <span class="corr-axis" aria-hidden="true">
              <span class="ca-mid"></span>
              <template v-if="s.r !== null">
                <span
                  class="ca-bar"
                  :style="{
                    left: `${Math.min(50, rPos(s.r))}%`,
                    width: `${Math.abs(rPos(s.r) - 50)}%`,
                  }"
                ></span>
                <span class="ca-dot" :style="{ left: `${rPos(s.r)}%` }"></span>
              </template>
            </span>
            <span class="corr-s">{{ s.n }} 对有效数据</span>
            <small v-if="s.r === null" class="why">{{ whyNoR(s.n) }}</small>
          </li>
        </ul>
        <p class="caveat as-note">
          <Info :size="15" aria-hidden="true" /><span
            >仅使用两个指标均有效的样本，缺失值不补零。相关不等于因果；合并不同类型可能受原料、打浆条件和配比影响，请结合分组结果判断。此处不作显著性检验。</span
          >
        </p>
      </section>

      <section class="card as-table" aria-labelledby="as-table-title">
        <div class="table-head">
          <h2 id="as-table-title">
            配对数据明细 <span class="quiet-tag">{{ visible.length }}</span>
          </h2>
          <p>每个唯一样本一行，按样本编码排序；“—”表示缺失。</p>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="配对数据明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th>样本编码</th>
                <th>样本类型</th>
                <th class="numeric">
                  {{ xMetric.name }} / {{ unit(xMetric) }}
                </th>
                <th class="numeric">
                  {{ yMetric.name }} / {{ unit(yMetric) }}
                </th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in visible"
                :key="r.canonical_code"
                :class="{ on: focused?.canonical_code === r.canonical_code }"
              >
                <td data-l="样本编码">
                  <button class="sample-code" @click="selected = r">
                    {{ r.canonical_code }}
                  </button>
                </td>
                <td data-l="样本类型">
                  <span class="type-tag" :class="r.sample_type"
                    ><i></i>{{ typeNames[r.sample_type] }}</span
                  >
                </td>
                <td class="numeric" :data-l="`${xMetric.name} / ${unit(xMetric)}`">
                  {{ number(value(r, xMetric), 4) }}
                </td>
                <td class="numeric" :data-l="`${yMetric.name} / ${unit(yMetric)}`">
                  {{ number(value(r, yMetric), 4) }}
                </td>
                <td class="c-act">
                  <button
                    class="text-button"
                    :aria-label="`查看 ${r.canonical_code} 详情`"
                    @click="selected = r"
                  >
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!visible.length" class="as-state">暂无匹配数据。</p>
      </section>
    </template>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
/* ================================================================ page grid
   DOM order: header · controls · chart · statistics · table.
   Dense auto-flow pairs the chart with the statistics panel (v1 as-grid / v4 s-8 + s-4). */
.association-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  grid-auto-flow: row dense;
  gap: 18px;
  align-items: start;
}
.association-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.association-page > .page-header {
  margin-bottom: 0;
}
/* both paired cards fill the row; the plot row of the chart absorbs any extra height */
.association-page > .as-chart {
  grid-column: 1;
  align-self: stretch;
}
.association-page > .as-stats {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .association-page {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}

.nw {
  white-space: nowrap;
}
.garden-only,
.garden-inline {
  display: none;
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
.mk-all {
  display: inline-block;
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid var(--text);
}
/* per-group colour (legend rows, r rows, bars) */
.corr-row {
  --row-c: var(--text);
  --row-ink: var(--text);
  --row-tint: var(--surface-2);
}
.corr-row.softwood {
  --row-c: var(--sw);
  --row-ink: var(--sw-ink);
  --row-tint: var(--sw-tint);
}
.corr-row.hardwood {
  --row-c: var(--hw);
  --row-ink: var(--hw-ink);
  --row-tint: var(--hw-tint);
}
.corr-row.blend {
  --row-c: var(--bl);
  --row-ink: var(--bl-ink);
  --row-tint: var(--bl-tint);
}

/* ================================================================ states */
.as-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.as-state p {
  margin: 14px 0;
}
.as-status {
  display: grid;
  justify-items: center;
}

/* ================================================================ signature (garden hero) */
.as-sig {
  position: relative;
  margin: 0;
  min-width: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.as-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.as-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 132;
}
.as-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.as-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
}
.sg-base {
  stroke: var(--chart-axis);
  stroke-width: 1;
}
.sg-dot {
  fill: var(--sw);
  fill-opacity: 0.92;
  stroke: var(--surface);
  stroke-width: 0.8;
}
.sg-dot.hardwood {
  fill: var(--hw);
}
.sg-dot.blend {
  fill: var(--bl);
}
.sg-t {
  font: 400 11.5px var(--font-body);
  fill: var(--text-2);
}
.sg-m {
  font: 400 10.5px var(--font-mono);
  fill: var(--text-2);
}
.sg-n {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-size: 46px;
  font-weight: 340;
  letter-spacing: -0.02em;
  fill: var(--text);
}

/* ================================================================ controls */
.as-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 18px 28px;
  padding: 20px 22px;
}
.ctl {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ctl-axis {
  min-width: 200px;
}
.as-types > button {
  gap: 8px;
}
.as-types .mk {
  width: 8px;
  height: 8px;
}
.as-types .mk.blend {
  width: 9px;
  height: 9px;
}
.as-reset {
  margin-left: auto;
  align-self: flex-end;
  gap: 7px;
}

/* ================================================================ chart card */
.as-chart {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: auto auto 1fr auto auto;
  grid-template-areas:
    "head head"
    "note note"
    "plot plot"
    "legend hint"
    "axis axis";
  align-items: start;
  column-gap: 20px;
  padding: 22px 24px;
}
.as-chart-head {
  grid-area: head;
  min-width: 0;
}
.as-chart-head h2 {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--text);
  text-wrap: balance;
}
.pair-count {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-2);
}
.pair-count .sep {
  margin: 0 8px;
  color: var(--text-3);
}
.as-legend {
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
.as-legend li {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.axis-caption {
  grid-area: axis;
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-3);
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
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-top: 10px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--warn);
}
.unit-note svg {
  flex: none;
  margin-top: 3px;
}
.as-plot-box,
.as-plot-state {
  grid-area: plot;
}
.as-plot-box {
  position: relative;
  align-self: stretch;
  width: 100%;
  min-width: 0;
  min-height: var(--plot-min, 420px);
  margin-top: 14px;
  /* the svg is sized from this box; clip a resize frame instead of scrolling the page */
  overflow-x: clip;
}
/* absolute, so the measured box height comes from the grid row, never from the svg itself */
.as-plot {
  position: absolute;
  left: 0;
  top: 0;
  display: block;
  touch-action: pan-y;
}
.as-plot.pointing {
  cursor: pointer;
}
.as-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--chart-text);
}
.as-plot .axis-title {
  font-family: var(--font-body);
  font-size: 12px;
}
.grid line {
  stroke: var(--chart-grid);
  shape-rendering: crispEdges;
}
.axis line {
  stroke: var(--chart-axis);
  shape-rendering: crispEdges;
}
.reticle {
  display: none;
}
.reticle path {
  fill: none;
  stroke: var(--text-3);
  stroke-width: 1;
}
.pt {
  cursor: pointer;
}
.pt:focus {
  outline: none;
}
.hit {
  fill: transparent;
}
.pt:focus-visible .hit {
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
.pt.hardwood .mark {
  fill: var(--hw);
}
.pt.blend .mark {
  fill: var(--bl);
}
.hot {
  pointer-events: none;
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
  stroke-width: 1;
}
.hud-box {
  fill: var(--surface);
  stroke: var(--line-strong);
  stroke-width: 1;
}
.as-plot .hud-t {
  font-size: 10.5px;
  fill: var(--text);
}
.guide-focus {
  fill: none;
  stroke: var(--text);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}
/* floating tooltip (also the polite live region for the readout) */
.as-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 5;
  min-width: 180px;
  max-width: 250px;
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
.as-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) - 100% - 12px));
}
.as-tip.below {
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) + 16px));
}
.as-tip.left.below {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) + 16px));
}
.as-tip.on {
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
.tip-row small {
  margin-left: 4px;
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
}
.as-hint {
  grid-area: hint;
  margin-top: 12px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-3);
  text-align: right;
}

/* ================================================================ statistics panel */
.as-stats {
  display: flex;
  flex-direction: column;
  padding: 22px;
  container-type: inline-size;
}
.as-eyebrow {
  margin: 0;
}
.as-stats h2 {
  margin: 4px 0 6px;
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}
.as-stats-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.as-dial {
  display: none;
}
.corr-list {
  list-style: none;
  margin: 16px 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.corr-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "label value"
    "axis value"
    "n n"
    "why why";
  gap: 2px 12px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid transparent;
}
.corr-l {
  grid-area: label;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 13.5px;
  color: var(--text);
}
.corr-n {
  grid-area: value;
  align-self: center;
  font-family: var(--font-display);
  font-weight: 200;
  font-size: 34px;
  line-height: 1;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  white-space: nowrap;
}
.corr-axis {
  grid-area: axis;
  position: relative;
  height: 10px;
  margin-top: 6px;
}
.corr-axis::before {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  top: 4.5px;
  height: 1px;
  background: var(--line-strong);
}
.ca-mid {
  position: absolute;
  left: 50%;
  top: 0;
  width: 1px;
  height: 10px;
  background: var(--text-3);
}
.ca-bar {
  position: absolute;
  top: 3.5px;
  height: 3px;
  border-radius: 2px;
  background: var(--row-c);
  opacity: 0.55;
}
.ca-dot {
  position: absolute;
  top: 1px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--row-c);
  transform: translateX(-4px);
}
.corr-s {
  grid-area: n;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
.why {
  grid-area: why;
  display: block;
  font-size: 12px;
  line-height: 1.6;
  color: var(--warn);
}
.as-note {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: auto;
}
.as-note svg {
  flex: none;
  margin-top: 3px;
  color: var(--text-3);
}

/* ================================================================ table */
.as-table {
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
.as-table .table-scroll {
  max-height: 560px;
}
.as-table .table-scroll:focus-visible {
  outline-offset: -2px;
}
.as-table tbody tr.on td {
  background: var(--surface-hover);
}

/* ================================================================ polarized (v1) */
:root[data-mode="polarized"] .reticle {
  display: inline;
}
:root[data-mode="polarized"] .hud {
  display: inline;
}
:root[data-mode="polarized"] .mark {
  fill-opacity: 0.92;
}
:root[data-mode="polarized"] .pair-count {
  font-family: var(--font-mono);
  font-size: 12.5px;
}
:root[data-mode="polarized"] .as-tip {
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
  font-size: 14px;
  font-weight: 400;
}
:root[data-mode="polarized"] .as-reset {
  min-height: 34px;
  padding: 0 13px;
  font-size: 13px;
  color: var(--text-2);
}
:root[data-mode="polarized"] .as-reset:not(:disabled):hover {
  color: var(--text);
}
:root[data-mode="polarized"] .corr-row.first {
  border-color: var(--line-strong);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .corr-row.first.all .ca-bar,
:root[data-mode="polarized"] .corr-row.first.all .ca-dot {
  background: var(--ifl);
  opacity: 1;
}
:root[data-mode="polarized"] .as-table th {
  font-family: var(--font-mono);
}
:root[data-mode="polarized"] .as-table td.numeric {
  font-family: var(--font-mono);
  font-size: 13px;
}
:root[data-mode="polarized"] .as-table .text-button {
  color: var(--accent-ink);
}

/* ================================================================ garden (v4) */
:root[data-mode="garden"] .garden-only {
  display: inline;
}
:root[data-mode="garden"] .garden-inline {
  display: inline;
}
:root[data-mode="garden"] .guide {
  display: inline;
}
:root[data-mode="garden"] .as-controls {
  gap: 22px 28px;
  padding: 22px 24px;
}
:root[data-mode="garden"] .ctl-axis {
  min-width: 230px;
}
:root[data-mode="garden"] .as-reset {
  margin-left: 0;
  min-height: 0;
  padding: 7px 14px;
  margin-bottom: 4px;
  font-size: 13px;
  border: 0;
  background: color-mix(in oklab, var(--surface) 80%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .as-chart {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto auto 1fr auto;
  grid-template-areas:
    "head legend"
    "axis axis"
    "note note"
    "plot plot"
    "hint hint";
}
:root[data-mode="garden"] .as-chart-head h2,
:root[data-mode="garden"] .table-head h2 {
  font-size: 19px;
  font-weight: 500;
}
:root[data-mode="garden"] .pair-count {
  margin-top: 2px;
}
:root[data-mode="garden"] .as-legend {
  margin: 4px 0 0;
  justify-content: flex-end;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .as-legend .mk {
  width: 11px;
  height: 11px;
}
:root[data-mode="garden"] .axis-caption {
  margin-top: 4px;
  color: var(--text-2);
}
:root[data-mode="garden"] .unit-note {
  padding: 10px 14px;
  border-radius: 16px;
  color: var(--text-2);
  background: color-mix(in oklab, var(--warn-tint) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .unit-note svg {
  color: var(--warn);
}
:root[data-mode="garden"] .as-plot .axis-title {
  font-size: 11.5px;
  fill: var(--text-2);
}
:root[data-mode="garden"] .mark {
  stroke: var(--surface);
}
:root[data-mode="garden"] .as-tip {
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
:root[data-mode="garden"] .as-hint {
  text-align: left;
  font-size: 13px;
  color: var(--text-2);
}

/* garden statistics tile: eyebrow · title · dial · group rows · note · caveat (v4 dial-tile) */
:root[data-mode="garden"] .as-stats {
  padding: 22px 24px;
}
:root[data-mode="garden"] .as-stats h2 {
  margin: 4px 0 0;
  font-size: 18px;
  font-weight: 500;
  line-height: 1.35;
}
:root[data-mode="garden"] .as-stats-desc {
  order: 5;
  margin-top: 12px;
}
:root[data-mode="garden"] .as-note {
  order: 6;
  margin-top: 10px;
}
:root[data-mode="garden"] .as-note svg {
  color: var(--accent);
}
:root[data-mode="garden"] .as-dial {
  display: block;
  position: relative;
  margin: 6px -4px 0;
}
.dial-svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}
.dial-track {
  fill: none;
  stroke: var(--accent-tint);
  stroke-width: 16;
  stroke-linecap: round;
}
.dial-fill {
  fill: none;
  stroke: var(--accent);
  stroke-width: 16;
  stroke-linecap: round;
  stroke-opacity: 0.82;
}
.dial-tick {
  stroke: var(--chart-axis);
  stroke-width: 1.2;
}
.dial-tl {
  font: 400 11px var(--font-mono);
  fill: var(--text-2);
}
.dial-mk {
  fill: var(--sw);
  stroke: var(--surface);
  stroke-width: 2;
  paint-order: stroke;
}
.dial-mk.hardwood {
  fill: var(--hw);
}
.dial-mk.blend {
  fill: var(--bl);
}
.dial-needle {
  transform: rotate(var(--a));
  transform-origin: 180px 176px;
  transition: transform 0.9s var(--spring);
  animation: as-needle 1.1s var(--spring) backwards;
}
@keyframes as-needle {
  from {
    transform: rotate(-90deg);
  }
}
.dial-needle line {
  stroke: var(--text);
  stroke-width: 2.6;
  stroke-linecap: round;
}
.dial-needle circle {
  fill: var(--text);
}
.dial-hub {
  fill: var(--surface);
  stroke: var(--text);
  stroke-width: 2.6;
}
.dial-num {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: -4px;
  text-align: center;
}
.dial-big {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-size: 68px;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  line-height: 0.95;
  color: var(--text);
}
.dial-cap {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-2);
}
.dial-num .why {
  margin-top: 4px;
}
:root[data-mode="garden"] .corr-list {
  gap: 8px;
  margin: 14px 0 0;
}
:root[data-mode="garden"] .corr-row {
  grid-template-columns: minmax(0, 1fr) auto auto;
  grid-template-areas:
    "label n value"
    "why why why";
  align-items: center;
  gap: 2px 12px;
  padding: 10px 14px;
  border: 0;
  border-radius: 16px;
  background: linear-gradient(
    150deg,
    color-mix(in oklab, var(--surface) 55%, var(--row-tint)),
    var(--row-tint)
  );
}
:root[data-mode="garden"] .corr-row.first {
  display: none;
}
:root[data-mode="garden"] .corr-l {
  white-space: nowrap;
}
/* a narrow tile (two-column layout near 1000px) stacks the pair count under the name */
@container (max-width: 300px) {
  :root[data-mode="garden"] .corr-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "label value"
      "n value"
      "why why";
    padding: 9px 14px;
  }
}
:root[data-mode="garden"] .corr-axis {
  display: none;
}
:root[data-mode="garden"] .corr-l {
  font-size: 13.5px;
}
:root[data-mode="garden"] .corr-s {
  font-size: 12px;
  color: var(--text-2);
}
:root[data-mode="garden"] .corr-n {
  min-width: 62px;
  font-family: var(--font-mono);
  font-weight: 500;
  font-size: 17px;
  letter-spacing: 0;
  text-align: right;
}
:root[data-mode="garden"] .as-table .text-button {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  background: color-mix(in oklab, var(--surface) 80%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .as-table .text-button:hover {
  text-decoration: none;
  background: var(--surface);
}

/* ================================================================ responsive */
@media (max-width: 1280px) {
  .association-page {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
  :root[data-mode="polarized"] .as-chart {
    grid-template-rows: auto auto 1fr auto auto auto;
    grid-template-areas:
      "head head"
      "note note"
      "plot plot"
      "legend legend"
      "hint hint"
      "axis axis";
  }
  :root[data-mode="polarized"] .as-hint {
    text-align: left;
    margin-top: 8px;
  }
}
/* one column: polarized below 1100px (v1 as-grid), garden below 980px (v4 s-8/s-4);
   each mode re-places both paired blocks, since its own rules set their columns */
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .association-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="polarized"] .association-page > .as-chart,
  :root[data-mode="polarized"] .association-page > .as-stats {
    grid-column: 1;
  }
  :root[data-mode="polarized"] .corr-list {
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .association-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .association-page > .as-chart,
  :root[data-mode="garden"] .association-page > .as-stats {
    grid-column: 1;
  }
  :root[data-mode="garden"] .as-dial {
    width: min(100%, 420px);
    margin: 6px auto 0;
  }
  :root[data-mode="garden"] .corr-list {
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  }
}
@media (max-width: 720px) {
  .as-controls,
  :root[data-mode="garden"] .as-controls {
    padding: 16px;
    gap: 16px;
  }
  .ctl,
  .ctl-axis,
  :root[data-mode="garden"] .ctl-axis {
    width: 100%;
    min-width: 0;
  }
  .as-reset {
    margin-left: 0;
  }
  .as-chart,
  :root[data-mode="garden"] .as-chart {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto auto 1fr auto;
    grid-template-areas:
      "head"
      "legend"
      "axis"
      "note"
      "plot"
      "hint";
    padding: 16px;
  }
  :root[data-mode="garden"] .as-legend {
    justify-content: flex-start;
    margin-top: 10px;
  }
  .as-hint {
    text-align: left;
  }
  .as-stats,
  :root[data-mode="garden"] .as-stats {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .dial-big {
    font-size: 54px;
  }
  .table-head {
    padding: 18px 16px 12px;
  }
}
/* polarized phones: every table row becomes a card (v1 tbl-stack): code and type on top,
   the two values below, the detail button full width; the list scrolls in its own box */
@media (max-width: 600px) {
  :root[data-mode="polarized"] .as-table .table-scroll {
    max-height: min(620px, 72vh);
    padding: 0 12px 12px;
    overscroll-behavior-y: auto;
  }
  :root[data-mode="polarized"] .as-table table {
    display: block;
    white-space: normal;
  }
  :root[data-mode="polarized"] .as-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  :root[data-mode="polarized"] .as-table tbody {
    display: grid;
    gap: 10px;
  }
  :root[data-mode="polarized"] .as-table tbody tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
    gap: 8px 14px;
    padding: 12px 14px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--surface-2);
  }
  :root[data-mode="polarized"] .as-table tbody tr.on {
    box-shadow: inset 3px 0 0 var(--accent);
  }
  :root[data-mode="polarized"] .as-table tbody td {
    display: block;
    height: auto;
    padding: 0;
    border: 0;
    background: none;
    text-align: left;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  :root[data-mode="polarized"] .as-table td[data-l]::before {
    content: attr(data-l);
    display: block;
    margin-bottom: 2px;
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.06em;
    color: var(--text-3);
  }
  /* code and type tag explain themselves: no field label, tag pinned to the right */
  :root[data-mode="polarized"] .as-table td:nth-child(-n + 2)::before {
    display: none;
  }
  :root[data-mode="polarized"] .as-table td:nth-child(2) {
    justify-self: end;
  }
  :root[data-mode="polarized"] .as-table td.c-act {
    grid-column: 1 / -1;
  }
  @media (max-width: 380px) {
    :root[data-mode="polarized"] .as-table td:first-child {
      grid-column: 1 / -1;
    }
    :root[data-mode="polarized"] .as-table td:nth-child(2) {
      justify-self: start;
    }
  }
  :root[data-mode="polarized"] .as-table td.c-act .text-button {
    display: flex;
    width: 100%;
    min-height: 36px;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--line-strong);
    border-radius: 999px;
  }
}
</style>
