<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { useRoute } from "vue-router";
import { X } from "lucide-vue-next";
import ModeSwitch from "../ModeSwitch.vue";
import AmbientPolarized from "../ambient/AmbientPolarized.vue";
import { navItemFor, navItems, introItem } from "../../nav";
import { reducedMotion } from "../../mode";

/*
 * 「偏光」 workspace chrome (v1): microscope HUD on top, objective turret on the left.
 * Below 720px the turret becomes a bottom sheet opened from a floating objective pill;
 * App.vue owns the open state, focus trap and Escape handling.
 */
const props = defineProps<{ navOpen: boolean }>();
const emit = defineEmits<{ "update:navOpen": [value: boolean]; about: [] }>();

const route = useRoute();
const current = computed(() => navItemFor(route.path) ?? navItems[0]!);
const activeIndex = computed(() => navItems.indexOf(current.value));

const drawer = ref<HTMLElement>();
const toggle = ref<HTMLButtonElement>();
defineExpose({ drawer, toggle });

function closeNav() {
  if (props.navOpen) emit("update:navOpen", false);
}

/* ---------------------------------------------------------------- stage: pointer, scroll, analyzer */
const pointer = reactive({
  x: window.innerWidth / 2,
  y: window.innerHeight / 2,
  w: window.innerWidth,
  h: window.innerHeight,
});
const scrollY = ref(window.scrollY);
const phase = ref(0);
const sweep = ref(0);
let frameRaf = 0,
  sweepRaf = 0,
  lastPhaseStep = -1;

function frame() {
  frameRaf = 0;
  scrollY.value = window.scrollY;
  const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  phase.value = Math.min(1, Math.max(0, window.scrollY / max));
  // card / lens interference edges turn with the analyzer (quantised: one style pass per step)
  const step = reducedMotion.value ? 0 : Math.round(phase.value * 40);
  if (step !== lastPhaseStep) {
    lastPhaseStep = step;
    document.documentElement.style.setProperty("--phase", (step / 40).toFixed(3));
  }
}
function schedule() {
  if (!frameRaf) frameRaf = requestAnimationFrame(frame);
}
function onPointer(event: PointerEvent) {
  pointer.x = event.clientX;
  pointer.y = event.clientY;
  schedule();
}
function onResize() {
  pointer.w = window.innerWidth;
  pointer.h = window.innerHeight;
  schedule();
}
const stageX = computed(() => (pointer.x / pointer.w - 0.5) * 2);
const stageY = computed(() => (pointer.y / pointer.h - 0.5) * 2);

/*
 * A route change rotates the analyzer ("change objective = refocus"): the band's colours
 * swing through the interference sequence and every interference edge (cards, lenses,
 * primary buttons: --ifc / --ifl in style.css) turns with it through --sweep.
 * --sweep is quantised to 5° steps so the whole document restyles at most ~40 times.
 */
let lastSweepStep = -1;
function writeSweep(value: number) {
  const step = Math.round((value * 200) / 5);
  if (step === lastSweepStep) return;
  lastSweepStep = step;
  document.documentElement.style.setProperty("--sweep", `${step * 5}deg`);
}
function analyzerSweep() {
  cancelAnimationFrame(sweepRaf);
  if (reducedMotion.value) {
    sweep.value = 0;
    writeSweep(0);
    return;
  }
  const t0 = performance.now(),
    duration = 1100;
  const step = (now: number) => {
    const k = Math.min(1, (now - t0) / duration);
    sweep.value = Math.pow(1 - k, 3);
    writeSweep(sweep.value);
    if (k < 1) sweepRaf = requestAnimationFrame(step);
  };
  sweepRaf = requestAnimationFrame(step);
}
watch(reducedMotion, (value) => {
  if (!value) return;
  cancelAnimationFrame(sweepRaf);
  sweep.value = 0;
  writeSweep(0);
});
watch(
  () => route.path,
  () => {
    analyzerSweep();
    schedule();
  },
);

