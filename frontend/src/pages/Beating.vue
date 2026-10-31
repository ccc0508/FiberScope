<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  nextTick,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ChartNoAxesCombined,
  ChevronLeft,
  ChevronRight,
  Download,
  Minus,
  Plus,
  RefreshCw,
  TriangleAlert,
} from "lucide-vue-next";
import {
  get,
  number,
  type Metadata,
  type ListResult,
  type Sample,
} from "../api";
import {
  fiberPaths,
  firstReach,
  interpolateAt,
  niceTicks,
  type CurvePoint,
} from "../beating";
import { materialCodeColors } from "../palette";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import FiberHero from "../components/FiberHero.vue";

type Material = "SW" | "HW";
interface BeatingRow {
  canonical_code: string;
  display_name: string;
  material_code: Material;
  beating_revolutions: number;
  [key: string]: string | number | null;
}
const MATERIALS: Material[] = ["SW", "HW"];
const SR_KEY = "beating_degree_sr";

const route = useRoute(),
  router = useRouter();
const rows = ref<BeatingRow[]>([]),
  samples = ref<Sample[]>([]);
const metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const detailSample = ref<Sample | null>(null);
const selectedCode = ref<string | null>(null);
const cursorRevs = ref<number | null>(null);

/* ---------- 筛选：原料、指标、目标打浆度都放在 URL 上 ---------- */
const defaultMetric = {
  key: SR_KEY,
  name: "打浆度",
  unit: "°SR",
  group: "condition",
  scope: ["core"],
  unit_status: "confirmed",
};
const metrics = computed(() => [
  defaultMetric,
  ...(metadata.value?.indicators.filter((i) => i.scope.includes("core")) ?? []),
]);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ?? defaultMetric,
);
const isSr = computed(() => metric.value.key === SR_KEY);
const material = computed<"all" | Material>(() =>
  MATERIALS.includes(route.query.material as Material)
    ? (route.query.material as Material)
    : "all",
);
const target = computed(() => {
  const t = Number(route.query.target);
  return Number.isFinite(t) && t >= 20 && t <= 85 ? Math.round(t) : 45;
});
const metricOptions = computed(() =>
  metrics.value.map((i) => ({ value: i.key, label: i.name })),
);
function update(key: string, next: string | undefined) {
  void router.replace({ query: { ...route.query, [key]: next } });
}
const setTarget = (t: number) =>
  update("target", String(Math.max(20, Math.min(85, t))));

/* ---------- 数据 ---------- */
const materialName = (code: Material) =>
  code === "SW" ? "针叶木浆" : "阔叶木浆";
const color = (code: Material) => materialCodeColors[code];
const unit = computed(() => metric.value.unit ?? "单位未确认");
const value = (r: BeatingRow): number | null =>
  typeof r[metric.value.key] === "number" &&
  Number.isFinite(r[metric.value.key])
    ? (r[metric.value.key] as number)
    : null;
const digits = computed(() => {
  const values = rows.value.map(value).filter((v): v is number => v !== null);
  const span = values.length ? Math.max(...values) - Math.min(...values) : 1;
  return span >= 50 ? 1 : span >= 5 ? 2 : 3;
});
const fmt = (v: number | null) => number(v, digits.value);

const byMaterial = computed(
  () =>
    Object.fromEntries(
      MATERIALS.map((code) => [
        code,
        rows.value
          .filter((r) => r.material_code === code)
          .sort(
            (a, b) =>
              a.beating_revolutions - b.beating_revolutions ||
              a.canonical_code.localeCompare(b.canonical_code),
          ),
      ]),
    ) as Record<Material, BeatingRow[]>,
);
const shownMaterials = computed(() =>
  material.value === "all" ? MATERIALS : [material.value],
);
const visible = computed(() =>
  shownMaterials.value.flatMap((code) => byMaterial.value[code]),
);
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const curve = (code: Material): CurvePoint[] =>
  byMaterial.value[code]
    .filter((r) => value(r) !== null)
    .map((r) => ({ x: r.beating_revolutions, y: value(r)! }));
const counts = computed(() => ({
  all: rows.value.filter(inRange).length,
  SW: byMaterial.value.SW.filter(inRange).length,
  HW: byMaterial.value.HW.filter(inRange).length,
}));

/* ---------- 打浆度区间：筛选表格与读数，曲线保留全部点、区间外淡化 ---------- */
const srOf = (r: BeatingRow) =>
  typeof r[SR_KEY] === "number" && Number.isFinite(r[SR_KEY])
    ? (r[SR_KEY] as number)
    : null;
const srRange = computed(() => {
  const m = /^(\d{1,3})-(\d{1,3})$/.exec(String(route.query.sr ?? ""));
  const lo = m ? Number(m[1]) : 0,
    hi = m ? Number(m[2]) : 100;
  return lo <= hi && hi <= 100 ? { lo, hi } : { lo: 0, hi: 100 };
});
const rangeActive = computed(
  () => srRange.value.lo > 0 || srRange.value.hi < 100,
);
// 区间未收窄时不按打浆度过滤，打浆度缺失的行照常显示
function inRange(r: BeatingRow) {
  if (!rangeActive.value) return true;
  const sr = srOf(r);
  return sr !== null && sr >= srRange.value.lo && sr <= srRange.value.hi;
}
function setRange(lo: number, hi: number) {
  const a = Math.min(lo, hi),
    b = Math.max(lo, hi);
  update("sr", a === 0 && b === 100 ? undefined : `${a}-${b}`);
}
const listedBy = (code: Material) => byMaterial.value[code].filter(inRange);
const listed = computed(() =>
  shownMaterials.value.flatMap((code) => listedBy(code)),
);
const histogram = computed(() => {
  const bins = Array.from({ length: 10 }, () => 0);
  for (const r of visible.value) {
    const sr = srOf(r);
    if (sr !== null) bins[Math.min(9, Math.floor(sr / 10))]!++;
  }
  const max = Math.max(1, ...bins);
  return bins.map((n, i) => ({
    n,
    h: n ? Math.max(8, (n / max) * 100) : 0,
    on: i * 10 + 10 > srRange.value.lo && i * 10 < srRange.value.hi,
  }));
});

/* ---------- KPI ---------- */
const round100 = (v: number) => Math.round(v / 100) * 100;
const reach = computed(
  () =>
    Object.fromEntries(
      MATERIALS.map((code) => [code, firstReach(curve(code), target.value)]),
    ) as Record<Material, number | null>,
);
const reachGap = computed(() => {
  const { SW, HW } = reach.value;
  // 用取整后的值相减，和上面两格显示的数字对得上
  return SW !== null && HW !== null ? round100(SW) - round100(HW) : null;
});
const change = (code: Material) => {
  const c = curve(code);
  if (c.length < 2) return null;
  const first = c[0]!,
    last = c[c.length - 1]!;
  return {
    from: first,
    to: last,
    pct: first.y !== 0 ? ((last.y - first.y) / Math.abs(first.y)) * 100 : null,
  };
};

