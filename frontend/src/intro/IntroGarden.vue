<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ArrowDown, ArrowRight, Info, RefreshCw, X } from "lucide-vue-next";
import ModeSwitch from "../components/ModeSwitch.vue";
import { navItems, navTotal, platformName } from "../nav";
import { reducedMotion } from "../mode";
import { chartColors, materialColors } from "../palette";
import { number, type SampleType } from "../api";
import { formatR } from "../analysis";
import { useCountUp, vTilt } from "../motion";
import { createPulp, type PulpController } from "../ambient/pulp";
import { TARGET_SR, useGardenIntroData } from "./garden/data";
import { CHAPTERS, clamp, frame, storyPosition, type Frame } from "./garden/choreo";
import { strandPaths } from "./garden/strands";
import type { LandingScene } from "./garden/fibers3d";
import LiveValue from "./garden/LiveValue.vue";
import BeatingSpark from "./garden/BeatingSpark.vue";
import clayFibers from "../assets/modes/garden/clay-fibers.jpg";
import paperNetwork from "../assets/modes/garden/paper-network.jpg";
import glassLeaves from "../assets/modes/garden/glass-leaves.jpg";

/*
 * 序章 · 纤维花园 (v4 landing): 「从树，到浆，到纤维，到纸，再到数据」.
 * A sticky multi-depth stage (pulp shader → blurred clay fibres → giant word → Three.js fibres
 * → drifting strands → glass leaves) with the story chapters scrolling over it. Scrolling
 * beats the pulp, then lets the fibres settle and interlace into a sheet of paper.
 *
 *  - every number is read live from the API (garden/data.ts); "—" when it has no value;
 *  - the stage is decorative (aria-hidden): the chapters carry all content and stay
 *    readable without WebGL, images or motion;
 *  - reduced motion: no scroll scrubbing, no pointer parallax; each chapter shows a still
 *    frame of its own resting state.
 */

const data = useGardenIntroData();
const { stats, composition, correlations, curves, beatingFacts, notes, loading } = data;
const still = computed(() => reducedMotion.value);
const fmt = (v: number | null | undefined, digits = 0) => number(v, digits);

/* ---------------------------------------------------------------- story copy that depends on data */
const chapterLabels = ["序 · 纤维花园", "01 树 · 原料", "02 浆 · 打浆", "03 纤维 · 读数", "04 纸 · 成形", "05 数据 · 入口"];
const MARK: Record<SampleType, string> = { softwood: "sw", hardwood: "hw", blend: "bl" };
const compositionLabel = computed(() =>
  composition.value ? `样本组成：${composition.value.map((c) => `${c.label} ${c.n}`).join("，")}` : "样本组成",
);
const finePointer = ref(false);
const stirNote = computed(() =>
  still.value ? "" : finePointer.value ? "背景里的纸浆正被“打浆”——移动鼠标也能搅动它。" : "背景里的纸浆正随滚动被“打浆”。",
);
const reachRows = computed(() => {
  const f = beatingFacts.value;
  return [
    { key: "hardwood" as const, label: "阔叶木浆", value: f?.reach.hardwood ?? null },
    { key: "softwood" as const, label: "针叶木浆", value: f?.reach.softwood ?? null },
  ];
});
const groupNote = computed(() => {
  const groups = data.indicatorGroups.value;
  return groups?.length ? groups.map((g) => `${g.label} ${fmt(g.n)}`).join(" · ") : "纤维特性、纸张性能、长度分布";
});

// 复配展示点中复用的纯浆端点 = 复配展示点 − 复配样本 (as on the overview page)
const displayNote = computed(() => {
  const s = stats.value;
  if (s.beatingPoints == null || s.blendPoints == null) return "复配端点复用已有纯浆样本";
  const blendSamples = composition.value?.find((c) => c.type === "blend")?.n;
  const reused = blendSamples == null ? null : s.blendPoints - blendSamples;
  return `打浆 ${fmt(s.beatingPoints)} + 复配 ${fmt(s.blendPoints)}${reused != null && reused >= 0 ? ` · 含 ${fmt(reused)} 个复用端点` : ""}`;
});

/* ---------------------------------------------------------------- KPI wall (counts up once it is seen) */
const wallEl = ref<HTMLElement>();
const wallSeen = ref(false);
const gate = (value: () => number | null) => () => (wallSeen.value ? value() : null);
const counted = {
  samples: useCountUp(gate(() => stats.value.samples), { el: wallEl }),
  display: useCountUp(gate(() => stats.value.displayPoints), { el: wallEl }),
  recycled: useCountUp(gate(() => stats.value.recycledObs), { el: wallEl }),
  indicators: useCountUp(gate(() => stats.value.indicators), { el: wallEl }),
};
const kpis = computed(() => {
  const s = stats.value;
  return [
    { key: "samples" as const, value: s.samples, unit: "个", label: "唯一物理样本", sub: "针叶木、阔叶木与针阔复配" },
    {
      key: "display" as const,
      value: s.displayPoints,
      unit: "个",
      label: "核心实验展示点",
      sub: displayNote.value,
    },
    {
      key: "recycled" as const,
      value: s.recycledObs,
      unit: "条",
      label: "再生纸浆原始观测",
      sub: `${fmt(s.recycledBlocks)} 个数据块 · ${fmt(s.recycledCycles)} 个循环汇总点`,
    },
    { key: "indicators" as const, value: s.indicators, unit: "项", label: "已收录指标", sub: groupNote.value },
  ];
});
/** the counting value while it runs, otherwise the real one */
const kpiText = (key: keyof typeof counted, value: number | null) => fmt(counted[key].value ?? value);

/* ---------------------------------------------------------------- stage */
const strands = strandPaths(5, 9);
const root = ref<HTMLElement>();
const L = {
  far: ref<HTMLElement>(),
  paperB: ref<HTMLElement>(),
  paperS: ref<HTMLElement>(),
  giant: ref<HTMLElement>(),
  gl: ref<HTMLCanvasElement>(),
  mid: ref<HTMLElement>(),
  near: ref<HTMLElement>(),
  glass: ref<HTMLElement>(),
  chips: ref<HTMLElement>(),
  cue: ref<HTMLElement>(),
};
const stageEl = ref<HTMLElement>();
const pulpCanvas = ref<HTMLCanvasElement>();
const imgFailed = reactive({ clay: false, paper: false, glass: false });

const glOn = ref(false);
const glLost = ref(false);
const pulpOn = ref(false);
const pulpLost = ref(false);
const active = ref(0);
const solid = ref(false);
const mobile = ref(false);

let fibers: LandingScene | null = null;
let pulp: PulpController | null = null;
let disposed = false;
let tops: number[] = [];
let storyEnd = 0;
const mouse = { x: 0, y: 0, sx: 0, sy: 0 };
const last = { c: -1, vh: 0, mx: 1e9, my: 1e9 };
let raf = 0,
  scheduled = 0,
  running = false;

function measure() {
  const el = root.value;
  if (!el) return;
  const y = window.scrollY;
  const sections = [...el.querySelectorAll<HTMLElement>(".gi-ch")];
  tops = sections.map((s) => s.getBoundingClientRect().top + y);
  const lastSection = sections[sections.length - 1];
  storyEnd = lastSection ? lastSection.getBoundingClientRect().bottom + y : 0;
}

