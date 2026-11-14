// 「偏光」 birefringence field — ported from the v1 prototype (js/field.js).
// Flowing cellulose fibres are built from domain-warped value noise; each ribbon carries an
// optical path difference (retardation, nm) and is coloured with a thin-film / Michel-Lévy
// interference function. Transmitted light follows the polarizer–analyzer law
//   I(λ) = cos²χ − sin2θ · sin2(θ−χ) · sin²(πΓ/λ)
// where θ is the local fibre direction, χ the analyzer angle and Γ the retardation.
//
// Decorative only: createField() returns null instead of throwing when WebGL, the shader
// or the context is unavailable; callers then show a CSS gradient.

const LAMBDAS = [400, 428, 456, 484, 512, 540, 568, 596, 624, 652, 680];
const g = (l: number, m: number, s: number) => Math.exp(-(((l - m) / s) ** 2));
const W = LAMBDAS.map((l) => [g(l, 602, 46) + 0.28 * g(l, 432, 20), g(l, 545, 40), g(l, 452, 30)] as const);
const SUM = W.reduce((a, w) => [a[0] + w[0], a[1] + w[1], a[2] + w[2]], [0, 0, 0]);
const f5 = (x: number) => x.toFixed(5);

/**
 * GLSL interference colour: `michel(G)` (Michel-Lévy colour for a retardation G in nm),
 * `foldG`, `brandRamp` and `interf(G)` (the brand-tinted colour the field paints with), plus
 * the helper `s2_`. Shared with the prologue's microfibril helix (src/intro/polarized/fibril3d.ts).
 */
export const INTERFERENCE_GLSL = `
float s2_(float x){ float s = sin(x); return s*s; }
vec3 michel(float G){
  vec3 c = vec3(0.0);
${LAMBDAS.map((l, i) => `  c += vec3(${f5(W[i]![0] / SUM[0]!)}, ${f5(W[i]![1] / SUM[1]!)}, ${f5(W[i]![2] / SUM[2]!)}) * s2_(G * ${f5(Math.PI / l)});`).join("\n")}
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

const FRAG_BODY = `
uniform vec2 uRes;
uniform float uTime;
uniform float uAnalyzer;
uniform float uRetard;
uniform float uZoom;
uniform float uScroll;
uniform vec2 uStage;
uniform float uIntensity;
uniform float uTexAmt;
uniform vec2 uTexSize;
uniform vec2 uFocus;
uniform float uVig;
uniform float uGrain;
uniform float uDensity;
uniform float uLeft;
uniform sampler2D uTex;
#define PI 3.14159265

float h1(float n){ return fract(sin(n) * 43758.5453123); }
float h2(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h2(i), h2(i + vec2(1.0, 0.0)), u.x), mix(h2(i + vec2(0.0, 1.0)), h2(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p){
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++){ s += a * vnoise(p); p = mat2(1.62, 1.18, -1.18, 1.62) * p; a *= 0.5; }
  return s;
}
${INTERFERENCE_GLSL}

