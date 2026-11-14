// Pure helpers for the fibre–paper association page. Self-contained on purpose: the unit
// test transpiles this file on its own and imports it from a data: URL (no relative imports).

export function pearson(pairs: [number, number][]): number | null {
  const values = pairs.filter(
    ([x, y]) => Number.isFinite(x) && Number.isFinite(y),
  );
  if (values.length < 3) return null;
  const meanX = values.reduce((sum, p) => sum + p[0], 0) / values.length;
  const meanY = values.reduce((sum, p) => sum + p[1], 0) / values.length;
  let xx = 0,
    yy = 0,
    xy = 0;
  for (const [x, y] of values) {
    const dx = x - meanX,
      dy = y - meanY;
    xx += dx * dx;
    yy += dy * dy;
    xy += dx * dy;
  }
  if (xx === 0 || yy === 0) return null;
  const result = xy / Math.sqrt(xx * yy);
  return Number.isFinite(result) ? Math.max(-1, Math.min(1, result)) : null;
}

/**
 * Range around the observations, padded by `ratio` of the span on both sides. Non-negative
 * data never gets a negative lower bound; constant data (including all zeros) still spans.
 */
export function paddedRange(values: number[], ratio = 0.12): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  const min = Math.min(...finite),
    max = Math.max(...finite);
  const pad = (max - min || Math.abs(max) || 1) * ratio;
  return [min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad];
}

export function axisDomain(values: number[]): [number, number] {
  return paddedRange(values, 0.12);
}

/**
 * Round tick values (steps of 1, 2 or 5 × 10ⁿ) that cover [min, max], with roughly `count`
 * intervals. The first and last tick enclose every value in the range.
 */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min > max) [min, max] = [max, min];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  const error = raw / power;
  const step =
    (error >= Math.sqrt(50)
      ? 10
      : error >= Math.sqrt(10)
        ? 5
        : error >= Math.SQRT2
          ? 2
          : 1) * power;
  const start = Math.floor(min / step + 1e-9),
    end = Math.ceil(max / step - 1e-9);
  const ticks: number[] = [];
  for (let i = start; i <= end; i++) ticks.push(Number((i * step).toPrecision(12)));
  return ticks.length > 1 ? ticks : [ticks[0]!, Number((ticks[0]! + step).toPrecision(12))];
}

/** Nice axis ticks for a scatter: a small pad around the observations, then round ticks. */
export function scatterTicks(values: number[], count = 5): number[] {
  const [min, max] = paddedRange(values, 0.03);
  return niceTicks(min, max, count);
}

/** Decimal places needed to print every tick of an evenly spaced tick list exactly. */
export function tickDigits(ticks: number[]): number {
  const step = Math.abs((ticks[1] ?? 1) - (ticks[0] ?? 0)) || 1;
  for (let d = 0; d < 8; d++) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6 * Math.max(1, scaled)) return d;
  }
  return 8;
}

/** Pearson r for display: three decimals and a true minus sign; null shows "—". */
export function formatR(r: number | null | undefined, digits = 3): string {
  if (r == null || !Number.isFinite(r)) return "—";
  const fixed = Math.abs(r).toFixed(digits);
  // −0.000 is not a negative correlation
  return r < 0 && Number(fixed) !== 0 ? `−${fixed}` : fixed;
}