const px = (v: number) => `${v.toFixed(1)}px`;
function place(el: HTMLElement | undefined, opacity: number, transform?: string) {
  if (!el) return;
  el.style.opacity = opacity.toFixed(3);
  if (transform) el.style.transform = transform;
}
function apply(f: Frame, mx: number, my: number) {
  place(L.far.value, f.far.opacity, `translate3d(${px(f.far.x)}, ${px(f.far.y)}, 0) scale(1.04)`);
  place(L.giant.value, f.giant.opacity, `translate3d(${px(f.giant.x)}, ${px(f.giant.y)}, 0)`);
  const paper = `translate3d(${px(f.paper.x)}, ${px(f.paper.y)}, 0) scale(${f.paper.scale.toFixed(3)})`;
  place(L.paperB.value, f.paperBlur, paper);
  place(L.paperS.value, f.paperSharp, paper);
  place(L.mid.value, f.mid.opacity, `translate3d(${px(f.mid.x)}, ${px(f.mid.y)}, 0)`);
  const near = L.near.value;
  place(near, f.glass.opacity, `translate3d(${px(f.glass.x)}, ${px(f.glass.y)}, 0)`);
  if (near) near.style.visibility = f.glass.opacity < 0.03 ? "hidden" : "visible";
  L.glass.value?.style.setProperty("--grx", `${f.glass.rx.toFixed(2)}deg`);
  L.glass.value?.style.setProperty("--gry", `${f.glass.ry.toFixed(2)}deg`);
  for (const el of [L.chips.value, L.cue.value]) {
    if (!el) continue;
    el.style.opacity = f.heroFade.toFixed(3);
    el.style.visibility = f.heroFade < 0.02 ? "hidden" : "visible";
  }
  if (L.gl.value) L.gl.value.style.opacity = f.gl.toFixed(3);
  fibers?.set({ ...f.camera, settle: f.settle, beat: f.beat, mx, my });
  pulp?.set({ beat: f.beat, settle: f.settle, fibers: f.pulpFibers });
}

function update(force = false) {
  const vh = window.innerHeight;
  const y = window.scrollY;
  let c = storyPosition(y, tops, storyEnd);
  let mx = 0,
    my = 0;
  if (still.value) {
    // a still frame per chapter: its resting state, no scrubbing, no pointer
    c = clamp(Math.round(c), 0, CHAPTERS - 1);
  } else {
    mouse.sx += (mouse.x - mouse.sx) * 0.08;
    mouse.sy += (mouse.y - mouse.sy) * 0.08;
    mx = mouse.sx;
    my = mouse.sy;
  }
  solid.value = y > 24;
  active.value = clamp(Math.round(c), 0, CHAPTERS - 1);
  if (!force && c === last.c && vh === last.vh && Math.abs(mx - last.mx) < 0.002 && Math.abs(my - last.my) < 0.002)
    return;
  Object.assign(last, { c, vh, mx, my });
  apply(frame(c, mx, my, vh, mobile.value, !!fibers && !glLost.value), mx, my);
}

function loop() {
  if (!running) return;
  update();
  raf = requestAnimationFrame(loop);
}
function startLoop() {
  if (running || still.value || disposed || document.hidden) return;
  running = true;
  raf = requestAnimationFrame(loop);
}
function stopLoop() {
  running = false;
  cancelAnimationFrame(raf);
}
/** rAF-throttled update for scroll / resize while the frame loop is not running */
function schedule(remeasure = false) {
  if (remeasure) measure();
  if (running || scheduled) return;
  scheduled = requestAnimationFrame(() => {
    scheduled = 0;
    update(remeasure);
  });
}

const onScroll = () => schedule();
const onResize = () => schedule(true);
const onPointer = (event: PointerEvent) => {
  if (event.pointerType === "touch") return;
  mouse.x = (event.clientX / window.innerWidth - 0.5) * 2;
  mouse.y = -(event.clientY / window.innerHeight - 0.5) * 2;
};
const onVisibility = () => (document.hidden ? stopLoop() : startLoop());

/* ---------------------------------------------------------------- WebGL layers (decorative) */
function webglAvailable() {
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2") ?? probe.getContext("webgl");
    if (!gl) return false;
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}
const weights = (): [number, number, number] | null => {
  const c = composition.value;
  return c && c.some((x) => x.n > 0) ? [c[0]!.n, c[1]!.n, c[2]!.n] : null;
};

function initPulp() {
  if (!pulpCanvas.value) return;
  try {
    pulp = createPulp(pulpCanvas.value, {
      still: still.value,
      onLost: () => {
        pulpOn.value = false;
        pulpLost.value = true;
      },
      onRestored: () => {
        pulpLost.value = false;
        pulpOn.value = true;
      },
      onFail: () => {
        pulp?.dispose();
        pulp = null;
        pulpOn.value = false;
        pulpLost.value = true;
      },
      target: { intensity: 1, fibers: 0.9, filA: 0.42, beat: 0.08, settle: 0, scale: mobile.value ? 0.4 : 0.5, fps: 45, idle: 0 },
    });
  } catch {
    pulp = null;
  }
  pulpOn.value = !!pulp;
}

function initFibers() {
  if (!L.gl.value || !webglAvailable()) return;
  import("./garden/fibers3d")
    .then((m) => {
      if (disposed || !L.gl.value) return;
      const css = getComputedStyle(document.documentElement);
      const token = (name: string) => css.getPropertyValue(name).trim() || chartColors.paper;
      try {
        fibers = m.createLanding(L.gl.value, {
          mobile: mobile.value,
          still: still.value,
          colors: {
            softwood: materialColors.softwood,
            hardwood: materialColors.hardwood,
            blend: materialColors.blend,
            paper: chartColors.paper,
            fog: token("--bg"),
            paperShade: token("--surface-hover"),
          },
          weights: weights(),
          onLost: () => {
            glLost.value = true;
            update(true);
          },
          onRestored: () => {
            glLost.value = false;
            update(true);
          },
        });
        glOn.value = true;
        update(true);
      } catch {
        fibers = null;
        glOn.value = false;
      }
    })
    .catch(() => {
      glOn.value = false;
    });
}
watch(composition, () => {
  const w = weights();
  if (w) fibers?.setWeights(w);
});

watch(still, (value) => {
  pulp?.setStill(value);
  fibers?.setStill(value);
  if (value) {
    stopLoop();
    mouse.x = mouse.y = mouse.sx = mouse.sy = 0;
  } else startLoop();
  update(true);
});

/* ---------------------------------------------------------------- navigation inside the prologue */
function scrollToY(y: number) {
  window.scrollTo({ top: Math.max(0, y), behavior: still.value ? "auto" : "smooth" });
}
function goChapter(i: number) {
  measure();
  const section = root.value?.querySelectorAll<HTMLElement>(".gi-ch")[i];
  section?.focus({ preventScroll: true });
  scrollToY(tops[i] ?? 0);
}
function toEnter() {
  const target = document.getElementById("gi-enter");
  if (!target) return;
  target.focus({ preventScroll: true });
  target.scrollIntoView({ block: "center", behavior: still.value ? "auto" : "smooth" });
}

/* ---------------------------------------------------------------- 关于数据 */
const about = ref<HTMLDialogElement>();
const aboutButton = ref<HTMLButtonElement>();
function openAbout() {
  if (!about.value?.open) about.value?.showModal();
}
function onAboutClose() {
  if (!document.activeElement || document.activeElement === document.body)
    aboutButton.value?.focus({ preventScroll: true });
}

