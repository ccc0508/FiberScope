// Three.js microfibril helix for the polarized prologue (ported from v1 js/fibril3d.js).
// Decorative only, and only ever loaded through a dynamic import from IntroPolarized, so
// "three" lands in its own chunk that is fetched when the magnification section approaches.
//
// One straight TubeGeometry is instanced ~130 times; the vertex shader wraps every instance
// into a helix (radius, phase, twist rate per instance). The S1 / S2 / S3 cell-wall layers
// differ only in their microfibril angle, i.e. their twist rate.
//
// Compositing: the canvas is alpha + premultiplied. Every fragment writes premultiplied colour
// with alpha = max(r, g, b) and blends ONE/ONE, so a strand that fog or a low layer opacity
// pushed to black stays transparent instead of painting opaque black over the page.
import {
  AddEquation,
  CustomBlending,
  Group,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  LineCurve3,
  Mesh,
  OneFactor,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  TubeGeometry,
  Vector3,
  Vector4,
  WebGLRenderer,
  type IUniform,
} from "three";

/* ---------------------------------------------------------------- interference colour (Michel-Lévy) */
// Same spectral model as src/ambient/field.ts (which does not export its GLSL).
const LAMBDAS = [400, 428, 456, 484, 512, 540, 568, 596, 624, 652, 680];
const gauss = (l: number, m: number, s: number) => Math.exp(-(((l - m) / s) ** 2));
const W = LAMBDAS.map((l) => [gauss(l, 602, 46) + 0.28 * gauss(l, 432, 20), gauss(l, 545, 40), gauss(l, 452, 30)]);
const SUM = W.reduce((a, w) => [a[0]! + w[0]!, a[1]! + w[1]!, a[2]! + w[2]!], [0, 0, 0]);
const f5 = (x: number) => x.toFixed(5);
const INTERF_GLSL = `
float s2_(float x){ float s = sin(x); return s*s; }
vec3 michel(float G){
  vec3 c = vec3(0.0);
${LAMBDAS.map((l, i) => `  c += vec3(${f5(W[i]![0]! / SUM[0]!)}, ${f5(W[i]![1]! / SUM[1]!)}, ${f5(W[i]![2]! / SUM[2]!)}) * s2_(G * ${f5(Math.PI / l)});`).join("\n")}
  return c;
}
float foldG(float G){
  if (G <= 280.0) return G;
  float t = mod(G - 280.0, 960.0);
  return 280.0 + (t < 480.0 ? t : 960.0 - t);
}
vec3 brandRamp(float t){
  t = clamp(t, 0.0, 1.0) * 3.0;
  vec3 a = vec3(0.949, 0.757, 0.306), b = vec3(0.878, 0.278, 0.620), c = vec3(0.357, 0.357, 0.839), d = vec3(0.180, 0.769, 0.839);
  return t < 1.0 ? mix(a, b, t) : (t < 2.0 ? mix(b, c, t - 1.0) : mix(c, d, t - 2.0));
}
vec3 interf(float G){
  float g = foldG(G);
  vec3 m = michel(g);
  float k = smoothstep(180.0, 320.0, g);
  vec3 b = brandRamp((g - 280.0) / 480.0) * (0.25 + 1.2 * dot(m, vec3(0.3333)));
  return mix(m, b, 0.45 * k);
}`;

