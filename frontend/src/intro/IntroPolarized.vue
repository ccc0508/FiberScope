<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import ModeSwitch from "../components/ModeSwitch.vue";
import { navItems, platformName } from "../nav";
import { reducedMotion } from "../mode";
import { number, typeKeys, typeNames, type SampleType } from "../api";
import { createField, type FieldController, type FieldParams } from "../ambient/field";
import heroImage from "../assets/modes/polarized/hero-polarized.jpg";
import fibrilImage from "../assets/modes/polarized/microfibril.jpg";
import tracheidImage from "../assets/modes/polarized/tracheid-section.jpg";
import IntroReticle from "./polarized/IntroReticle.vue";
import IntroTurret from "./polarized/IntroTurret.vue";
import { MAGS, SCALEBAR_PX, nearStrands, umPerPx } from "./polarized/content";
import { useIntroStats } from "./polarized/data";
import type { FibrilScene } from "./polarized/fibril3d";

/*
 * 序章 · 偏光 (v1 landing). Scrolling turns the analyzer and raises the magnification:
 * 10× fibre → 40× wall layers → 400× S2 helix → 4000× inside the microfibril helix, then the
 * objective turret leads into the eight workspace pages.
 *
 * Depth planes (back → front): L0 birefringence shader (ambient/field.ts) · L1 blurred far
 * fibres · L2 photograph · L3 crisp SVG strands · veil · content · microscope HUD.
 * Every number on the page comes from the API (polarized/data.ts).
 *
 * Reduced motion: one still frame of the field, no parallax, no pointer or scroll following;
 * the stage scrolls away with the hero and the magnification story becomes a plain list.
 * No WebGL: CSS gradient + photographs, and the static magnification list.
 */
const { stats, composition, coreStatus, sourceStatus, message, reload } = useIntroStats();
const n = (v: number | null | undefined) => number(v);

const still = computed(() => reducedMotion.value);
const loading = computed(() => coreStatus.value === "loading" || sourceStatus.value === "loading");
const failed = computed(() => coreStatus.value === "error" || sourceStatus.value === "error");

const compositionRows = computed(
  () =>
    composition.value ??
    typeKeys.map((type: SampleType) => ({ type, label: typeNames[type], n: null, share: null, range: null })),
);
const firstObjective = navItems[0]!,
  lastObjective = navItems[navItems.length - 1]!;

/* ---------------------------------------------------------------- element refs */
const fieldCanvas = ref<HTMLCanvasElement>();
const fibrilCanvas = ref<HTMLCanvasElement>();
const stageFar = ref<HTMLElement>();
const stageImg = ref<HTMLElement>();
const stageNear = ref<SVGSVGElement>();
const stageVeil = ref<HTMLElement>();
const retWrap = ref<HTMLElement>();
const crossH = ref<HTMLElement>();
const crossV = ref<HTMLElement>();
const crossLabel = ref<HTMLElement>();
const readX = ref<HTMLElement>();
const readY = ref<HTMLElement>();
const readT = ref<HTMLElement>();
const anDot = ref<HTMLElement>();
const anValue = ref<HTMLElement>();
const contentEl = ref<HTMLElement>();
const treeEl = ref<HTMLElement>();
const eyepiece = ref<HTMLElement>();
const magEl = ref<HTMLElement>();
const plate = ref<HTMLElement>();
const enterEl = ref<HTMLElement>();

/* ---------------------------------------------------------------- state */
const glAvailable = ref(true); // the field could be created (layout decision, set once)
const fieldOn = ref(false); // the field is drawing right now (false while the context is lost)
const fibrilOn = ref(false);
const fibrilLost = ref(false);
const fibrilFailed = ref(false);
/** a disposed scene force-loses its context, so every new scene gets a fresh canvas element */
const fibrilGen = ref(0);
const crossLive = ref(false);
const stageIdx = ref(0);
const capIdx = ref(0);
/** the pinned 3D story needs motion and WebGL; otherwise the magnifications are a plain list */
const no3d = computed(() => still.value || !glAvailable.value || fibrilFailed.value);
const fibrilShown = computed(() => fibrilOn.value && !fibrilLost.value && !no3d.value);

let field: FieldController | null = null;
let fibril: FibrilScene | null = null;
let fibrilLoading = false;
let dead = false;

/* ---------------------------------------------------------------- scroll / pointer driven frame */
const pointer = { x: window.innerWidth / 2, y: window.innerHeight / 2, nx: 0, ny: 0 };
let mx = 0,
  my = 0,
  raf = 0,
  lastPhase = -1,
  lastFieldKey = "";