/* ---------------------------------------------------------------- lifecycle */
let mobileQuery: MediaQueryList | undefined;
let pointerQuery: MediaQueryList | undefined;
let resizeObserver: ResizeObserver | undefined;
let wallObserver: IntersectionObserver | undefined;
let stageObserver: IntersectionObserver | undefined;
const onMobile = () => {
  mobile.value = !!mobileQuery?.matches;
  schedule(true);
};
const onPointerQuery = () => (finePointer.value = !!pointerQuery?.matches);

const router = useRouter();

onMounted(() => {
  mobileQuery = window.matchMedia("(max-width: 720px)");
  pointerQuery = window.matchMedia("(hover: hover) and (pointer: fine)");
  mobile.value = mobileQuery.matches;
  finePointer.value = pointerQuery.matches;
  mobileQuery.addEventListener("change", onMobile);
  pointerQuery.addEventListener("change", onPointerQuery);
  measure();
  initPulp();
  initFibers();
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onResize);
  window.addEventListener("pointermove", onPointer, { passive: true });
  document.addEventListener("visibilitychange", onVisibility);
  // fonts, images and late data change the chapter heights
  resizeObserver = new ResizeObserver(() => schedule(true));
  if (root.value) resizeObserver.observe(root.value);
  wallObserver = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      wallSeen.value = true;
      wallObserver?.disconnect();
    }
  });
  if (wallEl.value) wallObserver.observe(wallEl.value);
  stageObserver = new IntersectionObserver((entries) => {
    const visible = entries.some((e) => e.isIntersecting);
    fibers?.setVisible(visible);
  });
  if (stageEl.value) stageObserver.observe(stageEl.value);
  update(true);
  startLoop();
});

onBeforeUnmount(() => {
  disposed = true;
  stopLoop();
  cancelAnimationFrame(scheduled);
  mobileQuery?.removeEventListener("change", onMobile);
  pointerQuery?.removeEventListener("change", onPointerQuery);
  window.removeEventListener("scroll", onScroll);
  window.removeEventListener("resize", onResize);
  window.removeEventListener("pointermove", onPointer);
  document.removeEventListener("visibilitychange", onVisibility);
  resizeObserver?.disconnect();
  wallObserver?.disconnect();
  stageObserver?.disconnect();
  fibers?.dispose();
  fibers = null;
  pulp?.dispose();
  pulp = null;
  // unmounted by a navigation (not by a mode switch, which swaps prologues in place): the
  // workspace page opens at its top, not at the prologue's depth
  if (!router.currentRoute.value.meta.bare) window.scrollTo(0, 0);
});
</script>