/* ---------- 曲线：按容器实际宽度绘制，文字不随缩放变形 ---------- */
const plotBox = ref<HTMLElement>();
const plotWidth = ref(720);
const PLOT_H = 360;
let sizeObserver: ResizeObserver | undefined;
onMounted(() => {
  sizeObserver = new ResizeObserver(([entry]) => {
    if (entry) plotWidth.value = Math.max(240, entry.contentRect.width);
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
// 纸面纤维随尺寸重新生成；同一尺寸下结果固定
const fibers = computed(() => fiberPaths(plotWidth.value, PLOT_H));
const margin = computed(() => ({
  t: 22,
  r: plotWidth.value < 480 ? 14 : 26,
  b: 46,
  l: plotWidth.value < 480 ? 46 : 58,
}));
const xMax = computed(
  () =>
    Math.ceil(
      Math.max(5000, ...rows.value.map((r) => r.beating_revolutions)) / 5000,
    ) * 5000,
);
const xTicks = computed(() => {
  const step = plotWidth.value < 560 ? 10000 : 5000,
    out: number[] = [];
  for (let v = 0; v <= xMax.value; v += step) out.push(v);
  return out;
});
const yTicks = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (isSr.value) values.push(target.value);
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values);
  return niceTicks(min >= 0 ? Math.max(0, min - (max - min) * 0.08) : min, max);
});
const yMin = computed(() => yTicks.value[0]!),
  yMax = computed(() => yTicks.value[yTicks.value.length - 1]!);
const px = (revs: number) =>
  margin.value.l +
  (revs / xMax.value) * (plotWidth.value - margin.value.l - margin.value.r);
const py = (v: number) =>
  margin.value.t +
  (1 - (v - yMin.value) / (yMax.value - yMin.value || 1)) *
    (PLOT_H - margin.value.t - margin.value.b);
const series = computed(() =>
  shownMaterials.value.map((code) => {
    let connected = false;
    // 缺失值处断开，只连接相邻有效观测
    const path = byMaterial.value[code]
      .map((r) => {
        const v = value(r);
        if (v === null) {
          connected = false;
          return "";
        }
        const seg = `${connected ? "L" : "M"}${px(r.beating_revolutions).toFixed(1)},${py(v).toFixed(1)}`;
        connected = true;
        return seg;
      })
      .join(" ");
    return {
      code,
      path,
      points: byMaterial.value[code].filter((r) => value(r) !== null),
    };
  }),
);
const targetHits = computed(() =>
  isSr.value
    ? shownMaterials.value
        .map((code) => ({ code, x: reach.value[code] }))
        .filter((h): h is { code: Material; x: number } => h.x !== null)
    : [],
);
const measuredRevs = computed(() =>
  [...new Set(valid.value.map((r) => r.beating_revolutions))].sort(
    (a, b) => a - b,
  ),
);
function pointer(event: PointerEvent) {
  const box = (event.currentTarget as SVGElement).getBoundingClientRect();
  const x = event.clientX - box.left;
  if (x < margin.value.l - 8 || x > plotWidth.value - margin.value.r + 8) {
    cursorRevs.value = null;
    return;
  }
  let best: number | null = null;
  for (const r of measuredRevs.value)
    if (best === null || Math.abs(px(r) - x) < Math.abs(px(best) - x)) best = r;
  cursorRevs.value = best;
}
const cursorRows = computed(() =>
  cursorRevs.value === null
    ? []
    : shownMaterials.value.map((code) => ({
        code,
        row:
          byMaterial.value[code].find(
            (r) => r.beating_revolutions === cursorRevs.value,
          ) ?? null,
      })),
);

/* ---------- 读数面板 ---------- */
const selected = computed(
  () =>
    listed.value.find((r) => r.canonical_code === selectedCode.value) ??
    listed.value[0] ??
    null,
);
const selectedIndex = computed(() =>
  selected.value ? listed.value.indexOf(selected.value) : -1,
);
function select(row: BeatingRow) {
  selectedCode.value = row.canonical_code;
}
async function step(delta: number) {
  const next = listed.value[selectedIndex.value + delta];
  if (!next) return;
  select(next);
  // 逐个浏览时，把表格里对应的行滚进视野
  await nextTick();
  document
    .querySelector(`[data-code="${next.canonical_code}"]`)
    ?.scrollIntoView({ block: "nearest" });
}
// 同转数下另一种原料：有实测用实测，否则相邻实测点线性插值，超出实测范围为 null（不外推）
function otherAt(row: BeatingRow) {
  const other: Material = row.material_code === "SW" ? "HW" : "SW";
  const exact = byMaterial.value[other].find(
    (r) => r.beating_revolutions === row.beating_revolutions,
  );
  const exactValue = exact ? value(exact) : null;
  if (exactValue !== null)
    return { code: other, value: exactValue, estimated: false };
  const estimated = interpolateAt(curve(other), row.beating_revolutions);
  return { code: other, value: estimated, estimated: estimated !== null };
}
const otherAtSameRevs = computed(() =>
  selected.value ? otherAt(selected.value) : null,
);
// 选中样本距目标打浆度：还差多少 °SR、按本原料曲线估算还需多少转
const toTarget = computed(() => {
  const s = selected.value,
    v = s ? value(s) : null;
  if (!isSr.value || !s || v === null) return null;
  const at = reach.value[s.material_code];
  return {
    gap: target.value - v,
    revs:
      at === null ? null : Math.max(0, round100(at - s.beating_revolutions)),
  };
});
function deltaOf(row: BeatingRow) {
  const own = value(row),
    other = otherAt(row);
  return own === null || other.value === null
    ? null
    : { d: own - other.value, estimated: other.estimated };
}
const deltaMax = computed(() =>
  Math.max(1e-9, ...listed.value.map((r) => Math.abs(deltaOf(r)?.d ?? 0))),
);
const signed = (d: number) =>
  `${d > 0 ? "+" : d < 0 ? "−" : ""}${number(Math.abs(d), digits.value)}`;

// 选中点旁的读数标签：自己在另一条曲线下方就放下面，在上方就放上面，避开另一条线
const selLabel = computed(() => {
  const s = selected.value,
    v = s ? value(s) : null;
  if (!s || v === null || !shownMaterials.value.includes(s.material_code))
    return null;
  const x = px(s.beating_revolutions),
    y = py(v);
  const text = `${fmt(v)} ${unit.value}`,
    w = text.length * 6.8 + 12;
  // 看标签将要占据的位置上另一条曲线在哪：另一条线在上方就放下面，反之放上面
  const otherCode: Material = s.material_code === "SW" ? "HW" : "SW";
  const perRev =
    xMax.value / (plotWidth.value - margin.value.l - margin.value.r);
  const otherY =
    material.value === "all"
      ? interpolateAt(
          curve(otherCode),
          s.beating_revolutions + (6 + w / 2) * perRev,
        )
      : null;
  const below = otherY === null ? y < PLOT_H / 2 : otherY >= v;
  let ly = below ? y + 12 : y - 32;
  ly = Math.max(margin.value.t, Math.min(PLOT_H - margin.value.b - 22, ly));
  const right = x + 6 + w <= plotWidth.value - margin.value.r;
  return { x: right ? x + 6 : x - 6 - w, y: ly, w, text };
});

/* ---------- 勾选与导出 ---------- */
const checked = ref(new Set<string>());
function toggle(code: string, on: boolean) {
  const next = new Set(checked.value);
  if (on) next.add(code);
  else next.delete(code);
  checked.value = next;
}
const allChecked = computed(
  () =>
    listed.value.length > 0 &&
    listed.value.every((r) => checked.value.has(r.canonical_code)),
);
const someChecked = computed(
  () =>
    !allChecked.value &&
    listed.value.some((r) => checked.value.has(r.canonical_code)),
);
function toggleAll(on: boolean) {
  const next = new Set(checked.value);
  for (const r of listed.value)
    if (on) next.add(r.canonical_code);
    else next.delete(r.canonical_code);
  checked.value = next;
}
const exportRows = computed(() => {
  const picked = listed.value.filter((r) =>
    checked.value.has(r.canonical_code),
  );
  return picked.length ? picked : listed.value;
});
function exportCsv() {
  const head = [
    "样本编码",
    "样本名称",
    "原料",
    "打浆转数(r)",
    "打浆度(°SR)",
    `${metric.value.name}(${unit.value})`,
    "较另一种原料(同转数)",
    "另一种原料取值方式",
  ];
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = exportRows.value.map((r) => {
    const delta = deltaOf(r);
    return [
      r.canonical_code,
      r.display_name,
      materialName(r.material_code),
      r.beating_revolutions,
      srOf(r) ?? "",
      value(r) ?? "",
      delta ? delta.d : "",
      delta
        ? delta.estimated
          ? "线性插值"
          : "实测"
        : "无（超出实测范围或缺失）",
    ];
  });
  // 数值原样导出，不做取整；带 BOM 便于 Excel 识别中文
  const csv =
    "\ufeff" + [head, ...lines].map((l) => l.map(cell).join(",")).join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  link.download = `打浆分析_${metric.value.key}_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function openDetail(row: BeatingRow) {
  detailSample.value =
    samples.value.find((s) => s.canonical_code === row.canonical_code) ?? null;
}
const valueBar = (v: number | null) =>
  v === null
    ? 0
    : Math.max(
        0,
        Math.min(
          100,
          ((v - yMin.value) / (yMax.value - yMin.value || 1)) * 100,
        ),
      );

/* ---------- 读取 ---------- */
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  try {
    const [data, meta, sampleData] = await Promise.all([
      get<ListResult<BeatingRow>>(
        "beating",
        { page_size: 500 },
        current.signal,
      ),
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
  () => [material.value, metric.value.key],
  () => {
    cursorRevs.value = null;
  },
);
void load();
onBeforeUnmount(() => {
  controller?.abort();
  sizeObserver?.disconnect();
});
</script>

<template>
  <div class="overview beating-page">
    <section class="page-heading">
      <FiberHero />
      <div>
        <span class="eyebrow"><ChartNoAxesCombined :size="14" /> 实验分析</span>
        <h1>打浆分析</h1>
        <p>比较打浆转数变化下的纤维特性与纸张性能。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </section>
    <div v-if="error" class="card beating-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card beating-state" role="status">
      正在读取打浆实验数据…
    </div>
    <template v-else>
      <section class="card beating-controls" aria-label="打浆分析筛选">
        <div>
          <span class="control-caption" id="beating-material-label">原料</span>
          <div
            class="material-seg"
            role="radiogroup"
            aria-labelledby="beating-material-label"
          >
            <button
              v-for="opt in ['all', ...MATERIALS] as const"
              :key="opt"
              type="button"
              role="radio"
              :aria-checked="material === opt"
              :class="{ on: material === opt }"
              @click="update('material', opt === 'all' ? undefined : opt)"
            >
              <i
                :class="{ all: opt === 'all' }"
                :style="opt === 'all' ? {} : { background: color(opt) }"
              ></i
              >{{ opt === "all" ? "全部" : materialName(opt)
              }}<span class="seg-count">{{ counts[opt] }}</span>
            </button>
          </div>
        </div>
        <div>
          <span class="control-caption">分析指标</span
          ><FilterSelect
            id="beating-metric"
            label="分析指标"
            :model-value="metric.key"
            :options="metricOptions"
            @update:model-value="update('metric', $event)"
          />
        </div>
        <div class="range-group">
          <div class="range-head">
            <span class="control-caption" id="beating-sr-label">打浆度区间</span
            ><span class="range-val"
              >{{ srRange.lo }} – {{ srRange.hi }}<small>°SR</small></span
            >
          </div>
          <div class="hist" aria-hidden="true">
            <i
              v-for="(b, i) in histogram"
              :key="i"
              :class="{ out: !b.on }"
              :style="{ height: `${b.h}%` }"
            ></i>
          </div>
          <div class="dual-range">
            <div class="dual-track">
              <i
                :style="{
                  left: `${srRange.lo}%`,
                  width: `${srRange.hi - srRange.lo}%`,
                }"
              ></i>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              :value="srRange.lo"
              aria-label="打浆度下限"
              @input="
                setRange(
                  Math.min(
                    +($event.target as HTMLInputElement).value,
                    srRange.hi,
                  ),
                  srRange.hi,
                )
              "
            />
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              :value="srRange.hi"
              aria-label="打浆度上限"
              @input="
                setRange(
                  srRange.lo,
                  Math.max(
                    +($event.target as HTMLInputElement).value,
                    srRange.lo,
                  ),
                )
              "
            />
          </div>
          <div class="ruler-labels">
            <span>0</span><span>50</span><span>100</span>
          </div>
        </div>
        <div class="count-group">
          <p class="beating-count" role="status">
            {{ listed.length }} 个样本 <span>·</span>
            {{ valid.length }} 个有效数据点
          </p>
          <button
            v-if="rangeActive"
            class="text-button"
            type="button"
            @click="setRange(0, 100)"
          >
            重置区间
          </button>
        </div>
      </section>

      <!-- KPI：打浆度看“达到目标需要多少转”，其他指标看打浆前后的变化 -->
      <section class="card beating-kpis" aria-label="关键指标">
        <template v-if="isSr">
          <div class="kpi">
            <div class="kpi-label">目标打浆度</div>
            <div class="kpi-value">
              <strong>{{ target }}</strong
              ><small>°SR</small>
              <span class="stepper">
                <button
                  type="button"
                  aria-label="目标打浆度降低 5"
                  :disabled="target <= 20"
                  @click="setTarget(target - 5)"
                >
                  <Minus :size="13" /></button
                ><button
                  type="button"
                  aria-label="目标打浆度提高 5"
                  :disabled="target >= 85"
                  @click="setTarget(target + 5)"
                >
                  <Plus :size="13" />
                </button>
              </span>
            </div>
            <div class="ruler" aria-hidden="true">
              <i :style="{ left: `${target}%` }"></i>
            </div>
            <div class="ruler-labels">
              <span>0</span><span>50</span><span>100</span>
            </div>
          </div>
          <div
            v-for="code in MATERIALS"
            :key="code"
            class="kpi"
            :class="{ dim: material !== 'all' && material !== code }"
          >
            <div class="kpi-label">
              <i class="swatch" :style="{ background: color(code) }"></i
              >{{ materialName(code) }} · 达到 {{ target }} °SR
            </div>
            <div class="kpi-value">
              <template v-if="reach[code] !== null"
                ><strong>{{ number(round100(reach[code]!)) }}</strong
                ><small>转</small></template
              ><strong v-else class="na">未达到</strong>
            </div>
            <div class="ruler" aria-hidden="true">
              <i
                v-if="reach[code] !== null"
                :style="{ left: `${(reach[code]! / xMax) * 100}%` }"
              ></i>
            </div>
            <div class="ruler-labels">
              <span>0</span><span>{{ number(xMax) }}</span>
            </div>
          </div>
          <div class="kpi">
            <div class="kpi-label">两种原料相差</div>
            <div class="kpi-value">
              <template v-if="reachGap !== null"
                ><strong>{{ number(round100(Math.abs(reachGap))) }}</strong
                ><small>转</small></template
              ><strong v-else class="na">—</strong>
            </div>
            <p class="kpi-note">
              <template v-if="reachGap !== null"
                >{{
                  reachGap > 0 ? "阔叶木浆" : "针叶木浆"
                }}更早达到目标。</template
              >按相邻实测点线性插值估算，取整到百转。
            </p>
          </div>
        </template>
        <template v-else>
          <div
            v-for="code in MATERIALS"
            :key="code"
            class="kpi wide"
            :class="{ dim: material !== 'all' && material !== code }"
          >
            <div class="kpi-label">
              <i class="swatch" :style="{ background: color(code) }"></i
              >{{ materialName(code) }} · {{ metric.name }}
            </div>
            <div v-if="change(code)" class="kpi-value">
              <strong>{{ fmt(change(code)!.to.y) }}</strong
              ><small>{{ unit }}</small>
              <span v-if="change(code)!.pct !== null" class="delta"
                >{{ change(code)!.pct! >= 0 ? "+" : "−"
                }}{{ number(Math.abs(change(code)!.pct!), 1) }}%</span
              >
            </div>
            <div v-else class="kpi-value"><strong class="na">—</strong></div>
            <p v-if="change(code)" class="kpi-note">
              {{ number(change(code)!.from.x) }} 转时
              {{ fmt(change(code)!.from.y) }} →
              {{ number(change(code)!.to.x) }} 转时
              {{ fmt(change(code)!.to.y) }}
            </p>
          </div>
          <div class="kpi">
            <div class="kpi-label">有效数据点</div>
            <div class="kpi-value">
              <strong>{{ valid.length }}</strong
              ><small>/ {{ visible.length }}</small>
            </div>
            <p class="kpi-note">缺失值不计入，曲线在缺失处断开。</p>
          </div>
        </template>
      </section>
      <p v-if="metric.unit_status !== 'confirmed'" class="unit-note">
        {{ metric.name }}的单位{{
          metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
        }}，数值保留原始口径。
      </p>

      <div class="beating-row">
        <section class="card beating-chart">
          <div class="beating-chart-heading">
            <div>
              <h2>{{ metric.name }}随打浆转数的变化</h2>
              <p>纵轴：{{ metric.name }}（{{ unit }}）</p>
            </div>
          </div>
          <div class="sheet">
            <div v-if="!valid.length" class="beating-state" role="status">
              当前原料没有该指标的有效数据，请切换指标或原料。
            </div>
            <div v-else ref="plotBox" class="plot-box">
              <svg
                class="beating-plot"
                :width="plotWidth"
                :height="PLOT_H"
                :viewBox="`0 0 ${plotWidth} ${PLOT_H}`"
                aria-label="打浆趋势图；可用Tab定位数据点，Enter选中样本"
                @pointermove="pointer"
                @pointerleave="cursorRevs = null"
              >
                <g class="paper-fibers" aria-hidden="true">
                  <path
                    v-for="(f, i) in fibers"
                    :key="i"
                    :d="f.d"
                    :stroke-width="f.wide ? 1.4 : 1"
                  />
                </g>
                <g class="grid">
                  <line
                    v-for="t in yTicks"
                    :key="`gy${t}`"
                    :x1="margin.l"
                    :x2="plotWidth - margin.r"
                    :y1="py(t)"
                    :y2="py(t)"
                  />
                  <line
                    v-for="t in xTicks.slice(1)"
                    :key="`gx${t}`"
                    :x1="px(t)"
                    :x2="px(t)"
                    :y1="margin.t"
                    :y2="PLOT_H - margin.b"
                  />
                </g>
                <g class="axis">
                  <line
                    :x1="margin.l"
                    :x2="margin.l"
                    :y1="margin.t"
                    :y2="PLOT_H - margin.b"
                  />
                  <line
                    :x1="margin.l"
                    :x2="plotWidth - margin.r"
                    :y1="PLOT_H - margin.b"
                    :y2="PLOT_H - margin.b"
                  />
                  <g v-for="t in yTicks" :key="`ty${t}`">
                    <line
                      :x1="margin.l - 6"
                      :x2="margin.l"
                      :y1="py(t)"
                      :y2="py(t)"
                    />
                    <text :x="margin.l - 10" :y="py(t) + 4" text-anchor="end">
                      {{ number(t, t % 1 ? digits : 0) }}
                    </text>
                  </g>
                  <g v-for="t in xTicks" :key="`tx${t}`">
                    <line
                      :x1="px(t)"
                      :x2="px(t)"
                      :y1="PLOT_H - margin.b"
                      :y2="PLOT_H - margin.b + 6"
                    />
                    <text
                      :x="px(t)"
                      :y="PLOT_H - margin.b + 20"
                      :text-anchor="
                        t === 0 ? 'start' : t === xMax ? 'end' : 'middle'
                      "
                    >
                      {{ number(t) }}
                    </text>
                  </g>
                  <text
                    class="axis-title"
                    :x="plotWidth - margin.r"
                    :y="PLOT_H - 6"
                    text-anchor="end"
                  >
                    打浆转数 / r
                  </text>
                </g>
                <g v-if="isSr" class="target">
                  <line
                    :x1="margin.l"
                    :x2="plotWidth - margin.r"
                    :y1="py(target)"
                    :y2="py(target)"
                  />
                  <text
                    :x="plotWidth - margin.r - 4"
                    :y="py(target) - 6"
                    text-anchor="end"
                  >
                    目标 {{ target }} °SR
                  </text>
                </g>
                <g v-if="cursorRevs !== null" class="cursor">
                  <line
                    :x1="px(cursorRevs)"
                    :x2="px(cursorRevs)"
                    :y1="margin.t"
                    :y2="PLOT_H - margin.b"
                  />
                </g>
                <g
                  v-for="s in series"
                  :key="s.code"
                  :style="{ '--c': color(s.code) }"
                >
                  <path :d="s.path" class="line" />
                  <g
                    v-for="r in s.points"
                    :key="r.canonical_code"
                    class="plot-point"
                    :class="{
                      on: selected?.canonical_code === r.canonical_code,
                      out: !inRange(r),
                    }"
                    role="button"
                    tabindex="0"
                    :aria-label="`${r.canonical_code}，${r.beating_revolutions}转，${metric.name}${value(r)} ${unit}，选中查看读数`"
                    @click="select(r)"
                    @focus="select(r)"
                    @keydown.enter.prevent="openDetail(r)"
                    @keydown.space.prevent="openDetail(r)"
                  >
                    <circle
                      :cx="px(r.beating_revolutions)"
                      :cy="py(value(r)!)"
                      r="10"
                      fill="transparent"
                    />
                    <circle
                      v-if="s.code === 'SW'"
                      class="mark"
                      :cx="px(r.beating_revolutions)"
                      :cy="py(value(r)!)"
                      r="3.6"
                    />
                    <rect
                      v-else
                      class="mark"
                      :x="px(r.beating_revolutions) - 3.4"
                      :y="py(value(r)!) - 3.4"
                      width="6.8"
                      height="6.8"
                    />
                    <circle
                      v-if="selected?.canonical_code === r.canonical_code"
                      class="ring"
                      :cx="px(r.beating_revolutions)"
                      :cy="py(value(r)!)"
                      r="9"
                    />
                    <title>
                      {{ r.canonical_code }} ·
                      {{ number(r.beating_revolutions) }} r · {{ metric.name }}
                      {{ fmt(value(r)) }} {{ unit }}
                    </title>
                  </g>
                </g>
                <g class="target-hits">
                  <circle
                    v-for="h in targetHits"
                    :key="h.code"
                    :cx="px(h.x)"
                    :cy="py(target)"
                    r="3.5"
                  />
                </g>
                <g v-if="selLabel" class="sel-label" aria-hidden="true">
                  <rect
                    :x="selLabel.x"
                    :y="selLabel.y"
                    :width="selLabel.w"
                    height="20"
                  />
                  <text :x="selLabel.x + 6" :y="selLabel.y + 14">
                    {{ selLabel.text }}
                  </text>
                </g>
              </svg>
            </div>
            <div class="sheet-legend">
              <span class="legend-title">图例</span>
              <span
                v-for="code in shownMaterials"
                :key="code"
                class="legend-key"
              >
                <svg width="26" height="10" aria-hidden="true">
                  <line
                    x1="0"
                    x2="26"
                    y1="5"
                    y2="5"
                    :stroke="color(code)"
                    stroke-width="2"
                  />
                  <circle
                    v-if="code === 'SW'"
                    cx="13"
                    cy="5"
                    r="3.4"
                    :fill="color(code)"
                  />
                  <rect
                    v-else
                    x="9.8"
                    y="1.8"
                    width="6.4"
                    height="6.4"
                    :fill="color(code)"
                  />
                </svg>
                {{ materialName(code) }}
              </span>
              <span v-if="isSr" class="legend-key">
                <svg width="26" height="10" aria-hidden="true">
                  <line x1="0" x2="26" y1="5" y2="5" class="target-key" />
                </svg>
                目标打浆度
              </span>
            </div>
          </div>
          <div class="beating-tooltip" aria-live="polite">
            <template v-if="cursorRevs !== null">
              <strong>{{ number(cursorRevs) }} r</strong>
              <span v-for="c in cursorRows" :key="c.code" class="tip-item">
                <i :style="{ background: color(c.code) }"></i
                >{{ materialName(c.code) }}
                <b>{{
                  c.row && value(c.row) !== null
                    ? `${fmt(value(c.row))} ${unit}`
                    : "该转数无实测"
                }}</b>
              </span>
            </template>
            <span v-else
              >移到曲线上逐个转数读数；点击或用 Tab 选中数据点，Enter
              打开样本来源。</span
            >
          </div>
          <p class="beating-note">
            线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。<template
              v-if="isSr"
              >“达到目标”的转数是相邻两个实测点之间的线性插值估算。</template
            >
          </p>
        </section>

        <section class="card beating-readout" aria-label="样本读数">
          <div class="beating-chart-heading">
            <h2>样本读数</h2>
            <span v-if="selected" class="readout-pos"
              >{{ selectedIndex + 1 }} / {{ listed.length }}</span
            >
          </div>
          <div v-if="selected" class="readout-body">
            <div>
              <div class="readout-code">{{ selected.canonical_code }}</div>
              <div class="readout-name">{{ selected.display_name }}</div>
              <div class="readout-mat">
                <i :style="{ background: color(selected.material_code) }"></i
                >{{ materialName(selected.material_code) }}
              </div>
            </div>
            <div class="readout-big">
              <div>
                <span>{{ metric.name }}</span>
                <p>
                  <strong>{{ fmt(value(selected)) }}</strong
                  ><small>{{ unit }}</small>
                </p>
              </div>
              <div>
                <span>打浆转数</span>
                <p>
                  <strong class="sm">{{
                    number(selected.beating_revolutions)
                  }}</strong
                  ><small>r</small>
                </p>
              </div>
            </div>
            <div class="readout-block">
              <div class="block-head">
                <span>打浆进程</span
                ><span
                  ><b>{{ number(selected.beating_revolutions) }}</b> /
                  {{ number(xMax) }} r</span
                >
              </div>
              <div class="track">
                <i
                  :style="{
                    width: `${(selected.beating_revolutions / xMax) * 100}%`,
                    background: color(selected.material_code),
                  }"
                ></i>
              </div>
            </div>
            <div v-if="toTarget" class="readout-block">
              <div class="block-head">
                <span>距目标 {{ target }} °SR</span
                ><span v-if="toTarget.gap <= 0">已达到</span>
              </div>
              <div class="target-gap">
                <div>
                  <strong>{{
                    toTarget.gap > 0 ? number(toTarget.gap, 1) : "0"
                  }}</strong
                  ><small>°SR</small>
                  <span>还差</span>
                </div>
                <div>
                  <strong>{{
                    toTarget.gap <= 0
                      ? "—"
                      : toTarget.revs === null
                        ? "未达到"
                        : number(toTarget.revs)
                  }}</strong
                  ><small v-if="toTarget.gap > 0 && toTarget.revs !== null"
                    >r</small
                  >
                  <span>约需再打浆</span>
                </div>
              </div>
              <p class="kpi-note">
                {{
                  toTarget.gap > 0 && toTarget.revs === null
                    ? `${materialName(selected.material_code)}在实测范围内没有达到目标。`
                    : "转数按本原料相邻实测点线性插值估算，取整到百转。"
                }}
              </p>
            </div>
            <div v-if="otherAtSameRevs" class="readout-block">
              <div class="block-head">
                <span>同转数下另一种原料</span
                ><span>{{ number(selected.beating_revolutions) }} r</span>
              </div>
              <div class="compare-row me">
                <span>{{ materialName(selected.material_code) }}</span>
                <div class="track">
                  <i
                    :style="{
                      width: `${valueBar(value(selected))}%`,
                      background: color(selected.material_code),
                    }"
                  ></i>
                </div>
                <b>{{ fmt(value(selected)) }}</b>
              </div>
              <div class="compare-row">
                <span>{{ materialName(otherAtSameRevs.code) }}</span>
                <div class="track">
                  <i
                    :style="{
                      width: `${valueBar(otherAtSameRevs.value)}%`,
                      background: color(otherAtSameRevs.code),
                    }"
                  ></i>
                </div>
                <b>{{ fmt(otherAtSameRevs.value) }}</b>
              </div>
              <p class="kpi-note">
                <template v-if="otherAtSameRevs.value === null"
                  >该转数超出{{
                    materialName(otherAtSameRevs.code)
                  }}的实测范围，不外推。</template
                ><template v-else-if="otherAtSameRevs.estimated"
                  >{{
                    materialName(otherAtSameRevs.code)
                  }}在该转数无实测，按相邻实测点线性插值。</template
                ><template v-else>两种原料在该转数都有实测。</template>
              </p>
            </div>
            <div class="readout-actions">
              <button
                class="button"
                type="button"
                @click="openDetail(selected)"
              >
                查看样本详情与来源
              </button>
              <div class="readout-nav">
                <button
                  class="button"
                  type="button"
                  :disabled="selectedIndex <= 0"
                  aria-label="上一个样本"
                  @click="step(-1)"
                >
                  <ChevronLeft :size="15" />上一个
                </button>
                <button
                  class="button"
                  type="button"
                  :disabled="selectedIndex >= listed.length - 1"
                  aria-label="下一个样本"
                  @click="step(1)"
                >
                  下一个<ChevronRight :size="15" />
                </button>
              </div>
            </div>
          </div>
          <p v-else class="beating-state">暂无匹配数据。</p>
        </section>
      </div>

      <section class="card beating-table">
        <div class="beating-chart-heading">
          <div>
            <h2>
              实验明细 <span class="quiet-tag">{{ listed.length }}</span>
            </h2>
            <p>
              按原料分组、打浆转数升序；“—”表示缺失；“≈”表示另一种原料在该转数无实测、按插值比较。
            </p>
          </div>
          <div class="table-actions">
            <span>已勾选 {{ checked.size }}</span>
            <button
              class="button"
              type="button"
              :disabled="!listed.length"
              @click="exportCsv"
            >
              <Download :size="15" />{{
                exportRows.length === listed.length
                  ? "导出筛选结果"
                  : `导出已勾选 ${exportRows.length} 条`
              }}（CSV）
            </button>
          </div>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="打浆实验明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th class="check-cell">
                  <input
                    type="checkbox"
                    class="check"
                    aria-label="勾选当前筛选的全部样本"
                    :checked="allChecked"
                    :indeterminate="someChecked"
                    @change="
                      toggleAll(($event.target as HTMLInputElement).checked)
                    "
                  />
                </th>
                <th>样本编码</th>
                <th class="numeric">打浆转数 / r</th>
                <th class="value-head">{{ metric.name }} / {{ unit }}</th>
                <th class="numeric">较另一种原料（同转数）</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody v-for="code in shownMaterials" :key="code">
              <tr v-if="listedBy(code).length" class="group-row">
                <td colspan="6">
                  <i :style="{ background: color(code) }"></i
                  ><strong>{{ materialName(code) }}</strong
                  ><span>{{ listedBy(code).length }} 个样本</span>
                </td>
              </tr>
              <tr
                v-for="r in listedBy(code)"
                :key="r.canonical_code"
                :data-code="r.canonical_code"
                :class="{ on: selected?.canonical_code === r.canonical_code }"
                @click="select(r)"
              >
                <td class="check-cell" @click.stop>
                  <input
                    type="checkbox"
                    class="check"
                    :aria-label="`勾选 ${r.canonical_code}`"
                    :checked="checked.has(r.canonical_code)"
                    @change="
                      toggle(
                        r.canonical_code,
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                  />
                </td>
                <td>
                  <button class="sample-code" @click.stop="openDetail(r)">
                    {{ r.canonical_code }}
                  </button>
                </td>
                <td class="numeric">{{ number(r.beating_revolutions) }}</td>
                <td class="value-cell">
                  <div class="value-wrap">
                    <span class="numeric">{{ number(value(r), 4) }}</span>
                    <span class="value-bar" aria-hidden="true"
                      ><i
                        :style="{
                          width: `${valueBar(value(r))}%`,
                          background: color(code),
                        }"
                      ></i
                      ><b
                        v-if="isSr"
                        :style="{ left: `${valueBar(target)}%` }"
                      ></b
                    ></span>
                  </div>
                </td>
                <td class="delta-cell">
                  <template v-if="deltaOf(r)"
                    ><span
                      class="delta-value"
                      :title="
                        deltaOf(r)!.estimated
                          ? '另一种原料在该转数无实测，按相邻实测点线性插值'
                          : '两种原料在该转数都有实测'
                      "
                      >{{ deltaOf(r)!.estimated ? "≈" : ""
                      }}{{ signed(deltaOf(r)!.d) }}</span
                    ><svg width="64" height="10" aria-hidden="true">
                      <line x1="32" x2="32" y1="0" y2="10" class="mid" />
                      <rect
                        :x="
                          deltaOf(r)!.d < 0
                            ? 32 - (Math.abs(deltaOf(r)!.d) / deltaMax) * 30
                            : 32
                        "
                        y="2.5"
                        :width="(Math.abs(deltaOf(r)!.d) / deltaMax) * 30"
                        height="5"
                        :fill="color(code)"
                      /></svg
                  ></template>
                  <span v-else class="delta-none">—</span>
                </td>
                <td>
                  <button class="text-button" @click.stop="openDetail(r)">
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!listed.length" class="beating-state">
          <p>没有打浆度在 {{ srRange.lo }}–{{ srRange.hi }} °SR 之间的样本。</p>
          <button class="button" type="button" @click="setRange(0, 100)">
            重置区间
          </button>
        </div>
      </section>
    </template>
    <SampleDetail :sample="detailSample" @close="detailSample = null" />
  </div>
</template>

<style scoped>
/* 页头显微图向右出血，超出部分裁掉，不产生横向滚动 */
.beating-page {
  overflow-x: clip;
}
.page-heading {
  position: relative;
  isolation: isolate;
  min-height: 120px;
  margin-bottom: 16px;
}
.page-heading > :not(.fiber-hero) {
  position: relative;
  z-index: 1;
}
/* 页头按钮压在显微图上，垫一层纸色保证可读 */
.page-heading .button {
  background: var(--panel);
}
.page-heading .button:hover {
  background: #e9e1cf;
}
.beating-controls {
  display: flex;
  align-items: flex-end;
  gap: 28px;
  padding: 14px 20px;
  margin-bottom: 14px;
  position: relative;
  z-index: 3;
  flex-wrap: wrap;
}
.control-caption {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 8px;
}
.material-seg {
  display: flex;
  gap: 4px;
}
.material-seg button {
  flex: none;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--ink-2);
  font-size: 14px;
  transition:
    background-color 0.15s,
    border-color 0.15s;
}
.material-seg button:hover {
  background: var(--canvas);
}
.material-seg button.on {
  border-color: var(--signal);
  background: var(--signal-tint);
  color: var(--ink);
}
.material-seg i {
  width: 10px;
  height: 10px;
  border-radius: 1px;
}
.material-seg i.all {
  background: linear-gradient(90deg, var(--sw) 0 50%, var(--hw) 50%);
}
.seg-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}
.material-seg button.on .seg-count {
  color: var(--signal);
}
.count-group {
  margin-left: auto;
  align-self: center;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.beating-count {
  font-size: 13px;
  color: var(--muted);
}
/* 打浆度区间：分布直方图 + 双滑块，拇指做成游标卡尺的卡爪 */
.range-group {
  width: 240px;
}
.range-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.range-val {
  font: 500 13px var(--font-mono);
  color: var(--ink);
}
.range-val small {
  margin-left: 3px;
  font-size: 11px;
  color: var(--muted);
}
.hist {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 26px;
  padding: 0 4px;
}
.hist i {
  flex: 1;
  background: #a89a7d;
  border-radius: 1px 1px 0 0;
}
.hist i.out {
  opacity: 0.28;
}
.dual-range {
  position: relative;
  height: 18px;
}
.dual-track {
  position: absolute;
  left: 4px;
  right: 4px;
  top: 8px;
  height: 2px;
  background: var(--border-strong);
}
.dual-track i {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--signal);
}
.dual-range input {
  position: absolute;
  inset: 0;
  width: 100%;
  margin: 0;
  background: none;
  pointer-events: none;
  appearance: none;
  -webkit-appearance: none;
}
.dual-range input::-webkit-slider-runnable-track {
  height: 18px;
  background: none;
}
.dual-range input::-moz-range-track {
  height: 18px;
  background: none;
}
.dual-range input::-webkit-slider-thumb {
  -webkit-appearance: none;
  pointer-events: auto;
  width: 8px;
  height: 18px;
  border-radius: 1px;
  background: var(--signal);
  cursor: ew-resize;
}
.dual-range input::-moz-range-thumb {
  pointer-events: auto;
  width: 8px;
  height: 18px;
  border: 0;
  border-radius: 1px;
  background: var(--signal);
  cursor: ew-resize;
}
.dual-range input:focus-visible {
  outline: none;
}
.dual-range input:focus-visible::-webkit-slider-thumb {
  outline: 2px solid var(--signal);
  outline-offset: 2px;
}
.dual-range input:focus-visible::-moz-range-thumb {
  outline: 2px solid var(--signal);
  outline-offset: 2px;
}
.beating-count span {
  margin: 0 10px;
  color: var(--border-strong);
}

/* KPI：一条带刻度的读数条 */
.beating-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-bottom: 16px;
  padding: 0;
}
.kpi {
  padding: 14px 20px 12px;
  border-left: 1px solid var(--border);
  min-width: 0;
  transition: opacity 0.15s;
}
.kpi:first-child {
  border-left: 0;
}
.kpi.dim {
  opacity: 0.4;
}
.kpi-label {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  width: 8px;
  height: 8px;
  border-radius: 1px;
}
.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 6px;
  min-height: 40px;
}
.kpi-value strong {
  font: 500 40px/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  letter-spacing: -0.02em;
}
.kpi-value strong.na {
  font-size: 22px;
  color: var(--muted);
}
.kpi-value small {
  font: 400 13px/1 var(--font-mono);
  color: var(--muted);
}
.kpi-value .delta {
  margin-left: 8px;
  font: 500 13px var(--font-mono);
  color: var(--ink-2);
}
.kpi-note {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}
.stepper {
  margin-left: auto;
  display: inline-flex;
  gap: 4px;
  align-self: center;
}
.stepper button {
  width: 26px;
  height: 26px;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--ink-2);
}
.stepper button:hover:not(:disabled) {
  color: var(--signal);
  border-color: var(--signal);
}
/* 刻度尺：底线 + 短刻度 + 三角指针 */
.ruler {
  position: relative;
  height: 16px;
  margin-top: 10px;
  background:
    linear-gradient(var(--muted), var(--muted)) 0 7px / 100% 1px no-repeat,
    repeating-linear-gradient(90deg, var(--muted) 0 1px, transparent 1px 5%) 0
      7px / 100% 5px no-repeat;
  opacity: 0.9;
}
.ruler i {
  position: absolute;
  top: -3px;
  width: 0;
  height: 0;
  margin-left: -5px;
  border: 5px solid transparent;
  border-top: 8px solid var(--signal);
  border-bottom: 0;
}
.ruler-labels {
  display: flex;
  justify-content: space-between;
  font: 400 11px var(--font-mono);
  color: var(--muted);
}
.unit-note {
  font-size: 12px;
  color: #986f31;
  margin: -6px 0 14px;
}

/* 曲线 + 读数 */
.beating-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 16px;
  margin-bottom: 16px;
  align-items: stretch;
}
.beating-chart {
  border-color: var(--border-strong);
  padding: 16px 18px 14px;
  min-width: 0;
}
.beating-chart-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.beating-chart-heading p {
  font-size: 13px;
  color: var(--muted);
  margin-top: 6px;
}
/* 一张压在卡片上的白纸：纸边 + 淡投影 */
.sheet {
  margin-top: 14px;
  background: var(--paper);
  border: 1px solid var(--paper-edge);
  border-radius: 1px;
  box-shadow:
    0 1px 2px rgba(60, 45, 20, 0.08),
    0 4px 12px -6px rgba(60, 45, 20, 0.18);
}
.plot-box {
  width: 100%;
  overflow: hidden;
}
.beating-plot {
  display: block;
  touch-action: pan-y;
}
.beating-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--ink-2);
}
.beating-plot .axis-title {
  font-family: inherit;
  font-weight: 500;
}
.paper-fibers path {
  fill: none;
  stroke: var(--ink);
  stroke-linecap: round;
  opacity: 0.06;
}
.grid line {
  stroke: #e9e2d2;
  shape-rendering: crispEdges;
}
.axis line {
  stroke: #9a8d72;
  shape-rendering: crispEdges;
}
.line {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
}
.mark {
  fill: var(--c);
  stroke: var(--paper);
  stroke-width: 2;
  paint-order: stroke;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.plot-point.out .mark {
  opacity: 0.25;
}
.sel-label rect {
  fill: var(--paper);
  stroke: var(--signal-ink);
}
.sel-label text {
  fill: var(--signal-ink);
  font-weight: 500;
}
.plot-point:focus-visible .mark {
  stroke: var(--signal-ink);
  stroke-width: 2.5;
}
.ring {
  fill: none;
  stroke: var(--signal-ink);
  stroke-width: 1.5;
}
.target line,
.target-key {
  stroke: var(--signal-ink);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.target text {
  fill: var(--signal-ink);
  font-weight: 500;
}
.target-hits circle {
  fill: var(--paper);
  stroke: var(--signal-ink);
  stroke-width: 1.5;
}
.cursor line {
  stroke: var(--signal-ink);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
.sheet-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
  padding: 8px 14px;
  border-top: 1px solid #e9e2d2;
  font-size: 12px;
  color: var(--ink-2);
}
.legend-title {
  color: var(--muted);
}
.legend-key {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.beating-tooltip {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  padding: 10px 2px 0;
  font-size: 12px;
  color: var(--muted);
}
.beating-tooltip strong {
  font-family: var(--font-mono);
  color: var(--signal);
}
.tip-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-2);
}
.tip-item i {
  width: 10px;
  height: 2px;
}
.tip-item b {
  font: 500 12px var(--font-mono);
  color: var(--ink);
}
.beating-note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  line-height: 1.7;
}

/* 读数面板 */
.beating-readout {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
}
.readout-pos {
  font: 400 12px var(--font-mono);
  color: var(--muted);
}
.readout-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 14px;
  flex: 1;
}
.readout-code {
  font: 500 12px var(--font-mono);
  color: var(--muted);
}
.readout-name {
  font: 700 22px/1.3 var(--font-serif);
  color: var(--ink);
  margin-top: 2px;
}
.readout-mat {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink-2);
  margin-top: 6px;
}
.readout-mat i {
  width: 10px;
  height: 10px;
  border-radius: 1px;
}
.readout-big {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.readout-big span {
  font-size: 12px;
  color: var(--muted);
}
.readout-big p {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 4px;
}
.readout-big strong {
  font: 500 40px/1 var(--font-mono);
  color: var(--ink);
  letter-spacing: -0.02em;
}
.readout-big strong.sm {
  font-size: 26px;
  font-weight: 400;
}
/* 大数字正下方一条 4px 纸边色细条，与数字等宽 */
.readout-big div:first-child strong {
  padding-bottom: 6px;
  border-bottom: 4px solid var(--paper-edge);
}
.readout-big small {
  font: 400 12px var(--font-mono);
  color: var(--muted);
}
.readout-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--muted);
}
.block-head b {
  font: 500 12px var(--font-mono);
  color: var(--ink);
}
.track {
  position: relative;
  height: 6px;
  background: #e8e1d2;
  border-radius: 1px;
  overflow: hidden;
}
.track i {
  position: absolute;
  inset: 0 auto 0 0;
  transition: width 0.3s ease-out;
}
.target-gap {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.target-gap div {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-wrap: wrap;
}
.target-gap strong {
  font: 500 22px/1 var(--font-mono);
  color: var(--ink);
}
.target-gap small {
  font: 400 12px var(--font-mono);
  color: var(--muted);
}
.target-gap span {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--muted);
}
.compare-row {
  display: grid;
  grid-template-columns: 64px 1fr 56px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
}
.compare-row b {
  font: 500 12px var(--font-mono);
  color: var(--ink-2);
  text-align: right;
}
.compare-row.me {
  color: var(--ink);
}
.compare-row.me b {
  color: var(--ink);
}
.compare-row:not(.me) .track i {
  opacity: 0.5;
}
.readout-actions {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.readout-actions .button {
  justify-content: center;
}
.readout-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

/* 表格：按原料分组 */
.beating-table .beating-chart-heading {
  padding: 16px 20px;
}
.table-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: var(--muted);
}
.check-cell {
  width: 40px;
  padding-right: 0;
}
.check {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--signal);
  cursor: pointer;
}
.delta-cell {
  text-align: right;
  white-space: nowrap;
}
.delta-cell svg {
  vertical-align: middle;
  margin-left: 10px;
}
.delta-cell .mid {
  stroke: var(--border-strong);
}
.delta-value {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.delta-none {
  color: var(--muted);
}
.group-row td {
  height: 34px;
  background: #efe8da;
  padding-top: 4px;
  padding-bottom: 4px;
}
.group-row td > * {
  vertical-align: middle;
}
.group-row i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 1px;
  margin-right: 8px;
}
.group-row strong {
  font: 700 14px var(--font-serif);
  color: var(--ink);
}
.group-row span {
  margin-left: 10px;
  font-size: 12px;
  color: var(--muted);
}
tbody tr.on td {
  background: var(--signal-tint);
}
tbody tr.on td:first-child {
  box-shadow: inset 2px 0 0 var(--signal);
}
tbody tr:not(.group-row) {
  cursor: pointer;
}
.value-head,
.value-cell {
  padding-left: 24px;
}
.value-wrap {
  display: flex;
  align-items: center;
  gap: 14px;
}
.value-wrap .numeric {
  min-width: 64px;
}
.value-bar {
  position: relative;
  flex: 1;
  max-width: 260px;
  height: 4px;
  background: #e8e1d2;
  border-radius: 1px;
}
.value-bar i {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 1px;
}
.value-bar b {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 1px;
  background: var(--signal);
}
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--muted);
}
.beating-state p {
  margin: 14px 0;
}
@media (max-width: 1100px) {
  .beating-row {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 720px) {
  .beating-controls > div {
    width: 100%;
  }
  .material-seg {
    overflow-x: auto;
  }
  .beating-controls {
    gap: 14px;
    padding: 16px;
  }
  .count-group {
    margin-left: 0;
    width: 100%;
    align-items: flex-start;
  }
  .range-group {
    width: 100%;
  }
  .table-actions span {
    display: none;
  }
  .beating-kpis {
    grid-template-columns: 1fr 1fr;
  }
  .kpi {
    border-left: 0;
    border-top: 1px solid var(--border);
    padding: 12px 14px;
  }
  .kpi:nth-child(-n + 2) {
    border-top: 0;
  }
  .kpi:nth-child(even) {
    border-left: 1px solid var(--border);
  }
  .kpi-value strong {
    font-size: 26px;
  }
  .beating-chart,
  .beating-readout {
    padding: 14px;
  }
  .value-bar {
    display: none;
  }
}
</style>
