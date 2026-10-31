<script setup lang="ts">
// 页头装饰：纤维显微示意图（AI 生成，非实测），WebGL 让纤维缓慢漂移，
// 指针处是一枚约 1.8 倍的物镜视野。只做装饰，不承载数据；无 WebGL 时整块不显示。
import { onBeforeUnmount, onMounted, ref } from "vue";
import micrograph from "../assets/fiber-micrograph.jpg";

const canvas = ref<HTMLCanvasElement>();
const failed = ref(false);
let cleanup = () => {};

const VERTEX = `attribute vec2 p;varying vec2 v;void main(){v=p*.5+.5;gl_Position=vec4(p,0.,1.);}`;
const FRAGMENT = `precision mediump float;varying vec2 v;
uniform sampler2D T;uniform vec2 R,M,TS;uniform float t,L;uniform vec3 BG,LENS;
// 铺满画布并放大 1/0.88，四周留出漂移余量
vec2 cover(vec2 uv){float ra=R.x/R.y,ta=TS.x/TS.y;vec2 s=ra>ta?vec2(1.,ta/ra):vec2(ra/ta,1.);return (uv-.5)*s*.88+.5;}
// 越界时镜像取样，避免拉出边缘像素条
vec3 tex(vec2 uv){uv=1.-abs(1.-abs(uv));uv.y=1.-uv.y;return texture2D(T,uv).rgb;}
void main(){
  vec2 uv=v;
  uv+=.0035*vec2(sin(uv.y*9.+t*.35)+.5*sin(uv.x*17.-t*.2),cos(uv.x*7.-t*.3));
  uv.x+=.045*sin(t*.042);
  vec2 px=v*R;float d=length(px-M);float k=smoothstep(L,L-1.5,d);
  vec2 mu=cover(M/R+(uv-M/R)*.55);
  float ab=.0025*smoothstep(L*.55,L,d)*k;
  vec3 lens=vec3(tex(mu+vec2(ab,0.)).r,tex(mu).g,tex(mu-vec2(ab,0.)).b);
  vec3 c=mix(tex(cover(uv)),lens,k);
  c=mix(c,LENS,smoothstep(2.5,0.,abs(d-L))*.55*step(1.,L));
  c*=1.-.06*smoothstep(L*.6,L,d)*k;
  c=mix(c,BG,.1);
  gl_FragColor=vec4(c,1.);
}`;