<template>
  <div ref="root" class="gi" :class="{ 'gi-still': still }">
    <a class="skip-link" href="#gi-enter" @click.prevent="toEnter">跳到“进入工作台”</a>

    <!-- ambient: mesh gradient (always, also the fallback), pulp shader, grain -->
    <div class="gi-ambient" aria-hidden="true">
      <div class="gi-mesh"></div>
      <canvas ref="pulpCanvas" class="gi-pulp" :class="{ on: pulpOn, lost: pulpLost }"></canvas>
      <div class="gi-grain"></div>
    </div>

    <header class="gi-top" :class="{ solid }">
      <span class="gi-brand">
        <span class="gi-brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none" stroke-linecap="round">
            <path class="t-sw" d="M5 21c5-9 10 3 22-8" stroke-width="2.4" />
            <path class="t-hw" d="M5 14c6 6 12-7 22 1" stroke-width="2.4" />
            <path class="t-bl" d="M7 26c6-3 11-14 19-16" stroke-width="2.4" />
          </svg>
        </span>
        <span class="gi-brand-text">
          <span class="gi-brand-name">FiberScope</span>
          <span class="gi-brand-sub">{{ platformName }}</span>
        </span>
      </span>
      <div class="gi-top-r">
        <button ref="aboutButton" class="gi-btn ghost sm gi-about" type="button" aria-haspopup="dialog" @click="openAbout">
          <Info :size="16" aria-hidden="true" /><span class="gi-about-label">关于数据</span>
        </button>
        <ModeSwitch compact />
        <RouterLink class="gi-btn primary sm" to="/"
          ><span><span class="gi-hide-xs">进入</span>工作台</span><ArrowRight :size="16" aria-hidden="true"
        /></RouterLink>
      </div>
    </header>

    <nav class="gi-dots" aria-label="故事章节">
      <a
        v-for="(label, i) in chapterLabels"
        :key="label"
        :href="`#gi-ch-${i}`"
        :class="{ on: active === i }"
        :aria-current="active === i ? 'step' : undefined"
        @click.prevent="goChapter(i)"
        ><span class="gi-dot-label">{{ label }}</span><i aria-hidden="true"></i
      ></a>
    </nav>

    <main id="main" tabindex="-1">
      <!-- the stage: six depth planes behind the story (decorative) -->
      <div ref="stageEl" class="gi-stage" aria-hidden="true">
        <div :ref="L.far" class="gi-layer gi-far">
          <div class="gi-fallback"></div>
          <img v-if="!imgFailed.clay" :src="clayFibers" alt="" decoding="async" @error="imgFailed.clay = true" />
        </div>
        <div :ref="L.paperB" class="gi-layer gi-paper" style="opacity: 0">
          <div class="gi-fallback"></div>
          <img v-if="!imgFailed.paper" class="blurred" :src="paperNetwork" alt="" decoding="async" fetchpriority="low" @error="imgFailed.paper = true" />
        </div>
        <div :ref="L.paperS" class="gi-layer gi-paper" style="opacity: 0">
          <img v-if="!imgFailed.paper" :src="paperNetwork" alt="" decoding="async" fetchpriority="low" @error="imgFailed.paper = true" />
        </div>
        <div :ref="L.giant" class="gi-giant">FiberScope</div>
        <div class="gi-gl" :class="{ on: glOn, lost: glLost }">
          <canvas :ref="L.gl"></canvas>
        </div>
        <div :ref="L.mid" class="gi-layer gi-mid">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
            <path
              v-for="(s, i) in strands"
              :key="i"
              :class="`t-${s.tone}`"
              :d="s.d"
              :stroke-width="s.width.toFixed(2)"
              :stroke-opacity="s.opacity.toFixed(2)"
              vector-effect="non-scaling-stroke"
            />
          </svg>
        </div>
        <div :ref="L.near" class="gi-layer gi-near" style="opacity: 0; visibility: hidden">
          <figure :ref="L.glass" class="gi-glass" :class="{ noimg: imgFailed.glass }">
            <img v-if="!imgFailed.glass" :src="glassLeaves" alt="" decoding="async" fetchpriority="low" @error="imgFailed.glass = true" />
            <figcaption>pine &amp; birch, in glass</figcaption>
          </figure>
        </div>
      </div>

      <!-- 序 -->
      <section id="gi-ch-0" class="gi-ch gi-hero" aria-labelledby="gi-title" tabindex="-1">
        <div class="gi-hero-text">
          <p class="eyebrow"><span class="gi-lat">Soft Cellulose</span> · 纤维花园 · <span class="gi-lat">FiberScope</span></p>
          <h1 id="gi-title">
            植物纤维<br /><em
              >可视化<svg class="gi-em-strands" viewBox="0 0 200 18" preserveAspectRatio="none" aria-hidden="true" focusable="false">
                <path class="t-sw" d="M2 9c40-8 70 8 110 0s60-6 86 2" pathLength="1" />
                <path class="t-hw" d="M4 12c36-6 72 6 108-1s58-4 84 1" pathLength="1" />
                <path class="t-bl" d="M2 15c44-5 76 4 112-2s54-2 82 1" pathLength="1" /></svg></em
            >分析平台
          </h1>
          <p class="gi-lede">把一池纸浆里漂浮的纤维，变成可以追溯、比较与提问的数据——从树，到浆，到纤维，到纸，再到数据。</p>
          <div class="gi-cta">
            <RouterLink class="gi-btn primary lg" to="/">进入工作台 <ArrowRight :size="18" aria-hidden="true" /></RouterLink>
            <button class="gi-btn ghost lg" type="button" @click="goChapter(1)">
              跟着纤维走一遍 <ArrowDown :size="18" aria-hidden="true" />
            </button>
          </div>
          <div class="gi-live" :class="data.status.value">
            <span class="gi-live-dot" aria-hidden="true"></span>
            <span role="status">{{
              data.status.value === "loading"
                ? "正在读取实时数据…"
                : data.status.value === "ready"
                  ? "数据已连接 · 以下数字均实时读取自平台"
                  : `${data.allFailed.value ? "数据读取失败" : "部分数据读取失败"}：${data.message.value}`
            }}</span>
            <button v-if="data.status.value === 'error'" class="gi-retry" type="button" @click="data.reload()">
              <RefreshCw :size="14" aria-hidden="true" />重试
            </button>
          </div>
        </div>
        <div :ref="L.chips" class="gi-hero-chips">
          <span class="gi-chip"
            ><b><LiveValue :value="fmt(stats.samples)" :busy="loading.metadata.value" width="1.6em" /></b> 个唯一物理样本</span
          >
          <span class="gi-chip"
            ><b><LiveValue :value="fmt(stats.indicators)" :busy="loading.metadata.value" width="1.6em" /></b> 项指标</span
          >
          <span v-if="finePointer && !still" class="gi-chip" aria-hidden="true">移动鼠标 · 搅动纸浆</span>
        </div>
        <div :ref="L.cue" class="gi-cue" aria-hidden="true"><i></i>向下滚动</div>
      </section>

      <!-- 01 树 -->
      <section id="gi-ch-1" class="gi-ch right" aria-labelledby="gi-h1" tabindex="-1">
        <article class="gi-story">
          <div class="gi-story-k"><span class="gi-no">01</span><span class="eyebrow">From tree · 树</span></div>
          <h2 id="gi-h1"><span class="gi-nw">两种树，</span><span class="gi-nw">三种浆</span></h2>
          <p>
            针叶木与阔叶木分别制浆，再按比例复配成第三种浆料。全库共
            <b><LiveValue :value="fmt(stats.samples)" :busy="loading.metadata.value" width="1.6em" /></b>
            个唯一物理样本。
          </p>
          <div v-if="composition" class="gi-comp" role="img" :aria-label="compositionLabel">
            <i v-for="c in composition" :key="c.type" :class="`f-${MARK[c.type]}`" :style="{ flexGrow: c.n }"></i>
          </div>
          <div v-else class="gi-comp gi-comp-wait" aria-hidden="true"><i></i></div>
          <div class="gi-legend">
            <span v-for="t in (['softwood', 'hardwood', 'blend'] as const)" :key="t" class="gi-li"
              ><i class="gi-mk" :class="MARK[t]" aria-hidden="true"></i
              >{{ t === "softwood" ? "针叶木浆" : t === "hardwood" ? "阔叶木浆" : "针阔复配" }}
              <b class="gi-num"
                ><LiveValue
                  :value="fmt(composition?.find((c) => c.type === t)?.n)"
                  :busy="loading.fiberPaper.value"
                  width="1.2em" /></b
            ></span>
          </div>
          <div class="gi-facts">
            <div v-for="t in (['softwood', 'hardwood'] as const)" :key="t" class="gi-fact">
              <span class="l"
                ><i class="gi-mk" :class="MARK[t]" aria-hidden="true"></i
                >{{ t === "softwood" ? "针叶木浆" : "阔叶木浆" }} · 未打浆（0 r）纤维长度</span
              >
              <span class="v"
                ><LiveValue :value="fmt(beatingFacts?.unbeatenLength[t], 3)" :busy="loading.beating.value" />
                {{ beatingFacts?.unbeatenLength[t] == null ? "" : "mm" }}</span
              >
            </div>
            <p class="gi-note">纤维长度为长度加权平均值。</p>
          </div>
          <RouterLink class="gi-more" :to="navItems[0]!.path"
            >在「{{ navItems[0]!.label }}」中查看全部样本 <ArrowRight :size="15" aria-hidden="true"
          /></RouterLink>
        </article>
      </section>

      <!-- 02 浆 -->
      <section id="gi-ch-2" class="gi-ch" aria-labelledby="gi-h2" tabindex="-1">
        <article class="gi-story">
          <div class="gi-story-k"><span class="gi-no">02</span><span class="eyebrow">From pulp · 浆</span></div>
          <h2 id="gi-h2"><span class="gi-nw">搅动，</span><span class="gi-nw">让纤维舒展</span></h2>
          <p>打浆让纤维润胀、分丝帚化，打浆度（°SR）随打浆转数升高。{{ stirNote }}</p>
          <div class="gi-spark">
            <BeatingSpark
              v-if="curves"
              :softwood="curves.softwood"
              :hardwood="curves.hardwood"
              :target="TARGET_SR"
              :max-rev="beatingFacts?.maxRev ?? null"
            />
            <div v-else class="gi-spark-wait" :class="{ failed: !loading.beating.value }">
              {{ loading.beating.value ? "正在读取打浆曲线…" : "打浆曲线暂时无法读取" }}
            </div>
            <div class="gi-legend small">
              <span class="gi-li"><i class="gi-mk sw" aria-hidden="true"></i>针叶木浆</span>
              <span class="gi-li"><i class="gi-mk hw" aria-hidden="true"></i>阔叶木浆</span>
              <span class="gi-li"><i class="gi-dash" aria-hidden="true"></i>目标 {{ TARGET_SR }} °SR</span>
              <span class="gi-li gi-axis"
                >横轴：打浆转数 0–<LiveValue :value="fmt(beatingFacts?.maxRev)" :busy="loading.beating.value" /> r · 纵轴：0–100 °SR</span
              >
            </div>
          </div>
          <div class="gi-facts">
            <div v-for="row in reachRows" :key="row.key" class="gi-fact">
              <span class="l"><i class="gi-mk" :class="MARK[row.key]" aria-hidden="true"></i>{{ row.label }}达到 {{ TARGET_SR }} °SR</span>
              <span class="v"
                >{{ row.value == null ? "" : "≈ " }}<LiveValue :value="fmt(row.value)" :busy="loading.beating.value" />
                {{ row.value == null ? "" : "r" }}</span
              >
            </div>
            <div class="gi-fact">
              <span class="l">两种原料相差</span>
              <span class="v"
                ><LiveValue :value="fmt(beatingFacts?.diff)" :busy="loading.beating.value" />
                {{ beatingFacts?.diff == null ? "" : "r" }}</span
              >
            </div>
          </div>
          <p class="gi-caveat">
            <Info :size="17" aria-hidden="true" /><span
              >按相邻实测点线性插值估算，取整到百转。线段仅连接相邻有效观测，不作拟合或因果推断。</span
            >
          </p>
          <RouterLink class="gi-more" :to="navItems[1]!.path"
            >在「{{ navItems[1]!.label }}」中调整目标打浆度 <ArrowRight :size="15" aria-hidden="true"
          /></RouterLink>
        </article>
      </section>

      <!-- 03 纤维 -->
      <section id="gi-ch-3" class="gi-ch right" aria-labelledby="gi-h3" tabindex="-1">
        <article class="gi-story">
          <div class="gi-story-k"><span class="gi-no">03</span><span class="eyebrow">From fibre · 纤维</span></div>
          <h2 id="gi-h3"><span class="gi-nw">每根纤维，</span><span class="gi-nw">都有一组读数</span></h2>
          <p>
            平台为每个样本配对
            <b><LiveValue :value="fmt(stats.fiberProps)" :busy="loading.metadata.value" width="1.2em" /></b>
            项纤维特性与
            <b><LiveValue :value="fmt(stats.paperProps)" :busy="loading.metadata.value" width="1.2em" /></b>
            项纸张性能。以“纤维长度（长度加权）× 抗张指数”为例，各组 Pearson r：
          </p>
          <div class="gi-facts">
            <template v-if="correlations">
              <div v-for="row in correlations" :key="row.key" class="gi-fact">
                <span class="l"
                  ><i v-if="row.key !== 'all'" class="gi-mk" :class="MARK[row.key]" aria-hidden="true"></i
                  >{{ row.label }} · {{ fmt(row.n) }} 对</span
                >
                <span class="v">{{ formatR(row.r) }}</span>
              </div>
            </template>
            <template v-else>
              <div v-for="k in 4" :key="k" class="gi-fact">
                <span class="l"><LiveValue value="—" :busy="loading.fiberPaper.value" width="9em" /></span>
                <span class="v"><LiveValue value="—" :busy="loading.fiberPaper.value" /></span>
              </div>
            </template>
          </div>
          <p class="gi-caveat">
            <Info :size="17" aria-hidden="true" /><span>图表展示对应关系，不代表因果关系；此处不作显著性检验。</span>
          </p>
          <RouterLink class="gi-more" :to="navItems[3]!.path"
            >在「{{ navItems[3]!.label }}」中比较其他指标 <ArrowRight :size="15" aria-hidden="true"
          /></RouterLink>
        </article>
      </section>

      <!-- 04 纸 -->
      <section id="gi-ch-4" class="gi-ch" aria-labelledby="gi-h4" tabindex="-1">
        <article class="gi-story">
          <div class="gi-story-k"><span class="gi-no">04</span><span class="eyebrow">Into paper · 纸</span></div>
          <h2 id="gi-h4"><span class="gi-nw">纤维沉降，</span><span class="gi-nw">交织成纸</span></h2>
          <p>纤维在网上铺展、交织、脱水，成为一张纸。纸还会被回收、再次碎解——再生纸浆以逐行观测独立保存。</p>
          <div class="gi-facts">
            <div class="gi-fact">
              <span class="l">再生纸浆原始观测</span>
              <span class="v"
                ><span class="gi-big"><LiveValue :value="fmt(stats.recycledObs)" :busy="loading.metadata.value" /></span>
                {{ stats.recycledObs == null ? "" : "条" }}</span
              >
            </div>
            <div class="gi-fact">
              <span class="l">数据块 · 循环汇总点</span>
              <span class="v"
                ><LiveValue :value="fmt(stats.recycledBlocks)" :busy="loading.metadata.value" width="1.2em" /> 个 ·
                <LiveValue :value="fmt(stats.recycledCycles)" :busy="loading.metadata.value" width="1.2em" /> 个</span
              >
            </div>
          </div>
          <p class="gi-caveat">
            <Info :size="17" aria-hidden="true" /><span
              ><template v-if="loading.metadata.value || (stats.unknownBlocks ?? 0) > 0"
                ><LiveValue :value="fmt(stats.unknownBlocks)" :busy="loading.metadata.value" width="1.2em" />
                个再生纸浆数据块的正式处理条件未知，不作推断；</template
              >核心指数与再生纸浆强度不可混用。</span
            >
          </p>
          <RouterLink class="gi-more" :to="navItems[4]!.path"
            >在「{{ navItems[4]!.label }}」中查看循环 <ArrowRight :size="15" aria-hidden="true"
          /></RouterLink>
        </article>
      </section>

      <!-- 05 数据 -->
      <section id="gi-ch-5" class="gi-ch gi-final" aria-labelledby="gi-h5" tabindex="-1">
        <div class="gi-final-inner">
          <p class="eyebrow"><span class="gi-lat">Into data</span> · 05 · 数据</p>
          <h2 id="gi-h5"><span class="gi-nw">现在，</span><span class="gi-nw">走进纤维花园</span></h2>
          <div ref="wallEl" class="gi-wall">
            <div v-for="k in kpis" :key="k.key" v-tilt class="gi-tile">
              <span class="gi-tile-l">{{ k.label }}</span>
              <span class="gi-tile-n">
                <LiveValue v-if="loading.metadata.value" value="—" busy width="1.4em" />
                <template v-else
                  ><span aria-hidden="true">{{ kpiText(k.key, k.value) }}</span
                  ><span class="sr-only">{{ fmt(k.value) }}</span></template
                >
              </span>
              <span class="gi-tile-s">{{ k.unit }} · {{ k.sub }}</span>
            </div>
          </div>
          <p v-if="data.status.value === 'error'" class="gi-error">
            <span>{{ data.allFailed.value ? "数据读取失败" : "部分数据读取失败" }}：{{ data.message.value }}</span>
            <button class="gi-retry" type="button" @click="data.reload()"><RefreshCw :size="14" aria-hidden="true" />重试</button>
          </p>
          <RouterLink id="gi-enter" class="gi-btn primary xl" to="/">进入工作台 <ArrowRight :size="20" aria-hidden="true" /></RouterLink>
          <nav class="gi-pages" aria-label="工作台页面">
            <RouterLink v-for="item in navItems" :key="item.path" class="gi-page" :to="item.path">
              <component :is="item.icon" :size="16" aria-hidden="true" />
              <span class="gi-page-n" aria-hidden="true">{{ item.index }}/{{ navTotal }}</span>{{ item.label }}
            </RouterLink>
          </nav>
          <p class="gi-note gi-final-note">数字实时读取自平台只读接口 · 空值显示为“—”，不替换为 0 · 图表展示对应关系，不代表因果关系。</p>
        </div>
      </section>
    </main>

    <dialog ref="about" class="info-dialog gi-about-dialog" aria-labelledby="gi-about-title" @close="onAboutClose" @click="$event.target === about && about?.close()">
      <div class="dialog-heading">
        <div>
          <span class="eyebrow">About the data · FiberScope</span>
          <h2 id="gi-about-title">关于这些实验数据</h2>
        </div>
        <button class="icon-button" type="button" aria-label="关闭数据说明" @click="about?.close()">
          <X :size="20" aria-hidden="true" />
        </button>
      </div>
      <p>
        核心样本保存 {{ fmt(stats.fiberProps) }} 项纤维特性和 {{ fmt(stats.paperProps) }} 项纸张性能；再生纸浆以逐行观测独立保存（{{
          fmt(stats.recycledObs)
        }} 条），循环均值由数据库汇总。
      </p>
      <ul v-if="notes.length">
        <li v-for="note in notes" :key="note">{{ note }}</li>
      </ul>
      <p v-else class="gi-note">{{ loading.metadata.value ? "正在读取数据说明…" : "数据说明暂时无法读取。" }}</p>
      <button class="button primary" type="button" @click="about?.close()">知道了</button>
    </dialog>
  </div>