const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const ss = (a: number, b: number, v: number) => {
  const t = clamp((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const signed = (v: number) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).padStart(6, "0");
const cache = new WeakMap<Element, Record<string, string>>();
function setStyle(el: HTMLElement | SVGElement | undefined, prop: "transform" | "opacity", value: string) {
  if (!el) return;
  const c = cache.get(el) ?? {};
  if (c[prop] === value) return;
  c[prop] = value;
  cache.set(el, c);
  el.style[prop] = value;
}
function setText(el: HTMLElement | undefined, value: string) {
  if (el && el.textContent !== value) el.textContent = value;
}
/** drop every inline frame style (switching to the still layout) */
function clearFrameStyles() {
  for (const el of [stageFar.value, stageImg.value, stageNear.value, stageVeil.value, retWrap.value, eyepiece.value, plate.value, anDot.value]) {
    if (!el) continue;
    el.style.transform = "";
    el.style.opacity = "";
    cache.delete(el);
  }
}

// section geometry is cached and re-measured only when the layout changes
const geo = { magTop: 0, magH: 1, treeTop: 0, treeH: 1, max: 1 };
function measure() {
  const y = window.scrollY;
  const rm = magEl.value?.getBoundingClientRect();
  const rt = treeEl.value?.getBoundingClientRect();
  if (rm) {
    geo.magTop = rm.top + y;
    geo.magH = rm.height;
  }
  if (rt) {
    geo.treeTop = rt.top + y;
    geo.treeH = rt.height;
  }
  geo.max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
}

const STILL_FIELD: Partial<FieldParams> = {
  analyzer: Math.PI / 2,
  retard: 0,
  scroll: 0,
  stageX: 0,
  stageY: 0,
  intensity: 1,
  texAmt: 0.32,
  zoom: 1,
  left: 1,
};

function update(force = false) {
  const vh = window.innerHeight,
    vw = window.innerWidth,
    y = window.scrollY;
  const isStill = still.value;
  const P = clamp(y / geo.max);
  // interference edges (--ifl / --ifc) turn with the analyzer; quantised to 40 style passes
  const phaseStep = isStill ? 0 : Math.round(P * 40);
  if (phaseStep !== lastPhase) {
    lastPhase = phaseStep;
    document.documentElement.style.setProperty("--phase", (phaseStep / 40).toFixed(3));
  }
  if (!isStill) {
    mx += (pointer.nx - mx) * 0.07;
    my += (pointer.ny - my) * 0.07;
  }

  // magnification section progress
  const rTop = geo.magTop - y,
    rBottom = rTop + geo.magH;
  const pm = clamp(-rTop / Math.max(1, geo.magH - vh));
  const inMag = rTop < vh * 0.6 && rBottom > vh * 0.4;

  // the analyzer and the compensator follow the whole scroll
  const theta = isStill ? 90 : 90 - 26 * Math.sin(P * Math.PI);
  const heroOut = ss(0, vh * 1.1, y);
  const magIn = no3d.value ? 0 : ss(rTop - vh * 0.6, rTop, 0) * (1 - ss(rBottom - vh * 0.6, rBottom - vh * 0.1, 0));

  if (!isStill) {
    // L1–L3 parallax at different rates; depth from the pointer
    setStyle(stageFar.value, "transform", `translate3d(${(mx * -10).toFixed(1)}px, ${(-y * 0.12 + my * -8).toFixed(1)}px, 0) scale(1.22)`);
    setStyle(stageImg.value, "transform", `translate3d(${(mx * -22).toFixed(1)}px, ${(-y * 0.38 + my * -14).toFixed(1)}px, 0) scale(${(1.04 + heroOut * 0.18).toFixed(3)})`);
    setStyle(stageNear.value, "transform", `translate3d(${(mx * -46).toFixed(1)}px, ${(-y * 0.9 + my * -26).toFixed(1)}px, 0)`);
    setStyle(eyepiece.value, "transform", `translate3d(0, ${((geo.treeTop - y + geo.treeH / 2 - vh / 2) * -0.18).toFixed(1)}px, 0)`);
    setStyle(stageImg.value, "opacity", (1 - heroOut * 0.92).toFixed(3));
    setStyle(stageFar.value, "opacity", (0.5 * (1 - heroOut)).toFixed(3));
    setStyle(stageNear.value, "opacity", (1 - ss(vh * 0.5, vh * 2.2, y) * 0.75).toFixed(3));
    setStyle(stageVeil.value, "opacity", (heroOut * 0.6 + magIn * 0.3).toFixed(3));
    setStyle(retWrap.value, "opacity", (1 - ss(vh * 0.15, vh * 0.85, y)).toFixed(3));
    setStyle(retWrap.value, "transform", `translate(-50%, -50%) translate3d(${(mx * -10).toFixed(1)}px, ${(-y * 0.25 + my * -8).toFixed(1)}px, 0)`);
    setStyle(anDot.value, "transform", `translateY(${(P * 180).toFixed(1)}px)`);
  }

  if (field) {
    const post = clamp((y - (geo.magTop + geo.magH - vh)) / vh);
    const values: Partial<FieldParams> = isStill
      ? STILL_FIELD
      : {
          analyzer: (theta * Math.PI) / 180,
          retard: P * 1150,
          scroll: y / vh,
          stageX: mx * 0.55,
          stageY: -my * 0.55,
          intensity: (1 - magIn * 0.72) * (1 - post * 0.42),
          texAmt: (0.22 * (1 - heroOut) + 0.1) * (1 - magIn),
          zoom: 1 + pm * 0.6 * magIn,
          left: vw > 860 ? 1 - heroOut : 0,
        };
    const key = JSON.stringify(values);
    if (key !== lastFieldKey) {
      lastFieldKey = key;
      field.set(values);
    }
  }

  // magnification readouts
  let stage = 0;
  if (rTop < vh * 0.5) stage = Math.min(3, Math.floor(pm * 4 + 1e-4));
  if (rBottom < vh * 0.5) stage = 3;
  stageIdx.value = stage;
  capIdx.value = Math.min(3, Math.floor(pm * 4 + 1e-4));
  if ((inMag || force) && magEl.value) magEl.value.style.setProperty("--pm", isStill ? "0" : pm.toFixed(4));
  // the microfibril plate carries 10× / 40×, then hands over to the 3D helix (and returns faintly at 4000×)
  if (fibrilShown.value && !isStill)
    setStyle(plate.value, "opacity", (0.5 - ss(0.12, 0.55, pm) * 0.42 + ss(0.82, 1, pm) * 0.1).toFixed(3));
  if (fibril && !isStill && (inMag || force)) {
    fibril.setProgress(pm, pm * 220);
    fibril.setMouse(mx, my);
  }

  setText(readT.value, theta.toFixed(1));
  setText(anValue.value, `${theta.toFixed(0)}°`);
  if (!isStill) {
    // one calibration for the crosshair readout and the scale bar
    const k = umPerPx(MAGS[stage]!.mag);
    const cx = signed((pointer.x - vw / 2) * k),
      cy = signed((vh / 2 - pointer.y) * k);
    setText(readX.value, cx);
    setText(readY.value, cy);
    setStyle(crossH.value, "transform", `translateY(${pointer.y.toFixed(0)}px)`);
    setStyle(crossV.value, "transform", `translateX(${pointer.x.toFixed(0)}px)`);
    setStyle(crossLabel.value, "transform", `translate(${(pointer.x + 14).toFixed(0)}px, ${(pointer.y + 14).toFixed(0)}px)`);
    setText(crossLabel.value, `${cx} · ${cy} µm`);
  }
}

// rAF only while something changes: a scroll / pointer event, or the eased stage still converging
function frame() {
  raf = 0;
  if (dead || document.hidden) return;
  update(false);
  if (!still.value && (Math.abs(pointer.nx - mx) > 0.001 || Math.abs(pointer.ny - my) > 0.001)) schedule();
}
function schedule() {
  if (!raf && !dead) raf = requestAnimationFrame(frame);
}
function onPointer(event: PointerEvent) {
  if (event.pointerType === "touch") return;
  pointer.x = event.clientX;
  pointer.y = event.clientY;
  pointer.nx = (event.clientX / window.innerWidth - 0.5) * 2;
  pointer.ny = (event.clientY / window.innerHeight - 0.5) * 2;
  if (!still.value) crossLive.value = true;
  schedule();
}
function onResize() {
  measure();
  lastFieldKey = "";
  schedule();
}

/* ---------------------------------------------------------------- Three.js microfibril helix (lazy) */
async function loadFibril() {
  if (fibril || fibrilLoading || no3d.value || !fibrilCanvas.value) return;
  fibrilLoading = true;
  try {
    const { createFibrilScene } = await import("./polarized/fibril3d");
    if (dead || no3d.value || !fibrilCanvas.value) return;
    fibril = createFibrilScene(fibrilCanvas.value, {
      compact: window.innerWidth <= 720,
      onLost: () => {
        fibrilLost.value = true;
      },
      onRestored: () => {
        fibrilLost.value = false;
        update(true);
      },
    });
    fibrilOn.value = true;
    await nextTick();
    update(true);
  } catch {
    // no WebGL 2 or a failed chunk: the plate image and the static list carry the story
    fibrilFailed.value = true;
    fibril?.dispose();
    fibril = null;
  } finally {
    fibrilLoading = false;
  }
}
function disposeFibril() {
  if (fibril) fibrilGen.value++;
  fibril?.dispose();
  fibril = null;
  fibrilOn.value = false;
  fibrilLost.value = false;
  if (plate.value) {
    plate.value.style.opacity = "";
    cache.delete(plate.value);
  }
}
let magObserver: IntersectionObserver | undefined;
function observeMag() {
  magObserver?.disconnect();
  if (!magEl.value || typeof IntersectionObserver !== "function") return;
  magObserver = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) void loadFibril();
    },
    { rootMargin: "120% 0px" },
  );
  magObserver.observe(magEl.value);
}

