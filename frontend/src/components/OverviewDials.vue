<script setup lang="ts">
// 数据总览：刻度盘舞台与两组数据清单。
// 样本盘：一根辐条一个物理样本，长度为打浆度；观测盘：一点一条再生纸浆观测。
// 偏光：暗场视野、十字分划与发光辐条（纤维束端面）；花园：玻璃透镜上的柔和花瓣。
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ArrowRight, RotateCcw, TriangleAlert } from "lucide-vue-next";
import { get, number, type ListResult, type Sample } from "../api";
import { mode, reducedMotion } from "../mode";
import { paletteFor } from "../palette";
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
  type Spoke,
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

defineProps<{
  /** 下方样本库当前的类型筛选（"" 为全部），样本盘清单行按下态跟随它 */
  activeType?: string;
}>();
const emit = defineEmits<{
  /** 点击样本盘清单行：筛选下方样本库（再次点击同一类型取消） */
  pickType: [type: DialMaterial];
}>();

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
const selectedObservation = ref<DialObservation | null>(null);

/* ---------- 读取 ---------- */
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  selectedObservation.value = null;
  leave();
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
type RowKind = DialMaterial | "recycled" | "review";
interface Row {
  key: string;
  label: string;
  count: number;
  total: number;
  kind: RowKind;
}
const rowsA = computed<Row[]>(() =>
  dialMaterials.map((t) => ({
    key: t,
    label: t === "blend" ? "针阔复配（按配比分段）" : NAME[t],
    count: byType(t).length,
    total: samples.value.length,
    kind: t,
  })),
);
const rowsB = computed<Row[]>(() => [
  ...groups.value.map((g) => ({
    key: `g:${g.blocks.join(",")}`,
    label: `${g.blocks[0]}${g.blocks.length > 1 ? `–${g.blocks[g.blocks.length - 1]}` : ""}，${g.cycles} 次循环 × ${g.replicates} 重复`,
    count: g.count,
    total: observations.value.length,
    kind: "recycled" as const,
  })),
  {
    key: "review",
    label: "待复核：长度分布合计偏离 100%",
    count: reviewCount.value,
    total: observations.value.length,
    kind: "review",
  },
]);
const share = (r: Row) => (r.total ? (r.count / r.total) * 100 : 0);
const rowsOf = (set: SetKey) => (set === "A" ? rowsA.value : rowsB.value);
function clickRow(set: SetKey, r: Row) {
  if (set === "A") emit("pickType", r.key as DialMaterial);
}

/* ---------- 画布、时钟与交互状态 ---------- */
const canvas = ref<HTMLCanvasElement>();
const stage = ref<HTMLElement>();
const tip = ref<HTMLElement>();
const observationDetails = ref<HTMLElement>();
const still = () => reducedMotion.value;
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
type Dot = ReturnType<typeof buildDots>["dots"][number];
type Hit = { kind: "A"; key: Spoke } | { kind: "B"; key: Dot };
let hover: Hit | null = null,
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
const TAU = Math.PI * 2;
/** 视野光阑（CSS 圆环）的位置，跟随画布布局 */
const field = ref({ cx: 0, cy: 0, r: 0 });

/* ---------- 颜色与字体：来自当前模式的 palette 与字体 token，切换模式时重读 ---------- */
let polar = mode.value === "polarized";
let C = {
  ink: "",
  muted: "",
  grid: "",
  axis: "",
  paper: "",
  accent: "",
  focus: "",
  sw: "",
  hw: "",
  swInk: "",
  hwInk: "",
  rc: "",
  review: "",
};
const F = { body: "sans-serif", mono: "monospace", display: "sans-serif" };
function readTheme() {
  const p = paletteFor(mode.value);
  polar = mode.value === "polarized";
  C = {
    ink: p.chart.textStrong,
    muted: p.chart.text,
    grid: p.chart.grid,
    axis: p.chart.axis,
    paper: p.chart.paper,
    accent: p.chart.accent,
    focus: p.chart.focus,
    sw: p.material.softwood,
    hw: p.material.hardwood,
    swInk: p.materialInk.softwood,
    hwInk: p.materialInk.hardwood,
    rc: p.chart.recycled,
    review: p.chart.review,
  };
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback;
  F.body = token("--font-body", "sans-serif");
  F.mono = token("--font-mono", "monospace");
  F.display = token("--font-display", "sans-serif");
}
const font = (
  size: number,
  kind: keyof typeof F = "body",
  weight: number = 400,
) => `${weight} ${size}px ${F[kind]}`;
const displayWeight = () => (polar ? 200 : 400);
// 模式字体按需加载：加载完成后重绘一次，画布文字换成新字体
function loadFonts() {
  const fonts = document.fonts;
  if (!fonts?.load) return;
  const wanted = [
    font(13, "body", 500),
    font(11, "mono"),
    font(30, "display", displayWeight()),
  ];
  void Promise.all(wanted.map((f) => fonts.load(f).catch(() => [])))
    .then(() => kick())
    .catch(() => undefined);
}