/* ---------------------------------------------------------------- HUD readouts (decorative) */
// one calibration: the 64 px scale bar spans 200 µm at 10×, so µm per px = 31.25 / magnification
const SCALEBAR_PX = 64;
const magnification = computed(() => parseFloat(current.value.magnification) || 10);
const umPerPx = computed(() => 31.25 / magnification.value);
const signed = (v: number) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).padStart(6, "0");
const hudX = computed(() => signed((pointer.x - pointer.w / 2) * umPerPx.value));
const hudY = computed(() => signed((pointer.h / 2 - pointer.y) * umPerPx.value));
const scaleLabel = computed(() => {
  const v = SCALEBAR_PX * umPerPx.value;
  return (v >= 1 ? String(Math.round(v * 10) / 10) : String(+v.toPrecision(2))) + " µm";
});
// under reduced motion the analyzer stays crossed (90°): nothing turns with scroll
const theta = computed(() =>
  reducedMotion.value ? "90.0" : (90 - 32 * phase.value + sweep.value * 90).toFixed(1),
);

/* ---------------------------------------------------------------- turret geometry */
const turretHeight = ref(800);
let turretObserver: ResizeObserver | undefined;
const turret = computed(() => {
  const n = navItems.length;
  const H = turretHeight.value;
  const gap = Math.max(46, Math.min(66, (H - 150) / n));
  const R = 680,
    baseX = 84;
  const cy = 40 + (gap * (n - 1)) / 2 + 20;
  const points = navItems.map((_, i) => {
    const angle = ((i - (n - 1) / 2) * gap) / R;
    return { x: baseX - R * (1 - Math.cos(angle)), y: cy + R * Math.sin(angle) };
  });
  const RR = R + 34,
    size = RR * 2 + 20,
    c = size / 2;
  let shortTicks = "",
    longTicks = "";
  for (let k = 0; k < 360; k += 2) {
    const a = (k * Math.PI) / 180,
      long = k % 10 === 0;
    const r1 = RR - (long ? 12 : 6);
    const seg = `M${(c + r1 * Math.cos(a)).toFixed(1)} ${(c + r1 * Math.sin(a)).toFixed(1)}L${(c + RR * Math.cos(a)).toFixed(1)} ${(c + RR * Math.sin(a)).toFixed(1)}`;
    if (long) longTicks += seg;
    else shortTicks += seg;
  }
  return {
    points,
    R,
    size,
    c,
    left: baseX - R - RR - 10,
    top: cy - RR - 10,
    shortTicks,
    longTicks,
    minHeight: cy + R * Math.sin(((n - 1) / 2) * gap / R) + 70,
  };
});
const activeY = computed(() => turret.value.points[activeIndex.value]?.y ?? 0);
const ringTurn = computed(
  () => activeIndex.value * 9 + (reducedMotion.value ? 0 : phase.value * 40),
);
// the beam leaves the active lens and runs into the content (it lives outside the clipped
// turret, so it follows the turret's own scroll when the viewport is short)
const turretScroll = ref(0);
function onTurretScroll() {
  turretScroll.value = drawer.value?.scrollTop ?? 0;
}

onMounted(() => {
  window.addEventListener("pointermove", onPointer, { passive: true });
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", onResize, { passive: true });
  drawer.value?.addEventListener("scroll", onTurretScroll, { passive: true });
  if (drawer.value) {
    turretHeight.value = drawer.value.clientHeight || 800;
    turretObserver = new ResizeObserver(() => {
      if (drawer.value?.clientHeight) turretHeight.value = drawer.value.clientHeight;
    });
    turretObserver.observe(drawer.value);
  }
  frame();
  analyzerSweep();
});
onBeforeUnmount(() => {
  window.removeEventListener("pointermove", onPointer);
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("resize", onResize);
  cancelAnimationFrame(frameRaf);
  cancelAnimationFrame(sweepRaf);
  turretObserver?.disconnect();
  drawer.value?.removeEventListener("scroll", onTurretScroll);
  document.documentElement.style.removeProperty("--phase");
  document.documentElement.style.removeProperty("--sweep");
});
</script>