onMounted(() => {
  const cv = canvas.value;
  const gl = cv?.getContext("webgl", { antialias: false });
  if (!cv || !gl) {
    failed.value = true;
    return;
  }
  const shader = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return s;
  };
  const program = gl.createProgram()!;
  gl.attachShader(program, shader(gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, shader(gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    failed.value = true;
    return;
  }
  gl.useProgram(program);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
    gl.STATIC_DRAW,
  );
  const position = gl.getAttribLocation(program, "p");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  const u = (name: string) => gl.getUniformLocation(program, name);
  const uniforms = {
    R: u("R"),
    M: u("M"),
    TS: u("TS"),
    t: u("t"),
    L: u("L"),
    BG: u("BG"),
    LENS: u("LENS"),
  };
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  for (const [key, value] of [
    [gl.TEXTURE_MIN_FILTER, gl.LINEAR],
    [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
    [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE],
    [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE],
  ] as const)
    gl.texParameteri(gl.TEXTURE_2D, key, value);

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const css = getComputedStyle(document.documentElement);
  const rgb = (name: string, fallback: string) => {
    const hex = (css.getPropertyValue(name).trim() || fallback).replace(
      "#",
      "",
    );
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  };
  const background = rgb("--canvas", "#f4efe4"),
    ring = rgb("--signal-ink", "#0b5f5a");
  let textureSize = [1, 1],
    ready = false;
  const lens = { x: -999, y: -999, r: 0, target: 0 };
  let width = 0,
    height = 0,
    frame = 0,
    visible = true;
  const start = performance.now();

  function resize() {
    const dpr = Math.min(2, devicePixelRatio || 1);
    width = Math.round(cv!.clientWidth * dpr);
    height = Math.round(cv!.clientHeight * dpr);
    cv!.width = width;
    cv!.height = height;
    gl!.viewport(0, 0, width, height);
  }
  function draw() {
    if (!ready || !width) return;
    const dpr = width / (cv!.clientWidth || 1);
    lens.r += (lens.target - lens.r) * 0.18;
    gl!.uniform2f(uniforms.R, width, height);
    gl!.uniform2f(uniforms.TS, textureSize[0]!, textureSize[1]!);
    gl!.uniform1f(
      uniforms.t,
      reduceMotion ? 0 : (performance.now() - start) / 1000,
    );
    gl!.uniform2f(uniforms.M, lens.x * dpr, height - lens.y * dpr);
    gl!.uniform1f(uniforms.L, lens.r * dpr);
    gl!.uniform3fv(uniforms.BG, background);
    gl!.uniform3fv(uniforms.LENS, ring);
    gl!.drawArrays(gl!.TRIANGLE_STRIP, 0, 4);
  }
  function loop() {
    draw();
    const settling = Math.abs(lens.target - lens.r) > 0.5;
    frame =
      visible && !document.hidden && (!reduceMotion || settling)
        ? requestAnimationFrame(loop)
        : 0;
  }
  const kick = () => {
    if (!frame) frame = requestAnimationFrame(loop);
  };
  // 画布本身不接收指针（不挡标题和按钮），在整个页头上监听
  const host = cv.closest(".page-heading") ?? cv.parentElement!;
  const move = (event: Event) => {
    const e = event as PointerEvent;
    if (e.pointerType === "touch") return;
    const box = cv.getBoundingClientRect();
    lens.x = e.clientX - box.left;
    lens.y = e.clientY - box.top;
    const inside =
      lens.x > box.width * 0.3 &&
      lens.x < box.width &&
      lens.y > 0 &&
      lens.y < box.height;
    lens.target = inside ? 60 : 0;
    kick();
  };
  const leave = () => {
    lens.target = 0;
    kick();
  };
  host.addEventListener("pointermove", move);
  host.addEventListener("pointerleave", leave);
  const observer = new IntersectionObserver((entries) => {
    visible = entries[0]?.isIntersecting ?? true;
    if (visible) kick();
  });
  observer.observe(cv);
  const sizeObserver = new ResizeObserver(() => {
    resize();
    draw();
  });
  sizeObserver.observe(cv);
  document.addEventListener("visibilitychange", kick);

  const image = new Image();
  image.onload = () => {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    textureSize = [image.width, image.height];
    ready = true;
    resize();
    kick();
  };
  image.onerror = () => (failed.value = true);
  image.src = micrograph;

  cleanup = () => {
    cancelAnimationFrame(frame);
    host.removeEventListener("pointermove", move);
    host.removeEventListener("pointerleave", leave);
    document.removeEventListener("visibilitychange", kick);
    observer.disconnect();
    sizeObserver.disconnect();
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  };
});
onBeforeUnmount(() => cleanup());
</script>

<template>
  <div v-if="!failed" class="fiber-hero" aria-hidden="true">
    <canvas ref="canvas"></canvas>
    <span class="fiber-hero-note">纤维显微示意图，非实测</span>
  </div>
</template>

<style scoped>
.fiber-hero {
  position: absolute;
  z-index: 0;
  inset: -28px -32px -10px 30%;
  pointer-events: none;
}
/* 遮罩只作用在画布上：向左、向下渐隐到纸页底色，标注文字不受影响 */
canvas {
  -webkit-mask-image:
    linear-gradient(90deg, transparent 0, #000 40%),
    linear-gradient(0deg, transparent 0, #000 28%);
  -webkit-mask-composite: source-in;
  mask-image:
    linear-gradient(90deg, transparent 0, #000 40%),
    linear-gradient(0deg, transparent 0, #000 28%);
  mask-composite: intersect;
  display: block;
  width: 100%;
  height: 100%;
}
.fiber-hero-note {
  position: absolute;
  right: 32px;
  bottom: 2px;
  font-size: 11px;
  color: var(--muted);
}
@media (max-width: 720px) {
  .fiber-hero {
    inset: -16px -16px -6px 20%;
  }
  .fiber-hero-note {
    display: none;
  }
}
</style>
