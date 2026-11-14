// Drifting fibre strands for the prologue's middle depth layer (v4 app.js · fiberStrands).
// Deterministic: the same seed always draws the same strands. Colours are classes, so the
// component's CSS paints them with the material tokens.

export type StrandTone = "sw" | "hw" | "bl" | "ink";

export interface StrandPath {
  d: string;
  tone: StrandTone;
  width: number;
  opacity: number;
}

const TONES: readonly StrandTone[] = ["sw", "hw", "bl", "ink"];

/** n bezier strands across a 100 × 100 box (drawn with preserveAspectRatio="none") */
export function strandPaths(seed: number, n: number): StrandPath[] {
  let s = seed * 9973;
  const R = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const out: StrandPath[] = [];
  for (let i = 0; i < n; i++) {
    const y0 = R() * 100,
      y1 = R() * 100,
      c1 = R() * 100,
      c2 = R() * 100;
    const tone = TONES[i % TONES.length]!;
    const width = tone === "ink" ? 0.8 : 1.4 + R() * 2.2;
    const opacity = tone === "ink" ? 0.28 : 0.45 + R() * 0.3;
    const x0 = -10 + R() * 20,
      cx1 = 30 + R() * 20,
      cx2 = 60 + R() * 20,
      x1 = 100 + R() * 15;
    const f = (v: number) => v.toFixed(2);
    out.push({
      d: `M${f(x0)},${f(y0)} C${f(cx1)},${f(c1)} ${f(cx2)},${f(c2)} ${f(x1)},${f(y1)}`,
      tone,
      width,
      opacity,
    });
  }
  return out;
}