<template>
  <AmbientPolarized
    :phase="phase"
    :sweep="sweep"
    :stage-x="stageX"
    :stage-y="stageY"
    :retardation="current.retardation"
    :scroll-y="scrollY"
  />
  <header class="pz-top">
    <RouterLink class="pz-brand" to="/" aria-label="FiberScope 偏光 · 数据总览">
      <svg class="pz-pol" viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="pz-ifg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#F2C14E" />
            <stop offset=".4" stop-color="#E0479E" />
            <stop offset=".7" stop-color="#5B5BD6" />
            <stop offset="1" stop-color="#2EC4D6" />
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="13.5" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".55" />
        <circle cx="16" cy="16" r="9" fill="none" stroke="url(#pz-ifg)" stroke-width="2" />
        <line x1="6" y1="26" x2="26" y2="6" stroke="currentColor" stroke-width="1.2" />
      </svg>
      <span class="pz-brand-word">FiberScope</span><span class="pz-brand-cn">偏光</span>
    </RouterLink>
    <div class="pz-crumb">
      <span class="pz-k mono" title="总放大倍率" aria-hidden="true">TOTAL</span>
      <span class="sr-only">总放大倍率</span>
      <b class="pz-mag mono">{{ current.magnification }}</b>
      <span class="pz-sep" aria-hidden="true">/</span>
      <span class="pz-group">{{ current.group }}</span>
      <span class="pz-sep pz-sep-page" aria-hidden="true">/</span>
      <span class="pz-page">{{ current.label }}</span>
    </div>
    <div class="pz-read mono" aria-hidden="true">
      <span>X <b>{{ hudX }}</b></span>
      <span>Y <b>{{ hudY }}</b></span>
      <span class="pz-unit">µm</span>
      <span class="pz-scale"><i :style="{ width: `${SCALEBAR_PX}px` }"></i><b>{{ scaleLabel }}</b></span>
      <span>θ {{ theta }}°</span>
    </div>
    <button class="pz-about" type="button" aria-haspopup="dialog" @click="emit('about')">数据说明</button>
    <ModeSwitch class="pz-switch" compact />
  </header>

  <div
    class="pz-beam"
    aria-hidden="true"
    :style="{ transform: `translateY(${activeY - turretScroll}px)` }"
  ></div>
  <button
    v-if="navOpen"
    class="pz-scrim"
    type="button"
    aria-label="关闭导航"
    tabindex="-1"
    @click="closeNav"
  ></button>
  <nav
    id="pz-turret"
    ref="drawer"
    class="pz-turret"
    :class="{ open: navOpen }"
    aria-label="主导航 · 物镜转盘"
    :style="{ '--turret-min': `${turret.minHeight}px` }"
  >
    <div class="pz-turret-stage">
      <svg
        class="pz-ring"
        aria-hidden="true"
        :viewBox="`0 0 ${turret.size} ${turret.size}`"
        :style="{
          width: `${turret.size}px`,
          height: `${turret.size}px`,
          left: `${turret.left}px`,
          top: `${turret.top}px`,
        }"
      >
        <g
          class="pz-ring-rot"
          :style="{
            transformOrigin: `${turret.c}px ${turret.c}px`,
            transform: `rotate(${ringTurn}deg)`,
          }"
        >
          <path class="pz-tk" :d="turret.shortTicks" />
          <path class="pz-tk-l" :d="turret.longTicks" />
        </g>
        <circle :cx="turret.c" :cy="turret.c" :r="turret.R" class="pz-arc" />
        <circle :cx="turret.c" :cy="turret.c" :r="turret.R - 30" class="pz-arc2" />
      </svg>
    </div>
    <div class="pz-sheet-head">
      <span class="mono">OBJECTIVE TURRET · 物镜转盘 · 总放大倍率</span>
      <button
        class="pz-close"
        type="button"
        aria-label="关闭导航"
        @click="closeNav"
      >
        <X :size="18" />
      </button>
    </div>
    <ol class="pz-list">
      <li v-for="(item, i) in navItems" :key="item.path">
        <RouterLink
          :to="item.path"
          class="pz-obj"
          :class="{ on: i === activeIndex }"
          :aria-current="i === activeIndex ? 'page' : undefined"
          :title="`${item.group} · ${item.label}`"
          :style="{
            '--x': `${turret.points[i]!.x.toFixed(1)}px`,
            '--y': `${turret.points[i]!.y.toFixed(1)}px`,
          }"
          @click="closeNav"
        >
          <span class="pz-lens" aria-hidden="true"
            ><span class="pz-lens-mag mono">{{ item.magnification }}</span></span
          >
          <span class="pz-obj-label">
            <span class="pz-obj-n mono"
              >{{ item.index }}<span class="pz-obj-g"> · {{ item.group }}</span></span
            >
            <span class="pz-obj-cn">{{ item.label }}</span>
          </span>
        </RouterLink>
      </li>
    </ol>
    <RouterLink class="pz-intro" :to="introItem.path" @click="closeNav"
      ><span aria-hidden="true">←</span> {{ introItem.label }}</RouterLink
    >
  </nav>

  <button
    ref="toggle"
    class="pz-sheet-toggle"
    type="button"
    aria-controls="pz-turret"
    :aria-expanded="navOpen"
    aria-label="展开导航 · 切换物镜"
    @click="emit('update:navOpen', true)"
  >
    <span class="pz-lens pz-lens-sm" aria-hidden="true"
      ><span class="pz-lens-mag mono">{{ current.magnification }}</span></span
    >
    <span class="pz-sheet-cur">{{ current.label }}</span>
    <span class="pz-sheet-hint mono" aria-hidden="true">切换物镜 ▴</span>
  </button>