/* ---------------------------------------------------------------- the birefringence field (L0) */
function createStageField() {
  if (!fieldCanvas.value) return;
  try {
    field = createField(fieldCanvas.value, {
      scale: window.innerWidth <= 720 ? 0.42 : 0.5,
      texture: heroImage,
      still: still.value,
      params: { texAmt: 0.32, focusX: 0.42, focusY: 0, vig: 0.45, density: 0.62, intensity: 1.05 },
      onFail: () => {
        field?.dispose();
        field = null;
        fieldOn.value = false;
        glAvailable.value = false;
        disposeFibril();
      },
      // the CSS gradient stands in while the GPU context is lost
      onLost: () => {
        fieldOn.value = false;
      },
      onRestored: () => {
        fieldOn.value = true;
        lastFieldKey = "";
        update(true);
      },
    });
  } catch {
    field = null;
  }
  fieldOn.value = !!field;
  glAvailable.value = !!field;
}

/* ---------------------------------------------------------------- in-page jumps */
function focusSection(el: HTMLElement | undefined, smooth: boolean) {
  if (!el) return;
  el.focus({ preventScroll: true });
  el.scrollIntoView({ behavior: smooth && !still.value ? "smooth" : "auto", block: "start" });
}
const toTree = () => focusSection(treeEl.value, true);
const toEnter = () => focusSection(enterEl.value, false);

/* ---------------------------------------------------------------- lifecycle */
let resizeObserver: ResizeObserver | undefined;
onMounted(() => {
  createStageField();
  observeMag();
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("pointermove", onPointer, { passive: true });
  window.addEventListener("resize", onResize, { passive: true });
  document.addEventListener("visibilitychange", schedule);
  if (typeof ResizeObserver === "function" && contentEl.value) {
    resizeObserver = new ResizeObserver(() => onResize());
    resizeObserver.observe(contentEl.value);
  }
  measure();
  update(true);
});

watch(still, async (isStill) => {
  field?.setStill(isStill);
  lastFieldKey = "";
  if (isStill) {
    disposeFibril();
    clearFrameStyles();
    crossLive.value = false;
    mx = my = 0;
  }
  await nextTick();
  measure();
  update(true);
  if (!isStill) observeMag(); // re-observing reports the current intersection again
});

onBeforeUnmount(() => {
  dead = true;
  cancelAnimationFrame(raf);
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("pointermove", onPointer);
  window.removeEventListener("resize", onResize);
  document.removeEventListener("visibilitychange", schedule);
  resizeObserver?.disconnect();
  magObserver?.disconnect();
  field?.dispose();
  field = null;
  fibril?.dispose();
  fibril = null;
  document.documentElement.style.removeProperty("--phase");
});
</script>