</template>

<style scoped>
/* ================================================================ frame */
.gi {
  position: relative;
  isolation: isolate;
  overflow-x: clip;
  color: var(--text);
}
.gi-nw {
  white-space: nowrap;
}
.gi-lat {
  font-family: var(--font-display), var(--font-body);
  font-variation-settings: "SOFT" 100, "WONK" 1;
}
.t-sw {
  stroke: var(--sw);
}
.t-hw {
  stroke: var(--hw);
}
.t-bl {
  stroke: var(--bl);
}
.t-ink {
  stroke: var(--accent);
}

/* ================================================================ ambient (fixed, behind everything) */
.gi-ambient {
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  overflow: hidden;
}
.gi-mesh,
.gi-pulp,
.gi-grain {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.gi-mesh {
  background:
    radial-gradient(55% 45% at 8% 0%, var(--sw-tint) 0%, transparent 62%),
    radial-gradient(45% 55% at 100% 18%, var(--bl-tint) 0%, transparent 62%),
    radial-gradient(60% 55% at 28% 100%, var(--hw-tint) 0%, transparent 62%),
    linear-gradient(
      155deg,
      color-mix(in srgb, var(--sw-tint) 40%, var(--surface)) 0%,
      color-mix(in srgb, var(--bl-tint) 60%, var(--surface)) 52%,
      color-mix(in srgb, var(--hw-tint) 45%, var(--surface)) 100%
    );
}
.gi-pulp {
  display: block;
  opacity: 0;
  transition: opacity 1.4s var(--ease);
}
.gi-pulp.on {
  opacity: 1;
}
.gi-pulp.lost {
  visibility: hidden;
  transition: none;
}
.gi-grain {
  opacity: 0.5;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 .5  0 0 0 0 .45  0 0 0 0 .55  0 0 0 .35 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
}

/* ================================================================ top bar */
.gi-top {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 32px;
  isolation: isolate;
  transition: padding 0.35s var(--ease);
}
.gi-top::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  opacity: 0;
  background: color-mix(in srgb, var(--surface) 80%, transparent);
  -webkit-backdrop-filter: blur(18px) saturate(1.3);
  backdrop-filter: blur(18px) saturate(1.3);
  box-shadow:
    0 1px 0 var(--line),
    0 14px 30px -26px color-mix(in srgb, var(--accent) 50%, transparent);
  transition: opacity 0.35s var(--ease);
}
.gi-top.solid {
  padding-top: 12px;
  padding-bottom: 12px;
}
.gi-top.solid::before {
  opacity: 1;
}
.gi-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.gi-brand-mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
.gi-brand-mark svg {
  width: 28px;
  height: 28px;
}
.gi-brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.gi-brand-name {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 1, "opsz" 72;
  font-weight: 560;
  font-size: 21px;
  letter-spacing: -0.02em;
  line-height: 1;
}
.gi-brand-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-2);
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.gi-top-r {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ================================================================ buttons */
.gi-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  border: 0;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.2;
  white-space: nowrap;
  text-decoration: none;
  cursor: pointer;
  transition:
    transform 0.35s var(--spring),
    background 0.25s,
    box-shadow 0.25s;
}
.gi-btn:active {
  transform: scale(0.96);
}
.gi-btn.primary {
  background: var(--text);
  color: var(--accent-contrast);
  box-shadow:
    0 12px 26px -14px color-mix(in srgb, var(--text) 80%, transparent),
    inset 0 1px 0 color-mix(in srgb, var(--surface) 18%, transparent);
}
.gi-btn.primary:hover {
  background: color-mix(in srgb, var(--text) 86%, var(--accent-tint));
  transform: translateY(-1px);
}
.gi-btn.ghost {
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  color: var(--text);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--surface) 95%, transparent),
    0 6px 16px -10px color-mix(in srgb, var(--accent) 40%, transparent);
}
.gi-btn.ghost:hover {
  background: var(--surface);
}
.gi-btn.sm {
  padding: 8px 14px;
  font-size: 13px;
}
.gi-btn.lg {
  padding: 14px 24px;
  font-size: 15px;
}
.gi-btn.xl {
  padding: 16px 30px;
  font-size: 16px;
}