</template>

<style scoped>
/* ---------------------------------------------------------------- HUD top bar */
.pz-top {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 40;
  /* the token is what pages use for sticky offsets: the bar is exactly that tall */
  height: var(--chrome-top);
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 0 22px;
  background: rgba(6, 7, 10, 0.82);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  backdrop-filter: blur(14px) saturate(120%);
}
.pz-top::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line) 20%, var(--line) 80%, transparent);
}
.pz-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text);
  text-decoration: none;
  border-radius: 8px;
  flex-shrink: 0;
}
.pz-pol {
  width: 28px;
  height: 28px;
  color: var(--text);
}
.pz-brand-word {
  font-family: var(--font-display);
  font-weight: 400;
  font-size: 15px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.pz-brand-cn {
  font-weight: 200;
  font-size: 15px;
  color: var(--text-2);
  padding-left: 10px;
  border-left: 1px solid var(--line-strong);
}
.pz-crumb {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-2);
  min-width: 0;
  margin-left: 30px;
  white-space: nowrap;
}
.pz-k {
  font-size: 10.5px;
  color: var(--text-3);
  letter-spacing: 0.14em;
}
.pz-mag {
  font-weight: 400;
  color: var(--text);
  font-size: 13px;
  padding: 2px 8px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
}
.pz-sep {
  color: var(--text-3);
}
.pz-page {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
}
.pz-read {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.pz-read b {
  color: var(--text-2);
  font-weight: 400;
  display: inline-block;
  min-width: 7ch;
  text-align: right;
}
.pz-unit {
  margin-left: -8px;
}
.pz-scale {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.pz-scale i {
  position: relative;
  height: 1px;
  background: var(--text-2);
}
.pz-scale i::before,
.pz-scale i::after {
  content: "";
  position: absolute;
  top: -3px;
  width: 1px;
  height: 7px;
  background: var(--text-2);
}
.pz-scale i::before {
  left: 0;
}
.pz-scale i::after {
  right: 0;
}
.pz-scale b {
  min-width: 0;
  text-align: left;
}
.pz-about {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.02em;
  white-space: nowrap;
  transition:
    background 0.2s,
    border-color 0.2s;
}
.pz-about:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.3);
}