function layout() {
  const cv = canvas.value;
  if (!cv) return;
  ctx = cv.getContext("2d");
  const dpr = Math.min(2, devicePixelRatio || 1);
  W = cv.clientWidth;
  H = cv.clientHeight;
  cv.width = Math.round(W * dpr);
  cv.height = Math.round(H * dpr);
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  // 外圈留出扇区标签：窄屏只有一行标签
  const pad = W < 560 ? 44 : 66;
  RAD = Math.max(70, Math.min(W / 2 - pad, H / 2 - pad));
  CX = W / 2;
  CY = H / 2;
  field.value = { cx: CX, cy: CY, r: Math.max(0, Math.min(W, H) / 2 - 6) };
}
const busy = (s: number) => {
  busyUntil = Math.max(busyUntil, clock() + s);
  kick();
};
const kick = () => {
  if (!frame) frame = requestAnimationFrame(loop);
};
// palette 里既有 #RRGGBB 也有 rgba()：统一乘上透明度
function alpha(color: string, a: number) {
  const c = color.trim();
  if (c.startsWith("#")) {
    let h = c.slice(1);
    if (h.length === 3)
      h = [...h].map((x) => x + x).join("");
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
  }
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b, al = "1"] = m[1]!.split(",").map((s) => s.trim());
    return `rgba(${r},${g},${b},${Number(al) * a})`;
  }
  return c;
}
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const easeOut = (x: number) => 1 - Math.pow(1 - clamp01(x), 3);
const pol = (a: number, r: number): [number, number] => [
  CX + Math.cos(a) * r,
  CY + Math.sin(a) * r,
];
const filterK = () => (still() ? 1 : clamp01((clock() - filter.at) / 0.3));
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
  f = font(12),
  align: CanvasTextAlign = "center",
) {
  if (!ctx) return;
  ctx.fillStyle = color;
  ctx.font = f;
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  ctx.fillText(s, x, y);
}
// 刻度数字：先垫一块纸色底，避免压在环线上
function tag(s: string, x: number, y: number, size = 10.5) {
  if (!ctx) return;
  ctx.font = font(size, "mono");
  const w = ctx.measureText(s).width + 8;
  ctx.fillStyle = C.paper;
  if (polar) ctx.fillRect(x - w / 2, y - 7, w, 14);
  else {
    ctx.beginPath();
    ctx.roundRect(x - w / 2, y - 8, w, 16, 8);
    ctx.fill();
  }
  text(s, x, y, C.muted, font(size, "mono"));
}
// 沿圆弧排字；下半圈反向，字头朝外
function arcText(s: string, a: number, r: number, color: string, f: string) {
  if (!ctx) return;
  const c = ctx;
  c.save();
  c.font = f;
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

/* ---------- 共用底图 ---------- */
// 偏光：十字分划与刻度（目镜分划板）
function drawReticle() {
  if (!polar || !ctx) return;
  const c = ctx,
    ext = Math.min(W, H) / 2 - 10,
    step = RAD / 10;
  c.save();
  c.strokeStyle = C.grid;
  c.lineWidth = 1;
  c.beginPath();
  c.moveTo(CX - ext, CY);
  c.lineTo(CX + ext, CY);
  c.moveTo(CX, CY - ext);
  c.lineTo(CX, CY + ext);
  for (let i = 1; i * step <= ext; i++) {
    const d = i * step,
      t = i % 5 === 0 ? 5 : 2.5;
    for (const s of [-1, 1]) {
      c.moveTo(CX + s * d, CY - t);
      c.lineTo(CX + s * d, CY + t);
      c.moveTo(CX - t, CY + s * d);
      c.lineTo(CX + t, CY + s * d);
    }
  }
  c.stroke();
  c.restore();
}
// 中心圆盘：偏光为暗场中的细圈，花园为带柔影的纸片
function drawHub(r: number) {
  const c = ctx!;
  c.save();
  if (!polar) {
    c.shadowColor = alpha(C.ink, 0.18);
    c.shadowBlur = 22;
    c.shadowOffsetY = 6;
  }
  c.fillStyle = C.paper;
  c.beginPath();
  c.arc(CX, CY, r, 0, TAU);
  c.fill();
  c.restore();
  c.strokeStyle = polar ? C.axis : alpha(C.ink, 0.1);
  c.lineWidth = 1;
  c.beginPath();
  c.arc(CX, CY, r, 0, TAU);
  c.stroke();
}
function hubCount(value: number, unit: string) {
  text(
    String(value),
    CX,
    CY - 6,
    C.ink,
    font(polar ? 28 : 32, "display", displayWeight()),
  );
  text(unit, CX, CY + 19, C.muted, font(11.5));
}

/* ---------- 样本盘 ---------- */
const spokeBounds = new Map<
  Spoke,
  { inner: number; outer: number; half: number }
>();
const dotPositions = new Map<Dot, [number, number]>();
function drawA(T: number) {
  const c = ctx!;
  const { spokes, slots, step, sector, ordered } = spokeModel.value;
  const r0 = RAD * 0.2,
    r1 = RAD,
    len = (v: number) => r0 + ((r1 - r0) * v) / 100;
  drawReticle();
  c.lineWidth = 1;
  for (const v of [25, 50, 75, 100]) {
    c.strokeStyle = v === 100 ? C.axis : alpha(C.ink, polar ? 0.2 : 0.16);
    c.setLineDash(v === 100 ? [] : polar ? [1, 4] : [2, 5]);
    c.beginPath();
    c.arc(CX, CY, len(v), 0, TAU);
    c.stroke();
  }
  c.setLineDash([]);
  drawHub(r0 * 0.78);
  let started = 0;
  for (const p of spokes) {
    const st = spokeStart(p.index, slots);
    if (T >= st || still()) started++;
    const k = still() ? 1 : easeOut((T - st) / 0.5);
    if (k <= 0) continue;
    const on = hover?.kind === "A" && hover.key === p;
    const a =
      fade((f) => f === null || f === p.type) *
      (hover?.kind === "A" && !on ? 0.55 : 1);
    // 楔形辐条：占本格 62% 的角宽，相邻之间留缝
    const half = step * (on ? 0.44 : 0.31);
    let end: number;
    if (p.type === "blend") {
      // 复配：长度表示配比（满刻度 = 100%），内段针叶、外段阔叶
      const mid = r0 + ((r1 - r0) * p.sample.sw * k) / 100;
      end = r0 + (r1 - r0) * k;
      spoke(p.angle, half, r0, mid, end, C.sw, a, on, false);
      spoke(p.angle, half, mid, end, end, C.hw, a, on, true);
    } else {
      end = r0 + (len(p.sample.sr ?? 0) - r0) * k;
      spoke(
        p.angle,
        half,
        r0,
        end,
        end,
        p.type === "softwood" ? C.sw : C.hw,
        a,
        on,
        true,
      );
    }
    if (end > r0) spokeBounds.set(p, { inner: r0, outer: end, half });
    if (on) {
      const [x, y] = pol(p.angle, end + (polar ? 0 : 3));
      c.strokeStyle = C.focus;
      c.lineWidth = 1.5;
      c.beginPath();
      c.arc(x, y, 8 + Math.sin((clock() - hoverAt) * 6) * 1.5, 0, TAU);
      c.stroke();
    }
  }
  c.globalAlpha = 1;
  shown.value.A = started;
  // 刻度数字放在针叶木扇区之后的空档里
  const sw = sector("softwood"),
    ga = (sw ? sw[1] : 0) + 1.5 * step;
  for (const v of [25, 50, 75, 100]) {
    const [x, y] = pol(ga, len(v));
    tag(String(v), x, y);
  }
  const [ux, uy] = pol(ga, len(100) + 17);
  text("°SR", ux, uy, C.muted, font(10.5, "mono"));
  const la = still() ? 1 : clamp01((T - 1.6) / 0.5);
  if (la > 0) {
    c.globalAlpha = la;
    dialMaterials.forEach((t, i) => {
      const sec = sector(t);
      if (!sec) return;
      const [a0, a1] = sec,
        mid = (a0 + a1) / 2,
        col = t === "softwood" ? C.swInk : t === "hardwood" ? C.hwInk : C.ink;
      c.strokeStyle = C.axis;
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
      arcText(`${NAME[t]}  ${l.length}`, mid, r1 + 32, col, font(13, "body", 500));
      if (W >= 560) arcText(sub, mid, r1 + 50, C.muted, font(11));
    });
    c.globalAlpha = 1;
  }
  const h = hover?.kind === "A" ? hover.key.sample : null;
  if (h) {
    text(
      h.type === "blend"
        ? `${number(h.sw)}/${number(100 - h.sw)}`
        : number(h.sr, 1),
      CX,
      CY - 6,
      C.ink,
      font(17, "mono", 500),
    );
    text(h.type === "blend" ? "针/阔 %" : "°SR", CX, CY + 14, C.muted, font(10.5, "mono"));
  } else hubCount(started, "个样本");
}
// 一段辐条。偏光：由暗到亮的发光楔形（叠加混合）；花园：圆头花瓣
function spoke(
  angle: number,
  half: number,
  ra: number,
  rb: number,
  tipR: number,
  col: string,
  a: number,
  on: boolean,
  tip: boolean,
) {
  const c = ctx!;
  if (rb <= ra) return;
  c.save();
  c.globalAlpha = a;
  if (polar) {
    c.globalCompositeOperation = "lighter";
    const g = c.createLinearGradient(...pol(angle, RAD * 0.2), ...pol(angle, tipR));
    g.addColorStop(0, alpha(col, 0.16));
    g.addColorStop(1, col);
    c.fillStyle = g;
    c.shadowColor = alpha(col, 0.8);
    c.shadowBlur = on ? 18 : 8;
    c.beginPath();
    c.arc(CX, CY, rb, angle - half, angle + half);
    c.arc(CX, CY, ra, angle + half, angle - half, true);
    c.closePath();
    c.fill();
  } else {
    // 圆头收在数值处：楔形到 rb − cap，再接一个半径为 cap 的圆
    const cap = tip ? Math.min(half * rb, (rb - ra) / 2) : 0;
    const body = rb - cap;
    c.fillStyle = col;
    c.beginPath();
    c.arc(CX, CY, body, angle - half, angle + half);
    c.arc(CX, CY, ra, angle + half, angle - half, true);
    c.closePath();
    c.fill();
    if (cap > 0.5) {
      const [x, y] = pol(angle, body);
      c.beginPath();
      c.arc(x, y, cap, 0, TAU);
      c.fill();
    }
  }
  c.restore();
}

/* ---------- 观测盘 ---------- */
function drawB(T: number) {
  const c = ctx!;
  const { dots, blocks, cycles, sector, sectorGap, has } = dotModel.value;
  const ringR = (i: number) =>
      RAD * (0.26 + (0.74 * (i + 0.5)) / blocks.length),
    band = (RAD * 0.74) / blocks.length;
  drawReticle();
  blocks.forEach((b, i) => {
    for (let cy = 1; cy <= cycles; cy++) {
      const a0 = -Math.PI / 2 + (cy - 1) * sector + sectorGap / 2,
        a1 = a0 + sector - sectorGap;
      c.beginPath();
      c.arc(CX, CY, ringR(i), a0, a1);
      if (has(b, cy)) {
        c.lineWidth = band * 0.78;
        c.lineCap = polar ? "butt" : "round";
        c.strokeStyle = polar
          ? alpha(C.ink, i % 2 ? 0.045 : 0.085)
          : alpha(C.rc, i % 2 ? 0.1 : 0.18);
      } else {
        c.lineWidth = 1;
        c.strokeStyle = alpha(C.ink, polar ? 0.22 : 0.18);
        c.setLineDash([2, 3]);
      }
      c.stroke();
      c.setLineDash([]);
      c.lineCap = "butt";
    }
  });
  drawHub(RAD * 0.2);
  const swp = still() ? 2 : (T - 0.25) / 1.7;
  if (swp > 0 && swp < 1) {
    const a = -Math.PI / 2 + swp * TAU,
      g = c.createLinearGradient(...pol(a, RAD * 0.2), ...pol(a, RAD));
    g.addColorStop(0, alpha(C.accent, 0));
    g.addColorStop(1, alpha(C.accent, 0.85));
    c.strokeStyle = g;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(...pol(a, RAD * 0.2));
    c.lineTo(...pol(a, RAD + 6));
    c.stroke();
  }
  const dr = Math.max(2.5, Math.min(band * 0.32, 6));
  let started = 0;
  const hv = hover?.kind === "B" ? hover.key : null;
  for (const d of dots) {
    const st = sweepStart(d.angle);
    if (T >= st || still()) started++;
    const k = still() ? 1 : easeOut((T - st) / 0.25);
    if (k <= 0) continue;
    const o = d.obs,
      on = hv === d,
      same = hv && hv.obs.block === o.block && hv.obs.cycle === o.cycle;
    const [x, y] = pol(d.angle, ringR(d.ring));
    dotPositions.set(d, [x, y]);
    c.save();
    c.globalAlpha =
      fade(
        (f) =>
          f === null ||
          (f === "review"
            ? o.review
            : f.startsWith("g:") && f.slice(2).split(",").includes(o.block)),
      ) * (hv && !same ? 0.45 : 1);
    const r = dr * k * (on ? 1.6 : 1);
    if (polar) {
      c.shadowColor = alpha(o.review ? C.review : C.rc, 0.9);
      c.shadowBlur = on ? 14 : 6;
    }
    c.fillStyle = o.review ? C.review : C.rc;
    c.beginPath();
    if (o.review) {
      // 待复核：三角形，和清单里的标记一致
      const s = r * 1.35;
      c.moveTo(x, y - s);
      c.lineTo(x + s * 0.92, y + s * 0.6);
      c.lineTo(x - s * 0.92, y + s * 0.6);
      c.closePath();
    } else c.arc(x, y, r, 0, TAU);
    c.fill();
    if (o.review) {
      c.shadowBlur = 0;
      c.strokeStyle = C.paper;
      c.lineWidth = 1;
      c.stroke();
    }
    c.restore();
  }
  c.globalAlpha = 1;
  shown.value.B = started;
  const la = still() ? 1 : clamp01((T - 1.9) / 0.5);
  if (la > 0) {
    c.globalAlpha = la;
    for (let cy = 1; cy <= cycles; cy++)
      arcText(
        `第 ${cy} 次循环`,
        -Math.PI / 2 + (cy - 0.5) * sector,
        RAD + 22,
        C.ink,
        font(13, "body", 500),
      );
    // 环带比标签矮时隔环标注，最内与最外两环始终标出
    const last = blocks.length - 1;
    blocks.forEach((b, i) => {
      if (band < 15 && i !== last && (i % 2 || i === last - 1)) return;
      const [x, y] = pol(-Math.PI / 2, ringR(i));
      tag(b, x, y, 10);
    });
    c.globalAlpha = 1;
  }
  if (hv) {
    text(hv.obs.block, CX, CY - 10, C.ink, font(15, "mono", 500));
    text(
      `第 ${hv.obs.cycle} 次 · 重复 ${hv.obs.replicate}`,
      CX,
      CY + 10,
      C.muted,
      font(10.5),
    );
  } else hubCount(started, "条观测");
}

/* ---------- 绘制循环：开场结束后只在交互时重绘 ---------- */
function loop() {
  frame = 0;
  if (!ctx || loading.value || error.value) return;
  ctx.clearRect(0, 0, W, H);
  const T = now();
  spokeBounds.clear();
  dotPositions.clear();
  if (active.value === "A") drawA(T);
  else drawB(T);
  if ((T < 2.6 && !still()) || clock() < busyUntil)
    frame = requestAnimationFrame(loop);
}
function replay() {
  spokeBounds.clear();
  dotPositions.clear();
  leave();
  t0 = clock();
}
function show(set: SetKey) {
  if (active.value !== set) {
    active.value = set;
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

/* ---------- 刻度盘命中与详情 ---------- */
const tipContent = ref<ReturnType<typeof describe> | null>(null);
const tipPos = ref({ x: 0, y: 0, on: false });
function pick(x: number, y: number): Hit | null {
  if (active.value === "A") {
    const r = Math.hypot(x - CX, y - CY);
    const a = Math.atan2(y - CY, x - CX);
    for (const [p, { inner, outer, half }] of spokeBounds) {
      if (r < inner || r > outer) continue;
      const d = Math.abs(
        Math.atan2(Math.sin(a - p.angle), Math.cos(a - p.angle)),
      );
      if (d <= half) return { kind: "A", key: p };
    }
    return null;
  }
  let best = null,
    bd = 9;
  for (const [d, xy] of dotPositions) {
    const dd = Math.hypot(xy[0] - x, xy[1] - y);
    if (dd < bd) {
      bd = dd;
      best = d;
    }
  }
  return best ? { kind: "B", key: best } : null;
}
function observationTitle(o: DialObservation) {
  return `${o.block}，第 ${o.cycle} 次循环，重复 ${o.replicate}`;
}
function describeObservation(o: DialObservation) {
  return {
    title: observationTitle(o),
    subtitle: `${o.grade ?? "原料未注明"}，工作簿第 ${o.row} 行`,
    label: "长度加权纤维长度",
    value: `${number(o.fl, 3)} mm`,
    review: o.review,
  };
}
const selectedDetail = computed(() =>
  selectedObservation.value
    ? describeObservation(selectedObservation.value)
    : null,
);
function describe(h: Hit) {
  if (h.kind === "A") {
    const s = h.key.sample;
    return {
      title: s.code,
      subtitle: s.name,
      label:
        s.type === "blend"
          ? `针叶 ${number(s.sw)}%，阔叶 ${number(100 - s.sw)}%`
          : `打浆转数 ${number(s.revs)} r`,
      value:
        s.type === "blend" ? "端点按纯浆打浆条件" : `${number(s.sr, 1)} °SR`,
      review: false,
    };
  }
  return describeObservation(h.key.obs);
}
function pickAt(e: MouseEvent) {
  if (loading.value || error.value || !canvas.value) return null;
  const b = canvas.value.getBoundingClientRect();
  return pick(e.clientX - b.left, e.clientY - b.top);
}
function selectDot(e: MouseEvent) {
  const hit = pickAt(e);
  if (hit?.kind !== "B") return;
  selectedObservation.value = hit.key.obs;
  leave();
  observationDetails.value?.scrollIntoView({ block: "nearest" });
}
function move(e: PointerEvent) {
  if (e.pointerType === "touch") return;
  const h = pickAt(e);
  if ((h?.key ?? null) !== (hover?.key ?? null)) {
    hover = h;
    tipContent.value = h ? describe(h) : null;
    hoverAt = clock();
    busy(1.2);
  }
  if (h) {
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
const fieldStyle = computed(() => ({
  left: `${field.value.cx - field.value.r}px`,
  top: `${field.value.cy - field.value.r}px`,
  width: `${field.value.r * 2}px`,
  height: `${field.value.r * 2}px`,
}));

let observer: ResizeObserver | undefined;
onMounted(() => {
  readTheme();
  loadFonts();
  document.fonts?.addEventListener?.("loadingdone", kick);
  observer = new ResizeObserver(() => {
    layout();
    kick();
  });
  if (stage.value) observer.observe(stage.value);
  void load();
});
watch(
  stage,
  (current, previous) => {
    if (previous) observer?.unobserve(previous);
    if (current) observer?.observe(current);
  },
  { flush: "post" },
);
watch(
  loading,
  (pending) => {
    if (!pending && !error.value) {
      layout();
      replay();
    }
  },
  { flush: "post" },
);
// 切换模式不重播开场：重读颜色与字体，按当前状态重绘一帧
watch(
  mode,
  () => {
    readTheme();
    loadFonts();
    kick();
  },
  { flush: "post" },
);
// 打开“减少动态效果”时立即停在终态
watch(reducedMotion, () => kick());
onBeforeUnmount(() => {
  controller?.abort();
  observer?.disconnect();
  cancelAnimationFrame(frame);
  frame = 0;
  document.fonts?.removeEventListener?.("loadingdone", kick);
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
const total = (set: SetKey) =>
  set === "A" ? samples.value.length : observations.value.length;
</script>

<template>
  <div class="dials">
    <div v-if="error" class="card dials-state" role="alert">
      <TriangleAlert :size="20" /><span>{{ error }}</span>
      <button class="button" type="button" @click="load">重新读取</button>
    </div>
    <section
      v-else
      class="card dials-tile"
      :data-set="active"
      aria-labelledby="dials-title"
    >
      <header class="dials-head">
        <div class="dials-heading">
          <p class="dials-kicker" aria-hidden="true">
            <span class="dials-kicker-pz">{{
              active === "A" ? "Dial A · spokes" : "Dial B · points"
            }}</span
            ><span class="dials-kicker-gd">{{
              active === "A" ? "Sample dial" : "Observation dial"
            }}</span>
          </p>
          <h2 id="dials-title">{{ caption.title }}</h2>
          <p class="dials-sub">{{ caption.text }}</p>
        </div>
        <div class="dials-tools">
          <button class="button" type="button" @click="replay">
            <RotateCcw :size="14" />重新演示</button
          ><RouterLink class="button" :to="`/${caption.link}`"
            >{{ caption.linkText }}<ArrowRight :size="14"
          /></RouterLink>
        </div>
      </header>

      <div class="dials-body">
        <section ref="stage" class="stage" aria-label="刻度盘">
          <div class="field" aria-hidden="true" :style="fieldStyle"></div>
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
            @click="selectDot"
          ></canvas>
          <div class="hud" aria-hidden="true">
            <span class="hud-tl">{{
              active === "A"
                ? `N ${loading ? "—" : samples.length} · SPOKES`
                : `N ${loading ? "—" : observations.length} · POINTS`
            }}</span>
            <span class="hud-tr">{{
              active === "A" ? "R ∝ °SR · 0–100" : "RING = BLOCK"
            }}</span>
            <span class="hud-bl">{{
              active === "A" ? "CW ↻ REV / SW%" : "SECTOR = CYCLE"
            }}</span>
          </div>
          <p v-if="loading" class="stage-loading" role="status">
            正在读取样本与观测…
          </p>
        </section>

        <section class="sets" aria-label="数据清单" :aria-busy="loading">
          <p id="dial-row-hint" class="sr-only">
            点击类型筛选下方样本库，再次点击取消筛选
          </p>
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
                  loading ? "—" : active === set ? shown[set] : total(set)
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
              <li v-for="r in rowsOf(set)" :key="r.key">
                <button
                  type="button"
                  class="row"
                  :class="`row-${r.kind}`"
                  :aria-pressed="set === 'A' ? activeType === r.key : undefined"
                  :aria-describedby="set === 'A' ? 'dial-row-hint' : undefined"
                  @pointerenter="enterRow(set, r.key)"
                  @focus="enterRow(set, r.key)"
                  @pointerleave="setFilter(null)"
                  @blur="setFilter(null)"
                  @click="clickRow(set, r)"
                >
                  <i class="mk" aria-hidden="true"></i
                  ><span class="row-label">{{ r.label }}</span
                  ><b class="row-count">{{ loading ? "—" : r.count }}</b
                  ><span class="row-bar" aria-hidden="true"
                    ><span :style="{ width: `${share(r)}%` }"></span></span
                  ><span class="row-pct" aria-hidden="true">{{
                    loading || !r.total ? "—" : `${number(share(r), 1)}%`
                  }}</span>
                </button>
              </li>
            </ul>
          </div>
        </section>
      </div>

      <div
        v-if="active === 'B' && !loading && observations.length"
        ref="observationDetails"
        class="observation-details"
      >
        <label>
          观测详情
          <select v-model="selectedObservation">
            <option :value="null" disabled>选择一条观测</option>
            <option
              v-for="o in observations"
              :key="`${o.block}:${o.cycle}:${o.replicate}`"
              :value="o"
            >
              {{ observationTitle(o) }}
            </option>
          </select>
        </label>
        <output>
          <template v-if="selectedDetail">
            <span>{{ selectedDetail.subtitle }}</span>
            <span
              >{{ selectedDetail.label }}
              <b class="mono">{{ selectedDetail.value }}</b></span
            >
            <span v-if="selectedDetail.review" class="rev">
              待复核：长度分布合计偏离 100%
            </span>
          </template>
        </output>
      </div>
    </section>
    <div
      ref="tip"
      class="dial-tip"
      :class="{ on: tipPos.on }"
      :style="tipStyle"
      aria-hidden="true"
    >
      <template v-if="tipContent">
        <div class="t1">{{ tipContent.title }}</div>
        <div>{{ tipContent.subtitle }}</div>
        <div class="t3">
          <span>{{ tipContent.label }}</span><b>{{ tipContent.value }}</b>
        </div>
        <div v-if="tipContent.review" class="t3 rev">
          <span>待复核</span><span>长度分布合计偏离 100%</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* ================================================================ shared */
.dials {
  min-width: 0;
}
.dials-tile {
  padding: 22px 24px 24px;
}
.dials-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 20px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.dials-heading {
  min-width: 0;
}
.dials-kicker {
  margin-bottom: 4px;
}
.dials-kicker-pz,
.dials-kicker-gd {
  display: none;
}
.dials-head h2 {
  color: var(--text);
}
.dials-sub {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-2);
  max-width: 640px;
}
.dials-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dials-tools .button {
  min-height: 32px;
  padding: 0 12px;
  font-size: 12.5px;
}
.dials-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  grid-template-areas: "stage sets";
  gap: 20px;
  align-items: start;
}
.stage {
  grid-area: stage;
  position: relative;
  align-self: stretch;
  min-height: clamp(500px, 64vh, 600px);
  border-radius: calc(var(--radius) - 6px);
  overflow: hidden;
}
.stage canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.field {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.hud {
  display: none;
}
.stage-loading,
.dials-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-2);
}
.stage-loading {
  position: absolute;
  inset: 0;
  margin: 0;
}
.dials-state {
  padding: 48px 24px;
  flex-wrap: wrap;
}

/* ---------------------------------------------------------------- legend sets */
.sets {
  grid-area: sets;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.set {
  position: relative;
  padding: 12px 12px 8px;
  border-radius: calc(var(--radius) - 8px);
  transition:
    background 0.25s,
    box-shadow 0.25s,
    border-color 0.25s;
}
.set-head {
  all: unset;
  box-sizing: border-box;
  cursor: pointer;
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "k hint"
    "v v";
  align-items: baseline;
  gap: 2px 10px;
  padding: 2px 4px 6px;
  border-radius: var(--radius-xs);
}
.set-head:focus-visible {
  outline: 2.5px solid var(--focus);
  outline-offset: 3px;
}
.set-head .k {
  grid-area: k;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}
.set-head .hint {
  grid-area: hint;
  font-size: 12px;
  color: var(--accent-ink);
  white-space: nowrap;
}
.set[data-active="true"] .set-head .hint {
  color: var(--text-2);
}
.set-head .v {
  grid-area: v;
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: fit-content;
  font-family: var(--font-display);
  font-size: 40px;
  line-height: 1;
  color: var(--text);
  font-variant-numeric: lining-nums tabular-nums;
}
.set-head .v small {
  font-family: var(--font-body);
  font-size: 13px;
  letter-spacing: 0;
  color: var(--text-2);
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.row {
  all: unset;
  box-sizing: border-box;
  cursor: pointer;
  width: 100%;
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto;
  grid-template-areas:
    "mk label count"
    ". bar pct";
  align-items: center;
  gap: 3px 10px;
  padding: 5px 10px;
  border-radius: var(--radius-xs);
  font-size: 13px;
  color: var(--text-2);
  transition:
    background 0.18s,
    color 0.18s,
    box-shadow 0.18s,
    transform 0.35s var(--spring);
}
.row:hover,
.row:focus-visible {
  color: var(--text);
  background: var(--surface-hover);
}
.row:focus-visible {
  outline: 2.5px solid var(--focus);
  outline-offset: 1px;
}
.row-label {
  grid-area: label;
  min-width: 0;
  overflow-wrap: anywhere;
}
.row-count {
  grid-area: count;
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 19px;
  line-height: 1;
  color: var(--text);
  font-variant-numeric: lining-nums tabular-nums;
  text-align: right;
}
.row-bar {
  grid-area: bar;
  position: relative;
  height: 4px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
}
.row-bar span {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: var(--row-c, var(--text-3));
  transition: width 0.4s var(--ease);
}
.row-pct {
  grid-area: pct;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
/* material markers keep a shape identity: softwood circle, hardwood square, blend triangle
   (split sw/hw: the dial draws blends as a softwood + hardwood spoke) */
.mk {
  grid-area: mk;
  width: 10px;
  height: 10px;
  justify-self: center;
  background: var(--row-c, var(--text-3));
}
.row-softwood {
  --row-c: var(--sw);
  --row-ink: var(--sw-ink);
  --row-tint: var(--sw-tint);
}
.row-softwood .mk {
  border-radius: 50%;
}
.row-hardwood {
  --row-c: var(--hw);
  --row-ink: var(--hw-ink);
  --row-tint: var(--hw-tint);
}
.row-hardwood .mk {
  border-radius: 2px;
}
.row-blend {
  --row-c: var(--bl);
  --row-ink: var(--bl-ink);
  --row-tint: var(--bl-tint);
}
.row-blend .mk {
  width: 11px;
  height: 11px;
  clip-path: polygon(50% 4%, 98% 94%, 2% 94%);
  background: linear-gradient(90deg, var(--sw) 0 50%, var(--hw) 50% 100%);
}
.row-recycled {
  --row-c: var(--rc);
  --row-ink: var(--rc-ink);
  --row-tint: var(--rc-tint);
}
.row-recycled .mk {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.row-review {
  --row-c: var(--review);
  --row-ink: var(--review);
  --row-tint: var(--review-tint);
}
.row-review .mk {
  width: 11px;
  height: 10px;
  clip-path: polygon(50% 0, 100% 100%, 0 100%);
}
.row[aria-pressed="true"] {
  color: var(--text);
  box-shadow: inset 0 0 0 1.5px var(--row-c);
}

/* ---------------------------------------------------------------- observation details */
.observation-details {
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--line-soft);
  font-size: 13px;
  color: var(--text-2);
}
.observation-details label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  color: var(--text);
  font-weight: 500;
}
.observation-details select {
  max-width: 100%;
  min-height: 34px;
  padding: 4px 10px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text);
  font-weight: 400;
  cursor: pointer;
}
.observation-details output,
.observation-details output span {
  display: block;
}
.observation-details output:not(:empty) {
  margin-top: 10px;
  line-height: 1.8;
}
.observation-details output b {
  color: var(--text);
  font-weight: 500;
}

/* ---------------------------------------------------------------- tooltip */
.dial-tip {
  position: fixed;
  z-index: 29;
  pointer-events: none;
  min-width: 200px;
  max-width: 320px;
  background: var(--surface-glass);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-pop);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  padding: 10px 13px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-2);
  display: none;
}
.dial-tip.on {
  display: block;
}
.dial-tip .t1 {
  font: 500 13px var(--font-mono);
  color: var(--text);
}
.dial-tip .t3 {
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.dial-tip .t3 b {
  font: 500 12px var(--font-mono);
  color: var(--text);
}
.rev {
  color: var(--review);
}

/* ================================================================ polarized: dark field, reticle, HUD */
:root[data-mode="polarized"] .dials-kicker-pz {
  display: inline;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-3);
}
:root[data-mode="polarized"] .dials-head h2 {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
:root[data-mode="polarized"] .stage {
  background:
    radial-gradient(circle closest-side, var(--surface) 0%, var(--bg) 100%);
  box-shadow:
    inset 0 0 0 1px var(--line-soft),
    inset 0 0 80px var(--bg);
}
/* field stop: an interference rim around the circular field of view */
:root[data-mode="polarized"] .field {
  background: var(--ifc);
  -webkit-mask: radial-gradient(closest-side, transparent calc(100% - 1.5px), var(--text) calc(100% - 1px));
  mask: radial-gradient(closest-side, transparent calc(100% - 1.5px), var(--text) calc(100% - 1px));
  opacity: 0.55;
}
:root[data-mode="polarized"] .hud {
  display: block;
  position: absolute;
  inset: 0;
  pointer-events: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.12em;
  color: var(--text-3);
}
.hud span {
  position: absolute;
}
.hud-tl {
  left: 14px;
  top: 12px;
}
.hud-tr {
  right: 14px;
  top: 12px;
}
.hud-bl {
  left: 14px;
  bottom: 12px;
}
:root[data-mode="polarized"] .set {
  border: 1px solid var(--line);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .set[data-active="true"] {
  border-color: transparent;
  background: var(--surface-hover);
}
/* the active set wears the interference edge (v1 .card::before) */
:root[data-mode="polarized"] .set[data-active="true"]::before {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1px;
  pointer-events: none;
  background: var(--ifc);
  -webkit-mask:
    linear-gradient(var(--text) 0 0) content-box,
    linear-gradient(var(--text) 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0.7;
}
:root[data-mode="polarized"] .set-head .k {
  font-weight: 700;
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .set-head .hint {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
}
:root[data-mode="polarized"] .set-head .v {
  font-weight: 200;
  font-size: 42px;
  letter-spacing: -0.05em;
}
:root[data-mode="polarized"] .row {
  border: 1px solid transparent;
}
:root[data-mode="polarized"] .row:hover,
:root[data-mode="polarized"] .row:focus-visible {
  background: var(--surface);
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .row-count {
  font-weight: 300;
  font-size: 20px;
  letter-spacing: -0.03em;
  color: var(--row-ink, var(--text));
}
:root[data-mode="polarized"] .row-bar {
  height: 3px;
}
:root[data-mode="polarized"] .row-bar span {
  box-shadow: 0 0 10px var(--row-c);
}
:root[data-mode="polarized"] .mk {
  box-shadow: 0 0 8px var(--row-c);
}
:root[data-mode="polarized"] .row-blend .mk,
:root[data-mode="polarized"] .row-review .mk {
  box-shadow: none;
}
:root[data-mode="polarized"] .observation-details {
  background: transparent;
  border-color: var(--line);
}
:root[data-mode="polarized"] .dial-tip {
  border-radius: var(--radius-xs);
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .dial-tip::before {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 1px;
  background: var(--ifl);
  opacity: 0.8;
}

/* ================================================================ garden: glass lens, petals, tinted pills */
:root[data-mode="garden"] .dials-kicker-gd {
  display: inline;
  font-family: var(--font-display);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 14px;
  color: var(--text-2);
}
:root[data-mode="garden"] .dials-head h2 {
  font-size: 19px;
  font-weight: 500;
  line-height: 1.35;
}
:root[data-mode="garden"] .stage {
  background:
    radial-gradient(38% 46% at 24% 30%, color-mix(in oklab, var(--sw-tint) 85%, transparent), transparent 72%),
    radial-gradient(40% 48% at 78% 70%, color-mix(in oklab, var(--hw-tint) 85%, transparent), transparent 72%),
    radial-gradient(34% 40% at 74% 22%, color-mix(in oklab, var(--bl-tint) 85%, transparent), transparent 72%);
}
/* the dial sits on a glass lens with a fine tick rim (the hero lens motif) */
:root[data-mode="garden"] .field {
  background: radial-gradient(circle at 36% 28%, var(--surface) 0%, color-mix(in oklab, var(--surface) 72%, transparent) 70%);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    0 0 0 10px color-mix(in oklab, var(--surface) 35%, transparent),
    0 30px 60px -34px color-mix(in oklab, var(--accent) 55%, transparent);
}
:root[data-mode="garden"] .field::before {
  content: "";
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  background: repeating-conic-gradient(var(--line-strong) 0 0.5deg, transparent 0.5deg 6deg);
  -webkit-mask: radial-gradient(closest-side, transparent 95%, var(--text) 96%);
  mask: radial-gradient(closest-side, transparent 95%, var(--text) 96%);
}
:root[data-mode="garden"] .set {
  background: color-mix(in oklab, var(--surface) 55%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .set[data-active="true"] {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .set-head .k {
  font-weight: 500;
  font-size: 14px;
  color: var(--text-2);
}
:root[data-mode="garden"] .set[data-active="true"] .set-head .k {
  color: var(--text);
}
:root[data-mode="garden"] .set-head .hint {
  font-family: var(--font-display);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 13.5px;
}
:root[data-mode="garden"] .set-head .v {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-size: 44px;
  letter-spacing: -0.035em;
}
:root[data-mode="garden"] .rows {
  gap: 5px;
}
/* v4 .comp-btn: a soft pill washed in the row's stain tint */
:root[data-mode="garden"] .row {
  border-radius: 16px;
  padding: 6px 12px;
  color: var(--text);
  background: linear-gradient(150deg, color-mix(in oklab, var(--surface) 80%, transparent), color-mix(in oklab, var(--row-tint, var(--surface-2)) 80%, transparent));
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .row:hover,
:root[data-mode="garden"] .row:focus-visible {
  background: var(--surface);
  transform: translateY(-2px);
}
:root[data-mode="garden"] .row[aria-pressed="true"] {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--row-c),
    0 10px 22px -14px var(--row-c);
}
:root[data-mode="garden"] .row-count {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-weight: 400;
  font-size: 22px;
  letter-spacing: -0.02em;
}
:root[data-mode="garden"] .row-bar {
  height: 5px;
  background: color-mix(in oklab, var(--text) 8%, transparent);
}
:root[data-mode="garden"] .observation-details {
  border: 0;
  background: color-mix(in oklab, var(--surface) 60%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .observation-details select {
  border-radius: 999px;
  border-color: var(--line);
}
:root[data-mode="garden"] .dial-tip {
  border: 0;
  border-radius: 18px;
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-pop);
}

/* ================================================================ responsive */
@media (max-width: 1180px) {
  .dials-body {
    grid-template-columns: minmax(0, 1fr) minmax(270px, 310px);
  }
  :root[data-mode="polarized"] .set-head .v,
  :root[data-mode="garden"] .set-head .v {
    font-size: 38px;
  }
}
@media (max-width: 1080px) {
  .dials-body {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "sets"
      "stage";
  }
  .sets {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
}
@media (max-width: 720px) {
  .dials-tile {
    padding: 18px 16px 18px;
  }
  .sets {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
  }
  .set[data-active="false"] .rows {
    display: none;
  }
  .set[data-active="false"] .set-head {
    padding-bottom: 2px;
  }
  :root[data-mode="polarized"] .set-head .v,
  :root[data-mode="garden"] .set-head .v {
    font-size: 34px;
  }
  .stage {
    min-height: 0;
    height: 380px;
    margin: 0 -6px;
  }
  .hud-tr,
  .hud-bl {
    display: none;
  }
  .dials-tools {
    width: 100%;
  }
}
</style>