/* ================================================================ chapter rail */
.gi-dots {
  position: fixed;
  right: 26px;
  top: 50%;
  translate: 0 -50%;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.gi-dots a {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 4px 0;
  border-radius: 999px;
  color: var(--text-2);
  font-size: 12.5px;
  text-decoration: none;
}
.gi-dot-label {
  opacity: 0;
  translate: 6px 0;
  white-space: nowrap;
  transition:
    opacity 0.3s,
    translate 0.3s;
}
/* labels only on hover / focus, so the rail never covers the right-hand story cards */
.gi-dots a:hover .gi-dot-label,
.gi-dots a:focus-visible .gi-dot-label {
  opacity: 1;
  translate: 0 0;
  padding: 2px 10px;
  border-radius: 999px;
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  box-shadow: var(--shadow-sm);
}
.gi-dots i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 50%, transparent);
  transition:
    height 0.4s var(--spring),
    border-radius 0.4s,
    background 0.3s;
}
.gi-dots a.on i {
  height: 26px;
  border-radius: 9px;
  background: var(--text);
}

/* ================================================================ stage */
main {
  position: relative;
  display: block;
}
.gi-stage {
  position: sticky;
  top: 0;
  z-index: 0;
  height: 100vh;
  height: 100svh;
  margin-bottom: -100vh;
  margin-bottom: -100svh;
  overflow: hidden;
  pointer-events: none;
}
.gi-layer {
  position: absolute;
  inset: 0;
  will-change: transform, opacity;
}
.gi-far,
.gi-paper,
.gi-mid {
  inset: -12% -6%;
}
.gi-far img,
.gi-paper img {
  position: absolute;
  max-width: none;
  object-fit: cover;
}
.gi-far img {
  inset: -6% -4%;
  width: 108%;
  height: 112%;
  filter: blur(3px) saturate(1.02);
  opacity: 0.78;
}
.gi-far {
  -webkit-mask: radial-gradient(130% 120% at 70% 55%, var(--text) 45%, transparent 85%);
  mask: radial-gradient(130% 120% at 70% 55%, var(--text) 45%, transparent 85%);
}
.gi-fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(40% 50% at 75% 50%, color-mix(in srgb, var(--sw) 34%, transparent), transparent 70%),
    radial-gradient(35% 45% at 85% 70%, color-mix(in srgb, var(--bl) 34%, transparent), transparent 70%),
    radial-gradient(35% 40% at 65% 30%, color-mix(in srgb, var(--hw) 30%, transparent), transparent 70%);
}
.gi-paper img {
  inset: -4%;
  width: 108%;
  height: 108%;
}
.gi-paper img.blurred {
  filter: blur(16px) saturate(1.1);
}
.gi-paper {
  -webkit-mask: radial-gradient(120% 100% at 50% 60%, var(--text) 40%, transparent 90%);
  mask: radial-gradient(120% 100% at 50% 60%, var(--text) 40%, transparent 90%);
}
.gi-giant {
  position: absolute;
  left: 0;
  right: 0;
  top: 76%;
  translate: 0 -50%;
  text-align: center;
  white-space: nowrap;
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 1, "opsz" 144;
  font-weight: 300;
  font-style: italic;
  font-size: 23vw;
  letter-spacing: -0.06em;
  line-height: 1;
  color: transparent;
  background: linear-gradient(
    100deg,
    color-mix(in srgb, var(--sw) 40%, transparent),
    color-mix(in srgb, var(--bl) 36%, transparent) 55%,
    color-mix(in srgb, var(--hw) 36%, transparent)
  );
  -webkit-background-clip: text;
  background-clip: text;
  filter: blur(0.5px);
  will-change: transform, opacity;
}
.gi-gl {
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity 0.9s var(--ease);
}
.gi-gl.on {
  opacity: 1;
}
.gi-gl.lost {
  visibility: hidden;
  transition: none;
}
.gi-gl canvas {
  display: block;
  width: 100%;
  height: 100%;
}
.gi-mid svg {
  position: absolute;
  inset: -10% -5%;
  width: 110%;
  height: 120%;
  filter: blur(1.2px);
}
.gi-mid path {
  fill: none;
  stroke-linecap: round;
}
.gi-mid .t-sw {
  stroke: color-mix(in srgb, var(--sw) 82%, var(--surface));
}
.gi-mid .t-hw {
  stroke: color-mix(in srgb, var(--hw) 78%, var(--surface));
}
.gi-mid .t-bl {
  stroke: color-mix(in srgb, var(--bl) 82%, var(--surface));
}
.gi-near {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding-left: 7vw;
}
.gi-glass {
  position: relative;
  width: min(30vw, 400px);
  aspect-ratio: 1;
  margin: 0;
  border-radius: 44px;
  overflow: hidden;
  transform: perspective(900px) rotateX(var(--grx, 0deg)) rotateY(var(--gry, 0deg));
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--surface) 70%, transparent),
    color-mix(in srgb, var(--bl-tint) 60%, transparent)
  );
  box-shadow:
    0 50px 90px -40px color-mix(in srgb, var(--accent) 55%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--surface) 90%, transparent);
}
.gi-glass img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  scale: 1.14;
}
.gi-glass::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--surface) 45%, transparent),
    transparent 40%,
    transparent 70%,
    color-mix(in srgb, var(--surface) 25%, transparent)
  );
}
.gi-glass figcaption {
  position: absolute;
  left: 18px;
  bottom: 16px;
  z-index: 1;
  padding: 4px 12px;
  border-radius: 999px;
  font-family: var(--font-display);
  font-style: italic;
  font-size: 14px;
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 78%, transparent);
}