/* ---------------------------------------------------------------- objective turret */
.pz-turret {
  position: fixed;
  left: 0;
  top: var(--chrome-top);
  bottom: 0;
  width: 236px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: none;
}
.pz-turret::-webkit-scrollbar {
  display: none;
}
.pz-turret-stage {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.pz-ring {
  position: absolute;
  overflow: visible;
}
.pz-arc {
  fill: none;
  stroke: rgba(255, 255, 255, 0.12);
  stroke-width: 1;
}
.pz-arc2 {
  fill: none;
  stroke: rgba(255, 255, 255, 0.05);
  stroke-width: 18;
}
.pz-tk {
  stroke: rgba(255, 255, 255, 0.13);
  stroke-width: 1;
}
.pz-tk-l {
  stroke: rgba(255, 255, 255, 0.28);
  stroke-width: 1;
}
.pz-ring-rot {
  transition: transform 0.9s cubic-bezier(0.3, 0.7, 0.2, 1);
}
.pz-beam {
  position: fixed;
  left: 106px;
  top: var(--chrome-top);
  z-index: 30;
  width: calc(100vw - 84px);
  height: 1px;
  margin-top: -1px;
  pointer-events: none;
  opacity: 0.55;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.45), rgba(224, 71, 158, 0.18) 140px, transparent 60%);
  transition: transform 0.6s cubic-bezier(0.3, 0.7, 0.2, 1);
}
.pz-sheet-head {
  display: none;
}
.pz-list {
  list-style: none;
  margin: 0;
  padding: 0;
  position: relative;
  flex: 1 0 auto;
  min-height: var(--turret-min);
}
.pz-obj {
  position: absolute;
  left: 0;
  top: 0;
  transform: translate(calc(var(--x) - 21px), calc(var(--y) - 21px));
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--text-2);
  border-radius: 999px;
  transition: color 0.25s;
}
.pz-obj:hover {
  color: var(--text);
}
.pz-obj-label {
  display: grid;
  line-height: 1.25;
}
.pz-obj-n {
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.1em;
}
.pz-obj-g {
  display: none;
}
.pz-obj-cn {
  font-size: 14px;
  white-space: nowrap;
}
.pz-obj.on {
  color: var(--text);
}
.pz-obj.on .pz-obj-cn {
  font-weight: 700;
}
.pz-intro {
  position: relative;
  align-self: flex-start;
  margin: 0 0 18px 22px;
  border-radius: 6px;
  color: var(--text-2);
  font-size: 13px;
  text-decoration: none;
}
.pz-intro:hover {
  color: var(--text);
}

/* lens (objective) */
.pz-lens {
  position: relative;
  flex: none;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at 35% 30%, #2a2f3c, #0b0d12 70%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.14),
    inset 0 -6px 12px rgba(0, 0, 0, 0.6);
  transition:
    box-shadow 0.3s,
    transform 0.3s;
}
.pz-lens::before {
  content: "";
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  padding: 2px;
  background: var(--ifc);
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.3s;
}
.pz-lens-mag {
  font-size: 10px;
  color: var(--text-2);
  letter-spacing: -0.02em;
}
.pz-obj:hover .pz-lens {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.3),
    inset 0 -6px 12px rgba(0, 0, 0, 0.6);
}
.pz-obj.on .pz-lens {
  transform: scale(1.12);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.35),
    0 0 26px -2px rgba(224, 71, 158, 0.55),
    0 0 50px -10px rgba(46, 196, 214, 0.5);
}
.pz-obj.on .pz-lens::before,
.pz-obj:focus-visible .pz-lens::before {
  opacity: 1;
}
.pz-obj.on .pz-lens-mag {
  color: var(--text);
}
.pz-lens-sm {
  width: 32px;
  height: 32px;
}
.pz-lens-sm .pz-lens-mag {
  font-size: 8.5px;
}

.pz-scrim,
.pz-sheet-toggle {
  display: none;
}

