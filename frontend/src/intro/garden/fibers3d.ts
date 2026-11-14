// Three.js scene of the garden prologue: iridescent soft cellulose fibres (ported from the v4
// prototype, js/fibers3d.js · createLanding). Decorative only, and only ever loaded through a
// dynamic import from IntroGarden, so "three" lands in its own chunk on /intro.
//
// Each fibre is one instance of a shared unit tube (s ∈ [0,1] along its length, ring offset in
// yz). The centre-line is computed in the vertex shader, so the same instances can swirl in a
// helical vortex (a suspension being beaten), then settle into a flat, near-orthographic woven
// mat on a cloudy sheet: a sheet of paper forming.
//
// Fibre colours are the garden material colours (palette.ts), and the share of peach / sage /
// lilac fibres follows the real sample composition once it has loaded (setWeights).
import {
  Color,
  Float32BufferAttribute,
  FrontSide,
  Group,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  Mesh,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  WebGLRenderer,
  type IUniform,
} from "three";

function unitTube(segs: number, radial: number) {
  const pos: number[] = [],
    idx: number[] = [];
  for (let i = 0; i <= segs; i++) {
    const s = i / segs;
    for (let j = 0; j <= radial; j++) {
      const a = (j / radial) * Math.PI * 2;
      pos.push(s, Math.cos(a), Math.sin(a));
    }
  }
  for (let i = 0; i < segs; i++)
    for (let j = 0; j < radial; j++) {
      const a = i * (radial + 1) + j,
        b = a + radial + 1;
      idx.push(a, a + 1, b, b, a + 1, b + 1); // counter-clockwise from outside: outward faces are front faces
    }
  const g = new InstancedBufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  return g;
}

const VERT_HEAD = `
uniform float uTime;
uniform float uBeat;
uniform float uRadius;
attribute vec4 aSeed;
attribute vec3 aColor;
varying vec3 vNormal;
varying vec3 vView;
varying vec3 vColor;
varying float vS;
varying float vRand;
varying float vDepth;
varying float vFade;
`;

const VERT_MAIN = `
void main(){
  float s = position.x;
  float e = flatK();
  vec3 c  = C(s);
  vec3 c2 = C(min(s + 0.012, 1.0));
  vec3 c1 = C(max(s - 0.012, 0.0));
  vec3 T = normalize(c2 - c1 + vec3(1e-5, 0.0, 0.0));
  vec3 up = abs(T.y) > 0.92 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
  vec3 B = normalize(cross(T, up));
  vec3 N = cross(B, T);
  float taper = pow(sin(3.14159 * clamp(s, 0.0, 1.0)), 0.5);
  float rad = uRadius * radK() * taper;
  vec2 ring = position.yz;
  float fuzz = 1.0 + uBeat * 0.22 * sin(s * 90.0 + ring.x * 2.0 + aSeed.z * 20.0) * sin(s * 23.0 + aSeed.y * 9.0);
  float fn = mix(1.0, 0.55, e), fb = mix(1.0, 1.3, e);   // flatten into a ribbon when settled
  vec3 off = (N * ring.x * fn + B * ring.y * fb) * rad * fuzz;
  vec3 nrm = normalize(N * ring.x / fn + B * ring.y / fb);
  vec4 mv = modelViewMatrix * vec4(c + off, 1.0);
  vNormal = normalize(normalMatrix * nrm);
  vView = normalize(-mv.xyz);
  vColor = aColor;
  vS = s;
  vRand = aSeed.w;
  vDepth = -mv.z;
  vFade = fadeK();
  gl_Position = projectionMatrix * mv;
}`;

