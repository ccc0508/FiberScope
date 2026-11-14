<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
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
  firstReach,
  interpolateAt,
  niceTicks,
  type CurvePoint,
} from "../beating";
import { materialCodeColors } from "../palette";
import { isGarden } from "../mode";
import { useCountUp, vSeg, vTilt } from "../motion";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import PageHeader from "../components/PageHeader.vue";
import FiberHero from "../components/FiberHero.vue";

/*
 * 打浆分析：一个模板服务两种显示模式。
 *  偏光（v1）：控制条 → 四格目标读数条 → 曲线（HUD 十字准星）+ 读数面板 → 明细表
 *  花园（v4）：控制瓦片 → 曲线 + 「达到目标所需转数」瓦片 → 明细表 + 读数瓦片
 * 布局差异只在作用域 CSS（:root[data-mode=…]）里表达；两套装饰层都渲染，按模式显隐。
 */
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
const TARGET_MIN = 20,
  TARGET_MAX = 85;
const target = computed(() => {
  const t = Number(route.query.target);
  return Number.isFinite(t) && t >= TARGET_MIN && t <= TARGET_MAX
    ? Math.round(t)
    : 45;
});
const metricOptions = computed(() =>
  metrics.value.map((i) => ({ value: i.key, label: i.name })),
);
function update(key: string, next: string | undefined) {
  void router.replace({ query: { ...route.query, [key]: next } });
}
const setTarget = (t: number) =>
  update("target", String(Math.max(TARGET_MIN, Math.min(TARGET_MAX, t))));

/* ---------- 数据 ---------- */
const materialName = (code: Material) =>
  code === "SW" ? "针叶木浆" : "阔叶木浆";
const typeOf = (code: Material) => (code === "SW" ? "softwood" : "hardwood");
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
    // 偏光：每根柱子取同一条干涉色带的相邻切片
    slice: { "--bs": "1000% 100%", "--bp": `${(i / 9) * 100}% 0` },
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
// 花园模式下 KPI 数字首次出现时计数上升；屏幕阅读器始终读真实值
const kpiEl = ref<HTMLElement>();
const swReachShown = useCountUp(
  () => (isSr.value && reach.value.SW !== null ? round100(reach.value.SW) : null),
  { el: kpiEl },
);
const hwReachShown = useCountUp(
  () => (isSr.value && reach.value.HW !== null ? round100(reach.value.HW) : null),
  { el: kpiEl },
);
const gapShown = useCountUp(
  () =>
    isSr.value && reachGap.value !== null
      ? round100(Math.abs(reachGap.value))
      : null,
  { el: kpiEl },
);
const reachShown = computed<Record<Material, number | null>>(() => ({
  SW: swReachShown.value,
  HW: hwReachShown.value,
}));
// 页头签名始终画打浆度曲线（与当前选中的指标无关）
const srCurve = (code: Material): CurvePoint[] =>
  byMaterial.value[code]
    .filter((r) => srOf(r) !== null)
    .map((r) => ({ x: r.beating_revolutions, y: srOf(r)! }));
const sigCurves = computed(() => ({ SW: srCurve("SW"), HW: srCurve("HW") }));