<template>
  <div
    class="pzi"
    :class="{ 'pzi-still': still, 'pzi-nogl': !fieldOn }"
  >
    <a class="skip-link" href="#pzi-enter" @click.prevent="toEnter">跳到“进入工作台”</a>

    <!-- L0–L3 depth planes (decorative) -->
    <div class="pzi-stage" aria-hidden="true">
      <canvas ref="fieldCanvas" class="pzi-field"></canvas>
      <div class="pzi-fallback"></div>
      <div ref="stageFar" class="pzi-far"><img :src="heroImage" alt="" decoding="async" /></div>
      <div ref="stageImg" class="pzi-img"><img :src="heroImage" alt="" decoding="async" /></div>
      <svg
        ref="stageNear"
        class="pzi-near"
        viewBox="0 0 1600 1000"
        preserveAspectRatio="xMidYMid slice"
        focusable="false"
      >
        <defs>
          <linearGradient v-for="s in nearStrands" :id="s.id" :key="s.id" x1="0" y1="1" x2="0.3" y2="0">
            <stop offset="0" :class="`c${s.stops[0]}`" stop-opacity="0" />
            <stop offset=".3" :class="`c${s.stops[0]}`" />
            <stop offset=".62" :class="`c${s.stops[1]}`" />
            <stop offset="1" :class="`c${s.stops[2]}`" stop-opacity="0" />
          </linearGradient>
        </defs>
        <g v-for="s in nearStrands" :key="s.id">
          <path :d="s.d" :stroke="`url(#${s.id})`" :stroke-width="(s.width * 7).toFixed(1)" opacity=".07" fill="none" />
          <path :d="s.d" :stroke="`url(#${s.id})`" :stroke-width="s.width.toFixed(2)" :opacity="s.opacity" fill="none" stroke-linecap="round" />
          <path
            v-if="s.sparkle"
            :d="s.d"
            class="ns-sparkle"
            :stroke-width="(s.width * 0.35).toFixed(2)"
            fill="none"
            stroke-dasharray="1 14"
            stroke-linecap="round"
          />
        </g>
      </svg>
      <div ref="stageVeil" class="pzi-veil"></div>
    </div>

    <!-- microscope HUD (decorative) -->
    <div class="pzi-hud" aria-hidden="true">
      <div class="pzi-cross" :class="{ live: crossLive && !still }">
        <span ref="crossH" class="cx-h"></span>
        <span ref="crossV" class="cx-v"></span>
        <span ref="crossLabel" class="cx-lbl mono"></span>
      </div>
      <div ref="retWrap" class="pzi-ret">
        <IntroReticle />
        <div class="pzi-ret-lbl mono">
          <span class="pzi-ret-mag">{{ MAGS[stageIdx]!.m }}</span>
          <span class="pzi-scalebar"
            ><i :style="{ width: `${SCALEBAR_PX}px` }"></i><b>{{ MAGS[stageIdx]!.scale }}</b></span
          >
          <small class="pzi-ret-k">总放大倍率 · TOTAL MAG</small>
        </div>
      </div>
      <div class="pzi-analyzer mono">
        <span>ANALYZER</span>
        <div class="an-track"><i ref="anDot" class="an-dot"></i></div>
        <span ref="anValue" class="an-value">90°</span>
      </div>
    </div>

    <header class="pzi-top">
      <span class="pzi-brand">
        <svg class="pzi-pol" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <circle cx="16" cy="16" r="13.5" class="pol-o" />
          <circle cx="16" cy="16" r="9" class="pol-i" />
          <line x1="6" y1="26" x2="26" y2="6" class="pol-l" />
        </svg>
        <span class="brand-word">FiberScope</span><span class="brand-cn">偏光</span>
      </span>
      <ol class="pzi-mags mono" aria-hidden="true">
        <li v-for="(m, i) in MAGS" :key="m.m" :class="{ on: i === stageIdx }">{{ m.m }}</li>
      </ol>
      <div class="pzi-read mono" aria-hidden="true">
        <span>X <b ref="readX">+000.00</b></span>
        <span>Y <b ref="readY">+000.00</b> µm</span>
        <span>θ <i ref="readT">90.0</i>°</span>
      </div>
      <ModeSwitch compact class="pzi-switch" />
      <RouterLink class="button primary pzi-top-cta" to="/">进入工作台</RouterLink>
    </header>

    <main id="main" ref="contentEl" class="pzi-main" tabindex="-1">
      <!-- 10× · hero -->
      <section class="pzi-s pzi-hero" aria-labelledby="pzi-h1">
        <p class="pzi-kicker mono">正交偏光显微 · CROSSED POLARS · OBJ 10×</p>
        <h1 id="pzi-h1" class="pzi-title">
          <span class="t-latin">FiberScope</span>
          <span class="t-cn"><b>植物纤维</b> <i>可视化分析平台</i></span>
        </h1>
        <p class="pzi-lead">
          在正交偏光下，纤维素的双折射让每一根纤维显出干涉色。FiberScope
          把针叶木浆、阔叶木浆与针阔复配浆的实验数据放在同一台“显微镜”下——从打浆、复配、纤维与纸张的关联，到再生纸浆循环与文献证据。
        </p>
        <div class="pzi-cta">
          <RouterLink class="button primary pzi-btn-lg" to="/">进入工作台 <span aria-hidden="true">→</span></RouterLink>
          <button class="button pzi-btn-lg pzi-ghost" type="button" @click="toTree">
            转动检偏器 <span aria-hidden="true">↓</span>
          </button>
        </div>
        <p class="pzi-mini mono" :class="{ 'is-loading': loading }">
          <span>{{ n(stats.samples) }} 个物理样本</span>
          <span>{{ n(stats.indicators) }} 项指标</span>
          <span>{{ n(stats.sourceFiles) }} 个来源文件</span>
        </p>
        <p v-if="loading" class="pzi-state mono" role="status">正在读取实验数据库…</p>
        <div v-else-if="failed" class="pzi-state is-error" role="alert">
          <span>部分数据暂时无法读取：{{ message }}</span>
          <button class="button" type="button" @click="reload">重试</button>
        </div>
      </section>

      <!-- 原木 → 纸浆 -->
      <section
        ref="treeEl"
        class="pzi-s pzi-tree"
        tabindex="-1"
        aria-labelledby="pzi-h2a"
      >
        <div class="pzi-tree-text pzi-scrim">
          <p class="pzi-step mono"><span>01 原木 TREE</span><i aria-hidden="true"></i><span>02 纸浆 PULP</span></p>
          <h2 id="pzi-h2a" class="pzi-h2 pzi-focus"><b>从一棵树</b> <i>到一池纸浆</i></h2>
          <p class="pzi-p">
            针叶木的管胞细长，阔叶木的纤维短而细。原木经蒸煮、漂白成浆，再在打浆机中反复受力——细胞壁润胀、分丝帚化，纤维变得柔顺，纸页中的结合随之改变。
          </p>
          <ul class="pzi-comp" aria-label="全库物理样本组成" :aria-busy="coreStatus === 'loading'">
            <li v-for="c in compositionRows" :key="c.type" :class="`lc-${c.type}`">
              <span class="lc-n">{{ n(c.n) }}</span>
              <span class="lc-l"
                >{{ c.label }}<small v-if="c.range" class="mono">{{ c.range }}</small></span
              >
              <span class="lc-bar" aria-hidden="true"
                ><i :style="{ width: `${(c.share ?? 0).toFixed(1)}%` }"></i
              ></span>
              <span class="lc-p mono">{{ c.share == null ? "—" : `${c.share.toFixed(1)}%` }}</span>
            </li>
          </ul>
          <p class="pzi-note mono">全库 {{ n(stats.samples) }} 个唯一物理样本 · 复配两端复用纯浆样本</p>
        </div>
        <figure ref="eyepiece" class="pzi-eyepiece">
          <div class="ep-img"><img :src="tracheidImage" alt="" decoding="async" loading="lazy" /></div>
          <IntroReticle />
          <figcaption class="mono">针叶木横切面 · 正交偏光下的管胞壁（AI 生成的示意图像）</figcaption>
        </figure>
      </section>

      <!-- 10× → 4000× (pinned) -->
      <section
        ref="magEl"
        class="pzi-mag"
        :class="{ 'no-3d': no3d, 'has-3d': fibrilShown }"
        aria-labelledby="pzi-h2b"
      >
        <div class="pzi-mag-sticky">
          <div ref="plate" class="pzi-plate" aria-hidden="true">
            <img :src="fibrilImage" alt="" decoding="async" loading="lazy" />
          </div>
          <canvas v-show="!no3d" :key="fibrilGen" ref="fibrilCanvas" class="pzi-3d" aria-hidden="true"></canvas>
          <div class="pzi-mag-copy">
            <p class="pzi-step mono">
              <span>03 纤维 FIBRE</span><i aria-hidden="true"></i><span>04 微纤丝 MICROFIBRIL</span>
            </p>
            <h2 id="pzi-h2b" class="pzi-h2 pzi-h2-sm"><b>放大</b> <i>直到看见结构</i></h2>
            <ol class="pzi-caps">
              <li
                v-for="(m, i) in MAGS"
                :key="m.m"
                class="pzi-cap"
                :class="{ on: i === capIdx }"
              >
                <p class="cap-mag">
                  {{ m.m }}<span class="cap-scale mono"> · {{ m.scale }}</span>
                </p>
                <h3 class="cap-t">{{ m.title }}</h3>
                <p class="cap-d">{{ m.text }}</p>
              </li>
            </ol>
          </div>
          <div class="pzi-mag-side">
            <ol class="pzi-ladder mono" aria-hidden="true">
              <li v-for="(m, i) in MAGS" :key="m.m" :class="{ on: i === capIdx, past: i < capIdx }">
                <span>{{ m.m }}</span><i></i><small>{{ m.scale }}</small>
              </li>
            </ol>
            <p class="pzi-3d-note mono">三维示意：S1 / S2 / S3 层微纤丝的螺旋排列（非实测数据）</p>
          </div>
        </div>
      </section>

      <!-- 纸张 → 数据 -->
      <section class="pzi-s pzi-data" aria-labelledby="pzi-h2c">
        <div class="pzi-scrim pzi-data-head">
          <p class="pzi-step mono"><span>05 纸张 PAPER</span><i aria-hidden="true"></i><span>06 数据 DATA</span></p>
          <h2 id="pzi-h2c" class="pzi-h2 pzi-focus"><b>从一张纸</b> <i>到一组可追溯的数据</i></h2>
          <p class="pzi-p pzi-p-wide">
            每一张手抄片都被测量：{{ n(stats.fiberProps) }} 项纤维特性、{{ n(stats.paperProps) }}
            项纸张性能；再生纸浆按数据块与循环逐行记录。平台只展示实测的对应关系，不做拟合与因果推断。
          </p>
        </div>
        <ul class="pzi-kpis" :aria-busy="coreStatus === 'loading'">
          <li class="kpi">
            <span class="kpi-n">{{ n(stats.samples) }}</span>
            <span class="kpi-l">唯一物理样本</span>
            <span class="kpi-s">针叶木、阔叶木与针阔复配</span>
          </li>
          <li class="kpi">
            <span class="kpi-n">{{ n(stats.displayPoints) }}</span>
            <span class="kpi-l">核心实验展示点</span>
            <span class="kpi-s">复配端点复用已有纯浆样本</span>
          </li>
          <li class="kpi">
            <span class="kpi-n">{{ n(stats.recycledObs) }}</span>
            <span class="kpi-l">再生纸浆原始观测</span>
            <span class="kpi-s"
              ><span class="nw">{{ n(stats.recycledBlocks) }} 个数据块</span> ·
              <span class="nw">{{ n(stats.recycledCycles) }} 个循环汇总点</span></span
            >
          </li>
          <li class="kpi">
            <span class="kpi-n">{{ n(stats.indicators) }}</span>
            <span class="kpi-l">已收录指标</span>
            <span class="kpi-s">纤维特性、纸张性能、长度分布</span>
          </li>
        </ul>
        <p class="pzi-mini mono pzi-scrim-tight" :class="{ 'is-loading': loading }">
          <span>{{ n(stats.coreSources) }} 条核心来源行</span>
          <span>{{ n(stats.sourceRows) }} 条来源行</span>
          <span>{{ n(stats.sourceFiles) }} 个来源文件</span>
          <span>图表展示对应关系，不代表因果关系</span>
        </p>
        <div v-if="!loading && failed" class="pzi-state is-error">
          <span>部分数据暂时无法读取，缺失的数字显示为“—”。</span>
          <button class="button" type="button" @click="reload">重试</button>
        </div>
      </section>

      <!-- objective turret → the workspace -->
      <section
        id="pzi-enter"
        ref="enterEl"
        class="pzi-s pzi-enter"
        tabindex="-1"
        aria-labelledby="pzi-h2d"
      >
        <p class="pzi-step mono">
          <span>07 物镜转盘 OBJECTIVES</span><i aria-hidden="true"></i
          ><span>{{ navItems.length }} 个物镜 · 总放大 {{ firstObjective.magnification }}–{{ lastObjective.magnification }}</span>
        </p>
        <div class="pzi-enter-head">
          <h2 id="pzi-h2d" class="pzi-h2"><b>选择物镜</b> <i>进入工作台</i></h2>
          <RouterLink class="button primary pzi-btn-lg" to="/">进入工作台 <span aria-hidden="true">→</span></RouterLink>
        </div>
        <IntroTurret :recycled-blocks="stats.recycledBlocks" />
        <footer class="pzi-foot mono">
          <span>{{ platformName }} · FIBERSCOPE</span>
          <span>数字实时读取自实验数据库 · 显微图像为 AI 生成的示意</span>
        </footer>
      </section>
    </main>
  </div>
