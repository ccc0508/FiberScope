<script setup lang="ts">
// 数据总览：上方两组数据清单，下方一个刻度盘舞台。
// 样本盘：一根辐条一个物理样本，长度为打浆度；观测盘：一点一条再生纸浆观测。
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { TriangleAlert } from "lucide-vue-next";
import { get, number, type ListResult, type Sample } from "../api";
import {
  buildDots,
  buildSpokes,
  dialMaterials,
  groupBlocks,
  spokeStart,
  sweepStart,
  type DialMaterial,
  type DialObservation,
  type DialSample,
} from "../overview";

interface DetailRow {
  block_code: string;
  cycle_no: number;
  replicate_no: number;
  raw_material_grade: string | null;
  source_row: number;
  fiber_length_weighted_mm: number | null;
  length_distribution_qc: string | null;
}
type SetKey = "A" | "B";

const NAME: Record<DialMaterial, string> = {
  softwood: "针叶木浆",
  hardwood: "阔叶木浆",
  blend: "针阔复配",
};
const samples = ref<DialSample[]>([]),
  observations = ref<DialObservation[]>([]);
const loading = ref(true),
  error = ref("");
const active = ref<SetKey>("A");

/* ---------- 读取 ---------- */
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  try {
    const [s, d] = await Promise.all([
      get<ListResult<Sample>>("samples", { page_size: 500 }, current.signal),
      get<ListResult<DetailRow>>(
        "recycled/details",
        { page_size: 500 },
        current.signal,
      ),
    ]);
    if (current.signal.aborted) return;
    samples.value = s.data.map((x) => ({
      code: x.canonical_code,
      name: x.display_name,
      type: x.sample_type,
      sw: x.sw_proportion_pct,
      revs:
        x.sample_type === "softwood"
          ? x.sw_beating_revolutions
          : x.sample_type === "hardwood"
            ? x.hw_beating_revolutions
            : null,
      sr:
        x.sample_type === "softwood"
          ? x.sw_beating_degree_sr
          : x.sample_type === "hardwood"
            ? x.hw_beating_degree_sr
            : null,
    }));
    observations.value = d.data.map((x) => ({
      block: x.block_code,
      cycle: x.cycle_no,
      replicate: x.replicate_no,
      grade: x.raw_material_grade,
      row: x.source_row,
      fl: x.fiber_length_weighted_mm,
      review: x.length_distribution_qc === "REVIEW",
    }));
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "总览数据读取失败。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
defineExpose({ load });

/* ---------- 清单 ---------- */
const byType = (t: DialMaterial) => samples.value.filter((s) => s.type === t);
const blendRange = computed(() => {
  const l = byType("blend").map((s) => s.sw);
  return l.length ? [Math.min(...l), Math.max(...l)] : null;
});
const groups = computed(() => groupBlocks(observations.value));
const reviewCount = computed(
  () => observations.value.filter((o) => o.review).length,
);
interface Row {
  key: string;
  label: string;
  count: number;
  total: number;
  swatch: string;
  bar: string;
  tri?: boolean;
}
const rowsA = computed<Row[]>(() =>
  dialMaterials.map((t) => ({
    key: t,
    label: t === "blend" ? "针阔复配（按配比分段）" : NAME[t],
    count: byType(t).length,
    total: samples.value.length,
    swatch:
      t === "blend"
        ? "linear-gradient(0deg,var(--sw) 0 50%,var(--hw) 50%)"
        : t === "softwood"
          ? "var(--sw)"
          : "var(--hw)",
    bar:
      t === "blend"
        ? "var(--muted)"
        : t === "softwood"
          ? "var(--sw)"
          : "var(--hw)",
  })),
);
const rowsB = computed<Row[]>(() => [
  ...groups.value.map((g) => ({
    key: `g:${g.blocks.join(",")}`,
    label: `${g.blocks[0]}${g.blocks.length > 1 ? `–${g.blocks[g.blocks.length - 1]}` : ""}，${g.cycles} 次循环 × ${g.replicates} 重复`,
    count: g.count,
    total: observations.value.length,
    swatch: "var(--rc)",
    bar: "var(--rc)",
  })),
  {
    key: "review",
    label: "待复核：长度分布合计偏离 100%",
    count: reviewCount.value,
    total: observations.value.length,
    swatch: "",
    bar: "var(--review)",
    tri: true,
  },
]);

/* ---------- 画布、时钟与交互状态 ---------- */
const canvas = ref<HTMLCanvasElement>();
const stage = ref<HTMLElement>();
const tip = ref<HTMLElement>();
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const clock = () => performance.now() / 1000;
let t0 = clock(),
  busyUntil = 0,
  frame = 0;
const now = () => clock() - t0;
const filter = {
  on: null as string | null,
  prev: null as string | null,
  at: -9,
};
let hover: { kind: SetKey; key: object } | null = null,
  hoverAt = -9;
const shown = ref({ A: 0, B: 0 });

const spokeModel = computed(() => buildSpokes(samples.value));
const dotModel = computed(() => buildDots(observations.value));

let ctx: CanvasRenderingContext2D | null = null;
let W = 0,
  H = 0,
  CX = 0,
  CY = 0,
  RAD = 0;
const css = (n: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let C = {
  ink: "",
  muted: "",
  grid: "",
  signal: "",
  sw: "",
  hw: "",
  rc: "",
  review: "",
};
function readColors() {
  C = {
    ink: css("--ink"),
    muted: css("--muted"),
    grid: "#e9e2d2",
    signal: css("--signal"),
    sw: css("--sw"),
    hw: css("--hw"),
    rc: css("--rc"),
    review: css("--review") || "#b4532a",
  };
}
function layout() {
  const cv = canvas.value;
  if (!cv) return;
  ctx = cv.getContext("2d");
  const dpr = Math.min(2, devicePixelRatio || 1);
  W = cv.clientWidth;
  H = cv.clientHeight;
  cv.width = W * dpr;
  cv.height = H * dpr;
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  const mobile = W < 560,
    top = mobile ? 96 : 60;
  RAD = Math.max(80, Math.min(W * 0.3, (H - top - (mobile ? 60 : 30)) / 2));
  CX = W / 2;
  CY = top + (H - top) / 2;
}
const busy = (s: number) => {
  busyUntil = Math.max(busyUntil, clock() + s);
  kick();
};
const kick = () => {
  if (!frame) frame = requestAnimationFrame(loop);
};
const rgba = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
};
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const easeOut = (x: number) => 1 - Math.pow(1 - clamp01(x), 3);
const pol = (a: number, r: number): [number, number] => [
  CX + Math.cos(a) * r,
  CY + Math.sin(a) * r,
];
const filterK = () => (reduceMotion ? 1 : clamp01((clock() - filter.at) / 0.3));
const fade = (match: (f: string | null) => boolean) => {
  const m1 = match(filter.on) ? 1 : 0.15,
    m0 = match(filter.prev) ? 1 : 0.15;
  return m0 + (m1 - m0) * filterK();
};
function text(
  s: string,
  x: number,
  y: number,
  color = C.muted,
  font = "12px 'Noto Sans SC', sans-serif",
  align: CanvasTextAlign = "center",
) {
  if (!ctx) return;
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  ctx.fillText(s, x, y);
}
// 沿圆弧排字；下半圈反向，字头朝外
function arcText(s: string, a: number, r: number, color: string, font: string) {
  if (!ctx) return;
  const c = ctx;
  c.save();
  c.font = font;
  c.fillStyle = color;
  c.textAlign = "center";
  c.textBaseline = "middle";
  const flip = Math.sin(a) > 0.2,
    chars = [...s],
    widths = chars.map((ch) => c.measureText(ch).width),
    total = widths.reduce((x, y) => x + y, 0);
  let cur = a + ((flip ? 1 : -1) * total) / 2 / r;
  chars.forEach((ch, i) => {
    const da = widths[i]! / r,
      mid = cur + ((flip ? -1 : 1) * da) / 2,
      [x, y] = pol(mid, r);
    c.save();
    c.translate(x, y);
    c.rotate(mid + (flip ? -Math.PI / 2 : Math.PI / 2));
    c.fillText(ch, 0, 0);
    c.restore();
    cur += (flip ? -1 : 1) * da;
  });
  c.restore();
}

/* ---------- 样本盘 ---------- */
const tips = new Map<object, [number, number]>();
function drawA(T: number) {
  const c = ctx!;
  const { spokes, slots, step, sector, ordered } = spokeModel.value;
  const r0 = RAD * 0.2,
    r1 = RAD,
    len = (v: number) => r0 + ((r1 - r0) * v) / 100;
  c.lineWidth = 1;
  for (const v of [25, 50, 75, 100]) {
    c.strokeStyle = v === 100 ? rgba(C.ink, 0.3) : C.grid;
    c.setLineDash(v === 100 ? [] : [2, 4]);
    c.beginPath();
    c.arc(CX, CY, len(v), 0, Math.PI * 2);
    c.stroke();
  }
  c.setLineDash([]);
  const sw = sector("softwood"),
    ga = (sw ? sw[1] : 0) + 1.5 * step;
  for (const v of [25, 50, 75, 100]) {
    const [x, y] = pol(ga, len(v));
    c.fillStyle = "#fffefb";
    c.fillRect(x - 13, y - 8, 26, 16);
    text(String(v), x, y, C.muted, "11px 'IBM Plex Mono', monospace");
  }
  const [ux, uy] = pol(ga, len(100) + 16);
  text("°SR", ux, uy, C.muted, "11px 'IBM Plex Mono', monospace");
  c.fillStyle = "#fffefb";
  c.strokeStyle = rgba(C.ink, 0.35);
  c.beginPath();
  c.arc(CX, CY, r0 * 0.78, 0, Math.PI * 2);
  c.fill();
  c.stroke();
  let started = 0;
  for (const p of spokes) {
    const st = spokeStart(p.index, slots);
    if (T >= st || reduceMotion) started++;
    const k = reduceMotion ? 1 : easeOut((T - st) / 0.5);
    if (k <= 0) continue;
    const on = hover?.kind === "A" && hover.key === p;
    c.globalAlpha =
      fade((f) => f === null || f === p.type) *
      (hover?.kind === "A" && !on ? 0.55 : 1);
    // 楔形辐条：占本格 62% 的角宽，相邻之间留缝
    const half = step * (on ? 0.44 : 0.31);
    const wedge = (ra: number, rb: number, col: string) => {
      c.fillStyle = col;
      c.beginPath();
      c.arc(CX, CY, rb, p.angle - half, p.angle + half);
      c.arc(CX, CY, ra, p.angle + half, p.angle - half, true);
      c.closePath();
      c.fill();
    };
    let end: number;
    if (p.type === "blend") {
      // 复配：长度表示配比（满刻度 = 100%），内段针叶、外段阔叶
      const mid = r0 + ((r1 - r0) * p.sample.sw * k) / 100;
      end = r0 + (r1 - r0) * k;
      wedge(r0, mid, C.sw);
      wedge(mid, end, C.hw);
    } else {
      end = r0 + (len(p.sample.sr ?? 0) - r0) * k;
      wedge(r0, end, p.type === "softwood" ? C.sw : C.hw);
    }
    tips.set(p, pol(p.angle, end));
    if (on) {
      const [x, y] = pol(p.angle, end);
      c.globalAlpha = 1;
      c.strokeStyle = C.signal;
      c.lineWidth = 1.5;
      c.beginPath();
      c.arc(x, y, 8 + Math.sin((clock() - hoverAt) * 6) * 1.5, 0, Math.PI * 2);
      c.stroke();
    }
  }
  c.globalAlpha = 1;
  shown.value.A = started;
  const la = reduceMotion ? 1 : clamp01((T - 1.6) / 0.5);
  if (la > 0) {
    c.globalAlpha = la;
    dialMaterials.forEach((t, i) => {
      const sec = sector(t);
      if (!sec) return;
      const [a0, a1] = sec,
        mid = (a0 + a1) / 2,
        col = t === "softwood" ? C.sw : t === "hardwood" ? C.hw : C.ink;
      c.strokeStyle = rgba(C.ink, 0.35);
      c.lineWidth = 1;
      c.beginPath();
      c.arc(CX, CY, r1 + 14, a0, a1);
      c.stroke();
      for (const a of [a0, a1]) {
        c.beginPath();
        c.moveTo(...pol(a, r1 + 10));
        c.lineTo(...pol(a, r1 + 18));
        c.stroke();
      }
      const l = ordered[i]!;
      const sub =
        t === "blend"
          ? `针叶 ${number(l[0]!.sw)}%–${number(l[l.length - 1]!.sw)}%，长度为配比`
          : `${number(l[0]!.revs)}–${number(l[l.length - 1]!.revs)} r，顺时针增加`;
      arcText(
        `${NAME[t]}  ${l.length}`,
        mid,
        r1 + 32,
        col,
        "500 13px 'Noto Sans SC', sans-serif",
      );
      if (W >= 560)
        arcText(sub, mid, r1 + 50, C.muted, "11px 'Noto Sans SC', sans-serif");
    });
    c.globalAlpha = 1;
  }
  const h =
    hover?.kind === "A" ? (hover.key as (typeof spokes)[number]).sample : null;
  if (h) {
    text(
      h.type === "blend"
        ? `${number(h.sw)}/${number(100 - h.sw)}`
        : number(h.sr, 1),
      CX,
      CY - 6,
      C.ink,
      "500 18px 'IBM Plex Mono', monospace",
    );
    text(
      h.type === "blend" ? "针/阔 %" : "°SR",
      CX,
      CY + 14,
      C.muted,
      "11px 'IBM Plex Mono', monospace",
    );
  } else {
    text(
      String(started),
      CX,
      CY - 4,
      C.ink,
      "500 22px 'IBM Plex Mono', monospace",
    );
    text("个样本", CX, CY + 16);
  }
}

/* ---------- 观测盘 ---------- */
function drawB(T: number) {
  const c = ctx!;
  const { dots, blocks, cycles, sector, sectorGap, has } = dotModel.value;
  const ringR = (i: number) =>
      RAD * (0.26 + (0.74 * (i + 0.5)) / blocks.length),
    band = (RAD * 0.74) / blocks.length;
  blocks.forEach((b, i) => {
    for (let cy = 1; cy <= cycles; cy++) {
      const a0 = -Math.PI / 2 + (cy - 1) * sector + sectorGap / 2,
        a1 = a0 + sector - sectorGap;
      c.beginPath();
      c.arc(CX, CY, ringR(i), a0, a1);
      if (has(b, cy)) {
        c.lineWidth = band * 0.78;
        c.strokeStyle =
          i % 2 ? "rgba(233,226,210,.55)" : "rgba(233,226,210,.95)";
      } else {
        c.lineWidth = 1;
        c.strokeStyle = rgba(C.ink, 0.12);
        c.setLineDash([2, 3]);
      }
      c.stroke();
      c.setLineDash([]);
    }
  });
  const swp = reduceMotion ? 2 : (T - 0.25) / 1.7;
  if (swp > 0 && swp < 1) {
    const a = -Math.PI / 2 + swp * Math.PI * 2,
      g = c.createLinearGradient(...pol(a, RAD * 0.2), ...pol(a, RAD));
    g.addColorStop(0, rgba(C.signal, 0));
    g.addColorStop(1, rgba(C.signal, 0.8));
    c.strokeStyle = g;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(...pol(a, RAD * 0.2));
    c.lineTo(...pol(a, RAD + 6));
    c.stroke();
  }
  const dr = Math.max(2.5, Math.min(band * 0.32, 6));
  let started = 0;
  const hv = hover?.kind === "B" ? (hover.key as (typeof dots)[number]) : null;
  for (const d of dots) {
    const st = sweepStart(d.angle);
    if (T >= st || reduceMotion) started++;
    const k = reduceMotion ? 1 : easeOut((T - st) / 0.25);
    if (k <= 0) continue;
    const o = d.obs,
      on = hv === d,
      same = hv && hv.obs.block === o.block && hv.obs.cycle === o.cycle;
    c.globalAlpha =
      fade(
        (f) =>
          f === null ||
          (f === "review"
            ? o.review
            : f.startsWith("g:") && f.slice(2).split(",").includes(o.block)),
      ) * (hv && !same ? 0.45 : 1);
    const [x, y] = pol(d.angle, ringR(d.ring));
    tips.set(d, [x, y]);
    c.fillStyle = o.review ? C.review : C.rc;
    c.beginPath();
    c.arc(x, y, dr * k * (on ? 1.6 : 1), 0, Math.PI * 2);
    c.fill();
    if (o.review) {
      c.strokeStyle = "#fffefb";
      c.lineWidth = 1;
      c.stroke();
    }
  }
  c.globalAlpha = 1;
  shown.value.B = started;
  const la = reduceMotion ? 1 : clamp01((T - 1.9) / 0.5);
  if (la > 0) {
    c.globalAlpha = la;
    for (let cy = 1; cy <= cycles; cy++)
      arcText(
        `第 ${cy} 次循环`,
        -Math.PI / 2 + (cy - 0.5) * sector,
        RAD + 22,
        C.ink,
        "500 13px 'Noto Sans SC', sans-serif",
      );
    blocks.forEach((b, i) => {
      if (RAD < 200 && i % 2 && i !== blocks.length - 1) return;
      const [x, y] = pol(-Math.PI / 2, ringR(i));
      c.fillStyle = "#fffefb";
      c.fillRect(x - 13, y - 6, 26, 12);
      text(b, x, y, C.muted, "10px 'IBM Plex Mono', monospace");
    });
    c.globalAlpha = 1;
  }
  if (hv) {
    text(
      hv.obs.block,
      CX,
      CY - 12,
      C.ink,
      "500 16px 'IBM Plex Mono', monospace",
    );
    text(
      `第 ${hv.obs.cycle} 次 · 重复 ${hv.obs.replicate}`,
      CX,
      CY + 8,
      C.muted,
      "11px 'Noto Sans SC', sans-serif",
    );
  } else {
    text(
      String(started),
      CX,
      CY - 4,
      C.ink,
      "500 22px 'IBM Plex Mono', monospace",
    );
    text("条观测", CX, CY + 16);
  }
}

/* ---------- 绘制循环：开场结束后只在交互时重绘 ---------- */
function loop() {
  frame = 0;
  if (!ctx || loading.value || error.value) return;
  ctx.clearRect(0, 0, W, H);
  const T = now();
  tips.clear();
  if (active.value === "A") drawA(T);
  else drawB(T);
  if (T < 2.6 || clock() < busyUntil) frame = requestAnimationFrame(loop);
}
function replay() {
  t0 = clock();
  kick();
}
function show(set: SetKey) {
  if (active.value !== set) {
    active.value = set;
    hover = null;
    filter.on = filter.prev = null;
  }
  replay();
}
function setFilter(next: string | null) {
  if (filter.on === next) return;
  filter.prev = filter.on;
  filter.on = next;
  filter.at = clock();
  busy(0.4);
}
function enterRow(set: SetKey, key: string) {
  if (active.value !== set) show(set);
  setFilter(key);
}

/* ---------- 悬停：辐条按角度命中，观测点按距离命中 ---------- */
const tipHtml = ref("");
const tipPos = ref({ x: 0, y: 0, on: false });
function pick(x: number, y: number) {
  if (active.value === "A") {
    const { spokes, step } = spokeModel.value;
    const r = Math.hypot(x - CX, y - CY);
    if (r < RAD * 0.2 || r > RAD + 6) return null;
    const a = Math.atan2(y - CY, x - CX);
    let best = null,
      bd = step * 0.6;
    for (const p of spokes) {
      const d = Math.abs(
        Math.atan2(Math.sin(a - p.angle), Math.cos(a - p.angle)),
      );
      if (d < bd) {
        bd = d;
        best = p;
      }
    }
    return best ? { kind: "A" as SetKey, key: best } : null;
  }
  let best = null,
    bd = 9;
  for (const d of dotModel.value.dots) {
    const xy = tips.get(d);
    if (!xy) continue;
    const dd = Math.hypot(xy[0] - x, xy[1] - y);
    if (dd < bd) {
      bd = dd;
      best = d;
    }
  }
  return best ? { kind: "B" as SetKey, key: best } : null;
}
function describe(h: { kind: SetKey; key: object }) {
  if (h.kind === "A") {
    const s = (h.key as ReturnType<typeof buildSpokes>["spokes"][number])
      .sample;
    return `<div class="t1">${s.code}</div><div>${s.name}</div><div class="t3"><span>${s.type === "blend" ? `针叶 ${number(s.sw)}%，阔叶 ${number(100 - s.sw)}%` : `打浆转数 ${number(s.revs)} r`}</span><b>${s.type === "blend" ? "端点按纯浆打浆条件" : `${number(s.sr, 1)} °SR`}</b></div>`;
  }
  const o = (h.key as ReturnType<typeof buildDots>["dots"][number]).obs;
  return `<div class="t1">${o.block}，第 ${o.cycle} 次循环，重复 ${o.replicate}</div><div>${o.grade ?? "原料未注明"}，工作簿第 ${o.row} 行</div><div class="t3"><span>长度加权纤维长度</span><b>${number(o.fl, 3)} mm</b></div>${o.review ? `<div class="t3 rev"><span>待复核</span><span>长度分布合计偏离 100%</span></div>` : ""}`;
}
function move(e: PointerEvent) {
  const b = canvas.value!.getBoundingClientRect();
  const h = pick(e.clientX - b.left, e.clientY - b.top);
  if ((h?.key ?? null) !== (hover?.key ?? null)) {
    hover = h;
    hoverAt = clock();
    busy(1.2);
  }
  if (h) {
    tipHtml.value = describe(h);
    tipPos.value = { x: e.clientX + 14, y: e.clientY - 12, on: true };
  } else tipPos.value.on = false;
}
function leave() {
  hover = null;
  tipPos.value.on = false;
  busy(0.3);
}
// 提示框贴着指针，但不超出视口
const tipStyle = computed(() => {
  const el = tip.value,
    w = el?.offsetWidth ?? 220,
    hgt = el?.offsetHeight ?? 80;
  return {
    left: `${Math.min(innerWidth - w - 8, tipPos.value.x)}px`,
    top: `${Math.max(8, tipPos.value.y - hgt)}px`,
  };
});

let observer: ResizeObserver | undefined;
onMounted(() => {
  readColors();
  observer = new ResizeObserver(() => {
    layout();
    kick();
  });
  if (stage.value) observer.observe(stage.value);
  void load();
});
watch([samples, observations], () => {
  layout();
  replay();
});
watch(loading, (v) => {
  if (!v)
    requestAnimationFrame(() => {
      layout();
      replay();
    });
});
onBeforeUnmount(() => {
  controller?.abort();
  observer?.disconnect();
  cancelAnimationFrame(frame);
});
const caption = computed(() =>
  active.value === "A"
    ? {
        title: "样本盘",
        text: "一根辐条一个样本，长度为打浆度（°SR）",
        link: "beating",
        linkText: "查看打浆分析",
      }
    : {
        title: "观测盘",
        text: "一点一条观测；环为数据块（内 G01 → 外 G14），扇区为循环次数，虚线为没有该次循环",
        link: "recycled",
        linkText: "查看再生纸浆循环",
      },
);
const blendNote = computed(() =>
  blendRange.value
    ? `针叶 ${number(blendRange.value[0])}%–${number(blendRange.value[1])}%`
    : "",
);
</script>

<template>
  <div class="dials">
    <div v-if="error" class="card dials-state" role="alert">
      <TriangleAlert :size="20" /><span>{{ error }}</span>
      <button class="button" type="button" @click="load">重新读取</button>
    </div>
    <template v-else>
      <section class="sets" aria-label="数据清单" :aria-busy="loading">
        <div
          v-for="set in ['A', 'B'] as const"
          :key="set"
          class="set"
          :data-active="active === set"
        >
          <button
            class="set-head"
            type="button"
            :aria-pressed="active === set"
            @click="show(set)"
          >
            <span class="k">{{
              set === "A" ? "唯一物理样本" : "再生纸浆观测"
            }}</span>
            <span class="v" :class="{ skeleton: loading }"
              ><span>{{
                loading
                  ? "—"
                  : active === set
                    ? shown[set]
                    : set === "A"
                      ? samples.length
                      : observations.length
              }}</span
              ><small>{{ set === "A" ? "个" : "条" }}</small></span
            >
            <span class="hint">{{
              active === set
                ? set === "A"
                  ? "样本盘"
                  : "观测盘"
                : set === "A"
                  ? "查看样本盘"
                  : "查看观测盘"
            }}</span>
          </button>
          <ul class="rows">
            <li v-for="r in set === 'A' ? rowsA : rowsB" :key="r.key">
              <button
                type="button"
                @pointerenter="enterRow(set, r.key)"
                @focus="enterRow(set, r.key)"
                @pointerleave="setFilter(null)"
                @blur="setFilter(null)"
              >
                <i
                  :class="{ tri: r.tri }"
                  :style="r.tri ? {} : { background: r.swatch }"
                ></i
                ><span>{{ r.label }}</span
                ><b>{{ r.count }}</b
                ><span class="bar"
                  ><span
                    :style="{
                      width: `${r.total ? (r.count / r.total) * 100 : 0}%`,
                      background: r.bar,
                    }"
                  ></span
                ></span>
              </button>
            </li>
          </ul>
        </div>
      </section>

      <section ref="stage" class="stage" aria-label="刻度盘">
        <canvas
          ref="canvas"
          role="img"
          :aria-label="
            active === 'A'
              ? `样本盘：${samples.length} 根辐条对应 ${samples.length} 个物理样本，长度为打浆度；复配样本 ${blendNote}`
              : `观测盘：${observations.length} 个点对应 ${observations.length} 条再生纸浆观测，其中 ${reviewCount} 条待复核`
          "
          @pointermove="move"
          @pointerleave="leave"
        ></canvas>
        <div class="cap">
          <span
            ><b>{{ caption.title }}</b
            >{{ caption.text }}</span
          ><span class="tools"
            ><button type="button" @click="replay">重新演示</button
            ><RouterLink :to="`/${caption.link}`">{{
              caption.linkText
            }}</RouterLink></span
          >
        </div>
        <p v-if="loading" class="stage-loading" role="status">
          正在读取样本与观测…
        </p>
      </section>
    </template>
    <div
      ref="tip"
      class="dial-tip"
      :class="{ on: tipPos.on }"
      :style="tipStyle"
      aria-hidden="true"
      v-html="tipHtml"
    ></div>
  </div>
