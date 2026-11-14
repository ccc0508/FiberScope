// 「纸浆悬浮液」 pulp-suspension shader — ported from the v4 prototype (js/pulp-shader.js).
// A luminous gradient mesh, three pastel metaball "stain" fields (peach / sage / lilac) carried by
// domain-warped fBm flow, and thin plum fibre filaments. The pointer stirs the flow, scrolling
// gives a short "beating" pulse.
//
// Decorative only: createPulp() returns null instead of throwing when WebGL is unavailable;
// the CSS mesh gradient underneath is the fallback.

const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main(){ vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }`;

const FRAG = (deriv: boolean) => `
${deriv ? "#extension GL_OES_standard_derivatives : enable\n#define HAS_DERIV 1" : ""}
precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uMouse;
uniform vec2 uVel;
uniform float uBeat;
uniform float uIntensity;
uniform float uFibers;
uniform float uSettle;
uniform float uFilA;

const vec3 CREAM = vec3(1.000, 0.957, 0.933);
const vec3 MIST  = vec3(0.945, 0.941, 0.980);
const vec3 SAGEB = vec3(0.933, 0.965, 0.937);
const vec3 PEACH = vec3(1.000, 0.735, 0.600);
const vec3 SAGE  = vec3(0.640, 0.800, 0.665);
const vec3 LILAC = vec3(0.760, 0.680, 0.915);
const vec3 PLUM  = vec3(0.165, 0.133, 0.220);