/* ---------- 曲线：按容器实际宽度绘制，文字不随缩放变形 ---------- */
const plotBox = ref<HTMLElement>();
const plotWidth = ref(720);
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
const narrow = computed(() => plotWidth.value < 520);
const plotH = computed(() => (narrow.value ? 300 : 420));
// 花园：曲线末端直接标注原料名（v4 direct labels），右侧留出标签位
const directLabels = computed(() => isGarden.value && !narrow.value);
// 第一个刻度处的数据点与纵轴刻度文字之间留一点空
const X_PAD = 10;
const margin = computed(() => ({
  t: 34,
  r: directLabels.value ? 96 : narrow.value ? 14 : 26,
  b: 46,
  l: narrow.value ? 46 : 58,
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
// 花园 10k / 偏光 10,000（窄屏 10K）
const xTickLabel = (t: number) =>
  t === 0
    ? "0"
    : isGarden.value
      ? `${number(t / 1000, t % 1000 ? 1 : 0)}k`
      : plotWidth.value < 560
        ? `${number(t / 1000, t % 1000 ? 1 : 0)}K`
        : number(t);
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
const plotInner = computed(
  () => plotWidth.value - margin.value.l - margin.value.r - X_PAD,
);
const px = (revs: number) =>
  margin.value.l + X_PAD + (revs / xMax.value) * plotInner.value;
const py = (v: number) =>
  margin.value.t +
  (1 - (v - yMin.value) / (yMax.value - yMin.value || 1)) *
    (plotH.value - margin.value.t - margin.value.b);
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
// 达到目标处：从目标线落到横轴的竖线 + 转数标签；先达到的标签放竖线左侧，后达到的放右侧
const reachMarks = computed(() => {
  const hits = targetHits.value
    .map((h) => ({ ...h, px: px(h.x), r: round100(h.x) }))
    .sort((a, b) => a.px - b.px);
  return hits.map((h, i) => {
    const label = `${number(h.r)} r`,
      w = label.length * 7 + 4;
    let anchor: "start" | "end" = hits.length > 1 && i === 0 ? "end" : "start";
    if (anchor === "start" && h.px + 6 + w > plotWidth.value - margin.value.r)
      anchor = "end";
    if (anchor === "end" && h.px - 6 - w < margin.value.l) anchor = "start";
    const lx = anchor === "start" ? h.px + 6 : h.px - 6;
    // 与选中点的读数标签相撞时，挪到读数标签上方
    let ly = plotH.value - margin.value.b - 8;
    const sel = selLabel.value,
      x0 = anchor === "start" ? lx : lx - w;
    if (
      sel &&
      x0 < sel.x + sel.w &&
      x0 + w > sel.x &&
      ly - 12 < sel.y + 20 &&
      ly + 4 > sel.y
    )
      ly = sel.y - 7;
    return { ...h, label, anchor, lx, ly };
  });
});
const diamond = (x: number, y: number, s: number) =>
  `M${x},${y - s}L${x + s},${y}L${x},${y + s}L${x - s},${y}Z`;
// 花园：曲线末端的原料标签，彼此至少相隔 18px，不压住最后一个横轴刻度
const endLabels = computed(() => {
  if (!directLabels.value) return [];
  const labs = series.value
    .map((s) => {
      const last = s.points[s.points.length - 1];
      return last ? { code: s.code, y: py(value(last)!) } : null;
    })
    .filter((l): l is { code: Material; y: number } => l !== null)
    .sort((a, b) => a.y - b.y);
  const lo = margin.value.t + 6,
    hi = plotH.value - margin.value.b - 16;
  labs.forEach((l) => (l.y = Math.max(lo, Math.min(hi, l.y))));
  for (let k = 1; k < labs.length; k++)
    if (labs[k]!.y - labs[k - 1]!.y < 18) labs[k]!.y = labs[k - 1]!.y + 18;
  const last = labs[labs.length - 1];
  if (last && last.y > hi) {
    last.y = hi;
    for (let k = labs.length - 2; k >= 0; k--)
      if (labs[k + 1]!.y - labs[k]!.y < 18) labs[k]!.y = labs[k + 1]!.y - 18;
  }
  const x = plotWidth.value - margin.value.r + 12;
  return labs.map((l) => ({ ...l, x }));
});
const measuredRevs = computed(() =>
  [...new Set(valid.value.map((r) => r.beating_revolutions))].sort(
    (a, b) => a - b,
  ),
);

/* ---------- 悬停 / 聚焦：吸附到最近的实测转数，再取纵向最近的那一点 ---------- */
const hover = ref<{ revs: number; code: string } | null>(null);
const cursorRevs = computed(() => hover.value?.revs ?? null);
function nearestRow(event: MouseEvent): BeatingRow | null {
  const box = (event.currentTarget as SVGElement).getBoundingClientRect();
  const x = event.clientX - box.left,
    y = event.clientY - box.top;
  if (x < margin.value.l - 8 || x > plotWidth.value - margin.value.r + 8)
    return null;
  let best: number | null = null;
  for (const r of measuredRevs.value)
    if (best === null || Math.abs(px(r) - x) < Math.abs(px(best) - x)) best = r;
  if (best === null) return null;
  const candidates = shownMaterials.value.flatMap((code) =>
    byMaterial.value[code].filter(
      (r) => r.beating_revolutions === best && value(r) !== null,
    ),
  );
  return candidates.reduce<BeatingRow | null>(
    (a, b) =>
      !a || Math.abs(py(value(b)!) - y) < Math.abs(py(value(a)!) - y) ? b : a,
    null,
  );
}
function pointer(event: PointerEvent) {
  const r = nearestRow(event);
  hover.value = r
    ? { revs: r.beating_revolutions, code: r.canonical_code }
    : null;
}
// 点在曲线空白处也能选中最近的样本（点本身的点击由数据点处理）
function pickAt(event: MouseEvent) {
  if ((event.target as Element).closest(".plot-point")) return;
  const r = nearestRow(event);
  if (r) select(r);
}
function focusPoint(r: BeatingRow) {
  select(r);
  hover.value = { revs: r.beating_revolutions, code: r.canonical_code };
}
function blurPoint(r: BeatingRow) {
  if (hover.value?.code === r.canonical_code) hover.value = null;
}
// 方向键：←/→ 同一原料的前后实测点，↑/↓ 切换到另一种原料最接近的转数
function pointKey(event: KeyboardEvent, r: BeatingRow) {
  const own = byMaterial.value[r.material_code].filter(
    (x) => value(x) !== null,
  );
  const i = own.indexOf(r);
  let next: BeatingRow | undefined;
  if (event.key === "ArrowRight") next = own[i + 1];
  else if (event.key === "ArrowLeft") next = own[i - 1];
  else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    const other: Material = r.material_code === "SW" ? "HW" : "SW";
    if (shownMaterials.value.includes(other))
      next = byMaterial.value[other]
        .filter((x) => value(x) !== null)
        .reduce<BeatingRow | undefined>(
          (a, b) =>
            !a ||
            Math.abs(b.beating_revolutions - r.beating_revolutions) <
              Math.abs(a.beating_revolutions - r.beating_revolutions)
              ? b
              : a,
          undefined,
        );
  } else return;
  event.preventDefault();
  if (next)
    document
      .querySelector<SVGGElement>(`[data-point="${next.canonical_code}"]`)
      ?.focus();
}
const hoverPoint = computed(() => {
  const h = hover.value;
  const r = h
    ? (visible.value.find((x) => x.canonical_code === h.code) ?? null)
    : null;
  const v = r ? value(r) : null;
  if (!r || v === null) return null;
  return { row: r, v, x: px(r.beating_revolutions), y: py(v) };
});
// 同一转数下各原料的读数：有实测用实测，否则相邻实测点插值（≈），超出范围为空
const cursorRows = computed(() => {
  const revs = cursorRevs.value;
  if (revs === null) return [];
  return shownMaterials.value.map((code) => {
    const row =
      byMaterial.value[code].find((r) => r.beating_revolutions === revs) ??
      null;
    const exact = row ? value(row) : null;
    if (exact !== null) return { code, value: exact, estimated: false };
    const est = interpolateAt(curve(code), revs);
    return { code, value: est, estimated: est !== null };
  });
});
const hotPoints = computed(() => {
  const revs = cursorRevs.value;
  if (revs === null) return [];
  return series.value.flatMap((s) =>
    s.points
      .filter((r) => r.beating_revolutions === revs)
      .map((r) => ({ code: s.code, x: px(revs), y: py(value(r)!) })),
  );
});
// 偏光 HUD：准星两端钉在坐标轴上的读数框
const hud = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  const xl = `${number(p.row.beating_revolutions)} r`,
    yl = fmt(p.v);
  const xw = xl.length * 6.4 + 12,
    yw = yl.length * 6.4 + 12;
  const cx = Math.max(
    margin.value.l + xw / 2,
    Math.min(plotWidth.value - margin.value.r - xw / 2, p.x),
  );
  return { xl, yl, xw, yw, cx, base: plotH.value - margin.value.b };
});
const tip = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  return {
    style: { "--x": `${p.x}px`, "--y": `${p.y}px` },
    left: p.x + 16 + 236 > plotWidth.value,
    below: p.y < 124,
  };
});

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
// 打浆进程条上标出本原料达到目标的转数
const selectedReachPct = computed(() => {
  const s = selected.value;
  if (!isSr.value || !s) return null;
  const at = reach.value[s.material_code];
  return at === null ? null : Math.min(100, (at / xMax.value) * 100);
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
  const perRev = xMax.value / plotInner.value;
  const otherY =
    material.value === "all"
      ? interpolateAt(
          curve(otherCode),
          s.beating_revolutions + (6 + w / 2) * perRev,
        )
      : null;
  const below = otherY === null ? y < plotH.value / 2 : otherY >= v;
  let ly = below ? y + 12 : y - 32;
  ly = Math.max(margin.value.t, Math.min(plotH.value - margin.value.b - 22, ly));
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
    "﻿" + [head, ...lines].map((l) => l.map(cell).join(",")).join("\r\n");
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
    hover.value = null;
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
    <PageHeader description="比较打浆转数变化下的纤维特性与纸张性能。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <FiberHero
          :sw="sigCurves.SW"
          :hw="sigCurves.HW"
          :target="target"
          :x-max="xMax"
        />
      </template>
    </PageHeader>

    <div v-if="error" class="card beating-state beating-status" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div
      v-else-if="loading"
      class="card beating-state beating-status"
      role="status"
    >
      正在读取打浆实验数据…
    </div>
    <template v-else>
      <section class="card beating-controls" aria-label="打浆分析筛选">
        <div class="ctl">
          <span class="field-label" id="beating-material-label">原料</span>
          <div
            v-seg
            class="seg beating-seg"
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
              <i v-if="opt !== 'all'" class="mk" :class="`mk-${opt}`"></i
              >{{ opt === "all" ? "全部" : materialName(opt)
              }}<span class="cnt">{{ counts[opt] }}</span>
            </button>
          </div>
        </div>
        <div class="ctl ctl-metric">
          <span class="field-label">分析指标</span
          ><FilterSelect
            id="beating-metric"
            label="分析指标"
            :model-value="metric.key"
            :options="metricOptions"
            @update:model-value="update('metric', $event)"
          />
        </div>
        <div class="ctl range-group">
          <div class="range-head">
            <span class="field-label" id="beating-sr-label">打浆度区间</span
            ><span class="range-val"
              >{{ srRange.lo }} – {{ srRange.hi }}<small>°SR</small></span
            >
          </div>
          <div class="hist" aria-hidden="true">
            <i
              v-for="(b, i) in histogram"
              :key="i"
              :class="{ out: !b.on }"
              :style="{ height: `${b.h}%`, ...b.slice }"
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
            <span class="nw">{{ listed.length }} 个样本</span
            ><span class="sep" aria-hidden="true">·</span
            ><span class="nw">{{ valid.length }} 个有效数据点</span>
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

      <p v-if="metric.unit_status !== 'confirmed'" class="unit-note">
        {{ metric.name }}的单位{{
          metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
        }}，数值保留原始口径。
      </p>

      <!-- KPI：打浆度看“达到目标需要多少转”，其他指标看打浆前后的变化 -->
      <section
        ref="kpiEl"
        class="card beating-kpis"
        :class="{ 'is-sr': isSr }"
        aria-label="关键指标"
      >
        <template v-if="isSr">
          <div class="kpi kpi-target">
            <div class="kpi-label">
              <label for="beating-target">目标打浆度</label>
            </div>
            <div class="kpi-target-row">
              <button
                type="button"
                class="step-btn"
                aria-label="目标打浆度降低 5"
                :disabled="target <= TARGET_MIN"
                @click="setTarget(target - 5)"
              >
                <Minus :size="14" />
              </button>
              <output class="kpi-value" for="beating-target"
                ><strong>{{ target }}</strong><small>°SR</small></output
              >
              <button
                type="button"
                class="step-btn"
                aria-label="目标打浆度提高 5"
                :disabled="target >= TARGET_MAX"
                @click="setTarget(target + 5)"
              >
                <Plus :size="14" />
              </button>
            </div>
            <input
              id="beating-target"
              class="beating-range"
              type="range"
              :min="TARGET_MIN"
              :max="TARGET_MAX"
              step="1"
              :value="target"
              :aria-valuetext="`${target} °SR`"
              @input="setTarget(+($event.target as HTMLInputElement).value)"
            />
            <div class="ruler-labels">
              <span>{{ TARGET_MIN }}</span><span>{{ TARGET_MAX }}</span>
            </div>
          </div>
          <h3 class="kpi-reach-h">
            达到 <b>{{ target }}</b> °SR 所需转数
          </h3>
          <div
            v-for="code in MATERIALS"
            :key="code"
            v-tilt
            class="kpi kpi-mat"
            :class="[`kpi-${code}`, { dim: material !== 'all' && material !== code }]"
          >
            <div class="kpi-label">
              <i class="mk" :class="`mk-${code}`"></i
              ><span>{{ materialName(code) }}</span
              ><span class="kpi-label-target nw"> · 达到 {{ target }} °SR</span>
            </div>
            <div class="kpi-value">
              <template v-if="reach[code] !== null"
                ><strong
                  ><span aria-hidden="true">{{
                    number(reachShown[code] ?? round100(reach[code]!))
                  }}</span
                  ><span class="sr-only">{{
                    number(round100(reach[code]!))
                  }}</span></strong
                ><small>转</small></template
              ><strong v-else class="na">未达到</strong>
            </div>
            <div class="kpi-track" aria-hidden="true">
              <i
                v-if="reach[code] !== null"
                :style="{
                  '--at': `${Math.min(100, (reach[code]! / xMax) * 100)}%`,
                }"
              ></i>
            </div>
            <div class="ruler-labels kpi-scale-row">
              <span>0</span><span>{{ number(xMax) }}</span>
            </div>
          </div>
          <div class="ruler-labels kpi-scale" aria-hidden="true">
            <span>0</span><span>{{ number(xMax) }} r</span>
          </div>
          <div class="kpi kpi-diff">
            <div class="kpi-label">两种原料相差</div>
            <div class="kpi-value">
              <template v-if="reachGap !== null"
                ><strong
                  ><span aria-hidden="true">{{
                    number(gapShown ?? round100(Math.abs(reachGap)))
                  }}</span
                  ><span class="sr-only">{{
                    number(round100(Math.abs(reachGap)))
                  }}</span></strong
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
            v-tilt
            class="kpi kpi-mat wide"
            :class="[`kpi-${code}`, { dim: material !== 'all' && material !== code }]"
          >
            <div class="kpi-label">
              <i class="mk" :class="`mk-${code}`"></i
              ><span>{{ materialName(code) }} · {{ metric.name }}</span>
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
              <span class="nw"
                >{{ number(change(code)!.from.x) }} 转时
                {{ fmt(change(code)!.from.y) }}</span
              >
              →
              <span class="nw"
                >{{ number(change(code)!.to.x) }} 转时
                {{ fmt(change(code)!.to.y) }}</span
              >
            </p>
          </div>
          <div class="kpi kpi-valid">
            <div class="kpi-label">有效数据点</div>
            <div class="kpi-value">
              <strong>{{ valid.length }}</strong
              ><small>/ {{ visible.length }}</small>
            </div>
            <p class="kpi-note">缺失值不计入，曲线在缺失处断开。</p>
          </div>
        </template>
      </section>

      <section class="card beating-chart" aria-labelledby="beating-chart-title">
        <div class="beating-chart-head">
          <h2 id="beating-chart-title">{{ metric.name }}随打浆转数的变化</h2>
          <p>纵轴：{{ metric.name }}（{{ unit }}）</p>
        </div>
        <ul class="beating-legend" aria-label="图例">
          <li class="legend-title" aria-hidden="true">图例</li>
          <li v-for="code in shownMaterials" :key="code">
            <svg width="24" height="10" aria-hidden="true">
              <line
                x1="0"
                x2="24"
                y1="5"
                y2="5"
                :stroke="color(code)"
                stroke-width="2"
                stroke-linecap="round"
              />
              <circle
                v-if="code === 'SW'"
                cx="12"
                cy="5"
                r="3.6"
                :fill="color(code)"
              />
              <rect
                v-else
                x="8.6"
                y="1.6"
                width="6.8"
                height="6.8"
                rx="1.6"
                :fill="color(code)"
              />
            </svg>
            {{ materialName(code) }}
          </li>
          <li v-if="isSr">
            <svg width="24" height="10" aria-hidden="true">
              <line x1="0" x2="24" y1="5" y2="5" class="target-key" />
            </svg>
            目标打浆度
          </li>
        </ul>
        <div v-if="!valid.length" class="beating-state beating-plot-state" role="status">
          当前原料没有该指标的有效数据，请切换指标或原料。
        </div>
        <div v-else ref="plotBox" class="plot-box">
          <svg
            class="beating-plot"
            role="group"
            :width="plotWidth"
            :height="plotH"
            :viewBox="`0 0 ${plotWidth} ${plotH}`"
            aria-label="打浆趋势图；可用Tab定位数据点，方向键切换，Enter选中样本"
            @pointermove="pointer"
            @pointerleave="hover = null"
            @click="pickAt"
          >
            <g class="grid">
              <line
                v-for="t in yTicks"
                :key="`gy${t}`"
                :x1="margin.l"
                :x2="plotWidth - margin.r"
                :y1="py(t)"
                :y2="py(t)"
              />
            </g>
            <g class="axis">
              <line
                :x1="margin.l"
                :x2="plotWidth - margin.r"
                :y1="plotH - margin.b"
                :y2="plotH - margin.b"
              />
              <g v-for="t in yTicks" :key="`ty${t}`">
                <text :x="margin.l - 10" :y="py(t) + 4" text-anchor="end">
                  {{ number(t, t % 1 ? digits : 0) }}
                </text>
              </g>
              <g v-for="t in xTicks" :key="`tx${t}`">
                <line
                  :x1="px(t)"
                  :x2="px(t)"
                  :y1="plotH - margin.b"
                  :y2="plotH - margin.b + 5"
                />
                <text
                  :x="px(t)"
                  :y="plotH - margin.b + 20"
                  :text-anchor="t === xMax && !directLabels ? 'end' : 'middle'"
                >
                  {{ xTickLabel(t) }}
                </text>
              </g>
              <text class="axis-title" x="4" :y="margin.t - 16">
                {{ isGarden ? "↑ " : "" }}{{ metric.name }} / {{ unit }}
              </text>
              <text
                class="axis-title"
                :x="plotWidth - margin.r"
                :y="plotH - 6"
                text-anchor="end"
              >
                打浆转数 / r{{ isGarden ? " →" : "" }}
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
                class="target-t"
                :x="plotWidth - margin.r - 4"
                :y="py(target) - 7"
                text-anchor="end"
              >
                目标 {{ target }} °SR
              </text>
            </g>
            <g
              v-for="h in reachMarks"
              :key="`reach${h.code}`"
              class="reach"
              :style="{ '--c': color(h.code) }"
            >
              <line
                class="reach-drop"
                :x1="h.px"
                :x2="h.px"
                :y1="py(target)"
                :y2="plotH - margin.b"
              />
              <path class="reach-dia" :d="diamond(h.px, py(target), 4.4)" />
              <circle class="reach-ring" :cx="h.px" :cy="py(target)" r="6.5" />
            </g>
            <g
              v-for="s in series"
              :key="s.code"
              class="series"
              :style="{ '--c': color(s.code) }"
            >
              <path :d="s.path" class="line" />
              <g
                v-for="r in s.points"
                :key="r.canonical_code"
                class="plot-point"
                :data-point="r.canonical_code"
                :class="{
                  on: selected?.canonical_code === r.canonical_code,
                  out: !inRange(r),
                }"
                role="button"
                tabindex="0"
                :aria-label="`${r.canonical_code}，${r.beating_revolutions}转，${metric.name}${value(r)} ${unit}，选中查看读数`"
                @click="select(r)"
                @focus="focusPoint(r)"
                @blur="blurPoint(r)"
                @keydown="pointKey($event, r)"
                @keydown.enter.prevent="openDetail(r)"
                @keydown.space.prevent="openDetail(r)"
              >
                <circle
                  class="hit"
                  :cx="px(r.beating_revolutions)"
                  :cy="py(value(r)!)"
                  r="10"
                />
                <circle
                  v-if="s.code === 'SW'"
                  class="mark"
                  :cx="px(r.beating_revolutions)"
                  :cy="py(value(r)!)"
                  r="4.2"
                />
                <rect
                  v-else
                  class="mark"
                  :x="px(r.beating_revolutions) - 3.9"
                  :y="py(value(r)!) - 3.9"
                  width="7.8"
                  height="7.8"
                  rx="2"
                />
                <circle
                  v-if="selected?.canonical_code === r.canonical_code"
                  class="ring"
                  :cx="px(r.beating_revolutions)"
                  :cy="py(value(r)!)"
                  r="10.5"
                />
                <title>
                  {{ r.canonical_code }} ·
                  {{ number(r.beating_revolutions) }} r · {{ metric.name }}
                  {{ fmt(value(r)) }} {{ unit }}
                </title>
              </g>
            </g>
            <!-- 转数标签画在曲线之上，纸色描边让它在穿过曲线时仍可读 -->
            <g v-if="reachMarks.length" class="reach-labels" aria-hidden="true">
              <text
                v-for="h in reachMarks"
                :key="`reach-t${h.code}`"
                class="reach-t"
                :x="h.lx"
                :y="h.ly"
                :text-anchor="h.anchor"
              >
                {{ h.label }}
              </text>
            </g>
            <g v-if="endLabels.length" class="end-labels" aria-hidden="true">
              <g v-for="l in endLabels" :key="`end${l.code}`">
                <circle
                  v-if="l.code === 'SW'"
                  :cx="l.x"
                  :cy="l.y"
                  r="3.6"
                  :fill="color(l.code)"
                />
                <rect
                  v-else
                  :x="l.x - 3.4"
                  :y="l.y - 3.4"
                  width="6.8"
                  height="6.8"
                  rx="1.6"
                  :fill="color(l.code)"
                />
                <text :x="l.x + 9" :y="l.y + 4">{{ materialName(l.code) }}</text>
              </g>
            </g>
            <g v-if="selLabel && !hoverPoint" class="sel-label" aria-hidden="true">
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
            <!-- 花园：竖向引导线，同一转数的点放大 -->
            <g v-if="hoverPoint" class="guide" aria-hidden="true">
              <line
                class="guide-l"
                :x1="hoverPoint.x"
                :x2="hoverPoint.x"
                :y1="margin.t"
                :y2="plotH - margin.b"
              />
              <g
                v-for="p in hotPoints"
                :key="`hot${p.code}`"
                :style="{ '--c': color(p.code) }"
              >
                <circle v-if="p.code === 'SW'" class="hot" :cx="p.x" :cy="p.y" r="6" />
                <rect
                  v-else
                  class="hot"
                  :x="p.x - 5.6"
                  :y="p.y - 5.6"
                  width="11.2"
                  height="11.2"
                  rx="2.5"
                />
              </g>
              <circle
                class="guide-focus"
                :cx="hoverPoint.x"
                :cy="hoverPoint.y"
                r="12"
              />
            </g>
            <!-- 偏光：显微镜 HUD 十字准星，读数钉在两条坐标轴上 -->
            <g v-if="hoverPoint && hud" class="hud" aria-hidden="true">
              <line
                class="hud-l"
                :x1="hoverPoint.x"
                :x2="hoverPoint.x"
                :y1="margin.t"
                :y2="hud.base"
              />
              <line
                class="hud-l"
                :x1="margin.l"
                :x2="plotWidth - margin.r"
                :y1="hoverPoint.y"
                :y2="hoverPoint.y"
              />
              <path
                class="hud-tk"
                :d="`M${hoverPoint.x - 6},${hoverPoint.y}h12M${hoverPoint.x},${hoverPoint.y - 6}v12`"
              />
              <circle
                class="hud-ring"
                :cx="hoverPoint.x"
                :cy="hoverPoint.y"
                r="9"
              />
              <rect
                class="hud-box"
                :x="hud.cx - hud.xw / 2"
                :y="hud.base + 4"
                :width="hud.xw"
                height="17"
                rx="3"
              />
              <text
                class="hud-t"
                :x="hud.cx"
                :y="hud.base + 16.5"
                text-anchor="middle"
              >
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
            class="beating-tip"
            :class="{ on: tip, left: tip?.left, below: tip?.below }"
            :style="tip?.style"
            role="status"
            aria-live="polite"
          >
            <template v-if="hoverPoint">
              <div class="tip-head">
                <b>{{ number(hoverPoint.row.beating_revolutions) }} r</b
                ><span>{{ hoverPoint.row.canonical_code }}</span>
              </div>
              <div v-for="c in cursorRows" :key="c.code" class="tip-row">
                <span
                  ><i class="mk" :class="`mk-${c.code}`"></i
                  >{{ materialName(c.code) }}</span
                ><b>{{
                  c.value === null
                    ? "该转数无实测"
                    : `${c.estimated ? "≈ " : ""}${fmt(c.value)}`
                }}</b>
              </div>
              <div class="tip-foot">
                {{ metric.name }} / {{ unit
                }}<template v-if="cursorRows.some((c) => c.estimated)">
                  · ≈ 为相邻实测点插值</template
                >
              </div>
            </template>
          </div>
        </div>
        <p class="beating-hint">
          移到曲线上逐个转数读数；点击或用 Tab 选中数据点，方向键切换，Enter
          打开样本来源。
        </p>
        <p class="caveat beating-note">
          线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。<template
            v-if="isSr"
            >“达到目标”的转数是相邻两个实测点之间的线性插值估算。</template
          >
        </p>
      </section>

      <section class="card beating-readout" aria-labelledby="beating-readout-title">
        <div class="readout-head">
          <h2 id="beating-readout-title">样本读数</h2>
          <span v-if="selected" class="readout-pos"
            >{{ selectedIndex + 1 }} / {{ listed.length }}</span
          >
        </div>
        <div v-if="selected" class="readout-body">
          <div class="readout-id">
            <div class="readout-code">{{ selected.canonical_code }}</div>
            <div class="readout-name-row">
              <span class="readout-name">{{ selected.display_name }}</span>
              <span class="type-tag" :class="typeOf(selected.material_code)"
                ><i></i>{{ materialName(selected.material_code) }}</span
              >
            </div>
          </div>
          <div class="readout-big">
            <div class="readout-cell">
              <span class="readout-k">{{ metric.name }}</span>
              <p class="readout-num">
                <strong>{{ fmt(value(selected)) }}</strong
                ><small>{{ unit }}</small>
              </p>
            </div>
            <div class="readout-cell">
              <span class="readout-k">打浆转数</span>
              <p class="readout-num sm">
                <strong>{{ number(selected.beating_revolutions) }}</strong
                ><small>r</small>
              </p>
            </div>
          </div>
          <div class="readout-block readout-prog">
            <div class="block-head">
              <span>打浆进程</span
              ><span class="mono"
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
              ></i
              ><b
                v-if="selectedReachPct !== null"
                :style="{ left: `${selectedReachPct}%` }"
                :title="`${materialName(selected.material_code)}达到目标的转数`"
              ></b>
            </div>
          </div>
          <div v-if="toTarget" class="readout-block readout-target">
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
          <div v-if="otherAtSameRevs" class="readout-block readout-cmp">
            <div class="block-head">
              <span>同转数下另一种原料</span
              ><span class="mono">{{ number(selected.beating_revolutions) }} r</span>
            </div>
            <div class="compare-row me">
              <span
                ><i class="mk" :class="`mk-${selected.material_code}`"></i
                >{{ materialName(selected.material_code) }}</span
              >
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
              <span
                ><i class="mk" :class="`mk-${otherAtSameRevs.code}`"></i
                >{{ materialName(otherAtSameRevs.code) }}</span
              >
              <div class="track">
                <i
                  :style="{
                    width: `${valueBar(otherAtSameRevs.value)}%`,
                    background: color(otherAtSameRevs.code),
                  }"
                ></i>
              </div>
              <b
                >{{ otherAtSameRevs.estimated ? "≈" : ""
                }}{{ fmt(otherAtSameRevs.value) }}</b
              >
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
              class="button primary readout-open"
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

      <section class="card beating-table" aria-labelledby="beating-table-title">
        <div class="beating-table-head">
          <div>
            <h2 id="beating-table-title">
              实验明细 <span class="quiet-tag">{{ listed.length }}</span>
            </h2>
            <p>
              按原料分组、打浆转数升序；“—”表示缺失；“≈”表示另一种原料在该转数无实测、按插值比较。
            </p>
          </div>
          <div class="table-actions">
            <span class="checked-n">已勾选 {{ checked.size }}</span>
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
              <tr
                v-if="listedBy(code).length"
                class="group-row"
                :class="`group-${code}`"
              >
                <td colspan="6">
                  <i class="mk" :class="`mk-${code}`"></i
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
                        rx="1.5"
                        :fill="color(code)"
                      /></svg
                  ></template>
                  <span v-else class="delta-none">—</span>
                </td>
                <td>
                  <button
                    class="text-button detail-link"
                    @click.stop="openDetail(r)"
                  >
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
/* ================================================================ page grid
   DOM order: header · controls · (unit note) · KPI · chart · readout · table.
   Dense auto-flow pairs the side panels with their neighbours per mode:
   polarized (v1) chart | readout, garden (v4) chart | KPI tile and table | readout. */