</template>

<style scoped>
/* ================================================================ stage (depth planes) */
.pzi {
  /* a dark halo hugging the glyphs: small text stays legible where a strand drifts behind it */
  --pzi-halo: 0 0 2px var(--bg), 0 0 6px var(--bg), 0 1px 14px var(--bg);
  position: relative;
  color: var(--text);
}
.pzi-stage {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background: var(--bg);
  pointer-events: none;
}
.pzi-field {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.pzi-fallback {
  position: absolute;
  inset: 0;
  display: none;
  background:
    radial-gradient(60% 40% at 72% 38%, color-mix(in srgb, var(--bl) 32%, transparent), transparent 70%),
    radial-gradient(45% 35% at 82% 70%, color-mix(in srgb, var(--hw) 26%, transparent), transparent 70%),
    radial-gradient(40% 30% at 58% 62%, color-mix(in srgb, var(--sw) 22%, transparent), transparent 70%),
    radial-gradient(50% 40% at 30% 85%, color-mix(in srgb, var(--rc) 18%, transparent), transparent 70%),
    var(--bg);
}
.pzi-nogl .pzi-field {
  visibility: hidden;
}
.pzi-nogl .pzi-fallback {
  display: block;
}
.pzi-far,
.pzi-img {
  position: absolute;
  inset: -6% -4%;
  will-change: transform, opacity;
  -webkit-mask-image: linear-gradient(90deg, transparent 22%, color-mix(in srgb, black 50%, transparent) 44%, black 64%);
  mask-image: linear-gradient(90deg, transparent 22%, color-mix(in srgb, black 50%, transparent) 44%, black 64%);
}
.pzi-far img,
.pzi-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 70% 50%;
}
.pzi-far {
  filter: blur(16px) saturate(1.3);
  opacity: 0.5;
  mix-blend-mode: screen;
}
.pzi-img {
  mix-blend-mode: screen;
}
.pzi-near {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 160%;
  will-change: transform;
}
.pzi-near .c0 {
  stop-color: var(--sw);
}
.pzi-near .c1 {
  stop-color: var(--bl);
}
.pzi-near .c2 {
  stop-color: var(--rc);
}
.pzi-near .c3 {
  stop-color: var(--hw);
}
.ns-sparkle {
  stroke: var(--text);
  opacity: 0.35;
}
.pzi-veil {
  position: absolute;
  inset: 0;
  background: var(--bg);
  opacity: 0;
}

/* ================================================================ HUD */
.pzi-hud {
  position: fixed;
  inset: 0;
  z-index: 20;
  pointer-events: none;
  overflow: hidden;
}
.pzi-cross {
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity 0.6s;
}
.pzi-cross.live {
  opacity: 1;
}
.cx-h,
.cx-v {
  position: absolute;
  background: color-mix(in srgb, var(--text) 8.5%, transparent);
}
.cx-h {
  left: 0;
  right: 0;
  top: 0;
  height: 1px;
}
.cx-v {
  top: 0;
  bottom: 0;
  left: 0;
  width: 1px;
}
.cx-lbl {
  position: absolute;
  left: 0;
  top: 0;
  font-size: 10.5px;
  color: var(--text-2);
  white-space: nowrap;
  text-shadow: 0 1px 4px var(--bg);
}
.pzi-ret {
  position: absolute;
  left: 66%;
  top: 52%;
  width: min(70vh, 44vw);
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
}
.pzi-ret-lbl {
  position: absolute;
  right: -6%;
  bottom: 4%;
  display: grid;
  gap: 6px;
  justify-items: end;
  padding: 8px 12px 10px;
  border-radius: 12px;
  font-size: 12px;
  color: var(--text);
  background: color-mix(in srgb, var(--bg) 80%, transparent);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  text-shadow: 0 0 3px var(--bg);
}
.pzi-ret-mag {
  font-family: var(--font-display);
  font-weight: 200;
  font-size: 34px;
  letter-spacing: -0.02em;
}
.pzi-ret-k {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--text-2);
}
.pzi-scalebar {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.pzi-scalebar i {
  position: relative;
  height: 2px;
  background: var(--text);
}
.pzi-scalebar i::before,
.pzi-scalebar i::after {
  content: "";
  position: absolute;
  top: -4px;
  width: 1px;
  height: 10px;
  background: var(--text);
}
.pzi-scalebar i::before {
  left: 0;
}
.pzi-scalebar i::after {
  right: 0;
}
.pzi-scalebar b {
  font-weight: 400;
}
.pzi-analyzer {
  position: absolute;
  left: clamp(14px, 2vw, 28px);
  top: 50%;
  transform: translateY(-50%);
  display: grid;
  justify-items: center;
  gap: 10px;
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.14em;
}
.pzi-analyzer > span:first-child {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
}
.an-track {
  position: relative;
  width: 1px;
  height: 180px;
  background: linear-gradient(180deg, var(--sw), var(--bl), var(--rc), var(--hw));
  opacity: 0.8;
}
.an-dot {
  position: absolute;
  left: -4px;
  top: -4px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--text);
  box-shadow: 0 0 12px color-mix(in srgb, var(--text) 70%, transparent);
}
.an-value {
  color: var(--text-2);
  font-size: 11px;
  letter-spacing: 0;
}

