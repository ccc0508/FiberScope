<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { FileSpreadsheet, Info, RefreshCw, TriangleAlert, X } from "lucide-vue-next";
import { get, number, type Metadata, type ListResult } from "../api";
import { niceTicks } from "../beating";
import { isGarden } from "../mode";
import { vTilt } from "../motion";
import FilterSelect from "../components/FilterSelect.vue";
import PageHeader from "../components/PageHeader.vue";

/*
 * 再生纸浆循环：一个模板服务两种显示模式。
 *  偏光（v1）：「玻片托盘」选数据块（每片一条相对首次循环的变化折线）→ 单卡信息条
 *              → 循环趋势（HUD 准星）| 长度分布（每个循环一种线型与标记）→ 明细表
 *  花园（v4）：数据块按钮格（循环圆点）→ 三块信息瓦片 → 循环趋势（面积）| 长度分布（分组柱）→ 明细表
 * 循环颜色只按循环序号取同一色阶（.cyc-0 … .cyc-3），两种模式各自定义色阶。
 */
interface Cycle {
  block_code: string;
  cycle_no: number;
  replicate_count: number;
  [key: string]: string | number | null;
}
interface Observation extends Cycle {
  replicate_no: number;
  file_name: string;
  sheet_name: string;
  source_row: number;
}
type Shape = "circle" | "square" | "triangle" | "diamond";
const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null),
  rows = ref<Cycle[]>([]),
  originals = ref<Observation[]>([]);
const loading = ref(true),
  error = ref(""),
  focused = ref<Cycle | null>(null),
  selected = ref<Cycle | null>(null);
const dialog = ref<HTMLDialogElement>();
const showRaw = ref(true);
const metrics = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("recycled")) ??
    [],
);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ??
    metrics.value.find((i) => i.key === "fiber_length_weighted_mm") ??
    metrics.value[0],
);
const blocks = computed(() =>
  [...(metadata.value?.blocks ?? [])].sort(
    (a, b) => a.block_order - b.block_order,
  ),
);
const block = computed(
  () =>
    blocks.value.find((b) => b.block_code === route.query.block) ??
    blocks.value[0],
);
const byBlock = computed(() => {
  const map = new Map<string, Cycle[]>();
  for (const r of rows.value) {
    const list = map.get(r.block_code);
    if (list) list.push(r);
    else map.set(r.block_code, [r]);
  }
  for (const list of map.values()) list.sort((a, b) => a.cycle_no - b.cycle_no);
  return map;
});
const visible = computed(() => byBlock.value.get(block.value?.block_code ?? "") ?? []);
const obsOf = (b: string, c: number) =>
  originals.value
    .filter((r) => r.block_code === b && r.cycle_no === c)
    .sort((a, b) => a.replicate_no - b.replicate_no);
const details = computed(() =>
  selected.value ? obsOf(selected.value.block_code, selected.value.cycle_no) : [],
);
const total = computed(() =>
  visible.value.reduce((sum, r) => sum + r.replicate_count, 0),
);
const numeric = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const value = (r: Cycle) => (metric.value ? numeric(r[metric.value.key]) : null);
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const unit = computed(() => metric.value?.unit ?? "单位未确认");
// 紧凑读数（标签、准星）：按量级取位数；表格、提示与抽屉沿用原有 3 / 4 位
const digits = computed(() => {
  const m = Math.max(0, ...valid.value.map((r) => Math.abs(value(r)!)));
  return m >= 100 ? 1 : m >= 10 ? 2 : 3;
});
const short = (v: number | null) => number(v, digits.value);

/* ---------- 循环色阶：按全库循环序号映射到 4 档 ---------- */
const cycleSpan = computed(() => {
  const c = rows.value.map((r) => r.cycle_no);
  return c.length ? [Math.min(...c), Math.max(...c)] : [1, 1];
});
const slot = (cycle: number) => {
  const [lo, hi] = cycleSpan.value as [number, number];
  return hi <= lo ? 3 : Math.round(((cycle - lo) / (hi - lo)) * 3);
};
const cyc = (cycle: number) => `cyc-${slot(cycle)}`;
const SHAPES: Shape[] = ["circle", "square", "triangle", "diamond"];
function shapePath(shape: Shape, x: number, y: number, r: number) {
  const f = (n: number) => n.toFixed(2);
  if (shape === "square") {
    const s = r * 0.9;
    return `M${f(x - s)},${f(y - s)}h${f(2 * s)}v${f(2 * s)}h${f(-2 * s)}Z`;
  }
  if (shape === "triangle")
    return `M${f(x)},${f(y - r * 1.2)}L${f(x + r * 1.12)},${f(y + r * 0.8)}L${f(x - r * 1.12)},${f(y + r * 0.8)}Z`;
  if (shape === "diamond")
    return `M${f(x)},${f(y - r * 1.3)}L${f(x + r * 1.1)},${f(y)}L${f(x)},${f(y + r * 1.3)}L${f(x - r * 1.1)},${f(y)}Z`;
  return `M${f(x - r)},${f(y)}a${f(r)},${f(r)} 0 1 0 ${f(2 * r)},0a${f(r)},${f(r)} 0 1 0 ${f(-2 * r)},0Z`;
}

/* ---------- 长度分布待复核：原始观测的长度区间合计偏离 100%（数据自带 QC 标记） ---------- */
const isReview = (r: Observation) => {
  const qc = r.length_distribution_qc;
  return typeof qc === "string" && qc !== "PASS";
};
const reviewCount = computed(() => originals.value.filter(isReview).length);
const reviewCycles = computed(() => {
  const set = new Set<string>();
  for (const r of originals.value)
    if (isReview(r)) set.add(`${r.block_code}#${r.cycle_no}`);
  return set;
});
const hasReview = (r: Cycle) => reviewCycles.value.has(`${r.block_code}#${r.cycle_no}`);
const blockReview = computed(() => visible.value.filter(hasReview).map((r) => r.cycle_no));