.beating-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  grid-auto-flow: row dense;
  gap: 18px;
  align-items: start;
}
.beating-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.beating-page > .page-header {
  margin-bottom: 0;
}
.beating-page > .beating-chart {
  grid-column: 1;
}
.beating-page > .beating-readout {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}
:root[data-mode="garden"] .beating-page > .beating-kpis {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page > .beating-chart {
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page > .beating-table {
  grid-column: 1;
}

.nw {
  white-space: nowrap;
}
/* material marker: softwood circle, hardwood 2px square */
.mk {
  display: inline-block;
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--sw);
}
.mk.mk-HW {
  border-radius: 2px;
  background: var(--hw);
  transform: scale(0.92);
}

/* ================================================================ states */
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.beating-state p {
  margin: 14px 0;
}
.beating-status {
  display: grid;
  justify-items: center;
  gap: 4px;
}
.unit-note {
  font-size: 12.5px;
  color: var(--warn);
  margin: -6px 0 -4px;
}

/* ================================================================ controls */
.beating-controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 18px 28px;
  padding: 18px 22px;
  position: relative;
  z-index: 3;
}
.ctl {
  min-width: 0;
}
.beating-seg > button {
  gap: 8px;
}
.beating-seg > button.on .cnt {
  color: var(--text-2);
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
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
.beating-count .sep {
  margin: 0 10px;
  color: var(--text-3);
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
.range-head .field-label {
  margin-bottom: 4px;
}
.range-val {
  font: 500 13px var(--font-mono);
  color: var(--text);
}
.range-val small {
  margin-left: 3px;
  font-size: 11px;
  color: var(--text-3);
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
  border-radius: 1px 1px 0 0;
  background: var(--text-3);
  transition: opacity 0.2s;
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
  background: var(--line-strong);
}
.dual-track i {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--accent);
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
  background: var(--accent);
  cursor: ew-resize;
}
.dual-range input::-moz-range-thumb {
  pointer-events: auto;
  width: 8px;
  height: 18px;
  border: 0;
  border-radius: 1px;
  background: var(--accent);
  cursor: ew-resize;
}
.dual-range input:focus-visible {
  outline: none;
}
.dual-range input:focus-visible::-webkit-slider-thumb {
  outline: 2.5px solid var(--focus);
  outline-offset: 2px;
}
.dual-range input:focus-visible::-moz-range-thumb {
  outline: 2.5px solid var(--focus);
  outline-offset: 2px;
}
.ruler-labels {
  display: flex;
  justify-content: space-between;
  font: 400 10.5px var(--font-mono);
  color: var(--text-3);
}

/* ================================================================ KPI · target strip / reach tile */
.beating-kpis {
  display: grid;
  grid-template-columns: 1fr 1fr 0.8fr;
  padding: 0;
}
.beating-kpis.is-sr {
  grid-template-columns: 1.15fr 1fr 1fr 1fr;
}
.kpi {
  position: relative;
  min-width: 0;
  padding: 20px 22px;
  transition: opacity 0.15s;
}
/* the material the filter leaves out: numbers step back to --text-2 (still ≥4.5:1),
   marker and track fade */
.kpi.dim .kpi-value,
.kpi.dim .kpi-value strong {
  color: var(--text-2);
}
.kpi.dim .mk,
.kpi.dim .kpi-track {
  opacity: 0.35;
}
.kpi-label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 6px;
  font-size: 12.5px;
  color: var(--text-2);
}
.kpi-label .mk {
  margin-right: 2px;
}
.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 8px 0 10px;
  min-height: 46px;
  color: var(--text);
}
.kpi-value strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.05;
  white-space: nowrap;
}
.kpi-value strong.na {
  font-family: var(--font-body);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-2);
}
.kpi-value small {
  font-size: 13px;
  color: var(--text-2);
}
.kpi-value .delta {
  margin-left: 6px;
  font: 500 13px var(--font-mono);
  color: var(--text-2);
}
.kpi-note {
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
}
.kpi-target-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.kpi-target-row .kpi-value {
  margin: 4px 0 6px;
}
.step-btn {
  width: 34px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  color: var(--text);
  transition:
    background 0.15s,
    border-color 0.15s,
    transform 0.3s var(--spring);
}
.step-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--text-3);
}
.beating-range {
  display: block;
  width: 100%;
  height: 24px;
  border-radius: 999px;
  margin: 2px 0 2px;
  background: transparent;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
}
.beating-range::-webkit-slider-runnable-track {
  height: 3px;
  border-radius: 2px;
  background: var(--line-strong);
}
.beating-range::-moz-range-track {
  height: 3px;
  border-radius: 2px;
  background: var(--line-strong);
}
.beating-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin-top: -6.5px;
  border-radius: 50%;
  background: var(--text);
}
.beating-range::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: var(--text);
}
.kpi-track {
  position: relative;
  height: 3px;
  margin: 8px 0 6px;
  border-radius: 2px;
  background: var(--line);
}
.kpi-track i {
  position: absolute;
  top: -4px;
  left: var(--at);
  width: 3px;
  height: 11px;
  border-radius: 2px;
  transform: translateX(-1px);
  transition:
    left 0.3s var(--ease),
    width 0.8s var(--ease);
}
.kpi-SW .kpi-track i {
  background: var(--sw);
}
.kpi-HW .kpi-track i {
  background: var(--hw);
}
.kpi-reach-h,
.kpi-scale {
  display: none;
}