vec2 hash2(vec2 p){
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float gnoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(dot(hash2(i), f), dot(hash2(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
             mix(dot(hash2(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)), dot(hash2(i + vec2(1.0)), f - vec2(1.0)), u.x), u.y);
}
float fbm(vec2 p){
  float s = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 4; i++){ s += a * gnoise(p); p = m * p; a *= 0.5; }
  return s;
}
float h1(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main(){
  float asp = uRes.x / uRes.y;
  vec2 uv = vUv;
  vec2 p = vec2((uv.x - 0.5) * asp, uv.y - 0.5);
  float t = uTime * 0.045;

  vec2 m = vec2((uMouse.x - 0.5) * asp, uMouse.y - 0.5);
  vec2 dm = p - m;
  float fall = exp(-dot(dm, dm) * 6.0);
  float sp = length(uVel);
  float side = uVel.x * dm.y - uVel.y * dm.x;
  float ang = fall * clamp(sp * 1.6, 0.0, 1.4) * (side >= 0.0 ? 1.0 : -1.0);
  float ca = cos(ang), sa = sin(ang);
  p = m + mat2(ca, sa, -sa, ca) * dm;
  p -= uVel * fall * 0.10;

  float rr0 = length(p);
  float swirl = uBeat * (1.5 * exp(-rr0 * rr0 * 1.3) + 0.35 * sin(t * 2.4 + rr0 * 2.0));
  float cs = cos(swirl), ss = sin(swirl);
  p = mat2(cs, ss, -ss, cs) * p;

  float turb = 0.32 + uBeat * 0.85;
  float freq = 1.15 + uBeat * 0.55;
  vec2 q = vec2(fbm(p * freq + vec2(0.0, t * 2.0)), fbm(p * freq + vec2(5.2, 1.3) - t * 1.7));
  vec2 r = vec2(fbm(p * freq + q * 2.2 * turb + vec2(1.7, 9.2) + t * 1.3),
                fbm(p * freq + q * 2.2 * turb + vec2(8.3, 2.8) - t * 1.1));
  vec2 w = p + r * turb * 0.62;

  float gx = uv.x * 0.85 + (1.0 - uv.y) * 0.35;
  vec3 bg = mix(CREAM, MIST, smoothstep(0.1, 0.85, gx));
  bg = mix(bg, SAGEB, smoothstep(0.35, 1.0, uv.x * 0.5 + (1.0 - uv.y) * 0.7) * 0.85);

  vec3 acc = vec3(0.0);
  float wsum = 0.0;
  for (int i = 0; i < 6; i++){
    float fi = float(i);
    vec2 c = vec2(sin(t * 2.6 * (0.55 + 0.11 * fi) + fi * 1.9) * 0.58 * asp,
                  cos(t * 2.2 * (0.50 + 0.13 * fi) + fi * 2.7) * 0.40);
    vec2 d = w - c;
    float f = 0.055 / (dot(d, d) + 0.03);
    float k = mod(fi, 3.0);
    vec3 col = k < 0.5 ? PEACH : (k < 1.5 ? SAGE : LILAC);
    acc += col * f;
    wsum += f;
  }
  vec3 blob = acc / wsum;
  blob = mix(vec3(dot(blob, vec3(0.3333))), blob, 1.0 + uBeat * 0.75);
  float dens = smoothstep(0.9 - uBeat * 0.35, 3.4 - uBeat * 1.3, wsum);
  vec3 col = mix(bg, blob, clamp(dens * (0.78 + uBeat * 0.14) * uIntensity, 0.0, 0.95));

  float hl = smoothstep(0.18, 0.55, fbm(w * 2.1 - t * 0.8) + 0.25);
  col = mix(col, vec3(1.0), hl * 0.16 * uIntensity * (1.0 - min(uBeat, 1.0) * 0.6));

  vec2 fs = mix(vec2(2.1, 2.1), vec2(0.65, 4.2), uSettle);
  vec2 fw = w * fs;
  float v = fbm(fw * 1.25 + vec2(t * 0.6, -t * 0.4)) * (8.0 + uBeat * 2.0);
  float dist = abs(fract(v) - 0.5);
  dist = 0.5 - dist;
#ifdef HAS_DERIV
  float fwv = fwidth(v);
#else
  float fwv = 0.04 * (8.0 + uBeat * 2.0) / uRes.y * 300.0;
#endif
  float px = dist / max(fwv, 1e-4);
  float line = 1.0 - smoothstep(0.35, 1.35, px);
  float halo = 1.0 - smoothstep(0.8, 4.0, px);
  float seg = smoothstep(0.08, 0.32, gnoise(w * (2.6 + uBeat * 1.4) + vec2(13.1, 7.7) + t * 0.5));
  float thick = 0.55 + 0.45 * smoothstep(-0.2, 0.4, gnoise(w * 5.0 + 3.0));
  float fib = line * seg * thick * uFibers;
  float bk = clamp(uBeat, 0.0, 1.0);
  col = mix(col, col * 0.9 + PLUM * 0.05, halo * seg * (0.35 - bk * 0.22) * uFibers);
  col = mix(col, PLUM, fib * uFilA * mix(1.0, 0.6, bk));

  float vg = length(vec2((uv.x - 0.5) * 1.1, uv.y - 0.45));
  col = mix(col, vec3(1.0, 0.99, 0.985), (1.0 - smoothstep(0.0, 0.75, vg)) * 0.10);
  col *= 1.0 - smoothstep(0.55, 1.15, vg) * 0.05;

  col += (h1(gl_FragCoord.xy + fract(uTime)) - 0.5) / 255.0 * 1.5;
  gl_FragColor = vec4(col, 1.0);
}`;

export interface PulpTarget {
  intensity: number;
  fibers: number;
  beat: number;
  settle: number;
  /** render-buffer scale relative to CSS pixels */
  scale: number;
  fps: number;
  filA: number;
  /** stop rendering this many ms after the last stir / pulse (0 = never) */
  idle: number;
}

export interface PulpController {
  set(values: Partial<PulpTarget>): void;
  /** scroll / interaction "beating" pulse, 0..1 */
  pulse(amount: number): void;
  setStill(still: boolean): void;
  dispose(): void;
}

const UNIFORMS = ["uRes", "uTime", "uMouse", "uVel", "uBeat", "uIntensity", "uFibers", "uSettle", "uFilA"] as const;
type UniformName = (typeof UNIFORMS)[number];

export interface PulpOptions {
  target?: Partial<PulpTarget>;
  still?: boolean;
  onReady?: () => void;
  /** the GPU dropped the context (driver reset, sleep): show the CSS mesh until onRestored */
  onLost?: () => void;
  /** the context came back, the program was rebuilt and a frame was drawn */
  onRestored?: () => void;
  /** the context came back but could not be rebuilt: keep the CSS mesh for good */
  onFail?: () => void;
}

export function createPulp(canvas: HTMLCanvasElement, options: PulpOptions = {}): PulpController | null {
  let gl: WebGLRenderingContext | null = null;
  try {
    gl = canvas.getContext("webgl", {
      antialias: false, alpha: false, depth: false, stencil: false,
      powerPreference: "low-power", preserveDrawingBuffer: false,
    });
  } catch {
    gl = null;
  }
  if (!gl || gl.isContextLost()) return null;
  const ctx = gl;
  const loseContext = () => {
    try {
      ctx.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      /* noop */
    }
  };

  let prog: WebGLProgram | null = null;
  let buf: WebGLBuffer | null = null;
  const U: Partial<Record<UniformName, WebGLUniformLocation | null>> = {};
  // compile + link + upload the full-screen triangle; also used after a context restore
  const build = (): boolean => {
    try {
      const deriv = !!ctx.getExtension("OES_standard_derivatives");
      const sh = (type: number, src: string) => {
        const s = ctx.createShader(type);
        if (!s) return null;
        ctx.shaderSource(s, src);
        ctx.compileShader(s);
        return ctx.getShaderParameter(s, ctx.COMPILE_STATUS) ? s : null;
      };
      const vs = sh(ctx.VERTEX_SHADER, VERT),
        fs = sh(ctx.FRAGMENT_SHADER, FRAG(deriv));
      if (!vs || !fs) return false;
      prog = ctx.createProgram();
      if (!prog) return false;
      ctx.attachShader(prog, vs);
      ctx.attachShader(prog, fs);
      ctx.linkProgram(prog);
      if (!ctx.getProgramParameter(prog, ctx.LINK_STATUS)) return false;
      ctx.useProgram(prog);
      buf = ctx.createBuffer();
      ctx.bindBuffer(ctx.ARRAY_BUFFER, buf);
      ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), ctx.STATIC_DRAW);
      const loc = ctx.getAttribLocation(prog, "aPos");
      ctx.enableVertexAttribArray(loc);
      ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);
      for (const name of UNIFORMS) U[name] = ctx.getUniformLocation(prog, name);
      return true;
    } catch {
      return false;
    }
  };
  if (!build()) {
    loseContext();
    return null;
  }

  const target: PulpTarget = {
    intensity: 1, fibers: 1, beat: 0, settle: 0, scale: 0.5, fps: 30, filA: 0.42, idle: 0,
    ...options.target,
  };
  const cur = { intensity: target.intensity * 0.75, fibers: target.fibers, beat: 0, settle: target.settle, filA: target.filA };
  let still = !!options.still;
  let pulseAmt = 0;
  const mouse = { x: 0.62, y: 0.55, vx: 0, vy: 0, lx: null as number | null, ly: null as number | null, lt: 0 };
  let raf = 0, last = 0, time = 7.0, running = false, lost = false, disposed = false;
  let wokeAt = performance.now();

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.max(2, Math.round(canvas.clientWidth * dpr * target.scale));
    const h = Math.max(2, Math.round(canvas.clientHeight * dpr * target.scale));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  };
  const draw = (dt: number) => {
    if (disposed || lost || ctx.isContextLost()) return;
    const k = 1 - Math.pow(0.04, dt);
    cur.intensity += (target.intensity - cur.intensity) * k;
    cur.fibers += (target.fibers - cur.fibers) * k;
    cur.beat += (Math.min(1.4, target.beat + pulseAmt) - cur.beat) * Math.min(1, k * 1.6);
    cur.settle += (target.settle - cur.settle) * k;
    cur.filA += (target.filA - cur.filA) * k;
    pulseAmt *= Math.pow(0.25, dt);
    mouse.vx *= Math.pow(0.12, dt);
    mouse.vy *= Math.pow(0.12, dt);
    resize();
    ctx.viewport(0, 0, canvas.width, canvas.height);
    ctx.uniform2f(U.uRes ?? null, canvas.width, canvas.height);
    ctx.uniform1f(U.uTime ?? null, time);
    ctx.uniform2f(U.uMouse ?? null, mouse.x, mouse.y);
    ctx.uniform2f(U.uVel ?? null, Math.max(-3, Math.min(3, mouse.vx)), Math.max(-3, Math.min(3, mouse.vy)));
    ctx.uniform1f(U.uBeat ?? null, cur.beat);
    ctx.uniform1f(U.uIntensity ?? null, cur.intensity);
    ctx.uniform1f(U.uFibers ?? null, cur.fibers);
    ctx.uniform1f(U.uSettle ?? null, cur.settle);
    ctx.uniform1f(U.uFilA ?? null, cur.filA);
    ctx.drawArrays(ctx.TRIANGLES, 0, 3);
  };
  const drawStill = () => {
    Object.assign(cur, { intensity: target.intensity, fibers: target.fibers, beat: target.beat, settle: target.settle, filA: target.filA });
    pulseAmt = 0;
    mouse.vx = mouse.vy = 0;
    draw(1);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
  };
  const loop = (t: number) => {
    if (!running) return;
    raf = requestAnimationFrame(loop);
    if (lost) return;
    if (t - last < 1000 / target.fps - 1) return;
    const dt = t > last ? Math.min(0.1, (t - last) / 1000) : 0.016;
    last = t;
    time += dt * (1 + cur.beat * 1.8);
    draw(dt);
    if (
      target.idle &&
      t - wokeAt > target.idle &&
      pulseAmt < 0.01 &&
      Math.abs(target.intensity - cur.intensity) < 0.01 &&
      Math.abs(target.beat - cur.beat) < 0.01
    )
      stop();
  };
  const start = () => {
    if (running || document.hidden || lost || disposed) return;
    if (still) {
      drawStill();
      return;
    }
    running = true;
    last = performance.now();
    raf = requestAnimationFrame(loop);
  };
  const wake = () => {
    wokeAt = performance.now();
    if (!running) start();
  };
  const onMove = (event: PointerEvent) => {
    if (still) return;
    const now = performance.now();
    const x = event.clientX / window.innerWidth,
      y = 1 - event.clientY / window.innerHeight;
    if (mouse.lx != null && mouse.ly != null) {
      const dt = Math.max(8, now - mouse.lt) / 1000;
      const asp = window.innerWidth / window.innerHeight;
      mouse.vx = mouse.vx * 0.6 + (((x - mouse.lx) * asp) / dt) * 0.4;
      mouse.vy = mouse.vy * 0.6 + ((y - mouse.ly) / dt) * 0.4;
    }
    mouse.lx = x;
    mouse.ly = y;
    mouse.lt = now;
    mouse.x = x;
    mouse.y = y;
    wake();
  };
  const onVisibility = () => (document.hidden ? stop() : wake());
  const onResize = () => (still ? drawStill() : wake());
  const onLost = (event: Event) => {
    // preventDefault() asks the browser to restore the context; onRestored rebuilds it
    event.preventDefault();
    lost = true;
    stop();
    options.onLost?.();
  };
  const onRestored = () => {
    if (disposed) return;
    lost = false;
    // the old program and buffer belonged to the dead context
    if (!build()) {
      options.onFail?.();
      return;
    }
    try {
      if (still) drawStill();
      else draw(0.016);
    } catch {
      options.onFail?.();
      return;
    }
    options.onRestored?.();
    wake();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);
  window.addEventListener("pointermove", onMove, { passive: true });
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("resize", onResize);

  try {
    resize();
    if (still) drawStill();
    else draw(0.016);
  } catch {
    loseContext();
    return null;
  }
  options.onReady?.();
  start();

  return {
    set(values) {
      Object.assign(target, values);
      if (still) drawStill();
      else wake();
    },
    pulse(amount) {
      if (still) return;
      pulseAmt = Math.min(1, pulseAmt + amount);
      wake();
    },
    setStill(next) {
      if (next === still) return;
      still = next;
      stop();
      if (still) drawStill();
      else wake();
    },
    dispose() {
      disposed = true;
      stop();
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      try {
        ctx.deleteBuffer(buf);
        ctx.deleteProgram(prog);
      } catch {
        /* noop */
      }
      loseContext();
    },
  };
}