/* ================================================================ top bar */
.pzi-top {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 30;
  height: 64px;
  padding: 0 clamp(16px, 3vw, 36px);
  display: flex;
  align-items: center;
  gap: 20px;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  backdrop-filter: blur(14px) saturate(120%);
}
.pzi-top::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line) 18%, var(--line) 82%, transparent);
}
.pzi-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text);
  min-width: 0;
}
.pzi-pol {
  width: 28px;
  height: 28px;
}
.pol-o {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.2;
  opacity: 0.55;
}
.pol-i {
  fill: none;
  stroke: var(--bl);
  stroke-width: 2;
}
.pol-l {
  stroke: currentColor;
  stroke-width: 1.2;
}
.brand-word {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 15px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.brand-cn {
  font-weight: 200;
  font-size: 15px;
  color: var(--text-2);
  padding-left: 10px;
  border-left: 1px solid var(--line-strong);
}
.pzi-mags {
  list-style: none;
  margin: 0 auto;
  padding: 0;
  display: flex;
  gap: 4px;
}
.pzi-mags li {
  font-size: 12px;
  color: var(--text-3);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  transition:
    color 0.3s,
    border-color 0.3s,
    background 0.3s;
}
.pzi-mags li.on {
  color: var(--text);
  border-color: var(--line-strong);
  background: color-mix(in srgb, var(--text) 5%, transparent);
}
.pzi-read {
  display: flex;
  gap: 14px;
  font-size: 11.5px;
  color: var(--text-3);
}
.pzi-read b {
  color: var(--text-2);
  font-weight: 400;
  display: inline-block;
  min-width: 7ch;
}
.pzi-read i {
  font-style: normal;
  color: var(--text-2);
}
.pzi-switch {
  flex: none;
}
.pzi-top-cta {
  flex: none;
  min-height: 34px;
  padding: 0 14px;
  font-size: 13px;
}

/* ================================================================ scroll story */
.pzi-main {
  position: relative;
  z-index: 10;
  /* soft scrims may bleed past a column; never past the page (clip keeps sticky working) */
  overflow-x: clip;
}
.pzi-s {
  position: relative;
  min-height: 100vh;
  min-height: 100svh;
  padding: 120px clamp(20px, 7vw, 120px) 80px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.pzi-s:focus-visible {
  outline: none;
}
.pzi-btn-lg {
  min-height: 50px;
  padding: 0 26px;
  font-size: 16px;
}
.pzi-ghost {
  color: var(--text);
  background: transparent;
}

/* hero */
.pzi-hero {
  padding-left: clamp(20px, 8vw, 140px);
}
.pzi-hero > * {
  position: relative;
  max-width: 660px;
}
.pzi-hero::before {
  content: "";
  position: absolute;
  left: -10%;
  top: 10%;
  width: 72%;
  height: 85%;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--bg) 84%, transparent),
    color-mix(in srgb, var(--bg) 55%, transparent) 60%,
    transparent
  );
  pointer-events: none;
}
.pzi-kicker {
  margin: 0 0 22px;
  font-size: 12px;
  letter-spacing: 0.14em;
  color: var(--text-2);
  text-shadow: var(--pzi-halo);
}
.pzi-title {
  display: grid;
  gap: 10px;
  margin: 0 0 28px;
  max-width: none;
  font-weight: 400;
}
.t-latin {
  font-family: var(--font-display);
  font-weight: 200;
  font-size: clamp(54px, 9.4vw, 150px);
  line-height: 0.88;
  letter-spacing: -0.035em;
}
.t-cn {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 0.25em;
  font-family: var(--font-display-cn);
  font-size: clamp(30px, 4.3vw, 64px);
  line-height: 1.15;
}
.t-cn b {
  font-weight: 900;
  letter-spacing: 0.02em;
}
.t-cn i {
  font-style: normal;
  font-weight: 200;
  letter-spacing: 0.04em;
}
.pzi-lead {
  margin: 0;
  font-size: clamp(15px, 1.25vw, 17.5px);
  line-height: 1.85;
  font-weight: 300;
  color: color-mix(in srgb, var(--text) 60%, var(--text-2));
  text-shadow: var(--pzi-halo);
}
.pzi-cta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 34px;
}
.pzi-mini {
  position: relative;
  isolation: isolate;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 22px;
  margin: 40px 0 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 70%, var(--text-2));
  /* a near strand may drift behind the line */
  text-shadow: var(--pzi-halo);
}
/* a local dark field under the line (a near strand may cross it) */
.pzi-mini::before {
  content: "";
  position: absolute;
  inset: -16px -28px;
  z-index: -1;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--bg) 82%, transparent),
    color-mix(in srgb, var(--bg) 55%, transparent) 70%,
    transparent
  );
  pointer-events: none;
}
.pzi-mini span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.pzi-mini span::before {
  content: "";
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--bl);
}
.pzi-mini.is-loading span {
  color: var(--text-3);
}
.pzi-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin: 14px 0 0;
  font-size: 12.5px;
  color: var(--text-2);
}
.pzi-state.is-error {
  color: var(--review);
  font-family: var(--font-body);
}
.pzi-state .button {
  min-height: 32px;
  font-size: 13px;
}

/* shared section typography */
.pzi-step {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 0 0 18px;
  font-size: 11.5px;
  letter-spacing: 0.14em;
  color: var(--text-2);
  text-shadow: var(--pzi-halo);
}
.pzi-step i {
  width: 56px;
  height: 1px;
  background: var(--ifl);
}
.pzi-h2 {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 0.3em;
  margin: 0 0 22px;
  font-family: var(--font-display-cn);
  font-size: clamp(32px, 4.6vw, 68px);
  line-height: 1.12;
}
.pzi-h2 b {
  font-weight: 900;
}
.pzi-h2 i {
  font-style: normal;
  font-weight: 200;
}
.pzi-h2-sm {
  font-size: clamp(26px, 3.2vw, 46px);
}
.pzi-p {
  max-width: 560px;
  margin: 0;
  font-size: 16px;
  line-height: 1.9;
  font-weight: 300;
  color: color-mix(in srgb, var(--text) 60%, var(--text-2));
  text-shadow: 0 1px 16px var(--bg);
}
.pzi-p-wide {
  max-width: 760px;
}
.pzi-note {
  margin: 16px 0 0;
  font-size: 11.5px;
  color: var(--text-2);
  text-shadow: var(--pzi-halo);
}
/* a soft dark field behind a text column keeps small text legible over the shader */
.pzi-scrim {
  position: relative;
  isolation: isolate;
}
.pzi-scrim::before {
  content: "";
  position: absolute;
  inset: -12% -14% -12% -18%;
  z-index: -1;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--bg) 78%, transparent),
    color-mix(in srgb, var(--bg) 48%, transparent) 65%,
    transparent
  );
  pointer-events: none;
}
/* headings pull into focus as they scroll in ("change objective = refocus") */
@supports (animation-timeline: view()) {
  .pzi-focus {
    animation: pzi-refocus linear both;
    animation-timeline: view();
    animation-range: entry 10% cover 32%;
  }
  @keyframes pzi-refocus {
    from {
      filter: blur(8px);
      opacity: 0.35;
      transform: translateY(14px);
    }
    to {
      filter: none;
      opacity: 1;
      transform: none;
    }
  }
}