/* ================================================================ chapters */
.gi-ch {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  min-height: 100vh;
  min-height: 100svh;
  padding: 110px 7vw 90px;
}
.gi-ch:focus,
.gi-ch:focus-visible {
  outline: none;
}
.gi-ch.right {
  justify-content: flex-end;
}

/* 序 · hero */
.gi-hero-text {
  position: relative;
  max-width: 720px;
}
/* a soft light pool behind the copy, so it stays readable over the strands and the photo */
.gi-hero-text::before {
  content: "";
  position: absolute;
  inset: -16% -14% -18% -20%;
  z-index: -1;
  pointer-events: none;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--surface) 78%, transparent),
    color-mix(in srgb, var(--surface) 45%, transparent) 60%,
    transparent
  );
}
.gi-hero h1 {
  margin: 14px 0 20px;
  font-family: var(--font-display-cn);
  font-weight: 400;
  font-size: clamp(44px, 5.3vw, 80px);
  line-height: 1.04;
  letter-spacing: 0.02em;
  color: var(--text);
  text-wrap: balance;
  text-shadow: 0 2px 30px color-mix(in srgb, var(--surface) 90%, transparent);
}
.gi-hero h1 em {
  position: relative;
  display: inline-block;
  font-style: normal;
  color: var(--accent);
}
.gi-em-strands {
  position: absolute;
  left: -3%;
  bottom: -0.16em;
  width: 106%;
  height: 0.3em;
  overflow: visible;
  pointer-events: none;
}
.gi-em-strands path {
  fill: none;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-opacity: 0.9;
  stroke-dasharray: 1;
  /* resting state is drawn; the entrance animates from hidden (killed under reduced motion) */
  stroke-dashoffset: 0;
  animation: gi-draw 1.6s 0.35s var(--ease) backwards;
}
.gi-em-strands path:nth-child(2) {
  animation-delay: 0.5s;
}
.gi-em-strands path:nth-child(3) {
  animation-delay: 0.65s;
}
@keyframes gi-draw {
  from {
    stroke-dashoffset: 1;
  }
}
.gi-hero .eyebrow {
  font-size: 15px;
}
.gi-lede {
  max-width: 520px;
  font-size: 17px;
  line-height: 1.65;
  color: var(--text-2);
  text-shadow: 0 1px 14px color-mix(in srgb, var(--surface) 95%, transparent);
}
.gi-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
}
.gi-live {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin-top: 22px;
  padding: 5px 6px 5px 14px;
  border-radius: 18px;
  font-size: 13px;
  color: var(--text-2);
  background: color-mix(in srgb, var(--surface) 76%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface) 95%, transparent);
}
.gi-live:not(.error) {
  padding-right: 14px;
}
.gi-live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-3);
}
.gi-live.ready .gi-live-dot {
  background: var(--ok);
  box-shadow: 0 0 0 4px var(--ok-tint);
}
.gi-live.loading .gi-live-dot {
  animation: gi-pulse 1.2s ease-in-out infinite;
}
.gi-live.error .gi-live-dot {
  background: var(--bad);
}
@keyframes gi-pulse {
  50% {
    opacity: 0.3;
  }
}
.gi-retry {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 85%, transparent);
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.gi-retry:hover {
  background: var(--surface);
}
.gi-hero-chips {
  position: absolute;
  right: 7vw;
  bottom: 64px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.gi-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text-2);
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface) 95%, transparent);
  white-space: nowrap;
}
.gi-chip b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.gi-cue {
  position: absolute;
  left: 50%;
  bottom: 22px;
  translate: -50% 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text);
  text-shadow: 0 1px 10px var(--surface);
}
.gi-cue i {
  position: relative;
  width: 22px;
  height: 34px;
  border-radius: 12px;
  box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--text) 35%, transparent);
}
.gi-cue i::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 7px;
  width: 4px;
  height: 7px;
  margin-left: -2px;
  border-radius: 4px;
  background: var(--text);
  animation: gi-cue 1.8s ease-in-out infinite;
}
@keyframes gi-cue {
  60% {
    translate: 0 9px;
    opacity: 0;
  }
}

