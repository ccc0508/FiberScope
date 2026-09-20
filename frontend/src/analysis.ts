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

export function axisDomain(values: number[]): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  const min = Math.min(...finite),
    max = Math.max(...finite);
  const pad = (max - min || Math.abs(max) || 1) * 0.12;
  return [min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad];
}