const VERT = `
attribute vec4 aStrand;   // radius, phase, twist (rad / unit length), seed
attribute vec4 aExtra;    // layer id, unused
uniform float uTime;
uniform float uFlatten;
uniform float uSpin;
uniform float uRad;       // strand thickness multiplier (thick at low magnification)
varying float vSeed;
varying float vLayer;
varying float vZ;
varying float vFres;
varying float vDepth;
void main(){
  vec3 p = position;
  float z = p.z;
  float dir = aExtra.x > 0.5 && aExtra.x < 1.5 ? 1.0 : -1.0;
  float ang = aStrand.y + z * aStrand.z + uTime * uSpin * dir;
  float c = cos(ang), s = sin(ang);
  vec2 local = vec2(c * p.x - s * p.y, s * p.x + c * p.y) * uRad;
  vec3 wp = vec3(vec2(c, s) * aStrand.x + local, z);
  vec3 n = vec3(c * normal.x - s * normal.y, s * normal.x + c * normal.y, normal.z);
  wp.y *= uFlatten;
  n.y /= max(uFlatten, 0.25);
  vec4 mv = modelViewMatrix * vec4(wp, 1.0);
  vec3 vn = normalize(normalMatrix * normalize(n));
  vFres = pow(1.0 - abs(dot(vn, normalize(-mv.xyz))), 1.6);
  vSeed = aStrand.w;
  vLayer = aExtra.x;
  vZ = z;
  vDepth = -mv.z;
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
uniform float uTime;
uniform float uRetard;
uniform vec4 uAlpha;      // per-layer opacity: S1, S2, S3, primary wall
uniform float uIntensity;
uniform float uFogNear;
uniform float uFogFar;
uniform float uHalo;      // 0 = crisp strand, 1 = soft glow pass (wider tube)
varying float vSeed;
varying float vLayer;
varying float vZ;
varying float vFres;
varying float vDepth;
${INTERF_GLSL}
void main(){
  float a = vLayer < 0.5 ? uAlpha.x : (vLayer < 1.5 ? uAlpha.y : (vLayer < 2.5 ? uAlpha.z : uAlpha.w));
  float fog = 1.0 - smoothstep(uFogNear, uFogFar, vDepth);
  float near = smoothstep(0.6, 2.4, vDepth);
  float vis = a * fog * near;
  if (vis < 0.01) discard;
  // S1 gold/orange → S2 magenta/indigo → S3 indigo/cyan
  float base = vLayer < 0.5 ? 330.0 : (vLayer < 1.5 ? 470.0 : (vLayer < 2.5 ? 560.0 : 300.0));
  float G = base + vSeed * 240.0 + vZ * 2.2 + uRetard + 50.0 * sin(uTime * 0.35 + vZ * 0.08);
  vec3 c = interf(G);
  c = max(mix(vec3(dot(c, vec3(0.333))), c, 1.55), 0.0);
  float shade = uHalo > 0.5 ? pow(1.0 - vFres, 2.4) * 0.15 : (0.16 + 0.95 * vFres);
  vec3 col = c * shade * vis * uIntensity;
  float al = max(max(col.r, col.g), col.b);
  if (al < 0.002) discard;
  gl_FragColor = vec4(col, al);
}`;

interface Instance {
  r: number;
  phase: number;
  twist: number;
  seed: number;
  layer: number;
}