/* ---------------------------------------------------------------- responsive */
@media (max-width: 1180px) {
  .pz-read {
    display: none;
  }
  .pz-about {
    margin-left: auto;
  }
}
@media (max-width: 1100px) {
  .pz-turret {
    width: 212px;
  }
  .pz-obj-cn {
    font-size: 13px;
  }
}
@media (max-width: 900px) {
  .pz-crumb {
    margin-left: 0;
  }
  .pz-k,
  .pz-group,
  .pz-crumb .pz-sep:not(.pz-sep-page),
  .pz-brand-cn {
    display: none;
  }
}
@media (max-width: 720px) {
  .pz-beam {
    display: none;
  }
  .pz-top {
    gap: 10px;
    padding: 0 14px;
  }
  .pz-crumb {
    display: none;
  }
  .pz-brand {
    gap: 8px;
  }
  .pz-pol {
    width: 24px;
    height: 24px;
  }
  .pz-brand-word {
    font-size: 13px;
  }
  .pz-about {
    min-height: 32px;
    padding: 0 12px;
  }
  /* the turret becomes a bottom sheet */
  .pz-turret {
    top: auto;
    bottom: 0;
    left: 0;
    right: 0;
    width: auto;
    max-height: min(86dvh, 640px);
    z-index: 50;
    padding: 16px 16px calc(22px + env(safe-area-inset-bottom));
    border-radius: 22px 22px 0 0;
    border-top: 1px solid var(--line-strong);
    background: linear-gradient(180deg, #141824, #0a0c11);
    display: block;
    transform: translateY(105%);
    visibility: hidden;
    transition:
      transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1),
      visibility 0s linear 0.3s;
  }
  .pz-turret.open {
    transform: none;
    visibility: visible;
    transition: transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .pz-turret-stage {
    display: none;
  }
  .pz-sheet-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 10.5px;
    letter-spacing: 0.12em;
    color: var(--text-3);
    margin-bottom: 12px;
  }
  .pz-close {
    display: inline-grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px solid var(--line-strong);
    color: var(--text);
    flex-shrink: 0;
  }
  .pz-list {
    min-height: 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 14px;
  }
  .pz-obj {
    position: static;
    transform: none;
    gap: 10px;
    padding: 10px;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--line-soft);
    min-height: 58px;
  }
  .pz-obj.on {
    border-color: var(--line-strong);
    background: rgba(255, 255, 255, 0.07);
  }
  .pz-obj.on .pz-lens {
    transform: none;
  }
  .pz-obj .pz-lens {
    width: 34px;
    height: 34px;
  }
  .pz-obj .pz-lens-mag {
    font-size: 8.5px;
  }
  .pz-obj-label {
    min-width: 0;
  }
  .pz-obj-n {
    font-size: 9.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pz-obj-g {
    display: inline;
  }
  .pz-obj-cn {
    white-space: normal;
    line-height: 1.3;
  }
  .pz-intro {
    display: inline-block;
    margin: 0;
  }
  .pz-scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 45;
    border: 0;
    background: rgba(3, 4, 6, 0.7);
  }
  .pz-sheet-toggle {
    position: fixed;
    left: 12px;
    right: 12px;
    bottom: calc(12px + env(safe-area-inset-bottom));
    z-index: 44;
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 54px;
    padding: 0 16px 0 10px;
    border-radius: 999px;
    border: 1px solid var(--line-strong);
    background: rgba(12, 14, 20, 0.92);
    -webkit-backdrop-filter: blur(12px);
    backdrop-filter: blur(12px);
    color: var(--text);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
    text-align: left;
  }
  .pz-sheet-toggle .pz-lens::before {
    opacity: 1;
  }
  .pz-sheet-cur {
    font-weight: 700;
    font-size: 15px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pz-sheet-hint {
    margin-left: auto;
    font-size: 11px;
    color: var(--text-2);
    white-space: nowrap;
  }
}
@media (max-width: 380px) {
  .pz-brand-word {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .pz-ring-rot,
  .pz-beam,
  .pz-turret {
    transition: none !important;
  }
}
</style>
