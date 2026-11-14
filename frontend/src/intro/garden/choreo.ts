// Scroll choreography of the garden prologue (ported from the v4 landing, js/landing.js).
// `c` is the story position: chapter i sits at c = i (its section's top at the top of the
// viewport) and c grows linearly to i + 1 while the reader scrolls through that section.
// Everything here is pure: given c and the smoothed pointer it returns the state of every
// depth layer, so the reduced-motion still frame of chapter i is simply frame(i, 0, 0).

export const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** smoothstep from a to b */
export const smooth = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

export const CHAPTERS = 6;

// camera path per chapter: c, group x, camera y, camera z, look-at y, fov.
// 00–02 a three-quarter view of the helical vortex; 03 pulls up; 04–05 a narrow-FOV,
// near-orthographic top-down view so the settled strands read as a flat sheet.
const KEYS: readonly (readonly [number, number, number, number, number, number])[] = [
  [0, 2.3, 1.7, 8.6, 0.0, 34],
  [1, 1.2, 2.2, 8.2, 0.0, 34],
  [2, 2.2, 1.3, 7.2, 0.15, 37],
  [3, -2.1, 4.2, 7.4, 0.0, 32],
  [4, 0.0, 14.6, 1.3, 0.0, 22],
  [5, 0.0, 15.6, 1.4, 0.0, 22],
];

export interface CameraKey {
  gx: number;
  camY: number;
  camZ: number;
  lookY: number;
  fov: number;
}

export function keyAt(c: number, mobile: boolean): CameraKey {
  let i = 0;
  while (i < KEYS.length - 2 && c > KEYS[i + 1]![0]) i++;
  const a = KEYS[i]!,
    b = KEYS[i + 1]!;
  const t = smooth(a[0], b[0], clamp(c, a[0], b[0]));
  const v = a.map((x, k) => lerp(x, b[k]!, t));
  const td = smooth(3, 4, c); // 0 = vortex framing, 1 = top-down sheet
  // on phones the story cards sit at the bottom, so lift the vortex into the upper half
  return {
    gx: mobile ? 0 : v[1]!,
    camY: v[2]!,
    camZ: v[3]! * (mobile ? lerp(1.55, 1, td) : 1),
    lookY: v[4]! - (mobile ? 1.6 * (1 - td) : 0),
    fov: v[5]! + (mobile ? 8 * (1 - td) : 0),
  };
}

export interface Frame {
  /** hero chips and scroll cue */
  heroFade: number;
  beat: number;
  settle: number;
  far: { opacity: number; x: number; y: number };
  giant: { opacity: number; x: number; y: number };
  /** blurred paper network while the fibres settle */
  paperBlur: number;
  /** sharp paper photo: only without WebGL, where the 3D mat cannot become the paper */
  paperSharp: number;
  paper: { x: number; y: number; scale: number };
  mid: { opacity: number; x: number; y: number };
  glass: { opacity: number; x: number; y: number; rx: number; ry: number };
  /** 3D canvas opacity */
  gl: number;
  /** pulp shader filament density */
  pulpFibers: number;
  camera: CameraKey;
}

/**
 * @param c   story position
 * @param mx  smoothed pointer x, −1…1 (0 under reduced motion)
 * @param my  smoothed pointer y, −1…1
 * @param vh  viewport height in px
 */
export function frame(c: number, mx: number, my: number, vh: number, mobile: boolean, gl: boolean): Frame {
  const heroFade = 1 - smooth(0.04, 0.25, c);
  const settle = smooth(2.7, 3.9, c);
  const paperSharp = gl ? 0 : smooth(3.45, 4.1, c) * (1 - smooth(4.6, 5.2, c) * 0.35);
  const glass = smooth(0.35, 0.85, c) * (1 - smooth(1.3, 1.7, c));
  return {
    heroFade,
    beat: 0.08 + Math.exp(-((c - 2) ** 2) / 0.32),
    settle,
    // far: clay fibres, soft focus, slowest
    far: { opacity: 1 - smooth(1.1, 2.6, c) * 0.9, x: -mx * 10, y: -Math.min(c, 3) * 40 + my * 8 },
    // giant latin word sits behind the 3D fibres
    giant: { opacity: 1 - smooth(0.15, 0.95, c), x: -mx * 22, y: -c * 170 + my * 12 },
    paperBlur: smooth(2.6, 3.2, c) * (1 - smooth(3.6, 4.2, c)),
    paperSharp,
    paper: { x: -mx * 8, y: (4 - c) * 36, scale: 1.02 + (1 - paperSharp) * 0.06 },
    mid: { opacity: 0.95 - smooth(3, 4.2, c) * 0.6, x: mx * 26, y: -c * 190 - my * 14 },
    // near glass: comes into focus in chapter 01, then lifts away
    glass: {
      opacity: glass,
      x: mx * 34,
      y: (1 - c) * vh * (mobile ? 0.55 : 0.75) - my * 20,
      rx: my * 8 + (1 - c) * 6,
      ry: mx * 12,
    },
    gl: 1 - smooth(4.3, 4.9, c) * 0.6,
    pulpFibers: 0.9 - smooth(3.4, 4.4, c) * 0.45,
    camera: keyAt(c, mobile),
  };
}

/**
 * Story position from the sections' document offsets: chapter i spans from tops[i] to
 * tops[i + 1] (the last one to the end of the document).
 */
export function storyPosition(y: number, tops: readonly number[], end: number): number {
  if (!tops.length) return 0;
  if (y <= tops[0]!) return 0;
  for (let i = 0; i < tops.length; i++) {
    const a = tops[i]!,
      b = i + 1 < tops.length ? tops[i + 1]! : Math.max(a + 1, end);
    if (y < b) return i + (y - a) / Math.max(1, b - a);
  }
  return tops.length;
}