function strandGeometry(len: number, segs: number, radius: number, instances: Instance[]) {
  const tube = new TubeGeometry(
    new LineCurve3(new Vector3(0, 0, -len / 2), new Vector3(0, 0, len / 2)),
    segs,
    radius,
    6,
    false,
  );
  const geometry = new InstancedBufferGeometry().copy(tube as unknown as InstancedBufferGeometry);
  tube.dispose();
  const strand = new Float32Array(instances.length * 4);
  const extra = new Float32Array(instances.length * 4);
  instances.forEach((s, i) => {
    strand.set([s.r, s.phase, s.twist, s.seed], i * 4);
    extra.set([s.layer, 0, 0, 0], i * 4);
  });
  geometry.setAttribute("aStrand", new InstancedBufferAttribute(strand, 4));
  geometry.setAttribute("aExtra", new InstancedBufferAttribute(extra, 4));
  geometry.instanceCount = instances.length;
  return geometry;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const smooth = (t: number) => t * t * (3 - 2 * t);

interface Key {
  p: number;
  dist: number;
  ry: number;
  rz: number;
  rx: number;
  flat: number;
  rad: number;
  a: [number, number, number, number];
  fov: number;
  near: number;
  far: number;
}
// keyframes over the section's scroll progress: close with thick strands, thinning as it zooms in,
// ending inside the S2 helix looking down the fibre axis (the 4000× tunnel). The captions switch
// at quarters (10× · 40× · 400× · 4000×), so each look settles inside its quarter and the
// tunnel holds through the last one instead of arriving at the very end.
const KEYS: Key[] = [
  { p: 0.0, dist: 44, ry: 1.3, rz: 0.42, rx: 0.16, flat: 0.46, rad: 2.2, a: [0.85, 0.9, 0.45, 0.7], fov: 36, near: 40, far: 110 },
  { p: 0.1, dist: 42, ry: 1.28, rz: 0.4, rx: 0.15, flat: 0.48, rad: 2.15, a: [0.86, 0.9, 0.45, 0.68], fov: 36, near: 38, far: 106 },
  { p: 0.36, dist: 23, ry: 1.18, rz: 0.3, rx: 0.1, flat: 0.64, rad: 1.6, a: [0.95, 0.85, 0.45, 0.5], fov: 38, near: 22, far: 80 },
  { p: 0.6, dist: 12.5, ry: 0.95, rz: 0.12, rx: 0.06, flat: 0.92, rad: 1.05, a: [0.12, 1.0, 0.45, 0.0], fov: 40, near: 14, far: 60 },
  { p: 0.86, dist: 27, ry: 0.0, rz: 0.0, rx: 0.0, flat: 1.0, rad: 1.0, a: [0.0, 1.0, 0.0, 0.0], fov: 62, near: 18, far: 64 },
  { p: 1.0, dist: 24, ry: 0.0, rz: 0.0, rx: 0.0, flat: 1.0, rad: 1.0, a: [0.0, 1.0, 0.0, 0.0], fov: 64, near: 16, far: 62 },
];

export interface FibrilScene {
  /** 0..1 progress through the magnification section, retardation offset in nm */
  setProgress(progress: number, retard?: number): void;
  /** pointer, -1..1 */
  setMouse(x: number, y: number): void;
  dispose(): void;
}

export interface FibrilOptions {
  /** phones: fewer tube segments, no side offset for the copy column */
  compact?: boolean;
  /** the GPU dropped the context: show the static fallback until onRestored */
  onLost?: () => void;
  onRestored?: () => void;
}

/** Throws when WebGL 2 is unavailable; the caller keeps its static fallback. */
export function createFibrilScene(canvas: HTMLCanvasElement, options: FibrilOptions = {}): FibrilScene {
  // three.js needs WebGL 2. Ask for the context here so a WebGL 1-only browser falls back
  // quietly (three would log a console error before throwing).
  const attributes: WebGLContextAttributes = {
    antialias: true,
    alpha: true,
    premultipliedAlpha: true,
    depth: true,
    stencil: false,
    powerPreference: "high-performance",
  };
  const context = canvas.getContext("webgl2", attributes);
  if (!context || context.isContextLost()) throw new Error("WebGL 2 is not available");
  const renderer = new WebGLRenderer({ canvas, context, ...attributes });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);

  const scene = new Scene();
  const camera = new PerspectiveCamera(36, 1, 0.1, 400);
  const group = new Group();
  scene.add(group);

  const deg = Math.PI / 180;
  const inst: Instance[] = [];
  let seed = 1;
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  // S1: thin outer layer, flat helix (large microfibril angle)
  for (let i = 0; i < 22; i++)
    inst.push({ r: 2.2 + rnd() * 0.06, phase: (i / 22) * Math.PI * 2, twist: Math.tan(72 * deg) / 2.2, seed: rnd(), layer: 0 });
  // S2: thick middle layer, steep helix (small microfibril angle)
  [1.2, 1.45, 1.7, 1.95].forEach((r, k) => {
    const n = 16 + k * 3;
    for (let i = 0; i < n; i++)
      inst.push({ r: r + (rnd() - 0.5) * 0.05, phase: (i / n) * Math.PI * 2 + k * 0.4, twist: Math.tan(16 * deg) / r, seed: rnd(), layer: 1 });
  });
  // S3: inner layer lining the lumen
  for (let i = 0; i < 14; i++)
    inst.push({ r: 0.92, phase: (i / 14) * Math.PI * 2, twist: Math.tan(68 * deg) / 0.92, seed: rnd(), layer: 2 });
  // primary wall: loose random net (mixed shallow helices)
  for (let i = 0; i < 10; i++)
    inst.push({ r: 2.42, phase: rnd() * Math.PI * 2, twist: (rnd() - 0.5) * 1.6, seed: rnd(), layer: 3 });

  const geometry = strandGeometry(64, options.compact ? 150 : 240, 0.055, inst);
  const blend = {
    transparent: true,
    depthWrite: false,
    depthTest: false,
    premultipliedAlpha: true,
    blending: CustomBlending,
    blendEquation: AddEquation,
    blendSrc: OneFactor,
    blendDst: OneFactor,
    blendSrcAlpha: OneFactor,
    blendDstAlpha: OneFactor,
  } as const;
  const shared: Record<string, IUniform> = {
    uTime: { value: 0 },
    uFlatten: { value: 0.5 },
    uSpin: { value: 0.035 },
    uRetard: { value: 0 },
    uAlpha: { value: new Vector4(1, 0.7, 0.4, 0.6) },
    uIntensity: { value: 0.7 },
    uFogNear: { value: 60 },
    uFogFar: { value: 200 },
  };
  // the halo pass shares every uniform object with the core pass except uRad / uHalo
  const HALO = 3.6;
  const coreRad: IUniform<number> = { value: 2.2 },
    haloRad: IUniform<number> = { value: 2.2 * HALO };
  const core = new ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: { ...shared, uRad: coreRad, uHalo: { value: 0 } },
    ...blend,
  });
  const halo = new ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: { ...shared, uRad: haloRad, uHalo: { value: 1 } },
    ...blend,
  });
  const meshHalo = new Mesh(geometry, halo),
    meshCore = new Mesh(geometry, core);
  meshHalo.frustumCulled = false;
  meshCore.frustumCulled = false;
  meshHalo.renderOrder = 0;
  meshCore.renderOrder = 1;
  group.add(meshHalo, meshCore);

  let progress = 0,
    retard = 0;
  let mouse: [number, number] = [0, 0];
  const sm: [number, number] = [0, 0];
  const alpha = shared.uAlpha!.value as Vector4;

  function apply() {
    let i = 0;
    while (i < KEYS.length - 2 && progress > KEYS[i + 1]!.p) i++;
    const A = KEYS[i]!,
      B = KEYS[i + 1]!;
    const t = smooth(Math.min(1, Math.max(0, (progress - A.p) / (B.p - A.p))));
    group.rotation.set(lerp(A.rx, B.rx, t) + sm[1] * 0.06, lerp(A.ry, B.ry, t) + sm[0] * 0.08, lerp(A.rz, B.rz, t));
    camera.position.set(0, 0, lerp(A.dist, B.dist, t));
    camera.lookAt(0, 0, 0);
    camera.fov = lerp(A.fov, B.fov, t);
    camera.updateProjectionMatrix();
    shared.uFlatten!.value = lerp(A.flat, B.flat, t);
    alpha.set(lerp(A.a[0], B.a[0], t), lerp(A.a[1], B.a[1], t), lerp(A.a[2], B.a[2], t), lerp(A.a[3], B.a[3], t));
    shared.uFogNear!.value = lerp(A.near, B.near, t);
    shared.uFogFar!.value = lerp(A.far, B.far, t);
    shared.uRetard!.value = retard;
    const rad = lerp(A.rad, B.rad, t);
    coreRad.value = rad;
    haloRad.value = rad * HALO;
  }
  let lastW = 0,
    lastH = 0;
  function resize() {
    const w = canvas.clientWidth || 1,
      h = canvas.clientHeight || 1;
    if (w === lastW && h === lastH) return;
    lastW = w;
    lastH = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // wide screens: push the fibre right / up, clear of the copy in the lower left
    if (w > 860 && !options.compact) camera.setViewOffset(w, h, -w * 0.12, h * 0.12, w, h);
    else camera.setViewOffset(w, h, 0, h * 0.1, w, h);
    camera.updateProjectionMatrix();
  }

  let lost = false,
    disposed = false;
  function frame(t: number) {
    if (lost || disposed) return;
    sm[0] += (mouse[0] - sm[0]) * 0.06;
    sm[1] += (mouse[1] - sm[1]) * 0.06;
    shared.uTime!.value = t;
    resize();
    apply();
    renderer.render(scene, camera);
  }

  /* ---------------------------------------------------------------- lifecycle: only run while visible */
  let running = false,
    raf = 0,
    visible = false;
  const loop = (now: number) => {
    if (!running) return;
    raf = requestAnimationFrame(loop);
    frame(now / 1000);
  };
  const start = () => {
    if (disposed || lost || running || !visible || document.hidden) return;
    running = true;
    raf = requestAnimationFrame(loop);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
  };
  const io = new IntersectionObserver(
    (entries) => {
      visible = entries[0]?.isIntersecting ?? false;
      if (visible) start();
      else stop();
    },
    { rootMargin: "80px" },
  );
  io.observe(canvas);
  const onVisibility = () => (document.hidden ? stop() : start());
  document.addEventListener("visibilitychange", onVisibility);
  // three.js itself calls preventDefault() on loss and re-initialises its state on restore
  const onLost = () => {
    lost = true;
    stop();
    options.onLost?.();
  };
  const onRestored = () => {
    if (disposed) return;
    lost = false;
    lastW = lastH = 0;
    try {
      frame(performance.now() / 1000);
    } catch {
      return;
    }
    start();
    options.onRestored?.();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  frame(performance.now() / 1000);

  return {
    setProgress(p, r = 0) {
      progress = Math.min(1, Math.max(0, p));
      retard = r;
      if (!running && visible) frame(performance.now() / 1000);
    },
    setMouse(x, y) {
      mouse = [x, y];
    },
    dispose() {
      disposed = true;
      stop();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      geometry.dispose();
      core.dispose();
      halo.dispose();
      renderer.dispose();
      try {
        renderer.forceContextLoss();
      } catch {
        /* already lost */
      }
    },
  };
}