// soft, translucent cellulose: wrap light, thin-film hue shift at grazing angles, velvet sheen,
// back-light translucency, depth fog toward the page colour, premultiplied alpha with soft tips
const FRAG = `
uniform vec3 uBg;
uniform float uFogNear;
uniform float uFogFar;
uniform float uFogAmt;
uniform float uIrid;
uniform float uAlpha;
uniform float uBright;
varying vec3 vNormal;
varying vec3 vView;
varying vec3 vColor;
varying float vS;
varying float vRand;
varying float vDepth;
varying float vFade;
void main(){
  vec3 n = normalize(vNormal);
  if (!gl_FrontFacing) n = -n;
  vec3 v = normalize(vView);
  vec3 L = normalize(vec3(0.35, 0.85, 0.55));
  float ndl = dot(n, L);
  float wrap = clamp((ndl + 0.75) / 1.75, 0.0, 1.0);
  float ndv = clamp(abs(dot(n, v)), 0.0, 1.0);
  float fres = pow(1.0 - ndv, 1.4);
  vec3 col = vColor * (uBright + 0.30 * wrap);
  float ph = ndv * 1.6 + vRand * 1.7 + vS * 0.7;
  vec3 film = 0.80 + 0.20 * cos(6.2831 * (ph + vec3(0.0, 0.33, 0.67)));
  col = mix(col, film * mix(vColor, vec3(1.0), 0.55) * 1.18, clamp(fres * 0.55 * uIrid, 0.0, 0.88));
  vec3 H = normalize(L + v);
  col += pow(max(dot(n, H), 0.0), 40.0) * 0.30;
  col += vec3(1.0, 0.97, 0.99) * pow(1.0 - ndv, 3.0) * 0.16;
  col += vColor * pow(clamp(dot(v, -L) * 0.5 + 0.5, 0.0, 1.0), 3.0) * 0.12;
  float fog = smoothstep(uFogNear, uFogFar, vDepth) * uFogAmt;
  col = mix(col, uBg, fog);
  float tips = smoothstep(0.0, 0.07, vS) * smoothstep(1.0, 0.93, vS);
  float a = uAlpha * mix(0.62, 1.0, fres) * tips * vFade * (1.0 - fog * 0.45);
  gl_FragColor = vec4(col * a, a);
}`;

// helical vortex → woven mat
const LANDING_C = `
uniform float uSettle;
uniform float uSpin;
uniform float uMat;
attribute vec4 aSheet;
attribute float aKind;
float stag(){ return smoothstep(0.0, 1.0, clamp(uSettle * 1.7 - aSeed.w * 0.7, 0.0, 1.0)); }
float flatK(){ return aKind > 0.5 ? 1.0 : stag(); }
float radK(){ return (0.55 + aSeed.w * 1.15) * (aKind > 0.5 ? 0.72 : 1.0); }
float fadeK(){ return aKind > 0.5 ? smoothstep(0.0, 1.0, clamp(uMat * 1.6 - aSeed.x * 0.6, 0.0, 1.0)) : 1.0; }
vec3 vortexC(float s){
  float r = mix(0.42, 2.3, sqrt(aSeed.x));
  float span = 0.45 + aSeed.w * 2.0;
  float omega = 1.7 / (0.55 + r);
  float a = aSeed.z * 6.2831 + uSpin * omega + (s - 0.5) * span;
  float y = (aSeed.y - 0.5) * 2.5 + (s - 0.5) * span * 0.34;
  float rr = r * (0.74 + 0.26 * clamp((y + 1.4) / 2.8, 0.0, 1.0));
  vec3 c = vec3(cos(a) * rr, y, sin(a) * rr);
  float k = 5.0 + aSeed.w * 6.0;
  c += vec3(cos(s * k + uTime * 0.7 + aSeed.y * 6.0), sin(s * k * 0.7 + aSeed.z * 5.0 + uTime * 0.5), sin(s * k + uTime * 0.7)) * 0.028 * (1.0 + uBeat * 3.2);
  return c;
}
vec3 sheetC(float s){
  vec2 dir = vec2(cos(aSheet.z), sin(aSheet.z));
  vec2 nr = vec2(-dir.y, dir.x);
  float L = aSheet.w;
  float bend = (aSeed.z - 0.5) * 0.55;
  vec2 xz = aSheet.xy + dir * (s - 0.5) * L
          + nr * (sin(s * 3.14159 * (1.0 + aSeed.w * 1.4) + aSeed.z * 6.0) * 0.035 * L + bend * (s - 0.5) * (s - 0.5) * L);
  float y = sin(s * L * 4.6 + aSeed.z * 17.0) * 0.028 + (aSeed.y - 0.5) * 0.05;
  return vec3(xz.x, y, xz.y);
}
vec3 C(float s){
  if (aKind > 0.5) { vec3 c = sheetC(s); c.y += (1.0 - fadeK()) * 1.1; return c; }
  float e = stag();
  vec3 c = mix(vortexC(s), sheetC(s), e);
  c.y += sin(e * 3.14159) * 0.5 * (0.5 + aSeed.x);
  return c;
}`;

