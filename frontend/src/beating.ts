export interface CurvePoint {
  x: number;
  y: number;
}

// 按 x 升序、只保留有限值，同一 x 保留第一条
export function sortedCurve(points: CurvePoint[]): CurvePoint[] {
  const seen = new Set<number>();
  return points
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    .sort((a, b) => a.x - b.x)
    .filter((p) => (seen.has(p.x) ? false : (seen.add(p.x), true)));
}

// 相邻两个实测点之间线性插值；超出实测范围返回 null，不外推
export function interpolateAt(points: CurvePoint[], x: number): number | null {
  const curve = sortedCurve(points);
  if (!curve.length || x < curve[0]!.x || x > curve[curve.length - 1]!.x)
    return null;
  for (let i = 0; i < curve.length; i++) {
    const b = curve[i]!;
    if (b.x === x) return b.y;
    if (b.x > x) {
      const a = curve[i - 1]!;
      return a.y + ((b.y - a.y) * (x - a.x)) / (b.x - a.x);
    }
  }
  return null;
}

// 曲线首次达到 target 的 x（线性插值估算）；第一个点已达到时返回该点，始终未达到返回 null
export function firstReach(
  points: CurvePoint[],
  target: number,
): number | null {
  const curve = sortedCurve(points);
  if (!curve.length) return null;
  if (curve[0]!.y >= target) return curve[0]!.x;
  for (let i = 1; i < curve.length; i++) {
    const a = curve[i - 1]!,
      b = curve[i]!;
    if (b.y >= target)
      return a.x + ((b.x - a.x) * (target - a.y)) / (b.y - a.y);
  }
  return null;
}

// 1/2/5 × 10^n 的整齐刻度，覆盖 [min, max]
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ??
    10 * power;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step)
    ticks.push(Number(v.toFixed(10)));
  if (ticks[ticks.length - 1]! < max)
    ticks.push(Number((ticks[ticks.length - 1]! + step).toFixed(10)));
  return ticks;
}

// 与设计稿相同的确定性伪随机数（mulberry32），保证纹理每次渲染一致
export function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 图表纸面上的纤维纹理：每 900 px² 一根略弯的短纤维，约三成稍粗
export function fiberPaths(
  width: number,
  height: number,
  seed = 7301,
): { d: string; wide: boolean }[] {
  const rng = mulberry32(seed),
    n = Math.round((width * height) / 900),
    out: { d: string; wide: boolean }[] = [];
  const f = (v: number) => v.toFixed(1);
  for (let i = 0; i < n; i++) {
    const len = 20 + rng() * 40,
      ang = rng() * Math.PI;
    const cx = rng() * width,
      cy = rng() * height;
    const dx = Math.cos(ang),
      dy = Math.sin(ang),
      nx = -dy,
      ny = dx;
    const bend = (rng() - 0.5) * len * 0.35,
      bend2 = (rng() - 0.5) * len * 0.35;
    const x0 = cx - (dx * len) / 2,
      y0 = cy - (dy * len) / 2,
      x3 = cx + (dx * len) / 2,
      y3 = cy + (dy * len) / 2;
    const c1x = x0 + (dx * len) / 3 + nx * bend,
      c1y = y0 + (dy * len) / 3 + ny * bend;
    const c2x = x3 - (dx * len) / 3 + nx * bend2,
      c2y = y3 - (dy * len) / 3 + ny * bend2;
    out.push({
      d: `M${f(x0)},${f(y0)} C${f(c1x)},${f(c1y)} ${f(c2x)},${f(c2y)} ${f(x3)},${f(y3)}`,
      wide: rng() < 0.3,
    });
  }
  return out;
}