/* tree → pulp */
.pzi-tree {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 0.9fr);
  align-items: center;
  gap: clamp(28px, 6vw, 100px);
}
.pzi-comp {
  list-style: none;
  margin: 30px 0 0;
  padding: 0;
  display: grid;
  gap: 14px;
  max-width: 520px;
}
.pzi-comp li {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 54px;
  grid-template-rows: auto auto;
  column-gap: 14px;
  align-items: end;
}
.lc-n {
  grid-column: 1;
  grid-row: 1 / 3;
  font-family: var(--font-display);
  font-weight: 200;
  font-size: 52px;
  line-height: 0.9;
  font-variant-numeric: tabular-nums;
}
.lc-l {
  grid-column: 2;
  grid-row: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  font-size: 15px;
  font-weight: 500;
}
.lc-l small {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
}
.lc-p {
  grid-column: 3;
  grid-row: 1;
  font-size: 12px;
  color: var(--text-2);
  text-align: right;
}
.lc-bar {
  grid-column: 2 / 4;
  grid-row: 2;
  height: 3px;
  margin-top: 8px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
.lc-bar i {
  display: block;
  height: 100%;
  border-radius: 2px;
  transition: width 0.8s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.lc-softwood .lc-n {
  color: var(--sw-ink);
}
.lc-hardwood .lc-n {
  color: var(--hw-ink);
}
.lc-blend .lc-n {
  color: var(--bl-ink);
}
.lc-softwood .lc-bar i {
  background: var(--sw);
}
.lc-hardwood .lc-bar i {
  background: var(--hw);
}
.lc-blend .lc-bar i {
  background: var(--bl);
}
.pzi-eyepiece {
  position: relative;
  margin: 0;
  width: min(100%, 520px);
  aspect-ratio: 1;
  justify-self: center;
  will-change: transform;
}
.ep-img {
  position: absolute;
  inset: 6%;
  border-radius: 50%;
  overflow: hidden;
  background:
    radial-gradient(circle at 40% 40%, color-mix(in srgb, var(--sw) 35%, transparent), transparent 40%),
    radial-gradient(circle at 65% 60%, color-mix(in srgb, var(--hw) 35%, transparent), transparent 45%),
    radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--bl) 25%, transparent), var(--bg) 72%);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--text) 12%, transparent),
    0 0 120px -20px color-mix(in srgb, var(--bl) 35%, transparent);
}
.ep-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.pzi-eyepiece .pzi-reticle {
  position: absolute;
  inset: 0;
}
.pzi-eyepiece figcaption {
  position: absolute;
  left: 50%;
  bottom: -34px;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-2);
  text-shadow: var(--pzi-halo);
}

/* magnification: pinned while the story zooms 10× → 4000× */
.pzi-mag {
  position: relative;
  height: 420vh;
}
.pzi-mag-sticky {
  position: sticky;
  top: 0;
  height: 100vh;
  height: 100svh;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(180deg, black 0, black 88%, transparent);
  mask-image: linear-gradient(180deg, black 0, black 88%, transparent);
}
/* the plate is the 10× / 40× subject; it zooms with the story and cross-fades to the 3D helix */
.pzi-plate {
  position: absolute;
  inset: -4%;
  opacity: 0.5;
  mix-blend-mode: screen;
  transform: scale(calc(1.04 + var(--pm, 0) * 1.1));
  transition: opacity 0.35s;
  -webkit-mask-image: linear-gradient(180deg, transparent, black 16%, black 78%, transparent);
  mask-image: linear-gradient(180deg, transparent, black 16%, black 78%, transparent);
}
.pzi-plate img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.pzi-3d {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  opacity: 0;
  transition: opacity 0.6s;
}
.has-3d .pzi-3d {
  opacity: 1;
}
.pzi-mag-sticky::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: 0;
  z-index: 1;
  width: 70%;
  height: 70%;
  background: radial-gradient(
    ellipse at 0% 100%,
    color-mix(in srgb, var(--bg) 92%, transparent),
    color-mix(in srgb, var(--bg) 62%, transparent) 45%,
    transparent 72%
  );
  pointer-events: none;
}
.pzi-mag-copy {
  position: absolute;
  z-index: 2;
  left: clamp(20px, 7vw, 120px);
  bottom: clamp(40px, 10vh, 110px);
  width: min(480px, calc(100% - 40px));
}
/* a dark field right behind the copy: the step line and captions stay legible over the brightest strands */
.pzi-mag-copy::before {
  content: "";
  position: absolute;
  inset: -18% -26% -16% -34%;
  z-index: -1;
  background: radial-gradient(
    closest-side,
    color-mix(in srgb, var(--bg) 88%, transparent),
    color-mix(in srgb, var(--bg) 66%, transparent) 62%,
    transparent
  );
  pointer-events: none;
}
.pzi-caps {
  position: relative;
  list-style: none;
  margin: 0;
  padding: 0;
  min-height: 250px;
}
.pzi-cap {
  position: absolute;
  inset: 0 auto auto 0;
  opacity: 0;
  transform: translateY(18px);
  transition:
    opacity 0.5s,
    transform 0.5s;
}
.pzi-cap.on {
  opacity: 1;
  transform: none;
}
.cap-mag {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 200;
  font-size: clamp(64px, 8vw, 120px);
  line-height: 0.9;
  letter-spacing: -0.04em;
  background: var(--ifl);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.cap-scale {
  display: none;
}
.cap-t {
  margin: 10px 0 8px;
  font-size: 22px;
  font-weight: 900;
  color: var(--text);
}
.cap-d {
  margin: 0;
  font-size: 15px;
  line-height: 1.85;
  font-weight: 300;
  color: color-mix(in srgb, var(--text) 60%, var(--text-2));
  text-shadow: var(--pzi-halo);
}
.pzi-mag-side {
  position: absolute;
  z-index: 2;
  right: clamp(20px, 5vw, 80px);
  bottom: clamp(116px, 17vh, 168px);
  display: grid;
  gap: 22px;
  justify-items: end;
  padding: 18px 18px 16px;
  border-radius: 14px;
  border: 1px solid var(--line-soft);
  /* dark glass: the readouts stay legible over the brightest strands */
  background: color-mix(in srgb, var(--bg) 78%, transparent);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
.pzi-ladder {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 20px;
  font-size: 12px;
  color: var(--text-3);
}
.pzi-ladder li {
  display: grid;
  grid-template-columns: 56px 40px auto;
  align-items: center;
  gap: 10px;
  transition: color 0.3s;
}
.pzi-ladder li i {
  height: 1px;
  background: currentColor;
  opacity: 0.5;
}
.pzi-ladder li small {
  font-size: 10.5px;
}
.pzi-ladder li.on {
  color: var(--text);
}
.pzi-ladder li.on i {
  height: 2px;
  background: var(--ifl);
  opacity: 1;
}
.pzi-ladder li.past {
  color: var(--text-2);
}
.pzi-3d-note {
  max-width: 280px;
  margin: 0;
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
  text-align: right;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-2);
}

/* no motion / no WebGL: the four magnifications as a plain, fully readable list */
.pzi-mag.no-3d {
  height: auto;
}
.no-3d .pzi-mag-sticky {
  position: relative;
  height: auto;
  min-height: 100vh;
  padding: 120px clamp(20px, 7vw, 120px) 80px;
  -webkit-mask-image: none;
  mask-image: none;
}
.no-3d .pzi-plate {
  opacity: 0.42;
  transform: none;
}
.no-3d .pzi-mag-sticky::after {
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, color-mix(in srgb, var(--bg) 88%, transparent) 30%, color-mix(in srgb, var(--bg) 40%, transparent));
}
.no-3d .pzi-mag-copy::before {
  display: none;
}
.no-3d .pzi-mag-copy {
  position: relative;
  left: auto;
  bottom: auto;
  width: auto;
  max-width: 1100px;
}
.no-3d .pzi-caps {
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px 48px;
  margin-top: 12px;
}
.no-3d .pzi-cap {
  position: relative;
  inset: auto;
  opacity: 1;
  transform: none;
}
.no-3d .cap-mag {
  font-size: 48px;
}
.no-3d .cap-scale {
  display: inline;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--text-2);
  -webkit-text-fill-color: var(--text-2);
}
.no-3d .pzi-ladder {
  display: none;
}
.no-3d .pzi-mag-side {
  position: relative;
  right: auto;
  bottom: auto;
  justify-items: start;
  margin-top: 28px;
  padding: 0;
  border: 0;
  background: none;
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
}
.no-3d .pzi-3d-note {
  max-width: none;
  padding-top: 0;
  border-top: 0;
  text-align: left;
}