</template>

<style scoped>
.dials {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 22px;
}
.sets {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.set {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 2px;
  box-shadow: 0 1px 2px rgba(60, 45, 20, 0.06);
  padding: 16px 20px 14px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 28px;
  align-items: start;
  transition: border-color 0.2s;
}
.set[data-active="true"] {
  border-color: var(--signal);
  box-shadow:
    inset 0 3px 0 var(--signal),
    0 1px 2px rgba(60, 45, 20, 0.06);
}
.set-head {
  all: unset;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 132px;
}
.set-head:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 4px;
}
.set-head .k {
  font: 700 15px/1.4 var(--font-serif);
  color: var(--ink);
}
.set-head .v {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font: 400 64px/1 var(--font-mono);
  letter-spacing: -0.05em;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.set-head .v small {
  font-family: inherit;
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0;
  color: var(--muted);
}
.set-head .hint {
  font-size: 12px;
  color: var(--signal);
}
.set[data-active="true"] .hint {
  color: var(--muted);
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.rows button {
  all: unset;
  box-sizing: border-box;
  width: 100%;
  display: grid;
  grid-template-columns: 12px 1fr auto;
  align-items: center;
  gap: 4px 10px;
  padding: 6px 8px;
  border-radius: 2px;
  font-size: 13px;
  color: var(--ink-2);
}
.rows button:hover,
.rows button:focus-visible {
  background: var(--signal-tint);
  color: var(--ink);
}
.rows button:focus-visible {
  outline: 2px solid var(--signal);
}
.rows i {
  width: 10px;
  height: 10px;
  border-radius: 1px;
}
.rows i.tri {
  width: 0;
  height: 0;
  border-radius: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 9px solid var(--review);
}
.rows b {
  font: 500 14px var(--font-mono);
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.rows .bar {
  grid-column: 2 / 4;
  height: 3px;
  background: #e9e2d2;
  position: relative;
}
.rows .bar span {
  position: absolute;
  inset: 0 auto 0 0;
}
.stage {
  position: relative;
  height: max(560px, calc(100vh - 360px));
  background: var(--paper);
  border: 1px solid var(--border-strong);
  border-radius: 2px;
  box-shadow:
    0 1px 2px rgba(60, 45, 20, 0.08),
    0 6px 18px -10px rgba(60, 45, 20, 0.22);
  overflow: hidden;
}
.stage canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.cap {
  position: absolute;
  left: 20px;
  right: 20px;
  top: 16px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: baseline;
  font-size: 12px;
  color: var(--muted);
  pointer-events: none;
}
.cap b {
  font: 700 16px var(--font-serif);
  color: var(--ink);
  margin-right: 10px;
}
.cap .tools {
  display: flex;
  gap: 8px;
  pointer-events: auto;
}
.cap button,
.cap a {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--border);
  background: var(--paper);
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.cap button:hover,
.cap a:hover {
  border-color: var(--border-strong);
  color: var(--ink);
}
.stage-loading,
.dials-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--muted);
}
.stage-loading {
  position: absolute;
  inset: 0;
  margin: 0;
}
.dials-state {
  padding: 48px 24px;
}
.dial-tip {
  position: fixed;
  z-index: 30;
  pointer-events: none;
  min-width: 200px;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  box-shadow: 0 8px 22px -10px rgba(60, 45, 20, 0.45);
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-2);
  display: none;
}
.dial-tip.on {
  display: block;
}
.dial-tip :deep(.t1) {
  font: 500 13px var(--font-mono);
  color: var(--ink);
}
.dial-tip :deep(.t3) {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.dial-tip :deep(.t3 b) {
  font: 500 12px var(--font-mono);
  color: var(--ink);
}
.dial-tip :deep(.rev) {
  color: var(--review);
}
@media (max-width: 1180px) {
  .set {
    grid-template-columns: 1fr;
  }
  .set-head .v {
    font-size: 52px;
  }
}
@media (max-width: 720px) {
  .sets {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .set {
    padding: 12px;
  }
  .set-head {
    min-width: 0;
  }
  .set-head .v {
    font-size: 40px;
  }
  .set[data-active="false"] .rows {
    display: none;
  }
  .stage {
    height: 440px;
  }
  .cap {
    flex-direction: column;
    gap: 6px;
  }
}
</style>