/* ================================================================ chart card */
.beating-chart {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "head" "plot" "legend" "hint" "note";
  align-content: start;
  padding: 22px;
}
.beating-chart-head {
  grid-area: head;
  margin-bottom: 14px;
}
.beating-chart-head h2 {
  font-size: 17px;
}
.beating-chart-head p {
  font-size: 13px;
  color: var(--text-2);
  margin-top: 6px;
}
.beating-legend {
  grid-area: legend;
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
  font-size: 12.5px;
  color: var(--text-2);
}
.beating-legend li {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.legend-title {
  color: var(--text-3);
  font-size: 11px;
}
.target-key {
  stroke: var(--chart-target);
  stroke-width: 1.4;
  stroke-dasharray: 3 3;
}
.plot-box,
.beating-plot-state {
  grid-area: plot;
}
.plot-box {
  position: relative;
  width: 100%;
  min-width: 0;
  /* the svg is sized from this box; clip a resize frame instead of scrolling the page */
  overflow-x: clip;
}
.beating-plot {
  display: block;
  touch-action: pan-y;
}
.beating-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--chart-text);
}
.beating-plot .axis-title {
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
.line {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.mark {
  fill: var(--c);
  stroke: var(--chart-paper);
  stroke-width: 2;
  paint-order: stroke;
}
.hit {
  fill: transparent;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.plot-point:focus-visible .hit {
  stroke: var(--focus);
  stroke-width: 2.5;
}
.plot-point.out .mark {
  opacity: 0.25;
}
.ring {
  fill: none;
  stroke: var(--text);
  stroke-width: 1.5;
  stroke-dasharray: 2 3;
}
.target line {
  stroke: var(--chart-target);
  stroke-width: 1;
  stroke-dasharray: 4 5;
}
.beating-plot .target-t {
  fill: var(--text);
}
.reach-drop {
  stroke: var(--c);
  stroke-width: 1.3;
  stroke-dasharray: 2 4;
  opacity: 0.7;
}
.reach-dia {
  fill: var(--text);
}
.reach-ring {
  display: none;
  fill: var(--chart-paper);
  stroke: var(--c);
  stroke-width: 2.2;
}
.beating-plot .reach-t {
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--chart-paper);
  stroke-width: 4px;
  stroke-linejoin: round;
}
.beating-plot .end-labels text {
  font: 400 12.5px var(--font-body);
  fill: var(--text);
}
.sel-label rect {
  fill: var(--surface);
  stroke: var(--line-strong);
  rx: 3px;
}
.beating-plot .sel-label text {
  fill: var(--text);
  font-weight: 500;
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
.beating-plot .hud-t {
  font-size: 10.5px;
  fill: var(--text);
}
.guide-l {
  stroke: var(--chart-guide);
  stroke-dasharray: 3 4;
}
.hot {
  fill: var(--c);
  stroke: var(--chart-paper);
  stroke-width: 2.5;
}
.guide-focus {
  fill: none;
  stroke: var(--text);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}
/* floating tooltip (also the polite live region for the cursor readout) */
.beating-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 5;
  min-width: 168px;
  max-width: 240px;
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
.beating-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) - 100% - 12px));
}
.beating-tip.below {
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) + 16px));
}
.beating-tip.left.below {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) + 16px));
}
.beating-tip.on {
  opacity: 1;
}
.tip-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.tip-head b {
  font-weight: 500;
  font-size: 12px;
  color: var(--text);
}
.tip-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
}
.tip-row span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-2);
}
.tip-row b {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.tip-foot {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-3);
}
.beating-hint {
  grid-area: hint;
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--text-3);
}
.beating-note {
  grid-area: note;
  margin-top: 12px;
}