/* data */
.pzi-kpis {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 50px 0 0;
  padding: 0;
  border-top: 1px solid var(--line);
}
.kpi {
  display: grid;
  align-content: start;
  min-width: 0;
  padding: 26px 28px 10px;
  border-right: 1px solid var(--line-soft);
  background: linear-gradient(180deg, color-mix(in srgb, var(--bg) 55%, transparent), transparent);
}
.kpi:first-child {
  padding-left: 0;
}
.kpi:last-child {
  border-right: 0;
}
.kpi-n {
  font-family: var(--font-display);
  font-weight: 200;
  font-size: clamp(56px, 7vw, 104px);
  line-height: 0.95;
  letter-spacing: -0.05em;
  font-variant-numeric: tabular-nums;
}
.kpi:nth-child(1) .kpi-n {
  text-shadow: 0 0 60px color-mix(in srgb, var(--sw) 35%, transparent);
}
.kpi:nth-child(2) .kpi-n {
  text-shadow: 0 0 60px color-mix(in srgb, var(--bl) 35%, transparent);
}
.kpi:nth-child(3) .kpi-n {
  text-shadow: 0 0 60px color-mix(in srgb, var(--rc) 45%, transparent);
}
.kpi:nth-child(4) .kpi-n {
  text-shadow: 0 0 60px color-mix(in srgb, var(--hw) 35%, transparent);
}
.kpi-l {
  margin-top: 12px;
  font-size: 16px;
  font-weight: 700;
}
.kpi-s {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--text-2);
}
.nw {
  white-space: nowrap;
}
.pzi-data-head {
  max-width: 860px;
}
.pzi-data .pzi-mini {
  margin-top: 34px;
}

/* enter */
.pzi-enter {
  min-height: 110vh;
  justify-content: flex-start;
  padding-top: 110px;
}
.pzi-enter-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 24px;
}
.pzi-enter-head .pzi-h2 {
  margin: 0;
}
.pzi-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  margin-top: 80px;
  padding-top: 18px;
  border-top: 1px solid var(--line-soft);
  font-size: 11px;
  color: var(--text-2);
}

/* ================================================================ reduced motion: still frames */
/* the stage and HUD belong to the hero and scroll away with it; nothing follows scroll or pointer */
.pzi-still .pzi-stage,
.pzi-still .pzi-hud {
  position: absolute;
  inset: 0 0 auto 0;
  height: 100vh;
  height: 100svh;
}
.pzi-still .pzi-stage {
  -webkit-mask-image: linear-gradient(180deg, black 70%, transparent);
  mask-image: linear-gradient(180deg, black 70%, transparent);
}
.pzi-still .pzi-cross,
.pzi-still .pzi-analyzer {
  display: none;
}
.pzi-still .pzi-far,
.pzi-still .pzi-img,
.pzi-still .pzi-near,
.pzi-still .pzi-eyepiece {
  will-change: auto;
}

/* ================================================================ responsive */
@media (max-width: 1100px) {
  .pzi-read {
    display: none;
  }
}
@media (max-width: 860px) {
  .pzi-mags,
  .pzi-analyzer,
  .pzi-cross {
    display: none;
  }
  .pzi-top {
    gap: 12px;
  }
  .pzi-brand {
    margin-right: auto;
  }
  .pzi-tree {
    grid-template-columns: 1fr;
    padding-top: 100px;
  }
  .pzi-eyepiece {
    width: min(86vw, 420px);
    margin-top: 20px;
    margin-bottom: 40px;
  }
  .pzi-ret {
    left: 60%;
    top: 30%;
    width: 72vw;
    opacity: 0.5;
  }
  .pzi-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .kpi {
    padding: 20px 12px 14px 0;
    border-right: 0;
    border-bottom: 1px solid var(--line-soft);
  }
  .pzi-mag-side {
    top: 80px;
    bottom: auto;
    right: 16px;
    gap: 10px;
  }
  .pzi-ladder {
    gap: 8px;
    font-size: 10.5px;
  }
  .pzi-ladder li {
    grid-template-columns: 44px 18px auto;
  }
  .pzi-3d-note {
    max-width: 220px;
    font-size: 11px;
  }
  .no-3d .pzi-caps {
    grid-template-columns: 1fr;
  }
  .pzi-enter-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
@media (max-width: 720px) {
  .pzi-top {
    height: 56px;
    padding: 0 16px;
  }
  .pzi-top-cta {
    min-height: 32px;
    padding: 0 12px;
  }
  .pzi-s {
    padding: 96px 18px 64px;
  }
  .pzi-p {
    font-size: 15px;
  }
  .pzi-mag-copy {
    left: 18px;
    width: calc(100% - 36px);
    bottom: 48px;
  }
  .pzi-mag-copy::before {
    inset: -64px -18px -48px;
    background: linear-gradient(
      180deg,
      transparent,
      color-mix(in srgb, var(--bg) 84%, transparent) 64px,
      color-mix(in srgb, var(--bg) 92%, transparent)
    );
  }
  /* phones: the ladder becomes one strip of four objectives under the top bar */
  .pzi-mag-side {
    top: 68px;
    left: 16px;
    right: 16px;
    justify-items: stretch;
    gap: 10px;
    padding: 12px 14px 10px;
  }
  .pzi-ladder {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }
  .pzi-ladder li {
    grid-template-columns: none;
    justify-items: start;
    gap: 5px;
  }
  .pzi-ladder li i {
    width: 100%;
  }
  .pzi-ladder li small {
    display: block;
    font-size: 10px;
  }
  .pzi-3d-note {
    max-width: none;
    padding-top: 9px;
    text-align: left;
    font-size: 10.5px;
  }
  .no-3d .pzi-mag-sticky {
    padding: 96px 18px 64px;
  }
  .no-3d .pzi-mag-copy {
    left: auto;
    width: auto;
  }
  .pzi-enter {
    padding-top: 96px;
  }
}
@media (max-width: 560px) {
  .brand-cn {
    display: none;
  }
  .brand-word {
    font-size: 13px;
  }
  .pzi-pol {
    width: 24px;
    height: 24px;
  }
  .pzi-hero {
    justify-content: flex-end;
    padding-bottom: 72px;
  }
  .pzi-hero::before {
    left: 0;
    right: 0;
    width: auto;
    top: auto;
    bottom: 0;
    height: 78%;
    background: linear-gradient(
      180deg,
      transparent,
      color-mix(in srgb, var(--bg) 86%, transparent) 30%,
      color-mix(in srgb, var(--bg) 92%, transparent)
    );
  }
  .pzi-far,
  .pzi-img {
    -webkit-mask-image: linear-gradient(180deg, black 12%, color-mix(in srgb, black 35%, transparent) 42%, transparent 62%);
    mask-image: linear-gradient(180deg, black 12%, color-mix(in srgb, black 35%, transparent) 42%, transparent 62%);
  }
  .pzi-ret {
    top: 26%;
  }
  .pzi-ret-lbl {
    display: none;
  }
  .pzi-cta .button {
    flex: 1 1 auto;
  }
  .pzi-comp li {
    grid-template-columns: 56px minmax(0, 1fr) 46px;
    column-gap: 10px;
  }
  .lc-n {
    font-size: 40px;
  }
  .pzi-eyepiece figcaption {
    white-space: normal;
    width: 100%;
    text-align: center;
  }
  .kpi-n {
    font-size: 52px;
  }
  .kpi-l {
    font-size: 15px;
  }
  .pzi-foot {
    margin-top: 56px;
  }
}
@media (hover: none) {
  .pzi-cross {
    display: none;
  }
}
</style>