vec3 fibres(vec2 p, float ang, float dens, float seed, float soft){
  float c = cos(ang), s = sin(ang);
  vec2 r = mat2(c, -s, s, c) * p;
  vec2 w = vec2(fbm(r * 0.42 + seed + vec2(uTime * 0.018, 0.0)),
                fbm(r * 0.42 + seed * 1.73 + 5.2 - vec2(0.0, uTime * 0.014)));
  vec2 q = r + (w - 0.5) * 2.4;
  float v = q.y * dens;
  float id = floor(v);
  float f = fract(v) - 0.5;
  float ha = h1(id * 12.9898 + seed * 78.233);
  float hb = h1(id * 3.171 + seed * 1.7);
  float hc = h1(id * 7.31 + seed * 3.1);
  float lane = step(1.0 - uDensity, hc);
  float width = mix(0.11, 0.33, ha);
  float off = (hb - 0.5) * (0.5 - width) * 1.4;
  float d = abs(f - off);
  float edge = 1.0 - smoothstep(width - mix(0.015, 0.11, soft), width, d);
  float along = q.x * 0.24 / (0.55 + ha) + hb * 17.0;
  float seg = smoothstep(0.30, 0.44, vnoise(vec2(along, id * 1.37 + seed)));
  float m = edge * seg * lane;
  if (m < 0.002) return vec3(0.0);
  float x = clamp(d / width, 0.0, 1.0);
  float thick = 0.62 + 0.38 * smoothstep(0.35, 0.95, x);
  vec2 pc = vec2(fract(q.x * dens * 1.15 + ha * 3.0) - 0.5, (f - off) / width * 0.42);
  float pd = length(pc);
  float pit = step(0.72, h1(floor(q.x * dens * 1.15 + ha * 3.0) + id)) * smoothstep(0.17, 0.12, pd) * smoothstep(0.04, 0.08, pd);
  float stri = 0.86 + 0.14 * sin((q.x * 2.2 + f * 6.0) * 26.0 * (0.6 + hb));
  float G = mix(240.0, 1450.0, ha * 0.7 + hb * 0.3) * thick + uRetard + 150.0 * vnoise(q * vec2(0.35, 5.0) + seed) + pit * 150.0;
  vec2 gr = vec2(dFdx(v), dFdy(v));
  float theta = atan(gr.y, gr.x + 1e-5) + PI * 0.5;
  float k = -sin(2.0 * theta) * sin(2.0 * (theta - uAnalyzer));
  vec3 col = interf(G) * max(k, 0.07);
  col = mix(vec3(dot(col, vec3(0.333))), col, 1.45);
  return max(col, 0.0) * m * stri;
}

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  vec2 p = uv / uZoom;
  vec3 col = vec3(0.0);
  col += 0.40 * fibres(p * 1.05 + uStage * 0.05 - vec2(0.0, uScroll * 0.10), 0.62, 3.0, 3.1, 1.0);
  col += 0.80 * fibres(p * 1.75 + uStage * 0.12 - vec2(-0.3, uScroll * 0.26), -0.38, 2.5, 7.7, 0.45);
  col += 1.05 * fibres(p * 2.65 + uStage * 0.22 - vec2(0.2, uScroll * 0.46), 1.08, 2.15, 1.9, 0.10);

  if (uTexAmt > 0.001) {
    vec2 tuv = gl_FragCoord.xy / uRes;
    float sa = uRes.x / uRes.y, ia = uTexSize.x / max(uTexSize.y, 1.0);
    if (sa > ia) tuv.y = (tuv.y - 0.5) * ia / sa + 0.5; else tuv.x = (tuv.x - 0.5) * sa / ia + 0.5;
    tuv = (tuv - 0.5) / (1.0 + 0.08 * uScroll) + 0.5 + uStage * vec2(-0.012, 0.012) + vec2(0.0, uScroll * 0.05);
    tuv += 0.006 * vec2(vnoise(tuv * 6.0 + uTime * 0.05), vnoise(tuv * 6.0 - uTime * 0.05));
    vec3 tx = TEX(uTex, tuv).rgb;
    float lum = dot(tx, vec3(0.299, 0.587, 0.114));
    float key = smoothstep(0.05, 0.32, lum);
    vec3 tint = interf(lum * 1250.0 + uRetard * 0.85);
    tint = mix(vec3(dot(tint, vec3(0.333))), tint, 1.5);
    col += mix(tx, tint * 1.25, 0.42) * key * uTexAmt;
  }

  float cx = cos(uAnalyzer);
  col += vec3(0.008, 0.009, 0.013) + vec3(0.55, 0.58, 0.7) * cx * cx * 0.06;
  col *= mix(1.0, mix(0.16, 1.0, smoothstep(-0.78, 0.12, uv.x)), uLeft);
  float rr = length(uv - uFocus);
  col *= mix(1.0, smoothstep(1.05, 0.18, rr), uVig);
  col *= uIntensity;
  col = col / (1.0 + col * 0.32);
  col += (h2(gl_FragCoord.xy + fract(uTime * 7.0) * 113.0) - 0.5) * uGrain;
  OUT_COLOR = vec4(max(col, 0.0), 1.0);
}`;

const VS2 = `#version 300 es
in vec2 aPos; void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }`;
const FS2 = `#version 300 es
precision highp float;
out vec4 fragColor;
#define OUT_COLOR fragColor
#define TEX texture
${FRAG_BODY}`;
const VS1 = `attribute vec2 aPos; void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }`;
const FS1 = (deriv: boolean) => `${deriv ? "#extension GL_OES_standard_derivatives : enable" : ""}
precision highp float;
#define OUT_COLOR gl_FragColor
#define TEX texture2D
${deriv ? "" : "float dFdx(float x){ return 0.0; } float dFdy(float x){ return 1.0; }"}
${FRAG_BODY}`;

export interface FieldParams {
  analyzer: number;
  retard: number;
  zoom: number;
  scroll: number;
  stageX: number;
  stageY: number;
  intensity: number;
  texAmt: number;
  focusX: number;
  focusY: number;
  vig: number;
  grain: number;
  density: number;
  left: number;
}

export interface FieldController {
  set(values: Partial<FieldParams>): void;
  /** freeze (true) or resume (false) the animation; a frozen field draws one still frame */
  setStill(still: boolean): void;
  dispose(): void;
}

interface FieldOptions {
  /** render-buffer scale relative to CSS pixels (cheap, the field is soft anyway) */
  scale?: number;
  texture?: string;
  params?: Partial<FieldParams>;
  still?: boolean;
  /** called when the context is lost for good; the caller shows its CSS fallback */
  onFail?: () => void;
  /** the GPU dropped the context (driver reset, sleep): show the CSS fallback until onRestored */
  onLost?: () => void;
  /** the context came back and the field was rebuilt and redrawn */
  onRestored?: () => void;
}

type GL = WebGLRenderingContext | WebGL2RenderingContext;
const UNIFORMS = [
  "uRes", "uTime", "uAnalyzer", "uRetard", "uZoom", "uScroll", "uStage", "uIntensity",
  "uTexAmt", "uTexSize", "uFocus", "uVig", "uGrain", "uDensity", "uLeft", "uTex",
] as const;
type UniformName = (typeof UNIFORMS)[number];

export function createField(canvas: HTMLCanvasElement, opts: FieldOptions = {}): FieldController | null {
  const ctxOpts: WebGLContextAttributes = {
    antialias: false, alpha: false, depth: false, stencil: false,
    powerPreference: "low-power", preserveDrawingBuffer: false,
  };
  let gl: GL | null = null;
  let isGL2 = false;
  try {
    gl = canvas.getContext("webgl2", ctxOpts);
    isGL2 = !!gl;
    if (!gl) gl = canvas.getContext("webgl", ctxOpts);
  } catch {
    gl = null;
  }
  if (!gl || gl.isContextLost()) return null;
  const ctx: GL = gl;

  let prog: WebGLProgram | null = null;
  let buf: WebGLBuffer | null = null;
  let tex: WebGLTexture | null = null;
  let U: Partial<Record<UniformName, WebGLUniformLocation | null>> = {};
  let texSize: [number, number] = [1, 1];
  let texReady = false;
  let texImg: HTMLImageElement | null = null;

  const compile = (type: number, src: string) => {
    const s = ctx.createShader(type);
    if (!s) throw new Error("shader");
    ctx.shaderSource(s, src);
    ctx.compileShader(s);
    if (!ctx.getShaderParameter(s, ctx.COMPILE_STATUS)) {
      ctx.deleteShader(s);
      throw new Error("compile");
    }
    return s;
  };
  function uploadTex(im: HTMLImageElement) {
    ctx.bindTexture(ctx.TEXTURE_2D, tex);
    ctx.pixelStorei(ctx.UNPACK_FLIP_Y_WEBGL, true);
    ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, ctx.RGBA, ctx.UNSIGNED_BYTE, im);
    ctx.pixelStorei(ctx.UNPACK_FLIP_Y_WEBGL, false);
    texSize = [im.naturalWidth, im.naturalHeight];
    texReady = true;
  }
  function build(): boolean {
    try {
      let vs: WebGLShader, fs: WebGLShader;
      if (isGL2) {
        vs = compile(ctx.VERTEX_SHADER, VS2);
        fs = compile(ctx.FRAGMENT_SHADER, FS2);
      } else {
        const deriv = !!ctx.getExtension("OES_standard_derivatives");
        vs = compile(ctx.VERTEX_SHADER, VS1);
        fs = compile(ctx.FRAGMENT_SHADER, FS1(deriv));
      }
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
      U = {};
      for (const name of UNIFORMS) U[name] = ctx.getUniformLocation(prog, name);
      tex = ctx.createTexture();
      ctx.bindTexture(ctx.TEXTURE_2D, tex);
      ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, 1, 1, 0, ctx.RGBA, ctx.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
      ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MIN_FILTER, ctx.LINEAR);
      ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MAG_FILTER, ctx.LINEAR);
      ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_S, ctx.CLAMP_TO_EDGE);
      ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_T, ctx.CLAMP_TO_EDGE);
      ctx.uniform1i(U.uTex ?? null, 0);
      if (texImg) uploadTex(texImg);
      return true;
    } catch {
      return false;
    }
  }
  if (!build()) {
    loseContext();
    return null;
  }

  const P: FieldParams = {
    analyzer: Math.PI / 2, retard: 0, zoom: 1, scroll: 0, stageX: 0, stageY: 0, intensity: 1,
    texAmt: 0.6, focusX: 0.25, focusY: 0, vig: 0.35, grain: 0.018, density: 0.62, left: 0,
    ...opts.params,
  };
  const scale = opts.scale ?? 0.5;
  let still = !!opts.still;
  let disposed = false, running = false, raf = 0, visible = true, lost = false;
  let pendingDraw = 0;
  const t0 = performance.now();
  let tStill = 8;
  let lastW = 0, lastH = 0, lastFrame = 0;

  if (opts.texture) {
    const im = new Image();
    im.decoding = "async";
    im.onload = () => {
      if (disposed) return;
      texImg = im;
      if (lost || ctx.isContextLost()) return;
      try {
        uploadTex(im);
      } catch {
        return;
      }
      if (!running) draw();
    };
    im.onerror = () => undefined;
    im.src = opts.texture;
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.max(2, Math.round(canvas.clientWidth * dpr * scale));
    const h = Math.max(2, Math.round(canvas.clientHeight * dpr * scale));
    if (w !== lastW || h !== lastH) {
      canvas.width = w;
      canvas.height = h;
      lastW = w;
      lastH = h;
    }
  }
  function draw() {
    if (disposed || lost || ctx.isContextLost()) return;
    resize();
    ctx.viewport(0, 0, lastW, lastH);
    const t = still ? tStill : (performance.now() - t0) / 1000;
    ctx.uniform2f(U.uRes ?? null, lastW, lastH);
    ctx.uniform1f(U.uTime ?? null, t);
    ctx.uniform1f(U.uAnalyzer ?? null, P.analyzer);
    ctx.uniform1f(U.uRetard ?? null, P.retard);
    ctx.uniform1f(U.uZoom ?? null, P.zoom);
    ctx.uniform1f(U.uScroll ?? null, P.scroll);
    ctx.uniform2f(U.uStage ?? null, P.stageX, P.stageY);
    ctx.uniform1f(U.uIntensity ?? null, P.intensity);
    ctx.uniform1f(U.uTexAmt ?? null, texReady ? P.texAmt : 0);
    ctx.uniform2f(U.uTexSize ?? null, texSize[0], texSize[1]);
    ctx.uniform2f(U.uFocus ?? null, P.focusX, P.focusY);
    ctx.uniform1f(U.uVig ?? null, P.vig);
    ctx.uniform1f(U.uGrain ?? null, still ? 0 : P.grain);
    ctx.uniform1f(U.uDensity ?? null, P.density);
    ctx.uniform1f(U.uLeft ?? null, P.left);
    ctx.activeTexture(ctx.TEXTURE0);
    ctx.bindTexture(ctx.TEXTURE_2D, tex);
    ctx.drawArrays(ctx.TRIANGLES, 0, 3);
  }
  function loop(now: number) {
    if (!running) return;
    raf = requestAnimationFrame(loop);
    if (now - lastFrame < 1000 / 40) return; // a slow field needs no more than ~40 fps
    lastFrame = now;
    draw();
  }
  function start() {
    if (disposed || running || lost) return;
    if (still) {
      draw();
      return;
    }
    if (!visible || document.hidden) return;
    running = true;
    raf = requestAnimationFrame(loop);
  }
  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }
  function scheduleDraw() {
    if (running || pendingDraw || !visible) return;
    pendingDraw = requestAnimationFrame(() => {
      pendingDraw = 0;
      draw();
    });
  }
  function loseContext() {
    try {
      ctx.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      /* noop */
    }
  }

  const io =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver((entries) => {
          visible = entries[0]?.isIntersecting ?? true;
          if (visible) start();
          else stop();
        })
      : null;
  io?.observe(canvas);
  const onVisibility = () => {
    if (document.hidden) stop();
    else start();
  };
  document.addEventListener("visibilitychange", onVisibility);
  const onLost = (event: Event) => {
    event.preventDefault();
    lost = true;
    texReady = false;
    stop();
    opts.onLost?.();
  };
  const onRestored = () => {
    if (disposed) return;
    lost = false;
    if (!build()) {
      opts.onFail?.();
      return;
    }
    try {
      draw();
    } catch {
      opts.onFail?.();
      return;
    }
    start();
    opts.onRestored?.();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  try {
    draw();
  } catch {
    loseContext();
    return null;
  }
  start();

  return {
    set(values) {
      Object.assign(P, values);
      scheduleDraw();
    },
    setStill(next) {
      if (next === still) return;
      if (next) tStill = (performance.now() - t0) / 1000;
      still = next;
      stop();
      start();
      draw();
    },
    dispose() {
      disposed = true;
      stop();
      cancelAnimationFrame(pendingDraw);
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      try {
        ctx.deleteBuffer(buf);
        ctx.deleteTexture(tex);
        ctx.deleteProgram(prog);
      } catch {
        /* noop */
      }
      loseContext();
    },
  };
}
