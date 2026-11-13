// Static copy and procedural geometry for the polarized prologue (v1 「偏光」 landing).
// Nothing in here is dataset data: the numbers the prologue shows come from the API
// (see data.ts). Magnifications and scale bars are the microscope metaphor's calibration.
import { navItems, type NavItem } from "../../nav";

/* ---------------------------------------------------------------- microscope calibration */
/** the 64 px scale bar spans 200 µm at 10× (same calibration as the polarized shell HUD) */
export const SCALEBAR_PX = 64;
export const umPerPx = (mag: number) => 31.25 / mag;
export function scaleLabel(mag: number, px = SCALEBAR_PX) {
  const v = px * umPerPx(mag);
  return `${v >= 1 ? String(Math.round(v * 10) / 10) : String(+v.toPrecision(2))} µm`;
}

export interface MagStage {
  /** "10×" */
  m: string;
  mag: number;
  title: string;
  text: string;
  scale: string;
}
/** the four steps of the zoom story: whole fibre → wall layers → S2 helix → microfibrils */
export const MAGS: MagStage[] = [
  {
    m: "10×",
    title: "单根纤维",
    text: "打浆后的纸浆纤维是一条扁平的带状细胞壁。正交偏光下，纤维素结晶区的双折射让它在黑暗中发光。",
  },
  {
    m: "40×",
    title: "细胞壁分层",
    text: "细胞壁由初生壁与次生壁 S1、S2、S3 层构成；各层微纤丝的缠绕方向不同，外层几乎横绕。",
  },
  {
    m: "400×",
    title: "S2 层 · 微纤丝角",
    text: "S2 层最厚，微纤丝以较小的角度绕纤维轴螺旋上升——这一角度与纤维的强度和伸长密切相关。",
  },
  {
    m: "4000×",
    title: "纤维素微纤丝",
    text: "进入螺旋内部。打浆让微纤丝松散、分丝帚化，纤维更柔顺，纸页中的结合随之改变。",
  },
].map((s) => {
  const mag = parseFloat(s.m);
  return { ...s, mag, scale: scaleLabel(mag) };
});

/* ---------------------------------------------------------------- objectives (the 8 workspace pages) */
/** What each objective shows; the recycled note carries the live block count. */
export function routeNote(path: string, recycledBlocks: number | null): string {
  switch (path) {
    case "/":
      return "核心样本、再生纸浆观测与指标覆盖一览；每一行都是一个唯一物理样本。";
    case "/beating":
      return "比较打浆转数变化下的纤维特性与纸张性能。";
    case "/blends":
      return "针叶木与阔叶木按比例复配时，各项指标随针叶木比例的变化。";
    case "/association":
      return "把每个样本的纤维特性与纸张性能配对，观察对应关系与线性相关。";
    case "/recycled":
      return recycledBlocks == null
        ? "各再生纸浆数据块在多次循环中的纤维特性、长度分布与强度。"
        : `${recycledBlocks} 个再生纸浆数据块在多次循环中的纤维特性、长度分布与强度。`;
    case "/sources":
      return "已入库的 Excel 来源文件与逐行来源记录，以及各口径数量的区别。";
    case "/literature":
      return "基于本地文献库与实验数据库提问；回答分别标注文献与实验数据来源。";
    case "/literature-data":
      return "从论文 PDF 中提取表格与正文数值，逐条核对后再使用。";
    default:
      return "";
  }
}

/**
 * The brand interference ramp (gold → magenta → violet → cyan) as a CSS colour built from the
 * mode tokens, so no hex value is hard-coded. `ink` picks the text-safe (≥ 4.5:1) variants.
 */
export function toneAt(t: number, ink = false): string {
  const stops = ink
    ? ["var(--sw-ink)", "var(--bl-ink)", "var(--rc-ink)", "var(--hw-ink)"]
    : ["var(--sw)", "var(--bl)", "var(--rc)", "var(--hw)"];
  const x = Math.min(1, Math.max(0, t)) * 3;
  const i = Math.min(2, Math.floor(x));
  const f = x - i;
  return `color-mix(in srgb, ${stops[i]}, ${stops[i + 1]} ${(f * 100).toFixed(1)}%)`;
}

export interface Objective {
  item: NavItem;
  /** position on the revolving nosepiece, degrees (0 = top, clockwise) */
  angle: number;
  tone: string;
  toneInk: string;
}
export const objectives: Objective[] = navItems.map((item, i, all) => ({
  item,
  angle: -90 + i * (360 / all.length),
  tone: toneAt(i / (all.length - 1)),
  toneInk: toneAt(i / (all.length - 1), true),
}));

/* ---------------------------------------------------------------- procedural SVG geometry */
const f1 = (v: number) => v.toFixed(1);

/** radial tick marks as one path: every `step`°, long ticks where `isLong(deg)` */
function ticks(cx: number, r: number, step: number, len: (deg: number) => number) {
  let short = "",
    long = "";
  for (let k = 0; k < 360; k += step) {
    const a = (k * Math.PI) / 180,
      L = len(k);
    const seg = `M${f1(cx + (r - L) * Math.cos(a))} ${f1(cx + (r - L) * Math.sin(a))}L${f1(cx + r * Math.cos(a))} ${f1(cx + r * Math.sin(a))}`;
    if (L > 10) long += seg;
    else short += seg;
  }
  return { short, long };
}

/** eyepiece reticle, viewBox 0 0 400 400 */
export const reticleTicks = (() => {
  const t = ticks(200, 190, 5, (k) => (k % 30 === 0 ? 14 : 6));
  let scale = "";
  for (let k = -10; k <= 10; k++) scale += `M${200 + k * 8} ${k % 5 === 0 ? 192 : 196}L${200 + k * 8} 204`;
  return { ticks: t.short + t.long, scale };
})();

/** objective turret ring, viewBox 0 0 600 600 */
export const turretTicks = ticks(300, 296, 3, (k) => (k % 45 === 0 ? 16 : k % 15 === 0 ? 9 : 5));

export interface Strand {
  id: string;
  d: string;
  /** colour stops: index into the ramp classes c0…c3 */
  stops: [number, number, number];
  width: number;
  opacity: number;
  sparkle: boolean;
}
/** crisp foreground strands (deterministic), viewBox 0 0 1600 1000 */
export const nearStrands: Strand[] = (() => {
  let s = 7;
  const rnd = () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
  const out: Strand[] = [];
  for (let i = 0; i < 9; i++) {
    const right = i < 6;
    const x0 = right ? 760 + rnd() * 900 : -120 + rnd() * 300;
    const y0 = 1080 + rnd() * 80;
    const x3 = x0 + (right ? 260 + rnd() * 520 : 200 + rnd() * 300);
    const y3 = -120 - rnd() * 80;
    const c1x = x0 + (rnd() - 0.2) * 520,
      c1y = 700 - rnd() * 200;
    const c2x = x3 - (rnd() - 0.3) * 520,
      c2y = 300 - rnd() * 200;
    const width = 0.8 + rnd() * 2.2;
    const o = (rnd() * 3) | 0;
    const d = `M${x0.toFixed(0)},${y0.toFixed(0)} C${c1x.toFixed(0)},${c1y.toFixed(0)} ${c2x.toFixed(0)},${c2y.toFixed(0)} ${x3.toFixed(0)},${y3.toFixed(0)}`;
    out.push({
      id: `pzi-ns${i}`,
      d,
      stops: [o, (o + 1) % 4, (o + 2) % 4],
      width,
      opacity: +(0.45 + rnd() * 0.45).toFixed(2),
      sparkle: i % 3 === 0,
    });
  }
  return out;
})();