// the cloudy formation of a sheet of paper, under the settled mat
const SHEET_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const SHEET_FRAG = `
uniform float uSheet;
uniform vec3 uPaper;
uniform vec3 uPaperShade;
varying vec2 vUv;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n2(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1.0, 0.0)), f.x), mix(h(i + vec2(0.0, 1.0)), h(i + vec2(1.0)), f.x), f.y); }
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++){ s += a * n2(p); p *= 2.03; a *= 0.5; } return s; }
void main(){
  vec2 p = vUv * vec2(16.0, 11.0);
  float f = fbm(p * 0.75);
  vec3 col = mix(uPaper, uPaperShade, smoothstep(0.35, 0.75, f));
  float edge = smoothstep(0.0, 0.16, min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y)));
  float a = uSheet * (0.80 + 0.12 * f) * edge;
  gl_FragColor = vec4(col * a, a);
}`;

export interface LandingColors {
  softwood: string;
  hardwood: string;
  blend: string;
  /** fibres are lightened toward this colour (the chart paper) */
  paper: string;
  /** depth fog colour (the page colour) */
  fog: string;
  /** shade of the cloudy paper formation */
  paperShade: string;
}

export interface LandingTarget {
  settle: number;
  beat: number;
  gx: number;
  camY: number;
  camZ: number;
  lookY: number;
  fov: number;
  mx: number;
  my: number;
}

export interface LandingOptions {
  mobile: boolean;
  /** reduced motion: draw still frames only, no spin, no easing */
  still: boolean;
  colors: LandingColors;
  /** relative weights of softwood / hardwood / blend fibres (the sample composition) */
  weights?: readonly [number, number, number] | null;
  /** the GPU dropped the context: hide the canvas until onRestored */
  onLost?: () => void;
  /** the context came back and a frame has been drawn */
  onRestored?: () => void;
}

export interface LandingScene {
  set(values: Partial<LandingTarget>): void;
  setStill(still: boolean): void;
  setWeights(weights: readonly [number, number, number]): void;
  /** pause while the stage is off screen */
  setVisible(visible: boolean): void;
  dispose(): void;
}

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

type Kind = "core" | "veil" | "mat";
interface Strand {
  seed: [number, number, number, number];
  sheet: [number, number, number, number];
  /** uniform random number that picks the material colour */
  pick: number;
  kind: Kind;
}