/* ---------- 玻片托盘 / 数据块按钮 ---------- */
const tray = computed(() => {
  const key = metric.value?.key;
  const val = (c: Cycle) => (key ? numeric(c[key]) : null);
  const firstOf = (cs: Cycle[]) => cs.map(val).find((v) => v !== null) ?? null;
  // 所有玻片共用同一纵向比例：相对首次循环的最大变化
  let R = 0.01;
  for (const cs of byBlock.value.values()) {
    const f = firstOf(cs);
    if (!f) continue;
    for (const c of cs) {
      const v = val(c);
      if (v !== null) R = Math.max(R, Math.abs((v - f) / f));
    }
  }
  const means = blocks.value.map((b) => {
    const v = (byBlock.value.get(b.block_code) ?? [])
      .map(val)
      .filter((x): x is number => x !== null);
    return v.length ? v.reduce((a, x) => a + x, 0) / v.length : null;
  });
  const known = means.filter((m): m is number => m !== null);
  const mlo = Math.min(...known),
    mhi = Math.max(...known);
  return blocks.value.map((b, i) => {
    const cs = byBlock.value.get(b.block_code) ?? [];
    const n = cs.length,
      f0 = firstOf(cs);
    const X = (k: number) => 5 + (n <= 1 ? 27 : (k * 54) / (n - 1));
    const Y = (v: number) => 14 - ((v - (f0 ?? 0)) / Math.abs(f0 || 1) / R) * 11;
    let d = "",
      pen = false;
    const dots: { x: number; y: number }[] = [];
    cs.forEach((c, k) => {
      const v = val(c);
      if (v === null || f0 === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${X(k).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
      dots.push({ x: X(k), y: Y(v) });
    });
    const vals = cs.map(val).filter((v): v is number => v !== null);
    const first = vals[0],
      last = vals[vals.length - 1];
    const delta =
      vals.length > 1 && first ? ((last! - first) / Math.abs(first)) * 100 : null;
    const m = means[i];
    return {
      b,
      cycles: cs,
      n,
      obs: cs.reduce((s, c) => s + c.replicate_count, 0),
      d,
      dots,
      delta,
      deltaText:
        delta === null
          ? "Δ —"
          : `Δ ${delta >= 0 ? "+" : "−"}${number(Math.abs(delta), 1)}%`,
      lvl: m === null || m === undefined ? 0 : (m - mlo) / (mhi - mlo || 1),
    };
  });
});
const slideLabel = (t: (typeof tray.value)[number]) =>
  `${t.b.block_code} · ${t.b.block_name}，原料${t.b.raw_material_grade ?? "未记录"}，${t.n} 个循环，${t.obs} 条原始观测${
    t.delta === null
      ? ""
      : `，${metric.value?.name ?? ""}末次较首次${t.delta >= 0 ? "增加" : "减少"} ${number(Math.abs(t.delta), 1)}%`
  }`;
function blockKey(e: KeyboardEvent, i: number) {
  const list = blocks.value;
  let n = -1;
  if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % list.length;
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
    n = (i - 1 + list.length) % list.length;
  else if (e.key === "Home") n = 0;
  else if (e.key === "End") n = list.length - 1;
  else return;
  e.preventDefault();
  update("block", list[n]!.block_code);
  (e.currentTarget as HTMLElement).parentElement
    ?.querySelectorAll<HTMLButtonElement>(":scope > button")
    [n]?.focus();
}

/* ---------- 图表尺寸：按容器实际宽度绘制 ---------- */
const trendBox = ref<HTMLElement>(),
  distBox = ref<HTMLElement>();
const trendSvg = ref<SVGSVGElement>();
const trendW = ref(600),
  distW = ref(520);
let sizeObserver: ResizeObserver | undefined;
onMounted(() => {
  sizeObserver = new ResizeObserver((entries) => {
    for (const e of entries) {
      const w = Math.max(260, Math.round(e.contentRect.width));
      if (e.target === trendBox.value) trendW.value = w;
      else if (e.target === distBox.value) distW.value = w;
    }
  });
  for (const box of [trendBox, distBox])
    watch(
      box,
      (el, old) => {
        if (old) sizeObserver?.unobserve(old);
        if (el) sizeObserver?.observe(el);
      },
      { immediate: true },
    );
});
const tickDigits = (ticks: number[]) => {
  const step = Math.abs((ticks[1] ?? 1) - (ticks[0] ?? 0)) || 1;
  for (let d = 0; d < 6; d++)
    if (Math.abs(step * 10 ** d - Math.round(step * 10 ** d)) < 1e-6) return d;
  return 6;
};
const textWidth = (s: string) =>
  [...s].reduce((w, ch) => w + (/[　-鿿＀-￯]/.test(ch) ? 10.5 : 6.4), 0);

/* ---------- 循环趋势：平均值折线 + 原始观测散点 ---------- */
const tNarrow = computed(() => trendW.value < 480);
const tH = computed(() => (tNarrow.value ? 280 : 330));
const tm = computed(() => ({
  t: 38,
  r: tNarrow.value ? 12 : 26,
  b: 48,
  l: tNarrow.value ? 50 : 62,
}));
const tRight = computed(() => trendW.value - tm.value.r);
const tBottom = computed(() => tH.value - tm.value.b);
const rawPoints = computed(() => {
  if (!metric.value || !block.value) return [];
  const key = metric.value.key;
  return visible.value.flatMap((c) => {
    const list = obsOf(c.block_code, c.cycle_no)
      .map((o) => ({ o, v: numeric(o[key]) }))
      .filter((p): p is { o: Observation; v: number } => p.v !== null);
    return list.map((p, k) => ({
      key: `${p.o.file_name}-${p.o.sheet_name}-${p.o.source_row}`,
      cycle: c.cycle_no,
      v: p.v,
      off: (k - (list.length - 1) / 2) * 7,
      review: isReview(p.o),
    }));
  });
});
const rawRange = (c: Cycle) => {
  const v = rawPoints.value.filter((p) => p.cycle === c.cycle_no).map((p) => p.v);
  return v.length ? { lo: Math.min(...v), hi: Math.max(...v), n: v.length } : null;
};
const tTicks = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (showRaw.value) values.push(...rawPoints.value.map((p) => p.v));
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values);
  const pad = (max - min || Math.abs(max) || 1) * 0.08;
  return niceTicks(min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad, 4);
});
const tMin = computed(() => tTicks.value[0]!),
  tMax = computed(() => tTicks.value[tTicks.value.length - 1]!);
const tx = (cycle: number) => {
  const c0 = visible.value[0]?.cycle_no ?? 1,
    c1 = visible.value.at(-1)?.cycle_no ?? 1;
  return tm.value.l + ((cycle - (c0 - 0.5)) / (c1 - c0 + 1)) * (tRight.value - tm.value.l);
};
const ty = (v: number) =>
  tm.value.t + (1 - (v - tMin.value) / (tMax.value - tMin.value || 1)) * (tBottom.value - tm.value.t);
// 不跨缺失点连接：按连续段分别成线（花园再给每段铺一层渐隐面积）
const segments = computed(() => {
  const out: Cycle[][] = [];
  let cur: Cycle[] = [];
  for (const r of visible.value) {
    if (value(r) === null) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push(r);
  }
  if (cur.length) out.push(cur);
  return out.map((seg) => {
    const d = seg.map((r, i) => `${i ? "L" : "M"}${tx(r.cycle_no).toFixed(1)},${ty(value(r)!).toFixed(1)}`).join("");
    const area =
      seg.length > 1
        ? `${d}L${tx(seg[seg.length - 1]!.cycle_no).toFixed(1)},${tBottom.value}L${tx(seg[0]!.cycle_no).toFixed(1)},${tBottom.value}Z`
        : "";
    return { d, area };
  });
});
const hoverPoint = computed(() => {
  const r = focused.value;
  const v = r ? value(r) : null;
  if (!r || v === null) return null;
  return { row: r, v, x: tx(r.cycle_no), y: ty(v) };
});
const hud = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  const xl = `第 ${p.row.cycle_no} 次`,
    yl = short(p.v);
  const xw = textWidth(xl) + 12,
    yw = textWidth(yl) + 12;
  const cx = Math.max(tm.value.l + xw / 2, Math.min(tRight.value - xw / 2, p.x));
  return { xl, yl, xw, yw, cx };
});
const tip = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  return {
    style: { "--x": `${p.x}px`, "--y": `${p.y}px` },
    left: p.x + 16 + 236 > trendW.value,
    below: p.y < 128,
  };
});
let trendPointer = false;
function trendMove(e: PointerEvent) {
  if (e.pointerType === "touch") return;
  const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
  const mx = e.clientX - box.left,
    my = e.clientY - box.top;
  if (mx < tm.value.l || mx > tRight.value || my < tm.value.t - 14 || my > tBottom.value + 10) {
    if (trendPointer) focused.value = null;
    trendPointer = false;
    return;
  }
  let best: Cycle | null = null,
    d = Infinity;
  for (const r of valid.value) {
    const dist = Math.abs(tx(r.cycle_no) - mx);
    if (dist < d) {
      d = dist;
      best = r;
    }
  }
  trendPointer = true;
  focused.value = best;
}
function trendLeave() {
  if (trendPointer) focused.value = null;
  trendPointer = false;
}
function pointKey(e: KeyboardEvent, r: Cycle) {
  const list = valid.value,
    i = list.indexOf(r);
  let next: Cycle | undefined;
  if (e.key === "ArrowRight" || e.key === "ArrowUp") next = list[i + 1];
  else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = list[i - 1];
  else if (e.key === "Home") next = list[0];
  else if (e.key === "End") next = list[list.length - 1];
  else return;
  e.preventDefault();
  if (next)
    trendSvg.value?.querySelector<SVGGElement>(`[data-cycle="${next.cycle_no}"]`)?.focus();
}

/* ---------- 纤维长度分布：各循环在各长度区间的占比 ---------- */
const bins = computed(() =>
  (metadata.value?.indicators ?? [])
    .filter((i) => i.group === "distribution" && i.scope.includes("recycled"))
    .map((i) => ({
      key: i.key,
      name: i.name,
      short: i.name.replace("长度分布", "").replace("mm", "").trim(),
    })),
);
const dNarrow = computed(() => distW.value < 480);
const dH = computed(() => (dNarrow.value ? 290 : 330));
const dm = computed(() => ({ t: 38, r: 12, b: 70, l: dNarrow.value ? 40 : 48 }));
const dRight = computed(() => distW.value - dm.value.r);
const dBottom = computed(() => dH.value - dm.value.b);
const binValue = (c: Cycle, key: string) => numeric(c[key]);
const dTicks = computed(() => {
  const vals = visible.value.flatMap((c) =>
    bins.value.map((b) => binValue(c, b.key)).filter((v): v is number => v !== null),
  );
  return niceTicks(0, Math.max(1, ...vals), 4);
});
const dMax = computed(() => dTicks.value[dTicks.value.length - 1]!);
const dy = (v: number) =>
  dm.value.t + (1 - v / (dMax.value || 1)) * (dBottom.value - dm.value.t);