/* ================================================================ readout */
.beating-readout {
  padding: 22px;
  display: flex;
  flex-direction: column;
}
.readout-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.readout-head h2 {
  font-size: 17px;
}
.readout-pos {
  font: 400 13px var(--font-mono);
  color: var(--text-2);
}
.readout-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
  flex: 1;
}
.readout-code {
  font: 400 12px var(--font-mono);
  color: var(--text-2);
}
.readout-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  margin-top: 4px;
}
.readout-name {
  color: var(--text);
}
.readout-big {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.readout-k {
  font-size: 12px;
  color: var(--text-2);
}
.readout-num {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 2px;
  color: var(--text);
}
.readout-num strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.05;
  white-space: nowrap;
}
.readout-num small {
  font-size: 12px;
  color: var(--text-2);
}
.readout-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--text-2);
}
.block-head b {
  font-weight: 500;
  color: var(--text);
}
.track {
  position: relative;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.track i {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  transition: width 0.3s var(--ease);
}
.track b {
  position: absolute;
  top: -4px;
  width: 2px;
  height: 12px;
  margin-left: -1px;
  border-radius: 1px;
  background: var(--text);
}
.target-gap {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.target-gap div {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-wrap: wrap;
}
.target-gap strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 300;
  font-size: 26px;
  line-height: 1.1;
  color: var(--text);
}
.target-gap small {
  font-size: 12px;
  color: var(--text-2);
}
.target-gap span {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--text-2);
}
.compare-row {
  display: grid;
  grid-template-columns: 84px 1fr 56px;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-2);
}
.compare-row > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}
.compare-row b {
  font: 500 12.5px var(--font-mono);
  color: var(--text-2);
  text-align: right;
}
.compare-row.me,
.compare-row.me b {
  color: var(--text);
}
.compare-row:not(.me) .track i {
  opacity: 0.6;
}
.readout-actions {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.readout-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

/* ================================================================ table */
.beating-table {
  padding: 22px 22px 8px;
}
.beating-table-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 14px;
}
.beating-table-head h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
}
.beating-table-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-2);
}
.table-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: var(--text-2);
}
.check-cell {
  width: 40px;
  padding-right: 0;
}
.check {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--accent);
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
  stroke: var(--line-strong);
}
.delta-value {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.delta-none {
  color: var(--text-3);
}
.group-row td {
  height: 36px;
  padding-top: 6px;
  padding-bottom: 6px;
  color: var(--text);
  background: var(--surface-2);
}
.group-row td > * {
  vertical-align: middle;
}
.group-row .mk {
  margin-right: 9px;
}
.group-row strong {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.group-row span {
  margin-left: 10px;
  font: 400 12px var(--font-mono);
  color: var(--text-2);
}
tbody tr.on td {
  background: var(--accent-tint);
}
tbody tr.on td:first-child {
  box-shadow: inset 2px 0 0 var(--accent);
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
  min-width: 80px;
  max-width: 240px;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.value-bar i {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  opacity: 0.9;
}
.value-bar b {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 1px;
  background: var(--text-2);
}

/* ================================================================ polarized (v1 「偏光」) */
:root[data-mode="polarized"] .beating-controls .field-label {
  margin-bottom: 8px;
}
:root[data-mode="polarized"] .range-head .field-label {
  margin-bottom: 4px;
}
/* histogram: consecutive slices of one interference band */
:root[data-mode="polarized"] .hist i {
  background: var(--ifl);
  background-size: var(--bs);
  background-position: var(--bp);
  opacity: 0.85;
}
:root[data-mode="polarized"] .hist i.out {
  opacity: 0.22;
}
:root[data-mode="polarized"] .dual-track i {
  background: var(--ifl);
}
:root[data-mode="polarized"] .dual-range input::-webkit-slider-thumb {
  background: var(--text);
  box-shadow: 0 0 10px var(--accent-tint);
}
:root[data-mode="polarized"] .dual-range input::-moz-range-thumb {
  background: var(--text);
}
/* target strip: one dark card, four cells with hairline dividers */
:root[data-mode="polarized"] .kpi:not(:first-child) {
  border-left: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .kpi-label {
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .kpi-value strong {
  font-weight: 200;
  font-size: 46px;
  letter-spacing: -0.04em;
}
:root[data-mode="polarized"] .kpi-value strong.na {
  font-weight: 700;
  font-size: 22px;
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .kpi-value small {
  font-size: 13px;
}
:root[data-mode="polarized"] .kpi-target-row .kpi-value {
  min-width: 0;
}
/* interference track, white thumb with a halo (v1 .range) */
:root[data-mode="polarized"] .beating-range::-webkit-slider-runnable-track {
  background: var(--ifl);
  opacity: 0.9;
}
:root[data-mode="polarized"] .beating-range::-moz-range-track {
  background: var(--ifl);
}
:root[data-mode="polarized"] .beating-range::-webkit-slider-thumb {
  box-shadow:
    0 0 0 4px var(--bg),
    0 0 16px var(--text-3);
}
:root[data-mode="polarized"] .beating-range::-moz-range-thumb {
  box-shadow:
    0 0 0 4px var(--bg),
    0 0 16px var(--text-3);
}
:root[data-mode="polarized"] .beating-range:focus-visible {
  outline-offset: 4px;
}
/* chart: HUD crosshair, white diamonds at the target crossings */
:root[data-mode="polarized"] .hud {
  display: inline;
}
:root[data-mode="polarized"] .line {
  opacity: 0.95;
}
:root[data-mode="polarized"] .beating-tip {
  border-radius: 12px;
  background: var(--surface-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
:root[data-mode="polarized"] .beating-legend {
  margin-top: 14px;
}
/* readout: v1 .reading — mono code, 22px / 900 name, Unbounded 200 numerals */
:root[data-mode="polarized"] .readout-name {
  display: block;
  width: 100%;
  font-size: 22px;
  font-weight: 900;
  line-height: 1.3;
}
:root[data-mode="polarized"] .readout-num strong {
  font-weight: 200;
  font-size: 40px;
  letter-spacing: -0.04em;
}
:root[data-mode="polarized"] .readout-num.sm strong {
  font-size: 30px;
  font-weight: 300;
}
:root[data-mode="polarized"] .readout-target {
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .target-gap strong {
  letter-spacing: -0.03em;
}
:root[data-mode="polarized"] .readout-cmp {
  padding: 12px;
  border-radius: 12px;
  background: var(--surface-2);
}
:root[data-mode="polarized"] .readout-open {
  width: 100%;
}
/* table: transparent group rows with a material marker, cyan selection rule */
:root[data-mode="polarized"] .group-row td {
  background: var(--surface-2);
}
:root[data-mode="polarized"] .group-row strong {
  font-weight: 500;
}

/* ================================================================ garden (v4 「纤维花园」) */
:root[data-mode="garden"] .beating-controls {
  padding: 22px 24px;
}
:root[data-mode="garden"] .beating-count {
  font-family: var(--font-body);
  font-size: 13px;
}
:root[data-mode="garden"] .hist i {
  border-radius: 4px 4px 1px 1px;
  background: var(--rc);
  opacity: 0.75;
}
:root[data-mode="garden"] .hist i.out {
  opacity: 0.22;
}
:root[data-mode="garden"] .dual-range {
  height: 22px;
}
:root[data-mode="garden"] .dual-track {
  top: 8px;
  height: 6px;
  border-radius: 999px;
  background: var(--accent-tint);
}
:root[data-mode="garden"] .dual-track i {
  border-radius: 999px;
  background: var(--accent);
}
:root[data-mode="garden"] .dual-range input::-webkit-slider-runnable-track {
  height: 22px;
}
:root[data-mode="garden"] .dual-range input::-moz-range-track {
  height: 22px;
}
:root[data-mode="garden"] .dual-range input::-webkit-slider-thumb {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow:
    inset 0 0 0 4px var(--accent),
    var(--shadow-sm);
}
:root[data-mode="garden"] .dual-range input::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow: inset 0 0 0 4px var(--accent);
}
/* reach tile (v4 .reach-pair): target, two tinted rows with big Fraunces numbers, difference */
:root[data-mode="garden"] .beating-kpis {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 22px 24px;
}
:root[data-mode="garden"] .kpi {
  padding: 0;
}
:root[data-mode="garden"] .kpi-value strong {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  line-height: 0.92;
}
:root[data-mode="garden"] .kpi-value strong.na {
  font-variation-settings: normal;
  font-weight: 500;
  font-size: 20px;
  letter-spacing: 0.02em;
}
:root[data-mode="garden"] .kpi-value small {
  font-size: 14px;
}
:root[data-mode="garden"] .kpi-target {
  padding-bottom: 6px;
}
:root[data-mode="garden"] .kpi-target-row {
  gap: 6px;
}
:root[data-mode="garden"] .kpi-target-row .kpi-value {
  order: -1;
  margin: 6px auto 4px 0;
  min-height: 0;
}
:root[data-mode="garden"] .kpi-target-row .kpi-value strong {
  font-size: 42px;
}
:root[data-mode="garden"] .step-btn {
  width: 32px;
  height: 32px;
  border: 0;
  background: var(--surface);
  box-shadow:
    inset 0 0 0 1px var(--line),
    var(--shadow-sm);
}
:root[data-mode="garden"] .step-btn:hover:not(:disabled) {
  background: var(--surface);
  transform: translateY(-1px);
}
:root[data-mode="garden"] .step-btn:active:not(:disabled) {
  transform: scale(0.94);
}
/* v4 .range: 8px pill track, white thumb with a plum ring */
:root[data-mode="garden"] .beating-range {
  height: 26px;
}
:root[data-mode="garden"] .beating-range::-webkit-slider-runnable-track {
  height: 8px;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--accent-tint), var(--rc));
}
:root[data-mode="garden"] .beating-range::-moz-range-track {
  height: 8px;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--accent-tint), var(--rc));
}
:root[data-mode="garden"] .beating-range::-webkit-slider-thumb {
  width: 24px;
  height: 24px;
  margin-top: -8px;
  background: var(--surface);
  box-shadow:
    var(--shadow-sm),
    inset 0 0 0 6px var(--text);
}
:root[data-mode="garden"] .beating-range::-moz-range-thumb {
  width: 22px;
  height: 22px;
  background: var(--surface);
  box-shadow: inset 0 0 0 6px var(--text);
}
:root[data-mode="garden"] .kpi-reach-h {
  display: block;
  margin-top: 6px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 15px;
  line-height: 1.35;
  color: var(--text);
}
:root[data-mode="garden"] .kpi-reach-h b {
  font-family: var(--font-mono);
  font-weight: 500;
}
:root[data-mode="garden"] .kpi-label-target,
:root[data-mode="garden"] .kpi-scale-row {
  display: none;
}
:root[data-mode="garden"] .kpi-mat {
  flex: 1;
  display: grid;
  align-content: center;
  gap: 6px;
  padding: 12px 16px 14px;
  border-radius: 18px;
  background: linear-gradient(150deg, var(--surface), var(--sw-tint));
}
:root[data-mode="garden"] .kpi-mat.kpi-HW {
  background: linear-gradient(150deg, var(--surface), var(--hw-tint));
}
:root[data-mode="garden"] .kpi-mat.dim {
  background: var(--surface-2);
}
:root[data-mode="garden"] .kpi-mat .kpi-label {
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .kpi-mat .kpi-value {
  margin: 2px 0 0;
}
:root[data-mode="garden"] .kpi-mat .kpi-value strong {
  font-size: 56px;
}
:root[data-mode="garden"] .kpi-mat.wide .kpi-value strong {
  font-size: 46px;
}
:root[data-mode="garden"] .kpi-track {
  height: 10px;
  margin: 4px 0 2px;
  border-radius: 9px;
  background: var(--line-soft);
  overflow: hidden;
}
:root[data-mode="garden"] .kpi-track i {
  top: 0;
  bottom: 0;
  left: 0;
  height: auto;
  width: var(--at);
  border-radius: 9px;
  transform: none;
}
:root[data-mode="garden"] .kpi-scale {
  display: flex;
  font-size: 11px;
  color: var(--text-2);
}
:root[data-mode="garden"] .kpi-diff,
:root[data-mode="garden"] .kpi-valid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 4px 10px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
:root[data-mode="garden"] .kpi-diff .kpi-label,
:root[data-mode="garden"] .kpi-valid .kpi-label {
  font-size: 13.5px;
}
:root[data-mode="garden"] .kpi-diff .kpi-value,
:root[data-mode="garden"] .kpi-valid .kpi-value {
  margin: 0;
  min-height: 0;
}
:root[data-mode="garden"] .kpi-diff .kpi-value strong,
:root[data-mode="garden"] .kpi-valid .kpi-value strong {
  font-size: 40px;
  color: var(--accent-ink);
}
:root[data-mode="garden"] .kpi-diff .kpi-note,
:root[data-mode="garden"] .kpi-valid .kpi-note {
  grid-column: 1 / -1;
}
/* chart tile: legend top right, soft lines, white-ringed markers, direct labels */
:root[data-mode="garden"] .beating-chart {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto auto 1fr;
  grid-template-areas: "head legend" "plot plot" "hint hint" "note note";
  padding: 22px 24px;
}
:root[data-mode="garden"] .beating-chart .beating-note {
  align-self: end;
}
:root[data-mode="garden"] .beating-chart-head h2 {
  font-size: 19px;
}
:root[data-mode="garden"] .beating-legend {
  margin: 4px 0 0;
  align-self: start;
  justify-content: flex-end;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .legend-title {
  color: var(--text-2);
}
:root[data-mode="garden"] .beating-plot .axis-title {
  font-size: 11.5px;
  fill: var(--text-2);
}
:root[data-mode="garden"] .line {
  stroke-width: 2.2;
}
:root[data-mode="garden"] .ring {
  stroke: var(--c);
  stroke-width: 2;
  stroke-dasharray: 3 3;
}
:root[data-mode="garden"] .target line,
:root[data-mode="garden"] .target-key {
  stroke-width: 1.4;
  stroke-dasharray: 6 5;
}
:root[data-mode="garden"] .beating-plot .target-t {
  font: 400 12px var(--font-body);
}
:root[data-mode="garden"] .reach-drop {
  stroke-width: 1.4;
  opacity: 1;
}
:root[data-mode="garden"] .reach-dia {
  display: none;
}
:root[data-mode="garden"] .reach-ring {
  display: inline;
}
:root[data-mode="garden"] .beating-plot .reach-t {
  font-size: 11.5px;
}
:root[data-mode="garden"] .sel-label rect {
  fill: var(--chart-paper);
  stroke: var(--accent);
  rx: 10px;
}
:root[data-mode="garden"] .beating-plot .sel-label text {
  fill: var(--accent-ink);
}
:root[data-mode="garden"] .guide {
  display: inline;
}
:root[data-mode="garden"] .beating-tip {
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
:root[data-mode="garden"] .tip-head {
  font-family: var(--font-body);
}
:root[data-mode="garden"] .tip-head b {
  font-family: var(--font-mono);
}
:root[data-mode="garden"] .beating-hint {
  color: var(--text-2);
  font-size: 13px;
}
:root[data-mode="garden"] .beating-note {
  margin-top: 10px;
}
/* reading tile (v4 .reading): mono code, big Fraunces value, inset glass cells */
:root[data-mode="garden"] .beating-readout {
  padding: 22px 24px;
}
:root[data-mode="garden"] .readout-head {
  justify-content: space-between;
}
:root[data-mode="garden"] .readout-head h2 {
  font-size: 18px;
}
:root[data-mode="garden"] .readout-code {
  font-size: 20px;
  color: var(--text);
}
:root[data-mode="garden"] .readout-name {
  font-size: 14px;
}
:root[data-mode="garden"] .readout-num strong {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  font-size: 60px;
  line-height: 0.95;
}
:root[data-mode="garden"] .readout-num small {
  font-size: 14px;
}
:root[data-mode="garden"] .readout-num.sm strong {
  font-family: var(--font-mono);
  font-variation-settings: normal;
  font-weight: 400;
  font-size: 22px;
  letter-spacing: 0;
}
:root[data-mode="garden"] .readout-big {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
}
:root[data-mode="garden"] .readout-prog,
:root[data-mode="garden"] .target-gap > div {
  padding: 12px 14px;
  border-radius: 18px;
  background: var(--surface-2);
}
:root[data-mode="garden"] .readout-target {
  gap: 10px;
}
:root[data-mode="garden"] .target-gap strong {
  font-family: var(--font-mono);
  font-weight: 400;
  font-size: 18px;
}
:root[data-mode="garden"] .track {
  height: 8px;
  border-radius: 9px;
}
:root[data-mode="garden"] .compare-row .track {
  height: 10px;
  background: var(--line-soft);
}
:root[data-mode="garden"] .compare-row {
  grid-template-columns: 92px 1fr 64px;
  font-size: 13px;
}
:root[data-mode="garden"] .readout-actions {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
}
:root[data-mode="garden"] .readout-nav {
  display: flex;
  gap: 8px;
}
:root[data-mode="garden"] .readout-actions .button {
  min-height: 34px;
  padding: 0 14px;
  font-size: 13px;
}
/* table tile: rounded glass well, tinted group rows, small pill actions */
:root[data-mode="garden"] .beating-table {
  padding: 22px 24px 24px;
}
:root[data-mode="garden"] .beating-table-head h2 {
  font-size: 19px;
}
:root[data-mode="garden"] .beating-table .table-scroll {
  max-height: 560px;
  border-radius: 18px;
  background: var(--surface-glass);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}
:root[data-mode="garden"] .group-row td {
  background: linear-gradient(90deg, var(--sw-tint), var(--surface) 70%);
}
:root[data-mode="garden"] .group-HW td {
  background: linear-gradient(90deg, var(--hw-tint), var(--surface) 70%);
}
:root[data-mode="garden"] .group-row strong {
  font-weight: 500;
}
:root[data-mode="garden"] tbody tr.on td {
  background: var(--bl-tint);
}
:root[data-mode="garden"] tbody tr.on td:first-child {
  box-shadow: inset 3px 0 0 var(--bl);
}
:root[data-mode="garden"] .detail-link {
  padding: 4px 11px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  background: var(--surface);
  box-shadow:
    inset 0 0 0 1px var(--line),
    var(--shadow-sm);
}
:root[data-mode="garden"] .detail-link:hover {
  text-decoration: none;
  color: var(--accent-ink);
}

/* ================================================================ responsive */
@media (max-width: 1280px) {
  .beating-page {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
}
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .beating-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="polarized"] .beating-page > *,
  :root[data-mode="polarized"] .beating-page > .beating-readout {
    grid-column: 1 / -1;
  }
  :root[data-mode="polarized"] .beating-kpis.is-sr {
    grid-template-columns: 1fr 1fr;
  }
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-target,
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-HW {
    border-left: 0;
  }
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-target,
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-SW {
    border-bottom: 1px solid var(--line-soft);
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .beating-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .beating-page > *,
  :root[data-mode="garden"] .beating-page > .beating-kpis,
  :root[data-mode="garden"] .beating-page > .beating-table {
    grid-column: 1 / -1;
  }
  :root[data-mode="garden"] .beating-table .table-scroll {
    max-height: none;
  }
}
@media (max-width: 720px) {
  .beating-page {
    gap: 14px;
  }
  .beating-controls {
    gap: 14px;
    padding: 16px;
  }
  .beating-controls > .ctl,
  .range-group {
    width: 100%;
  }
  .count-group {
    margin-left: 0;
    width: 100%;
    align-items: flex-start;
  }
  .beating-chart,
  .beating-readout,
  .beating-table {
    padding: 16px;
  }
  .table-actions .checked-n {
    display: none;
  }
  .value-bar {
    display: none;
  }
  :root[data-mode="polarized"] .beating-kpis,
  :root[data-mode="polarized"] .beating-kpis.is-sr {
    grid-template-columns: 1fr 1fr;
  }
  :root[data-mode="polarized"] .kpi {
    padding: 16px 14px;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi {
    border-left: 0;
    border-bottom: 0;
    border-top: 1px solid var(--line-soft);
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi:first-child {
    border-top: 0;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi-target,
  :root[data-mode="polarized"] .beating-kpis .kpi-diff,
  :root[data-mode="polarized"] .beating-kpis .kpi-valid {
    grid-column: 1 / -1;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi-HW {
    border-left: 1px solid var(--line-soft);
  }
  :root[data-mode="polarized"] .kpi-value strong {
    font-size: 32px;
  }
  :root[data-mode="polarized"] .kpi-target .kpi-value strong {
    font-size: 46px;
  }
  :root[data-mode="polarized"] .readout-num strong {
    font-size: 34px;
  }
  :root[data-mode="polarized"] .readout-num.sm strong {
    font-size: 28px;
  }
  :root[data-mode="garden"] .beating-kpis,
  :root[data-mode="garden"] .beating-controls {
    padding: 18px;
  }
  :root[data-mode="garden"] .beating-chart {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "head" "legend" "plot" "hint" "note";
  }
  :root[data-mode="garden"] .beating-legend {
    justify-content: flex-start;
    margin-bottom: 8px;
  }
  :root[data-mode="garden"] .kpi-mat .kpi-value strong {
    font-size: 44px;
  }
  :root[data-mode="garden"] .beating-seg > button {
    padding: 0 10px;
  }
  :root[data-mode="garden"] .readout-num strong {
    font-size: 50px;
  }
}
</style>