const easeStep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** Throws when WebGL is unavailable; the caller keeps the CSS / photo fallback. */
export function createLanding(canvas: HTMLCanvasElement, options: LandingOptions): LandingScene {
  const { mobile, colors } = options;
  let still = options.still;
  const renderer = new WebGLRenderer({
    canvas,
    antialias: !mobile,
    alpha: true,
    premultipliedAlpha: true,
    powerPreference: "high-performance",
  });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const scene = new Scene();
  const camera = new PerspectiveCamera(34, 1, 0.1, 80);
  const R = rng(20261111);
  const nCore = mobile ? 34 : 58,
    nVeil = mobile ? 30 : 58,
    nMat = mobile ? 90 : 180;
  const total = nCore + nVeil + nMat;

  // sheet placement: a jittered grid, so the settled mat is even, like a well-formed sheet
  const SW = 11.5,
    SD = 7.4;
  const cols = Math.ceil(Math.sqrt((total * SW) / SD)),
    rows = Math.ceil(total / cols);
  const cells = Array.from({ length: cols * rows }, (_, i) => i);
  for (let i = cells.length - 1; i > 0; i--) {
    const j = Math.floor(R() * (i + 1));
    [cells[i], cells[j]] = [cells[j]!, cells[i]!];
  }
  const strand = (i: number, kind: Kind): Strand => {
    const cell = cells[i]!;
    const cx = ((cell % cols) + 0.15 + R() * 0.7) / cols,
      cz = (Math.floor(cell / cols) + 0.15 + R() * 0.7) / rows;
    // machine direction: most fibres lie roughly along x, some cross it
    const th = R() < 0.62 ? (R() - 0.5) * 1.1 : (R() - 0.5) * Math.PI;
    const pick = R();
    // mat-only strands are shorter fines that fill the sheet between the long fibres
    const len = kind === "mat" ? 0.6 + R() * 1.6 : 1.2 + R() * 2.4;
    return { seed: [R(), R(), R(), R()], sheet: [(cx - 0.5) * SW, (cz - 0.5) * SD, th, len], pick, kind };
  };
  const all: Strand[] = [];
  for (let i = 0; i < total; i++) all.push(strand(i, i < nCore ? "core" : i < nCore + nVeil ? "veil" : "mat"));

  const material = [new Color(colors.softwood), new Color(colors.hardwood), new Color(colors.blend)] as const;
  const paper = new Color(colors.paper);
  const lighten: Record<Kind, number> = { core: 0.1, veil: 0.26, mat: 0.32 };
  let weights: readonly [number, number, number] = options.weights ?? [1, 1, 1];
  const colourOf = (s: Strand, out: Float32Array, k: number) => {
    const sum = weights[0] + weights[1] + weights[2] || 1;
    const t = s.pick * sum;
    const base = t < weights[0] ? material[0] : t < weights[0] + weights[1] ? material[1] : material[2];
    const c = base.clone().lerp(paper, lighten[s.kind]);
    out[k * 3] = c.r;
    out[k * 3 + 1] = c.g;
    out[k * 3 + 2] = c.b;
  };

  const uniforms: Record<string, IUniform> = {
    uTime: { value: 0 },
    uBeat: { value: 0 },
    uRadius: { value: mobile ? 0.013 : 0.011 },
    uBg: { value: new Color(colors.fog) },
    uFogNear: { value: 6 },
    uFogFar: { value: 14 },
    uFogAmt: { value: 0.5 },
    uIrid: { value: 1.6 },
    uBright: { value: 0.8 },
    uSettle: { value: 0 },
    uSpin: { value: 0 },
    uMat: { value: 0 },
  };
  const segs = mobile ? 40 : 56,
    radial = mobile ? 5 : 6;
  const group = new Group();
  scene.add(group);

  const sheetUniforms: Record<string, IUniform> = {
    uSheet: { value: 0 },
    uPaper: { value: new Color(colors.paper) },
    uPaperShade: { value: new Color(colors.paperShade) },
  };
  const sheetGeo = new PlaneGeometry(16, 11, 1, 1);
  sheetGeo.rotateX(-Math.PI / 2);
  const sheetMat = new ShaderMaterial({
    uniforms: sheetUniforms,
    vertexShader: SHEET_VERT,
    fragmentShader: SHEET_FRAG,
    transparent: true,
    premultipliedAlpha: true,
    depthWrite: false,
  });
  const sheet = new Mesh(sheetGeo, sheetMat);
  sheet.position.y = -0.09;
  sheet.renderOrder = -1;
  sheet.visible = false;
  group.add(sheet);

  const layers: { mesh: Mesh<InstancedBufferGeometry, ShaderMaterial>; list: Strand[]; colour: InstancedBufferAttribute }[] = [];
  const add = (list: Strand[], alpha: number, depthWrite: boolean, order: number) => {
    const geo = unitTube(segs, radial);
    geo.instanceCount = list.length;
    geo.setAttribute("aSeed", new InstancedBufferAttribute(new Float32Array(list.flatMap((s) => s.seed)), 4));
    geo.setAttribute("aSheet", new InstancedBufferAttribute(new Float32Array(list.flatMap((s) => s.sheet)), 4));
    geo.setAttribute("aKind", new InstancedBufferAttribute(new Float32Array(list.map((s) => (s.kind === "mat" ? 1 : 0))), 1));
    const colourArray = new Float32Array(list.length * 3);
    list.forEach((s, k) => colourOf(s, colourArray, k));
    const colour = new InstancedBufferAttribute(colourArray, 3);
    geo.setAttribute("aColor", colour);
    const mat = new ShaderMaterial({
      uniforms: { ...uniforms, uAlpha: { value: alpha } },
      vertexShader: VERT_HEAD + LANDING_C + VERT_MAIN,
      fragmentShader: FRAG,
      side: FrontSide, // closed, tapered tubes: only the outer wall, no striped self-blending
      transparent: true,
      premultipliedAlpha: true,
      depthWrite,
    });
    const mesh = new Mesh(geo, mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = order;
    group.add(mesh);
    layers.push({ mesh, list, colour });
    return mesh;
  };
  add(all.slice(0, nCore), 0.96, true, 0);
  add(all.slice(nCore, nCore + nVeil), 0.5, false, 1);
  const matMesh = add(all.slice(nCore + nVeil), 0.62, false, 2);
  matMesh.visible = false;

  const target: LandingTarget = { settle: 0, beat: 0, gx: 2.3, camY: 1.7, camZ: 8.6, lookY: 0, fov: 34, mx: 0, my: 0 };
  const cur: LandingTarget = { ...target };
  const keys = Object.keys(target) as (keyof LandingTarget)[];
  let spin = 0,
    time = 0,
    raf = 0,
    last = 0,
    running = false,
    visible = true,
    lost = false,
    disposed = false,
    dirty = true,
    width = 0,
    height = 0;

  const size = () => {
    const w = canvas.clientWidth,
      h = canvas.clientHeight;
    if (w === width && h === height) return;
    width = w;
    height = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(1, h);
    dirty = true;
  };
  /** true while the eased values have not reached their targets */
  const easing = () => keys.some((k) => Math.abs(target[k] - cur[k]) > 1e-4);
  const render = (dt: number) => {
    if (disposed || lost) return;
    size();
    const k = still ? 1 : 1 - Math.pow(0.02, dt);
    for (const key of keys) cur[key] += (target[key] - cur[key]) * k;
    if (still) {
      // a still frame: the vortex keeps its phase, nothing drifts
      cur.mx = cur.my = 0;
    } else {
      const speed = (0.2 + cur.beat * 1.35) * (1 - cur.settle * 0.97);
      spin += dt * speed;
      time += dt;
    }
    uniforms.uTime!.value = time;
    uniforms.uSpin!.value = spin;
    uniforms.uBeat!.value = cur.beat;
    uniforms.uSettle!.value = cur.settle;
    uniforms.uMat!.value = easeStep(0.5, 1.0, cur.settle);
    sheetUniforms.uSheet!.value = easeStep(0.6, 1.0, cur.settle);
    matMesh.visible = uniforms.uMat!.value > 0.004;
    sheet.visible = sheetUniforms.uSheet!.value > 0.004;
    group.position.x = cur.gx;
    group.rotation.y = -0.25 + cur.mx * 0.12;
    group.rotation.z = (1 - cur.settle) * 0.1;
    camera.fov = cur.fov;
    camera.updateProjectionMatrix();
    const par = 1 - cur.settle * 0.6;
    camera.position.set(cur.mx * 0.55 * par, cur.camY + cur.my * 0.35 * par, cur.camZ);
    camera.lookAt(0, cur.lookY, 0);
    const dist = camera.position.length();
    uniforms.uFogNear!.value = dist - 1.0;
    uniforms.uFogFar!.value = dist + 4.2;
    uniforms.uFogAmt!.value = 0.55 * (1 - cur.settle * 0.7);
    renderer.render(scene, camera);
    dirty = false;
  };
  const loop = (t: number) => {
    if (!running) return;
    raf = requestAnimationFrame(loop);
    const dt = t > last ? Math.min(0.05, (t - last) / 1000) : 0.016;
    last = t;
    // once the sheet has formed and nothing eases any more, the picture is static: skip frames
    if (!dirty && cur.settle > 0.999 && !easing()) return;
    render(dt);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
  };
  const start = () => {
    if (running || disposed || lost || !visible || document.hidden) return;
    if (still) {
      render(1);
      return;
    }
    running = true;
    last = performance.now();
    raf = requestAnimationFrame(loop);
  };
  const onVisibility = () => (document.hidden ? stop() : start());
  const onResize = () => {
    dirty = true;
    if (still) render(1);
  };
  // three.js calls preventDefault() on webglcontextlost and rebuilds its GL state on restore;
  // the scene re-uploads its buffers and programs on the next render
  const onLost = () => {
    lost = true;
    stop();
    options.onLost?.();
  };
  const onRestored = () => {
    if (disposed) return;
    lost = false;
    dirty = true;
    try {
      render(0.016);
    } catch {
      return;
    }
    options.onRestored?.();
    start();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("resize", onResize);

  render(0.016);
  start();

  return {
    set(values) {
      Object.assign(target, values);
      dirty = true;
      if (still) render(1);
    },
    setStill(next) {
      if (next === still) return;
      still = next;
      stop();
      dirty = true;
      start();
    },
    setWeights(next) {
      if (next.every((v, i) => v === weights[i])) return;
      weights = next;
      for (const layer of layers) {
        const array = layer.colour.array as Float32Array;
        layer.list.forEach((s, k) => colourOf(s, array, k));
        layer.colour.needsUpdate = true;
      }
      dirty = true;
      if (still) render(1);
    },
    setVisible(next) {
      if (next === visible) return;
      visible = next;
      if (visible) start();
      else stop();
    },
    dispose() {
      disposed = true;
      stop();
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      for (const layer of layers) {
        layer.mesh.geometry.dispose();
        layer.mesh.material.dispose();
      }
      sheetGeo.dispose();
      sheetMat.dispose();
      renderer.dispose();
      try {
        renderer.forceContextLoss();
      } catch {
        /* noop */
      }
    },
  };
}