const colW = computed(() => (dRight.value - dm.value.l) / Math.max(1, bins.value.length));
const dx = (i: number) => dm.value.l + colW.value * (i + 0.5);
const distSeries = computed(() => {
  const n = visible.value.length;
  const cw = colW.value,
    gap = Math.max(4, cw * 0.2),
    bw = Math.max(2, (cw - gap - (n - 1) * 1.5) / Math.max(1, n));
  return visible.value.map((c, k) => {
    const last = k === n - 1;
    const pts = bins.value.map((b, i) => ({ i, v: binValue(c, b.key) }));
    let d = "",
      pen = false;
    for (const p of pts) {
      if (p.v === null) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${dx(p.i).toFixed(1)},${dy(p.v).toFixed(1)}`;
      pen = true;
    }
    const bars = pts
      .filter((p): p is { i: number; v: number } => p.v !== null)
      .map((p) => {
        const x = dm.value.l + cw * p.i + gap / 2 + k * (bw + 1.5),
          y = dy(p.v),
          h = Math.max(0, dBottom.value - y),
          rr = Math.min(3, bw / 2, h);
        return {
          i: p.i,
          d: `M${x.toFixed(1)},${dBottom.value}V${(y + rr).toFixed(1)}Q${x.toFixed(1)},${y.toFixed(1)} ${(x + rr).toFixed(1)},${y.toFixed(1)}H${(x + bw - rr).toFixed(1)}Q${(x + bw).toFixed(1)},${y.toFixed(1)} ${(x + bw).toFixed(1)},${(y + rr).toFixed(1)}V${dBottom.value}Z`,
        };
      });
    const shape = SHAPES[slot(c.cycle_no)] ?? "circle";
    const marks = pts
      .filter((p): p is { i: number; v: number } => p.v !== null)
      .map((p) => ({ i: p.i, d: shapePath(shape, dx(p.i), dy(p.v), last ? 3.6 : 3) }));
    return {
      c,
      last,
      d,
      bars,
      marks,
      shape,
      dash: last ? undefined : ["2 4", "8 4", "14 4"][Math.min(k, 2)],
      review: hasReview(c),
    };
  });
});
const activeBin = ref<number | null>(null);
function distMove(e: PointerEvent) {
  if (e.pointerType === "touch") return;
  const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
  const mx = e.clientX - box.left,
    my = e.clientY - box.top;
  if (mx < dm.value.l || mx > dRight.value || my < dm.value.t - 10 || my > dBottom.value + 4) {
    activeBin.value = null;
    return;
  }
  activeBin.value = Math.max(
    0,
    Math.min(bins.value.length - 1, Math.floor((mx - dm.value.l) / colW.value)),
  );
}
function distKey(e: KeyboardEvent) {
  const n = bins.value.length,
    i = activeBin.value;
  let next: number | null;
  if (e.key === "ArrowRight") next = i === null ? 0 : Math.min(n - 1, i + 1);
  else if (e.key === "ArrowLeft") next = i === null ? 0 : Math.max(0, i - 1);
  else if (e.key === "Home") next = 0;
  else if (e.key === "End") next = n - 1;
  else if (e.key === "Escape") next = null;
  else return;
  e.preventDefault();
  activeBin.value = next;
}
const distTip = computed(() => {
  const i = activeBin.value;
  if (i === null || !bins.value[i]) return null;
  const x = dx(i);
  return {
    bin: bins.value[i]!,
    rows: visible.value.map((c) => ({ c, v: binValue(c, bins.value[i]!.key) })),
    style: { "--x": `${x}px`, "--y": `${dm.value.t + 8}px` },
    left: x + 16 + 220 > distW.value,
  };
});

/* ---------- 页头签名（花园）：14 个数据块成环，每个循环一个点 ---------- */
const ring = computed(() => {
  const bl = blocks.value,
    n = bl.length;
  if (!n) return null;
  const cx = 66,
    cy = 66,
    rad = 52,
    seg = (Math.PI * 2) / n;
  const pt = (a: number) => `${(cx + Math.cos(a) * rad).toFixed(1)},${(cy + Math.sin(a) * rad).toFixed(1)}`;
  const arcs: string[] = [];
  const dots: { key: string; x: number; y: number; cls: string }[] = [];
  bl.forEach((b, i) => {
    const a0 = -Math.PI / 2 + i * seg + 0.08,
      a1 = a0 + seg - 0.16;
    arcs.push(`M${pt(a0)} A${rad},${rad} 0 0 1 ${pt(a1)}`);
    const cs = byBlock.value.get(b.block_code) ?? [];
    cs.forEach((c, k) => {
      const a = a0 + ((k + 0.5) / cs.length) * (a1 - a0);
      dots.push({
        key: `${b.block_code}-${c.cycle_no}`,
        x: cx + Math.cos(a) * rad,
        y: cy + Math.sin(a) * rad,
        cls: cyc(c.cycle_no),
      });
    });
  });
  const lw = (v: number | string) => 160 + String(v).length * 13 + 10;
  return {
    n,
    arcs,
    dots,
    points: rows.value.length,
    obs: originals.value.length,
    lw,
    c0: cycleSpan.value[0],
    c1: cycleSpan.value[1],
  };
});

/* ---------- 抽屉：原始观测与平均值 ---------- */
const strip = computed(() => {
  const c = selected.value;
  if (!c || !metric.value) return null;
  const key = metric.value.key;
  const raw = details.value
    .map((o) => ({ o, v: numeric(o[key]) }))
    .filter((p): p is { o: Observation; v: number } => p.v !== null);
  if (!raw.length) return null;
  const mean = value(c);
  const all = raw.map((p) => p.v).concat(mean === null ? [] : [mean]);
  let lo = Math.min(...all),
    hi = Math.max(...all);
  const pad = (hi - lo || Math.abs(hi) * 0.05 || 1) * 0.1;
  lo -= pad;
  hi += pad;
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return {
    dots: raw.map((p) => ({
      key: `${p.o.file_name}-${p.o.sheet_name}-${p.o.source_row}`,
      left: pct(p.v),
      review: isReview(p.o),
      label: `重复 ${p.o.replicate_no}：${number(p.v, 4)}`,
    })),
    mean: mean === null ? null : { left: pct(mean), text: number(mean, 3) },
    min: number(Math.min(...raw.map((p) => p.v)), 4),
    max: number(Math.max(...raw.map((p) => p.v)), 4),
  };
});
const isDistMetric = computed(() => metric.value?.group === "distribution");

function update(key: string, v: string) {
  router.replace({ query: { ...route.query, [key]: v } });
}
async function show(r: Cycle) {
  selected.value = r;
  await nextTick();
  dialog.value?.showModal();
}
function close() {
  dialog.value?.close();
  selected.value = null;
}
watch(
  () => [route.query.block, route.query.metric],
  () => {
    focused.value = null;
    activeBin.value = null;
    close();
  },
);
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  close();
  focused.value = null;
  activeBin.value = null;
  try {
    const [m, c, d] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      get<ListResult<Cycle>>(
        "recycled/cycles",
        { page_size: 500 },
        current.signal,
      ),
      get<ListResult<Observation>>(
        "recycled/details",
        { page_size: 500 },
        current.signal,
      ),
    ]);
    if (current.signal.aborted) return;
    metadata.value = m;
    rows.value = c.data;
    originals.value = d.data;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据加载失败，请重试。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  sizeObserver?.disconnect();
});
load();
</script>

<template>
  <div class="overview recycled-page">
    <PageHeader description="观察循环回用中的指标变化，追溯每一个平均值。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <figure class="rc-sig">
          <svg
            v-if="ring"
            viewBox="0 0 420 132"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <g class="sg-ring">
              <path v-for="(d, i) in ring.arcs" :key="i" class="sg-arc" :d="d" />
              <circle
                v-for="p in ring.dots"
                :key="p.key"
                class="sg-dot"
                :class="p.cls"
                :cx="p.x"
                :cy="p.y"
                r="3.3"
              />
            </g>
            <text class="sg-n sg-n-xl" x="66" y="76" text-anchor="middle">{{ ring.n }}</text>
            <text class="sg-m" x="66" y="92" text-anchor="middle">数据块</text>
            <text class="sg-n" x="160" y="40">{{ ring.points }}</text>
            <text class="sg-t" :x="ring.lw(ring.points)" y="39">个循环汇总点（环上每个点）</text>
            <text class="sg-n" x="160" y="74">{{ ring.obs }}</text>
            <text class="sg-t" :x="ring.lw(ring.obs)" y="73">条原始观测</text>
            <text class="sg-m" x="160" y="104">
              点色由浅到深 = 第 {{ ring.c0 }} → {{ ring.c1 }} 次循环
            </text>
          </svg>
          <div v-else class="rc-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            再生纸浆 · <b>{{ ring ? ring.n : "—" }}</b> 个数据块独立成环，不并入核心样本
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <p v-if="loading" class="card rc-state" role="status">正在加载循环数据…</p>
    <div v-else-if="error" class="card rc-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <template v-else>
      <!-- 数据块：偏光为玻片托盘，花园为按钮格；同一组单选按钮，路由参数 block -->
      <section class="card rc-blocks" aria-labelledby="rc-blocks-title">
        <div class="rc-blocks-head">
          <div class="rc-blocks-title">
            <h2 id="rc-blocks-title">数据块</h2>
            <p class="dataset-count">
              <span class="nw">全库 {{ blocks.length }} 个数据块</span>
              <span class="sep" aria-hidden="true">·</span>
              <span class="nw">{{ rows.length }} 个循环汇总点</span>
              <span class="sep" aria-hidden="true">·</span>
              <span class="nw">{{ originals.length }} 条原始观测</span>
            </p>
          </div>
          <div class="filter-field">
            <span class="field-label">观察指标</span
            ><FilterSelect
              id="recycled-metric"
              :model-value="metric?.key ?? ''"
              :options="metrics.map((m) => ({ value: m.key, label: m.name }))"
              label="选择循环指标"
              @update:model-value="update('metric', $event)"
            />
          </div>
        </div>
        <div class="rc-tray" role="radiogroup" aria-label="选择数据块">
          <button
            v-for="(t, i) in tray"
            :key="t.b.block_code"
            type="button"
            class="slide"
            role="radio"
            :aria-checked="t.b.block_code === block?.block_code"
            :tabindex="t.b.block_code === block?.block_code ? 0 : -1"
            :aria-label="slideLabel(t)"
            :style="{ '--lvl': t.lvl.toFixed(3) }"
            @click="update('block', t.b.block_code)"
            @keydown="blockKey($event, i)"
          >
            <span class="sl-top"
              ><span class="sl-code">{{ t.b.block_code }}</span
              ><span class="sl-d">{{ t.deltaText }}</span></span
            >
            <span class="sl-glass" aria-hidden="true">
              <svg viewBox="0 0 64 28" preserveAspectRatio="none">
                <line class="sl-base" x1="2" x2="62" y1="14" y2="14" />
                <path class="sl-line" :d="t.d" />
                <path
                  v-for="(p, k) in t.dots"
                  :key="k"
                  class="sl-dot"
                  :class="{ last: k === t.dots.length - 1 }"
                  :d="`M${p.x.toFixed(1)},${p.y.toFixed(1)}h0`"
                />
              </svg>
            </span>
            <span class="sl-meta"
              ><span class="sl-grade">{{ t.b.raw_material_grade ?? "未记录" }}</span
              ><span class="sl-n"
                ><span class="sl-cyc">{{ t.n }} 循环 · </span>{{ t.obs }} 条</span
              ></span
            >
            <span class="sl-dots" aria-hidden="true"
              ><i v-for="c in t.cycles" :key="c.cycle_no"></i
            ></span>
          </button>
        </div>
        <p class="tray-note">
          每张玻片：折线 = 当前观察指标<b>（{{ metric?.name }}）</b>各循环相对首次循环的变化（虚线 =
          首次水平，{{ blocks.length }} 张玻片共用同一纵向比例）；底色越亮 =
          该数据块均值越高；Δ = 末次相对首次的变化。
        </p>
      </section>

      <!-- 当前数据块：偏光一张信息条，花园三块瓦片 -->
      <section class="card rc-info" aria-label="当前数据块">
        <div class="metric ri ri-block">
          <span class="field-label">数据块</span
          ><b>{{ block?.block_code }} · {{ block?.block_name }}</b>
        </div>
        <div v-tilt class="metric ri">
          <span class="field-label">原料</span
          ><b>{{ block?.raw_material_grade ?? "未记录" }}</b>
        </div>
        <div v-tilt class="metric ri">
          <span class="field-label">处理条件</span
          ><b :class="{ unconf: !block?.condition_label }">{{
            block?.condition_label ?? "未确认"
          }}</b>
        </div>
        <div v-tilt class="metric ri">
          <span class="field-label"
            >当前数据块<span class="ri-inline">
              · {{ block?.block_code }} · {{ block?.block_name }}</span
            ></span
          ><b
            ><span class="nw">{{ visible.length }} 个循环</span> ·
            <span class="nw">{{ total }} 条原始观测</span></b
          >
        </div>
      </section>

      <section class="card rc-trend" aria-labelledby="cycle-title">
        <div class="section-head">
          <div>
            <h2 id="cycle-title">{{ metric?.name ?? "循环趋势" }}</h2>
            <p>
              {{ block?.block_code }} · 各循环原始观测的平均值<span class="unit-inline">
                · {{ unit }}</span
              >
            </p>
          </div>
          <span class="unit-tag">{{ unit }}</span>
        </div>
        <ul class="rc-legend" aria-label="图例">
          <li><i class="lg-mean" aria-hidden="true"></i>循环均值</li>
          <li>
            <button
              type="button"
              class="lg-toggle"
              :aria-pressed="showRaw"
              @click="showRaw = !showRaw"
            >
              <i class="lg-raw" aria-hidden="true"></i>原始观测
            </button>
          </li>
        </ul>
        <p v-if="!valid.length" class="rc-state rc-plot-state">
          当前数据块没有此指标的有效数值。
        </p>
        <div v-else ref="trendBox" class="plot-box">
          <svg
            ref="trendSvg"
            class="rc-plot"
            role="group"
            :width="trendW"
            :height="tH"
            :viewBox="`0 0 ${trendW} ${tH}`"
            :aria-label="`${metric?.name}随循环次数变化，点击数据点查看原始观测`"
            @pointermove="trendMove"
            @pointerleave="trendLeave"
          >
            <defs>
              <linearGradient id="rc-area-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" class="area-top" />
                <stop offset="1" class="area-bottom" />
              </linearGradient>
            </defs>
            <g class="grid" aria-hidden="true">
              <line
                v-for="t in tTicks"
                :key="`g${t}`"
                :x1="tm.l"
                :x2="tRight"
                :y1="ty(t)"
                :y2="ty(t)"
              />
            </g>
            <g class="axis" aria-hidden="true">
              <line :x1="tm.l" :x2="tRight" :y1="tBottom" :y2="tBottom" />
              <text
                v-for="t in tTicks"
                :key="`t${t}`"
                :x="tm.l - 10"
                :y="ty(t) + 4"
                text-anchor="end"
              >
                {{ number(t, tickDigits(tTicks)) }}
              </text>
              <g v-for="r in visible" :key="`x${r.cycle_no}`">
                <line :x1="tx(r.cycle_no)" :x2="tx(r.cycle_no)" :y1="tBottom" :y2="tBottom + 5" />
                <text :x="tx(r.cycle_no)" :y="tBottom + 20" text-anchor="middle">
                  第 {{ r.cycle_no }} 次
                </text>
              </g>
              <text class="axis-title" x="4" :y="tm.t - 18">
                <tspan class="garden-only">↑ </tspan>{{ metric?.name }} / {{ unit }}
              </text>
              <text class="axis-title" :x="tRight" :y="tH - 6" text-anchor="end">
                循环次数<tspan class="garden-only"> →</tspan>
              </text>
            </g>
            <g class="area" aria-hidden="true">
              <path v-for="(s, i) in segments" :key="`a${i}`" :d="s.area" />
            </g>
            <g v-if="showRaw" class="raw" aria-hidden="true">
              <circle
                v-for="p in rawPoints"
                :key="p.key"
                :class="{ review: p.review && isDistMetric }"
                :cx="tx(p.cycle) + p.off"
                :cy="ty(p.v)"
                r="2.8"
              />
            </g>
            <path
              v-for="(s, i) in segments"
              :key="`l${i}`"
              class="mean-line"
              :d="s.d"
            />
            <g
              v-for="r in valid"
              :key="r.cycle_no"
              class="cycle-point"
              :class="[cyc(r.cycle_no), { on: focused === r }]"
              :data-cycle="r.cycle_no"
              role="button"
              tabindex="0"
              :aria-label="`第${r.cycle_no}次循环，${number(value(r), 3)} ${unit}，查看${r.replicate_count}条原始观测`"
              @focus="focused = r"
              @blur="focused = null"
              @click="show(r)"
              @keydown="pointKey($event, r)"
              @keydown.enter.prevent="show(r)"
              @keydown.space.prevent="show(r)"
            >
              <circle class="hit" :cx="tx(r.cycle_no)" :cy="ty(value(r)!)" r="14" />
              <path
                class="mean-dia"
                :d="shapePath('diamond', tx(r.cycle_no), ty(value(r)!), focused === r ? 6.5 : 5)"
              />
              <circle
                class="mean-dot"
                :cx="tx(r.cycle_no)"
                :cy="ty(value(r)!)"
                :r="focused === r ? 7.5 : 6"
              />
            </g>
            <!-- 偏光：每个均值上方直接标注数值，纸色描边保证可读 -->
            <g class="value-labels" aria-hidden="true">
              <text
                v-for="r in valid"
                :key="`v${r.cycle_no}`"
                :x="tx(r.cycle_no)"
                :y="ty(value(r)!) - 14"
                text-anchor="middle"
              >
                {{ short(value(r)) }}
              </text>
            </g>
            <g v-if="hoverPoint" class="guide" aria-hidden="true">
              <line
                class="guide-l"
                :x1="hoverPoint.x"
                :x2="hoverPoint.x"
                :y1="tm.t"
                :y2="tBottom"
              />
              <circle class="guide-focus" :cx="hoverPoint.x" :cy="hoverPoint.y" r="13" />
            </g>
            <g v-if="hoverPoint && hud" class="hud" aria-hidden="true">
              <line class="hud-l" :x1="hoverPoint.x" :x2="hoverPoint.x" :y1="tm.t" :y2="tBottom" />
              <line class="hud-l" :x1="tm.l" :x2="tRight" :y1="hoverPoint.y" :y2="hoverPoint.y" />
              <path
                class="hud-tk"
                :d="`M${hoverPoint.x - 6},${hoverPoint.y}h12M${hoverPoint.x},${hoverPoint.y - 6}v12`"
              />
              <circle class="hud-ring" :cx="hoverPoint.x" :cy="hoverPoint.y" r="10" />
              <rect
                class="hud-box"
                :x="hud.cx - hud.xw / 2"
                :y="tBottom + 4"
                :width="hud.xw"
                height="17"
                rx="3"
              />
              <text class="hud-t" :x="hud.cx" :y="tBottom + 16.5" text-anchor="middle">
                {{ hud.xl }}
              </text>
              <rect
                class="hud-box"
                :x="tm.l - 4 - hud.yw"
                :y="hoverPoint.y - 8.5"
                :width="hud.yw"
                height="17"
                rx="3"
              />
              <text class="hud-t" :x="tm.l - 10" :y="hoverPoint.y + 4" text-anchor="end">
                {{ hud.yl }}
              </text>
            </g>
          </svg>
          <div
            class="chart-tip"
            :class="{ on: tip, left: tip?.left, below: tip?.below }"
            :style="tip?.style"
            role="status"
            aria-live="polite"
          >
            <template v-if="hoverPoint">
              <div class="tip-head">
                <i class="sw" :class="cyc(hoverPoint.row.cycle_no)" aria-hidden="true"></i
                ><b>{{ hoverPoint.row.block_code }} · 第 {{ hoverPoint.row.cycle_no }} 次循环</b>
              </div>
              <div class="tip-row">
                <span>{{ metric?.name }}</span><b>{{ number(hoverPoint.v, 3) }}</b>
              </div>
              <div class="tip-row">
                <span>原始观测</span><b>{{ hoverPoint.row.replicate_count }} 条</b>
              </div>
              <div v-if="rawRange(hoverPoint.row)" class="tip-row">
                <span>有效值范围</span
                ><b
                  >{{ number(rawRange(hoverPoint.row)!.lo, 3) }}–{{
                    number(rawRange(hoverPoint.row)!.hi, 3)
                  }}</b
                >
              </div>
              <div class="tip-foot">{{ unit }} · 点击查看原始观测</div>
            </template>
          </div>
        </div>
        <p class="point-summary">悬停查看数值，点击数据点或下方表格查看原始观测。</p>
      </section>

      <section v-if="bins.length" class="card rc-dist" aria-labelledby="rc-dist-title">
        <div class="section-head">
          <div>
            <h2 id="rc-dist-title">纤维长度分布</h2>
            <p>
              {{ block?.block_code }} · 各循环在 {{ bins.length }} 个长度区间的占比（%）· 区间单位 mm
            </p>
          </div>
        </div>
        <ul class="rc-legend dist-legend" aria-label="图例">
          <li v-for="s in distSeries" :key="s.c.cycle_no" :class="cyc(s.c.cycle_no)">
            <svg class="lg-cyc" viewBox="-14 -7 28 14" aria-hidden="true">
              <line
                class="lg-cyc-l"
                x1="-13"
                x2="13"
                y1="0"
                y2="0"
                :stroke-dasharray="s.dash"
                :class="{ last: s.last }"
              />
              <path class="lg-cyc-m" :d="shapePath(s.shape, 0, 0, 3.4)" />
            </svg>
            <i class="sw sq" aria-hidden="true"></i>
            第 {{ s.c.cycle_no }} 次<span v-if="s.review" class="qc-flag" title="含长度分布待复核的原始观测"
              >⚠</span
            >
          </li>
        </ul>
        <div ref="distBox" class="plot-box">
          <svg
            class="rc-plot rc-dist-plot"
            role="group"
            tabindex="0"
            :width="distW"
            :height="dH"
            :viewBox="`0 0 ${distW} ${dH}`"
            :aria-label="`${block?.block_code} 纤维长度分布，${visible.length} 个循环；聚焦后用左右方向键切换长度区间`"
            @pointermove="distMove"
            @pointerleave="activeBin = null"
            @keydown="distKey"
            @blur="activeBin = null"
          >
            <g class="grid" aria-hidden="true">
              <line
                v-for="t in dTicks"
                :key="`dg${t}`"
                :x1="dm.l"
                :x2="dRight"
                :y1="dy(t)"
                :y2="dy(t)"
              />
            </g>
            <rect
              v-if="activeBin !== null"
              class="bin-band"
              :x="dm.l + colW * activeBin"
              :y="dm.t"
              :width="colW"
              :height="dBottom - dm.t"
              rx="8"
            />
            <g class="axis" aria-hidden="true">
              <line :x1="dm.l" :x2="dRight" :y1="dBottom" :y2="dBottom" />
              <text
                v-for="t in dTicks"
                :key="`dt${t}`"
                :x="dm.l - 8"
                :y="dy(t) + 4"
                text-anchor="end"
              >
                {{ number(t, tickDigits(dTicks)) }}
              </text>
              <text
                v-for="(b, i) in bins"
                :key="b.key"
                class="bin-label"
                :x="dx(i)"
                :y="dBottom + 14"
                text-anchor="end"
                :transform="`rotate(-38 ${dx(i)} ${dBottom + 14})`"
              >
                {{ b.short }}
              </text>
              <text class="axis-title" x="4" :y="dm.t - 18">
                <tspan class="garden-only">↑ </tspan>比例 / %
              </text>
              <text class="axis-title" :x="dRight" :y="dH - 4" text-anchor="end">
                长度区间 / mm
              </text>
            </g>
            <!-- 花园：分组柱 -->
            <g class="dist-bars" aria-hidden="true">
              <g v-for="s in distSeries" :key="`b${s.c.cycle_no}`" :class="cyc(s.c.cycle_no)">
                <path
                  v-for="b in s.bars"
                  :key="b.i"
                  :d="b.d"
                  :class="{ dim: activeBin !== null && activeBin !== b.i }"
                />
              </g>
            </g>
            <!-- 偏光：每个循环一种线型与标记，最新一次实线加粗 -->
            <g class="dist-lines" aria-hidden="true">
              <g
                v-for="s in distSeries"
                :key="`l${s.c.cycle_no}`"
                :class="[cyc(s.c.cycle_no), { last: s.last }]"
              >
                <path class="dl" :d="s.d" :stroke-dasharray="s.dash" />
                <path v-for="m in s.marks" :key="m.i" class="dm" :d="m.d" />
              </g>
            </g>
            <line
              v-if="activeBin !== null"
              class="bin-hair"
              :x1="dx(activeBin)"
              :x2="dx(activeBin)"
              :y1="dm.t"
              :y2="dBottom"
            />
          </svg>
          <div
            class="chart-tip dist-tip"
            :class="{ on: distTip, left: distTip?.left }"
            :style="distTip?.style"
            role="status"
            aria-live="polite"
          >
            <template v-if="distTip">
              <div class="tip-head">
                <b>{{ distTip.bin.name }}</b>
              </div>
              <div v-for="d in distTip.rows" :key="d.c.cycle_no" class="tip-row">
                <span
                  ><i class="sw" :class="cyc(d.c.cycle_no)" aria-hidden="true"></i>第
                  {{ d.c.cycle_no }} 次<template v-if="hasReview(d.c)"> ⚠</template></span
                ><b>{{ d.v === null ? "—" : `${number(d.v, 2)}%` }}</b>
              </div>
            </template>
          </div>
        </div>
        <p class="point-summary">
          悬停或聚焦图表后用 ←/→ 查看各长度区间的占比。全库 {{ reviewCount }} 条长度分布异常记录保留原值，各循环合计可能略偏离
          100%。<template v-if="blockReview.length"
            >⚠ 当前数据块第 {{ blockReview.join("、") }} 次循环含待复核的原始观测。</template
          >
        </p>
      </section>

      <section class="card rc-table" aria-labelledby="rc-table-title">
        <div class="section-head">
          <div>
            <h2 id="rc-table-title">循环明细</h2>
            <p>按循环次数排序 · 缺失值显示为 —，曲线不跨缺失点连接</p>
          </div>
        </div>
        <div class="table-scroll" role="region" aria-label="循环明细" tabindex="0">
          <table>
            <thead>
              <tr>
                <th>循环次数</th>
                <th class="numeric">{{ metric?.name }} / {{ unit }}</th>
                <th class="numeric">原始观测数</th>
                <th>来源追溯</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in visible"
                :key="r.cycle_no"
                :class="{ on: focused === r }"
              >
                <td>
                  <span class="cycle-cell"
                    ><i class="sw" :class="cyc(r.cycle_no)" aria-hidden="true"></i>第
                    {{ r.cycle_no }} 次</span
                  >
                </td>
                <td class="numeric">{{ number(value(r), 3) }}</td>
                <td class="numeric">{{ r.replicate_count }}</td>
                <td>
                  <button class="text-link" @click="show(r)">
                    查看原始观测
                  </button>
                </td>
              </tr>
              <tr v-if="!visible.length">
                <td colspan="4">暂无循环记录。</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="caveat method-note">
          <Info :size="16" aria-hidden="true" /><span
            >每个点是同一数据块、同一次循环内该指标非空观测的算术平均值，原始观测数为该循环的记录总数。数据块保留原始分组；未确认的处理条件不推断。该数据集独立于总览中的
            {{ number(metadata?.counts?.samples) }} 个核心样本。</span
          >
        </p>
      </section>
    </template>

    <dialog
      ref="dialog"
      class="detail-drawer rc-drawer"
      aria-labelledby="original-title"
      @close="selected = null"
      @click="$event.target === dialog && close()"
    >
      <div v-if="selected" class="drawer-content">
        <div class="dialog-heading">
          <div>
            <span class="eyebrow">原始观测 · 循环汇总点</span>
            <h2 id="original-title">
              {{ selected.block_code }} · 第 {{ selected.cycle_no }} 次循环
            </h2>
          </div>
          <button class="icon-button" aria-label="关闭原始观测" @click="close">
            <X :size="20" />
          </button>
        </div>
        <p class="detail-name">
          {{ metric?.name }} · 平均值 {{ number(value(selected), 3) }}
          {{ unit }}
        </p>
        <div class="rc-chips">
          <span class="chip">{{ block?.block_name }}</span>
          <span class="chip">原料 {{ block?.raw_material_grade ?? "未记录" }}</span>
          <span class="chip">处理条件 {{ block?.condition_label ?? "未确认" }}</span>
        </div>
        <section v-if="strip" class="detail-section">
          <h3>原始观测与平均值</h3>
          <div class="strip" aria-hidden="true">
            <div class="strip-track">
              <span
                v-if="strip.mean"
                class="strip-mean"
                :style="{ left: `${strip.mean.left}%` }"
                ><b>均值 {{ strip.mean.text }}</b></span
              >
              <i
                v-for="d in strip.dots"
                :key="d.key"
                class="strip-dot"
                :class="{ review: d.review && isDistMetric }"
                :style="{ left: `${d.left}%` }"
                :title="d.label"
              ></i>
            </div>
            <div class="strip-scale">
              <span>{{ strip.min }}</span><span>{{ strip.max }}</span>
            </div>
          </div>
          <p class="strip-cap">
            每个圆点是一条原始观测，竖线是该循环的平均值（{{ unit }}）。
          </p>
        </section>
        <section class="detail-section">
          <h3>
            <FileSpreadsheet :size="17" />Excel 来源
            <span class="count-badge">{{ details.length }}</span>
          </h3>
          <p class="original-note">
            {{ details.length }} 条原始观测 · 该指标有效值
            {{ details.filter((r) => value(r) !== null).length }} 条
          </p>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>重复序号</th>
                  <th class="numeric">原始值 / {{ unit }}</th>
                  <th>Excel 来源</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in details"
                  :key="`${r.file_name}-${r.sheet_name}-${r.source_row}`"
                >
                  <td>
                    {{ r.replicate_no
                    }}<span
                      v-if="isDistMetric && isReview(r)"
                      class="qc-tag"
                      :title="`长度区间合计 ${number(numeric(r.length_distribution_sum_pct), 2)}%`"
                      >待复核</span
                    >
                  </td>
                  <td class="numeric">{{ number(value(r), 4) }}</td>
                  <td class="src-cell">
                    {{ r.file_name
                    }}<small>{{ r.sheet_name }} · 第 {{ r.source_row }} 行</small>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="isDistMetric && details.some(isReview)" class="detail-note">
            “待复核”的原始观测长度区间合计偏离 100%，数值保留原样并计入平均值。
          </p>
        </section>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
/* ================================================================ page grid
   DOM order: header · blocks · info · trend · distribution · table.
   Dense auto-flow pairs the two charts (v1 rc-grid 1:1, v4 s-7 + s-5). */
.recycled-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-auto-flow: row dense;
  gap: 18px;
  align-items: start;
}
.recycled-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.recycled-page > .page-header {
  margin-bottom: 0;
}
.recycled-page > .rc-trend {
  grid-column: 1;
  align-self: stretch;
}
.recycled-page > .rc-dist {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .recycled-page {
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
}
.nw {
  white-space: nowrap;
}
.garden-only,
.ri-inline,
.unit-inline {
  display: none;
}

/* ================================================================ cycle ramp
   one colour per cycle number, ≥3:1 on the chart paper in both modes.
   polarized: violet, later cycles brighter (v1); garden: plum-grey, later cycles darker (v4) */
.cyc-0 {
  --cyc: color-mix(in oklab, var(--rc) 62%, var(--surface));
}
.cyc-1 {
  --cyc: color-mix(in oklab, var(--rc) 82%, var(--surface));
}
.cyc-2 {
  --cyc: var(--rc);
}
.cyc-3 {
  --cyc: color-mix(in oklab, var(--rc) 45%, var(--text));
}
:root[data-mode="garden"] .cyc-0 {
  --cyc: color-mix(in oklab, var(--rc) 80%, var(--surface));
}
:root[data-mode="garden"] .cyc-1 {
  --cyc: var(--rc);
}
:root[data-mode="garden"] .cyc-2 {
  --cyc: color-mix(in oklab, var(--rc) 50%, var(--accent));
}
:root[data-mode="garden"] .cyc-3 {
  --cyc: var(--accent);
}
.sw {
  display: inline-block;
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--cyc);
}

/* ================================================================ states */
.rc-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 48px 24px;
  text-align: center;
  color: var(--text-2);
}

/* ================================================================ signature (garden hero) */
.rc-sig {
  position: relative;
  margin: 0;
  min-width: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rc-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.rc-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 132;
}
.rc-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.rc-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.sg-ring {
  transform-box: view-box;
  transform-origin: 66px 66px;
  animation: rc-spin 120s linear infinite;
}
@keyframes rc-spin {
  to {
    transform: rotate(360deg);
  }
}
.sg-arc {
  fill: none;
  stroke: var(--line);
  stroke-width: 7;
  stroke-linecap: round;
}
.sg-dot {
  fill: var(--cyc);
  stroke: var(--surface);
  stroke-width: 1;
}
.sg-n {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-size: 22px;
  font-weight: 420;
  letter-spacing: -0.02em;
  fill: var(--text);
}
.sg-n-xl {
  font-size: 46px;
  font-weight: 340;
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
}
.sg-t {
  font-family: var(--font-body);
  font-size: 11.5px;
  fill: var(--text-2);
}
.sg-m {
  font-family: var(--font-mono);
  font-size: 10.5px;
  fill: var(--text-2);
}

/* ================================================================ blocks (tray) */
.rc-blocks {
  padding: 22px 24px;
}
.rc-blocks-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 14px 24px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.rc-blocks-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px 14px;
  min-width: 0;
}
.rc-blocks h2,
.section-head h2 {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--text);
}
.dataset-count {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.dataset-count .sep {
  margin: 0 6px;
  color: var(--text-3);
}
.filter-field {
  display: flex;
  flex-direction: column;
  min-width: 240px;
}
.rc-tray {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}
.slide {
  --lvl: 0.5;
  position: relative;
  display: grid;
  grid-template-rows: auto 48px auto;
  gap: 7px;
  min-width: 0;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: linear-gradient(
    180deg,
    color-mix(in oklab, var(--text) 5%, transparent),
    color-mix(in oklab, var(--text) 1.5%, transparent)
  );
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.2s,
    box-shadow 0.2s,
    background 0.2s;
}
.slide:hover {
  border-color: var(--line-strong);
}
.slide[aria-checked="true"] {
  border-color: color-mix(in oklab, var(--rc) 85%, transparent);
  background: linear-gradient(
    180deg,
    color-mix(in oklab, var(--rc) 16%, transparent),
    color-mix(in oklab, var(--rc) 3%, transparent)
  );
  box-shadow: 0 0 30px -10px color-mix(in oklab, var(--rc) 80%, transparent);
}
.sl-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  font-family: var(--font-mono);
}
.sl-code {
  font-size: 12px;
  color: var(--text);
}
.sl-d {
  font-size: 10px;
  color: var(--text-2);
  white-space: nowrap;
}
/* the "glass slide": violet sheen whose brightness = block mean level; sparkline = trend */
.sl-glass {
  position: relative;
  display: block;
  border-radius: 5px;
  overflow: hidden;
  background: linear-gradient(
    115deg,
    color-mix(in oklab, var(--rc) calc(8% + var(--lvl) * 42%), transparent),
    color-mix(in oklab, var(--rc) calc(4% + var(--lvl) * 18%), transparent) 60%,
    color-mix(in oklab, var(--text) 2%, transparent)
  );
  box-shadow: inset 0 0 0 1px var(--line);
}
.sl-glass::after {
  content: "";
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    118deg,
    transparent 0 7px,
    color-mix(in oklab, var(--text) 3.5%, transparent) 7px 8px
  );
}
.slide[aria-checked="true"] .sl-glass {
  box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--rc) 60%, transparent);
}
.sl-glass svg {
  position: absolute;
  inset: 4px 0;
  width: 100%;
  height: calc(100% - 8px);
  overflow: visible;
}
.sl-line {
  fill: none;
  stroke: color-mix(in oklab, var(--rc) 30%, var(--text));
  stroke-width: 1.5;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
.sl-base {
  stroke: color-mix(in oklab, var(--rc) 30%, var(--text));
  stroke-opacity: 0.3;
  stroke-width: 1;
  stroke-dasharray: 2 2;
  vector-effect: non-scaling-stroke;
}
.sl-dot {
  stroke: color-mix(in oklab, var(--rc) 30%, var(--text));
  stroke-width: 3;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}
.sl-dot.last {
  stroke-width: 4.5;
}
.sl-meta {
  display: grid;
  min-width: 0;
  font-size: 11.5px;
  color: var(--text-2);
}
.sl-meta > span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.sl-n {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-3);
}
.sl-dots {
  display: none;
  gap: 3px;
  margin-top: 6px;
}
.sl-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.55;
}
.tray-note {
  margin-top: 12px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-3);
}
.tray-note b {
  font-weight: 500;
  color: var(--text-2);
}

/* ================================================================ info strip */
.rc-info {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  align-items: end;
  padding: 20px 24px;
}
.ri {
  min-width: 0;
}
.ri .field-label {
  margin-bottom: 4px;
}
.ri b {
  display: block;
  font-size: 16px;
  font-weight: 500;
  color: var(--text);
}
.ri b.unconf {
  color: var(--warn);
}

/* ================================================================ chart cards */
.rc-trend,
.rc-dist {
  display: flex;
  flex-direction: column;
  padding: 22px 24px;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.section-head p {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-2);
}
.unit-tag {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
.rc-legend {
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
.rc-legend li {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.lg-mean {
  position: relative;
  width: 22px;
  height: 2px;
  background: var(--rc);
}
.lg-mean::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 8px;
  height: 8px;
  background: var(--rc);
  transform: translate(-50%, -50%) rotate(45deg);
}
.lg-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: -4px -8px;
  padding: 4px 8px;
  border-radius: 999px;
  color: inherit;
  font-size: inherit;
}
.lg-toggle:hover {
  color: var(--text);
}
.lg-toggle[aria-pressed="false"] {
  text-decoration: line-through;
  color: var(--text-3);
}
.lg-raw {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1.4px solid var(--text-2);
}
.lg-cyc {
  width: 28px;
  height: 14px;
  overflow: visible;
}
.lg-cyc-l {
  stroke: var(--cyc);
  stroke-width: 1.5;
  opacity: 0.8;
}
.lg-cyc-l.last {
  stroke-width: 2.5;
  opacity: 1;
}
.lg-cyc-m {
  fill: var(--cyc);
}
.sw.sq {
  display: none;
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.qc-flag {
  margin-left: 2px;
  color: var(--review);
}
.plot-box,
.rc-plot-state {
  margin-top: 12px;
}
.plot-box {
  position: relative;
  width: 100%;
  min-width: 0;
  /* the svg is sized from this box; clip a resize frame instead of scrolling the page */
  overflow-x: clip;
}
.rc-plot {
  display: block;
  touch-action: pan-y;
}
.rc-plot:focus {
  outline: none;
}
/* drawn inside the box: the plot box clips horizontally */
.rc-dist-plot:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
  border-radius: 10px;
}
.rc-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--chart-text);
}
.rc-plot .axis-title {
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
.area {
  display: none;
}
.area path {
  fill: url(#rc-area-grad);
}
.area-top {
  stop-color: var(--accent);
  stop-opacity: 0.16;
}
.area-bottom {
  stop-color: var(--accent);
  stop-opacity: 0;
}
.mean-line {
  fill: none;
  stroke: var(--rc);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.raw circle {
  fill: none;
  stroke: var(--text-2);
  stroke-width: 1.2;
  stroke-opacity: 0.85;
}
.raw circle.review {
  stroke: var(--review);
  stroke-opacity: 1;
}
.cycle-point {
  cursor: pointer;
}
.cycle-point:focus {
  outline: none;
}
.hit {
  fill: transparent;
}
.cycle-point:focus-visible .hit {
  stroke: var(--focus);
  stroke-width: 2.5;
}
.mean-dia {
  fill: var(--rc);
  stroke: var(--chart-paper);
  stroke-width: 2;
  paint-order: stroke;
}
.mean-dot {
  display: none;
  fill: var(--cyc);
  stroke: var(--surface);
  stroke-width: 2;
}
.rc-plot .value-labels text {
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--chart-paper);
  stroke-width: 4px;
  stroke-linejoin: round;
}
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
.rc-plot .hud-t {
  font-size: 10.5px;
  fill: var(--text);
}
.guide-l {
  stroke: var(--chart-guide);
  stroke-dasharray: 3 4;
}
.guide-focus {
  fill: none;
  stroke: var(--text);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}
/* distribution */
.rc-dist-plot {
  cursor: crosshair;
}
.rc-plot .bin-label {
  font-size: 10.5px;
}
.bin-band {
  display: none;
  fill: var(--surface-hover);
}
.bin-hair {
  stroke: var(--text-2);
  stroke-opacity: 0.6;
  stroke-width: 1;
  pointer-events: none;
}
.dist-bars {
  display: none;
}
.dist-bars path {
  fill: var(--cyc);
  stroke: var(--surface);
  stroke-width: 1;
  transition: opacity 0.15s;
}
.dist-bars path.dim {
  opacity: 0.45;
}
.dist-lines > g {
  opacity: 0.72;
}
.dist-lines > g.last {
  opacity: 1;
}
.dl {
  fill: none;
  stroke: var(--cyc);
  stroke-width: 1.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.dist-lines > g.last .dl {
  stroke-width: 2.5;
}
.dm {
  fill: var(--cyc);
  stroke: var(--chart-paper);
  stroke-width: 1.5;
  paint-order: stroke;
}
/* floating tooltip (also the polite live region for the readout) */
.chart-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 5;
  min-width: 170px;
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
.chart-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) - 100% - 12px));
}
.chart-tip.below,
.dist-tip {
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) + 16px));
}
.chart-tip.left.below,
.dist-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) + 16px));
}
.chart-tip.on {
  opacity: 1;
}
.tip-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.tip-head b {
  font-weight: 500;
}
.tip-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
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
  white-space: nowrap;
}
.tip-foot {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}
.point-summary {
  margin-top: 12px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-3);
}

/* ================================================================ table */
.rc-table {
  overflow: hidden;
}
.rc-table .section-head {
  padding: 22px 24px 14px;
}
.rc-table .table-scroll:focus-visible {
  outline-offset: -2px;
}
.rc-table tbody tr.on td {
  background: var(--surface-hover);
}
.cycle-cell {
  display: inline-flex;
  align-items: center;
  gap: 9px;
}
.cycle-cell .sw {
  display: none;
}
.text-link {
  border: 0;
  background: none;
  color: var(--accent-ink);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  padding: 5px 0;
}
.text-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.method-note {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin: 14px 24px 22px;
}
.method-note svg {
  flex: none;
  margin-top: 3px;
  color: var(--text-3);
}

/* ================================================================ drawer */
.rc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.strip {
  padding: 26px 8px 0;
}
.strip-track {
  position: relative;
  height: 28px;
  border-radius: 999px;
  background: var(--surface-2);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}
.strip-dot {
  position: absolute;
  top: 50%;
  width: 11px;
  height: 11px;
  margin: -5.5px 0 0 -5.5px;
  border-radius: 50%;
  background: color-mix(in oklab, var(--rc) 35%, transparent);
  border: 1.5px solid var(--rc);
}
.strip-dot.review {
  border-color: var(--review);
  background: var(--review-tint);
}
.strip-mean {
  position: absolute;
  top: -6px;
  bottom: -6px;
  width: 2px;
  margin-left: -1px;
  background: var(--text);
}
.strip-mean b {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  font: 500 11.5px var(--font-mono);
  color: var(--text);
  white-space: nowrap;
}
.strip-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
.strip-cap {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.original-note {
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--text-2);
}
.rc-drawer table {
  white-space: normal;
}
.rc-drawer td.numeric {
  white-space: nowrap;
}
.src-cell {
  overflow-wrap: anywhere;
}
.rc-drawer small {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
}
.qc-tag {
  margin-left: 8px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  white-space: nowrap;
  color: var(--review);
  background: var(--review-tint);
}

/* ================================================================ polarized (v1) */
:root[data-mode="polarized"] .rc-info .metric {
  padding: 0;
  border: 0;
  background: none;
  box-shadow: none;
}
:root[data-mode="polarized"] .rc-info .metric::before {
  display: none;
}
:root[data-mode="polarized"] .hud {
  display: inline;
}
:root[data-mode="polarized"] .chart-tip {
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
:root[data-mode="polarized"] .rc-table th {
  font-family: var(--font-mono);
}
:root[data-mode="polarized"] .rc-table td.numeric,
:root[data-mode="polarized"] .rc-drawer td.numeric {
  font-family: var(--font-mono);
  font-size: 13px;
}

/* ================================================================ garden (v4) */
:root[data-mode="garden"] .garden-only {
  display: inline;
}
:root[data-mode="garden"] .rc-blocks h2,
:root[data-mode="garden"] .section-head h2 {
  font-size: 19px;
  font-weight: 500;
}
:root[data-mode="garden"] .rc-blocks-title {
  display: block;
}
:root[data-mode="garden"] .dataset-count {
  margin-top: 2px;
  font-family: var(--font-body);
  font-size: 13px;
}
:root[data-mode="garden"] .rc-tray {
  gap: 8px;
}
:root[data-mode="garden"] .slide {
  display: block;
  padding: 10px 12px;
  border: 0;
  border-radius: 18px;
  background: color-mix(in oklab, var(--surface) 55%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
  transition:
    transform 0.35s var(--spring),
    background 0.2s,
    box-shadow 0.2s;
}
:root[data-mode="garden"] .slide:hover {
  transform: translateY(-2px);
  background: color-mix(in oklab, var(--surface) 85%, transparent);
}
:root[data-mode="garden"] .slide[aria-checked="true"] {
  background: var(--text);
  color: var(--accent-contrast);
  box-shadow: 0 12px 24px -14px var(--text);
}
:root[data-mode="garden"] .sl-top {
  display: block;
}
:root[data-mode="garden"] .sl-code {
  font-size: 15px;
  font-weight: 500;
  color: inherit;
}
:root[data-mode="garden"] .sl-d,
:root[data-mode="garden"] .sl-glass,
:root[data-mode="garden"] .sl-cyc,
:root[data-mode="garden"] .tray-note {
  display: none;
}
:root[data-mode="garden"] .sl-meta {
  display: block;
  margin-top: 2px;
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
:root[data-mode="garden"] .sl-meta > span {
  display: inline;
}
:root[data-mode="garden"] .sl-n {
  font-family: var(--font-body);
  font-size: inherit;
  color: inherit;
}
:root[data-mode="garden"] .sl-n::before {
  content: " · ";
}
:root[data-mode="garden"] .slide[aria-checked="true"] .sl-meta {
  color: color-mix(in oklab, var(--accent-contrast) 85%, transparent);
}
:root[data-mode="garden"] .sl-dots {
  display: flex;
}
:root[data-mode="garden"] .rc-info {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  padding: 0;
  background: none;
  box-shadow: none;
  animation: none;
}
:root[data-mode="garden"] .ri-block {
  display: none;
}
:root[data-mode="garden"] .ri-inline {
  display: inline;
}
:root[data-mode="garden"] .ri {
  align-self: stretch;
  padding: 18px 22px;
}
:root[data-mode="garden"] .ri .field-label {
  font-size: 12.5px;
}
:root[data-mode="garden"] .ri b {
  margin-top: 4px;
  font-size: 20px;
  letter-spacing: 0.02em;
}
:root[data-mode="garden"] .ri b.unconf {
  color: var(--text);
}
:root[data-mode="garden"] .unit-tag {
  display: none;
}
:root[data-mode="garden"] .unit-inline {
  display: inline;
}
:root[data-mode="garden"] .rc-legend {
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .lg-mean,
:root[data-mode="garden"] .lg-mean::after {
  background: var(--accent);
}
:root[data-mode="garden"] .lg-mean::after {
  border-radius: 50%;
  transform: translate(-50%, -50%);
}
:root[data-mode="garden"] .lg-raw {
  border-color: var(--rc);
}
:root[data-mode="garden"] .lg-cyc {
  display: none;
}
:root[data-mode="garden"] .sw.sq {
  display: inline-block;
}
:root[data-mode="garden"] .rc-plot .axis-title {
  font-size: 11.5px;
  fill: var(--text-2);
}
:root[data-mode="garden"] .area,
:root[data-mode="garden"] .guide,
:root[data-mode="garden"] .mean-dot,
:root[data-mode="garden"] .dist-bars,
:root[data-mode="garden"] .bin-band {
  display: inline;
}
:root[data-mode="garden"] .mean-line {
  stroke: var(--accent);
  stroke-width: 2.2;
}
:root[data-mode="garden"] .raw circle {
  stroke: var(--rc);
}
:root[data-mode="garden"] .raw circle.review {
  stroke: var(--review);
}
:root[data-mode="garden"] .mean-dia,
:root[data-mode="garden"] .value-labels,
:root[data-mode="garden"] .dist-lines,
:root[data-mode="garden"] .bin-hair {
  display: none;
}
:root[data-mode="garden"] .chart-tip {
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
:root[data-mode="garden"] .tip-head b {
  font-weight: 500;
}
:root[data-mode="garden"] .point-summary {
  font-size: 13px;
  color: var(--text-2);
}
:root[data-mode="garden"] .cycle-cell .sw {
  display: inline-block;
}
:root[data-mode="garden"] .rc-table .text-link {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  background: color-mix(in oklab, var(--surface) 80%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .rc-table .text-link:hover {
  text-decoration: none;
  background: var(--surface);
}
:root[data-mode="garden"] .method-note svg {
  color: var(--accent);
}

/* ================================================================ responsive */
@media (max-width: 1100px) {
  .recycled-page,
  :root[data-mode="garden"] .recycled-page {
    grid-template-columns: minmax(0, 1fr);
  }
  .recycled-page > .rc-trend,
  .recycled-page > .rc-dist {
    grid-column: 1;
  }
  .rc-tray {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
  .rc-info {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .rc-blocks,
  .rc-trend,
  .rc-dist {
    padding: 16px;
  }
  .filter-field {
    width: 100%;
    min-width: 0;
  }
  .rc-tray,
  :root[data-mode="garden"] .rc-tray {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }
  .slide {
    grid-template-rows: auto 30px auto;
    padding: 8px;
  }
  :root[data-mode="garden"] .slide {
    padding: 8px 9px;
    border-radius: 14px;
  }
  .rc-info {
    gap: 14px;
    padding: 16px;
  }
  :root[data-mode="garden"] .rc-info {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    padding: 0;
  }
  :root[data-mode="garden"] .ri {
    padding: 16px 18px;
  }
  .ri b {
    font-size: 15px;
  }
  .rc-table .section-head {
    padding: 18px 16px 12px;
  }
  .method-note {
    margin: 12px 16px 18px;
  }
}
</style>