/* 01–04 · story cards */
.gi-story {
  width: min(520px, 100%);
  padding: 30px 32px 28px;
  border-radius: 36px;
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--surface) 84%, transparent),
    color-mix(in srgb, var(--surface) 64%, transparent)
  );
  -webkit-backdrop-filter: blur(22px) saturate(1.3);
  backdrop-filter: blur(22px) saturate(1.3);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--surface) 90%, transparent),
    inset 0 1px 0 var(--surface),
    var(--shadow);
}
.gi-story-k {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.gi-no {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums;
  font-size: 58px;
  line-height: 0.9;
  letter-spacing: -0.035em;
  color: var(--accent);
}
.gi-story h2 {
  margin: 6px 0 12px;
  font-family: var(--font-display-cn);
  font-weight: 400;
  font-size: clamp(30px, 2.7vw, 38px);
  line-height: 1.2;
  letter-spacing: 0.01em;
  color: var(--text);
  text-wrap: balance;
}
.gi-story p {
  font-size: 15px;
  line-height: 1.65;
  color: var(--text-2);
}
.gi-story p b,
.gi-legend b {
  font-weight: 700;
  color: var(--text);
}
.gi-comp {
  display: flex;
  gap: 3px;
  height: 16px;
  margin: 16px 0 10px;
}
.gi-comp i {
  display: block;
  height: 100%;
  border-radius: 9px;
}
.gi-comp-wait i {
  flex: 1;
  background: color-mix(in srgb, var(--text) 10%, transparent);
}
.f-sw {
  background: var(--sw);
}
.f-hw {
  background: var(--hw);
}
.f-bl {
  background: var(--bl);
}
.gi-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 13.5px;
  color: var(--text-2);
}
.gi-legend.small {
  gap: 4px 14px;
  margin-top: 6px;
  font-size: 12px;
}
.gi-li {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.gi-num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.gi-axis {
  color: var(--text-2);
}
.gi-mk {
  display: inline-block;
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.gi-mk.sw {
  background: var(--sw);
}
.gi-mk.hw {
  border-radius: 2px;
  background: var(--hw);
}
.gi-mk.bl {
  width: 10px;
  height: 10px;
  border-radius: 0;
  clip-path: polygon(50% 0, 100% 100%, 0 100%);
  background: var(--bl);
}
.gi-dash {
  display: inline-block;
  width: 18px;
  border-top: 1.5px dashed var(--chart-target);
}
.gi-facts {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}
.gi-fact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 14px;
  border-radius: 16px;
  font-size: 14px;
  background: color-mix(in srgb, var(--surface) 70%, transparent);
}
.gi-fact .l {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  color: var(--text-2);
}
.gi-fact .v {
  flex: none;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
  white-space: nowrap;
}
.gi-big {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums;
  font-size: 26px;
  letter-spacing: -0.035em;
}
.gi-note {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.gi-story .gi-note {
  font-size: 13px;
}
.gi-spark {
  margin-top: 16px;
  padding: 12px 12px 8px;
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface) 66%, transparent);
}
.gi-spark-wait {
  display: grid;
  place-items: center;
  height: 110px;
  border-radius: 12px;
  font-size: 13px;
  color: var(--text-2);
  background: color-mix(in srgb, var(--text) 5%, transparent);
}
.gi-story .gi-caveat {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface) 85%, transparent);
}
.gi-story .gi-caveat svg {
  flex: none;
  margin-top: 2px;
  color: var(--accent);
}
.gi-more {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  padding: 2px 0;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--accent-ink);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--accent) 35%, transparent);
  text-underline-offset: 4px;
}
.gi-more:hover {
  text-decoration-color: var(--accent);
}

/* 05 · into the workspace */
/* 120% tall, so the sheet keeps settling at the end; the content is centred in the last screen */
.gi-final {
  justify-content: center;
  min-height: 120vh;
  min-height: 120svh;
  padding-top: calc(20vh + 110px);
}
.gi-final-inner {
  position: relative;
  isolation: isolate;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 26px;
  width: 100%;
  text-align: center;
}
/* a light pool behind the closing copy */
.gi-final-inner::before {
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  z-index: -1;
  width: min(1300px, 130vw);
  height: 130%;
  translate: -50% -50%;
  pointer-events: none;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--surface) 90%, transparent),
    color-mix(in srgb, var(--surface) 74%, transparent) 66%,
    transparent
  );
}
.gi-final .eyebrow,
.gi-final-note {
  text-shadow: 0 0 12px var(--surface), 0 0 4px var(--surface);
}
.gi-final .eyebrow {
  font-size: 15px;
}
.gi-final h2 {
  font-family: var(--font-display-cn);
  font-weight: 400;
  font-size: clamp(38px, 5vw, 72px);
  line-height: 1.1;
  letter-spacing: 0.02em;
  color: var(--text);
  text-wrap: balance;
  text-shadow: 0 2px 30px color-mix(in srgb, var(--surface) 90%, transparent);
}
.gi-wall {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  width: min(1100px, 100%);
}
.gi-tile {
  display: flex;
  flex-direction: column;
  padding: 22px 22px 20px;
  border-radius: var(--radius);
  text-align: left;
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--surface) 94%, transparent),
    color-mix(in srgb, var(--surface) 80%, transparent)
  );
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--surface) 90%, transparent),
    inset 0 1px 0 var(--surface),
    var(--shadow);
}
.gi-tile-l {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}
.gi-tile-n {
  display: block;
  margin: 12px 0 8px;
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  font-size: clamp(56px, 6vw, 92px);
  line-height: 0.9;
  letter-spacing: -0.035em;
  color: var(--text);
}
.gi-tile-s {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-2);
}
.gi-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 12px;
  padding: 10px 16px;
  border-radius: 16px;
  font-size: 13.5px;
  color: var(--bad);
  background: var(--bad-tint);
}
.gi-pages {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 900px;
}
.gi-page {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13.5px;
  color: var(--text);
  text-decoration: none;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--surface) 95%, transparent),
    0 6px 16px -12px color-mix(in srgb, var(--accent) 45%, transparent);
  transition:
    background 0.2s,
    transform 0.35s var(--spring);
}
.gi-page:hover {
  background: var(--surface);
  transform: translateY(-1px);
}
.gi-page svg {
  color: var(--accent);
}
.gi-page-n {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-2);
}
.gi-final-note {
  max-width: 640px;
}

/* ================================================================ dialog */
.gi-about-dialog ul {
  margin-bottom: 20px;
}

/* ================================================================ reduced motion: still frames */
.gi-still .gi-gl,
.gi-still .gi-pulp {
  transition: none;
}

/* ================================================================ responsive */
@media (max-width: 980px) {
  /* the hero chips need the bottom edge on narrow screens */
  .gi-cue {
    display: none;
  }
  .gi-wall {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .gi-near {
    padding-left: 4vw;
  }
}
@media (max-width: 720px) {
  .gi-top,
  .gi-top.solid {
    padding: 10px 16px;
  }
  .gi-brand-mark {
    width: 36px;
    height: 36px;
    border-radius: 12px;
  }
  .gi-brand-name {
    font-size: 18px;
  }
  .gi-brand-sub,
  .gi-about-label,
  .gi-dots,
  .gi-hero-chips,
  .gi-cue {
    display: none;
  }
  .gi-top-r {
    gap: 6px;
  }
  .gi-about {
    width: 36px;
    height: 36px;
    padding: 0;
  }
  .gi-ch {
    align-items: flex-end;
    padding: 96px 16px 72px;
  }
  .gi-ch.right {
    justify-content: center;
  }
  .gi-hero {
    padding-bottom: 40px;
  }
  .gi-lede {
    font-size: 15px;
  }
  .gi-cta .gi-btn.lg {
    padding: 13px 20px;
  }
  .gi-story {
    padding: 22px 20px;
    border-radius: 28px;
  }
  .gi-no {
    font-size: 44px;
  }
  .gi-fact {
    align-items: flex-start;
    font-size: 13.5px;
  }
  .gi-giant {
    top: 30%;
    font-size: 34vw;
  }
  .gi-near {
    align-items: flex-start;
    justify-content: center;
    padding: 16vh 0 0;
  }
  .gi-glass {
    width: 54vw;
    border-radius: 30px;
  }
  .gi-final {
    align-items: center;
    padding-bottom: 72px;
  }
  .gi-final-inner {
    gap: 22px;
  }
  .gi-wall {
    gap: 10px;
  }
  .gi-tile {
    padding: 16px;
    border-radius: 24px;
  }
  .gi-tile-n {
    font-size: 52px;
  }
}
@media (max-width: 440px) {
  .gi-hide-xs {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .gi-top .gi-btn.primary.sm {
    padding: 8px 12px;
  }
}
@media (forced-colors: active) {
  .gi-story,
  .gi-tile {
    border: 1px solid CanvasText;
  }
}
</style>
