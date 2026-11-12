<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { isGarden, isPolarized, mode, reducedMotion } from "../mode";
import { navItemFor, navItems, navTotal, type GardenLens } from "../nav";
import clayFibers from "../assets/modes/garden/clay-fibers.jpg";
import paperNetwork from "../assets/modes/garden/paper-network.jpg";
import glassLeaves from "../assets/modes/garden/glass-leaves.jpg";

/*
 * Page header for both modes. Every prop falls back to the nav entry of the current
 * route, so `<PageHeader description="…" />` is enough on a workspace page.
 *
 *  polarized: OBJ 02 · 20× · 分析与探索 eyebrow, huge title with weight contrast
 *             (titleStrong 900 + titleLight 200), faint outlined Latin ghost word (english).
 *  garden:    italic Fraunces eyebrow "Beating · 分析与探索 · 02/08" (gardenEnglish),
 *             ZCOOL XiaoWei title, glass hero card with a visual slot and a microscope
 *             lens on the right (the lens image drifts a little with scroll).
 *
 * Slots: default (extra content under the description: chips, notes),
 *        actions (buttons / status), visual (illustration or data signature),
 *        description (rich description; overrides the prop).
 */
const props = defineProps<{
  /** full title, e.g. "打浆分析" (garden, and the accessible name in polarized) */
  title?: string;
  /** polarized heavy part, e.g. "打浆" */
  titleStrong?: string;
  /** polarized light part, e.g. "分析" */
  titleLight?: string;
  /** "02" */
  index?: string;
  /** polarized Latin ghost word, e.g. "Beating" */
  english?: string;
  /** garden eyebrow, e.g. "Garden overview" (falls back to `english` when only that is given) */
  gardenEnglish?: string;
  /** "分析与探索" */
  group?: string;
  /** "20×" */
  magnification?: string;
  description?: string;
  /** id of the <h1>, for aria-labelledby */
  headingId?: string;
  /** garden lens image override */
  lens?: GardenLens | null;
}>();

const route = useRoute();
const entry = computed(() => navItemFor(route.path) ?? navItems[0]!);
const title = computed(() => props.title ?? entry.value.label);
const strong = computed(() => {
  if (props.titleStrong != null) return props.titleStrong;
  return title.value === entry.value.label ? entry.value.titleStrong : title.value;
});
const light = computed(() => {
  if (props.titleLight != null) return props.titleLight;
  return title.value === entry.value.label ? entry.value.titleLight : "";
});
const index = computed(() => props.index ?? entry.value.index);
const english = computed(() => props.english ?? entry.value.english);
const gardenEnglish = computed(
  () => props.gardenEnglish ?? props.english ?? entry.value.gardenEnglish,
);
const group = computed(() => props.group ?? entry.value.group);
const magnification = computed(() => props.magnification ?? entry.value.magnification);

const LENS_IMAGES: Record<GardenLens["image"], string> = {
  "clay-fibers": clayFibers,
  "paper-network": paperNetwork,
  "glass-leaves": glassLeaves,
};
const lens = computed(() => (props.lens === undefined ? entry.value.gardenLens : props.lens));

// a few drifting fibre strands behind the garden hero (seeded per page, purely decorative)
const strands = computed(() => {
  let s = (Number(index.value) || 1) * 3 * 9973 + 9973;
  const R = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const colours = ["#F08A5D", "#7DB58C", "#A58BE3", "#4A3B63"];
  return Array.from({ length: 7 }, (_, i) => {
    const y0 = R() * 100,
      y1 = R() * 100,
      c1 = R() * 100,
      c2 = R() * 100;
    const colour = colours[i % 4]!;
    const plum = colour === "#4A3B63";
    return {
      d: `M${(-10 + R() * 20).toFixed(1)},${y0.toFixed(1)} C${(30 + R() * 20).toFixed(1)},${c1.toFixed(1)} ${(60 + R() * 20).toFixed(1)},${c2.toFixed(1)} ${(100 + R() * 15).toFixed(1)},${y1.toFixed(1)}`,
      colour,
      width: plum ? 0.8 : 1.4 + R() * 2.2,
      opacity: plum ? 0.28 : 0.45 + R() * 0.3,
    };
  });
});

/*
 * The outlined Latin word must never sit on the title, the description, the actions or
 * the default-slot content: shrink it until it clears them, or hide it (v1 fitGhost).
 * Text blocks are measured by their content (the right edge of their children), not by
 * their block box, which spans the whole column. The visual is not an obstacle: the word
 * stays at full size behind it (z-order), like the backdrop word in v1.
 */
const root = ref<HTMLElement>();
const ghost = ref<HTMLElement>();
const ghostSize = ref<number | null>(null);
const ghostHidden = ref(false);
type Box = { left: number; right: number; top: number; bottom: number };
function contentBox(el: HTMLElement): Box {
  const r = el.getBoundingClientRect();
  const kids = [...el.children].filter(
    (c): c is HTMLElement => c instanceof HTMLElement && c.getClientRects().length > 0,
  );
  if (!kids.length) {
    // bare text: measure the text itself (a <p> box is as wide as its column)
    const range = document.createRange();
    range.selectNodeContents(el);
    const t = range.getBoundingClientRect();
    return t.width ? { left: t.left, right: t.right, top: r.top, bottom: r.bottom } : r;
  }
  const boxes = kids.map((c) => c.getBoundingClientRect());
  return {
    left: Math.min(...boxes.map((b) => b.left)),
    right: Math.max(...boxes.map((b) => b.right)),
    top: r.top,
    bottom: r.bottom,
  };
}
function fitGhost() {
  const el = ghost.value,
    box = root.value;
  if (!el || !box || !isPolarized.value) return;
  ghostSize.value = null;
  ghostHidden.value = false;
  el.style.fontSize = "";
  void nextTick(() => {
    if (getComputedStyle(el).display === "none") return;
    const blocks = [
      ...box.querySelectorAll<HTMLElement>(".ph-title, .ph-desc, .ph-actions, .ph-extra > *"),
    ];
    const overlaps = () => {
      const g = el.getBoundingClientRect();
      return blocks.some((b) => {
        const r = contentBox(b);
        return g.left < r.right + 24 && g.right > r.left - 24 && g.bottom > r.top && g.top < r.bottom;
      });
    };
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (overlaps() && size > 34) {
      size -= 4;
      el.style.fontSize = `${size}px`;
    }
    ghostSize.value = size;
    if (overlaps()) ghostHidden.value = true;
  });
}

/* garden: the lens image drifts up to 24px with scroll (v4 --py), not under reduced motion */
const lensImg = ref<HTMLImageElement>();
let parallaxRaf = 0;
function parallax() {
  if (parallaxRaf) return;
  parallaxRaf = requestAnimationFrame(() => {
    parallaxRaf = 0;
    const img = lensImg.value;
    if (!img) return;
    const py = isGarden.value && !reducedMotion.value ? Math.min(24, window.scrollY * 0.06) : 0;
    img.style.setProperty("--py", `${py.toFixed(1)}px`);
  });
}

let resizeObserver: ResizeObserver | undefined;
onMounted(() => {
  fitGhost();
  document.fonts?.ready.then(fitGhost).catch(() => undefined);
  if (root.value) {
    resizeObserver = new ResizeObserver(() => fitGhost());
    resizeObserver.observe(root.value);
  }
  window.addEventListener("scroll", parallax, { passive: true });
  parallax();
});
watch([mode, english, title], () => void nextTick(fitGhost));
watch([mode, reducedMotion, lensImg], parallax);
onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  window.removeEventListener("scroll", parallax);
  cancelAnimationFrame(parallaxRaf);
});
</script>

<template>
  <header ref="root" class="page-header" :class="`page-header--${mode}`">
    <template v-if="!isPolarized">
      <div class="ph-fibers" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          <path
            v-for="(strand, i) in strands"
            :key="i"
            :d="strand.d"
            :stroke="strand.colour"
            :stroke-width="strand.width.toFixed(2)"
            :stroke-opacity="strand.opacity.toFixed(2)"
            vector-effect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div
        v-if="lens"
        class="ph-lens"
        aria-hidden="true"
        :style="{ '--op': lens.position, '--sc': String(lens.scale) }"
      >
        <img ref="lensImg" :src="LENS_IMAGES[lens.image]" alt="" decoding="async" />
      </div>
    </template>

    <div class="ph-text">
      <p class="ph-eyebrow">
        <template v-if="isPolarized">
          <span class="ph-obj">OBJ {{ index }}</span>
          <span class="ph-mag">{{ magnification }}</span>
          <span>{{ group }}</span>
          <span class="ph-line" aria-hidden="true"></span>
        </template>
        <template v-else>
          <span class="ph-lat">{{ gardenEnglish }}</span> · {{ group }} · {{ index }}/{{ navTotal }}
        </template>
      </p>
      <h1 :id="headingId" class="ph-title" tabindex="-1">
        <template v-if="isPolarized">
          <span class="ph-strong">{{ strong }}</span
          ><span v-if="light" class="ph-light">{{ light }}</span>
        </template>
        <template v-else>{{ title }}</template>
      </h1>
      <div v-if="$slots.description" class="ph-desc"><slot name="description" /></div>
      <p v-else-if="description" class="ph-desc">{{ description }}</p>
      <div v-if="$slots.default" class="ph-extra"><slot /></div>
      <div v-if="$slots.actions" class="ph-actions"><slot name="actions" /></div>
    </div>

    <div v-if="$slots.visual" class="ph-visual"><slot name="visual" /></div>

    <div
      v-if="isPolarized && english"
      ref="ghost"
      class="ph-latin"
      :class="{ hidden: ghostHidden }"
      aria-hidden="true"
      :style="ghostSize ? { fontSize: `${ghostSize}px` } : undefined"
    >
      {{ english }}
    </div>
  </header>
</template>

<style scoped>
.page-header {
  position: relative;
  margin-bottom: 22px;
}
.ph-title {
  margin: 0;
}
.ph-title:focus {
  outline: none;
}
.ph-desc {
  text-wrap: pretty;
}
.ph-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  /* as wide as its buttons, so the polarized ghost word can sit beside them */
  width: fit-content;
  max-width: 100%;
}
.ph-extra {
  min-width: 0;
}
.ph-visual {
  position: relative;
  min-width: 0;
}

/* ================================================================ polarized */
.page-header--polarized {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 18px 32px;
  padding: 26px 0 30px;
}
.page-header--polarized .ph-text {
  position: relative;
  z-index: 1;
  min-width: 0;
}
.page-header--polarized .ph-eyebrow {
  display: flex;
  align-items: center;
  gap: 14px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--text-2);
}
.page-header--polarized .ph-mag {
  color: var(--text);
  border: 1px solid var(--line-strong);
  padding: 1px 8px;
  border-radius: 999px;
}
.page-header--polarized .ph-line {
  flex: 1;
  height: 1px;
  max-width: 380px;
  background: linear-gradient(90deg, var(--line-strong), transparent);
}
.page-header--polarized .ph-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 0.12em;
  margin-top: 14px;
  font-family: var(--font-display-cn);
  font-size: clamp(40px, 5vw, 76px);
  line-height: 1.05;
  color: var(--text);
}
.page-header--polarized .ph-strong {
  font-weight: 900;
  letter-spacing: 0.01em;
}
.page-header--polarized .ph-light {
  font-weight: 200;
  letter-spacing: 0.03em;
}
.page-header--polarized .ph-desc {
  margin-top: 14px;
  max-width: 620px;
  color: var(--text-2);
  font-size: 15px;
  font-weight: 300;
  line-height: 1.7;
}
.page-header--polarized .ph-actions {
  margin-top: 18px;
}
.page-header--polarized .ph-visual {
  z-index: 1;
  align-self: center;
}
.ph-latin {
  position: absolute;
  right: 0;
  bottom: 28px;
  font-family: "Unbounded", var(--font-display), sans-serif;
  font-weight: 200;
  font-size: clamp(44px, 5.4vw, 88px);
  line-height: 1;
  letter-spacing: -0.04em;
  color: transparent;
  -webkit-text-stroke: 1px rgba(236, 239, 244, 0.16);
  pointer-events: none;
  user-select: none;
  white-space: nowrap;
}
.ph-latin.hidden {
  visibility: hidden;
}

/* ================================================================ garden */
.page-header--garden {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, auto);
  align-items: center;
  gap: 14px 40px;
  min-height: 184px;
  padding: 24px 226px 22px 38px;
  border-radius: 34px;
  overflow: hidden;
  isolation: isolate;
  background: linear-gradient(115deg, rgba(255, 255, 255, 0.88), rgba(255, 255, 255, 0.66) 55%, rgba(255, 255, 255, 0.46));
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.9),
    inset 0 1px 0 #fff,
    var(--shadow);
}
.page-header--garden .ph-text {
  position: relative;
  min-width: 0;
}
.page-header--garden .ph-eyebrow {
  font-family: var(--font-display), var(--font-body);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 15px;
  color: var(--text-2);
  letter-spacing: 0.01em;
}
.page-header--garden .ph-lat {
  font-variation-settings: "SOFT" 100, "WONK" 1;
}
.page-header--garden .ph-title {
  margin: 6px 0 10px;
  font-family: var(--font-display-cn);
  font-weight: 400;
  font-size: clamp(36px, 3.4vw, 50px);
  line-height: 1.1;
  letter-spacing: 0.14em;
  color: var(--text);
  text-wrap: balance;
}
.page-header--garden .ph-desc {
  max-width: 620px;
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-2);
}
.page-header--garden .ph-actions {
  margin-top: 16px;
}
.page-header--garden .ph-visual {
  max-width: 440px;
}
.page-header--garden .ph-visual::before {
  content: "";
  position: absolute;
  inset: -18px -26px;
  z-index: -1;
  pointer-events: none;
  background: radial-gradient(closest-side, rgba(255, 252, 253, 0.92), rgba(255, 252, 253, 0.6) 60%, rgba(255, 252, 253, 0));
}
.ph-fibers {
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  opacity: 0.6;
  -webkit-mask: linear-gradient(100deg, rgba(0, 0, 0, 0.18) 0%, rgba(0, 0, 0, 0.18) 38%, #000 70%);
  mask: linear-gradient(100deg, rgba(0, 0, 0, 0.18) 0%, rgba(0, 0, 0, 0.18) 38%, #000 70%);
}
.ph-fibers svg {
  width: 100%;
  height: 100%;
}
.ph-fibers path {
  fill: none;
  stroke-linecap: round;
  animation: ph-drift 14s ease-in-out infinite alternate;
}
.ph-fibers path:nth-child(2n) {
  animation-duration: 19s;
  animation-direction: alternate-reverse;
}
.ph-fibers path:nth-child(3n) {
  animation-duration: 23s;
}
@keyframes ph-drift {
  from {
    transform: translate(-2%, 2%) rotate(-1deg);
  }
  to {
    transform: translate(3%, -3%) rotate(1.5deg);
  }
}
.ph-lens {
  position: absolute;
  right: -60px;
  top: 50%;
  width: 252px;
  aspect-ratio: 1;
  translate: 0 -50%;
  border-radius: 50%;
  overflow: hidden;
  z-index: -1;
  background:
    radial-gradient(60% 60% at 40% 40%, #ffb38a, transparent 70%),
    radial-gradient(60% 60% at 70% 60%, #b9a3e3, transparent 70%),
    radial-gradient(50% 50% at 50% 80%, #9cc5a1, transparent 70%),
    #f6eff5;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.95),
    0 0 0 12px rgba(255, 255, 255, 0.32),
    0 30px 60px -30px rgba(74, 52, 110, 0.55);
}
.ph-lens img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  object-position: var(--op, 50% 50%);
  transform-origin: var(--op, 50% 50%);
  scale: var(--sc, 1);
  translate: 0 calc(var(--py, 0px) * -1);
}
.ph-lens::before {
  content: "";
  position: absolute;
  inset: 9px;
  z-index: 1;
  border-radius: 50%;
  pointer-events: none;
  opacity: 0.85;
  background: repeating-conic-gradient(rgba(255, 255, 255, 0.95) 0 0.45deg, transparent 0.45deg 6deg);
  -webkit-mask: radial-gradient(closest-side, transparent 91%, #000 92%);
  mask: radial-gradient(closest-side, transparent 91%, #000 92%);
}
.ph-lens::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 50%;
  pointer-events: none;
  background:
    radial-gradient(circle at 32% 26%, rgba(255, 255, 255, 0.5), transparent 36%),
    radial-gradient(closest-side, transparent 72%, rgba(255, 246, 241, 0.4) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.85),
    inset 0 -18px 40px -20px rgba(74, 52, 110, 0.35);
}

/* ================================================================ responsive */
@media (max-width: 1180px) {
  .page-header--garden {
    padding-right: 176px;
    gap: 14px 26px;
  }
  .ph-lens {
    width: 206px;
    right: -54px;
  }
}
@media (max-width: 980px) {
  .page-header--polarized {
    grid-template-columns: minmax(0, 1fr);
  }
  .page-header--polarized .ph-visual {
    justify-self: start;
  }
  .ph-latin {
    display: none;
  }
  .page-header--garden {
    grid-template-columns: 1fr;
    padding: 22px 150px 20px 28px;
  }
  .ph-lens {
    width: 176px;
    right: -44px;
    top: 22px;
    translate: none;
  }
}
@media (max-width: 720px) {
  .page-header--polarized {
    padding: 18px 0 22px;
  }
  .page-header--polarized .ph-eyebrow {
    gap: 10px;
  }
  .page-header--polarized .ph-title {
    font-size: 42px;
  }
  .page-header--polarized .ph-desc {
    font-size: 14px;
  }
  .page-header--garden {
    min-height: 0;
    padding: 20px 18px 18px;
    border-radius: 28px;
  }
  .page-header--garden .ph-eyebrow {
    padding-right: 72px;
    font-size: 13.5px;
  }
  .page-header--garden .ph-title {
    font-size: 32px;
    padding-right: 76px;
  }
  .page-header--garden .ph-desc {
    font-size: 13.5px;
  }
  .ph-lens {
    width: 100px;
    right: -22px;
    top: 10px;
    opacity: 0.9;
    box-shadow:
      0 0 0 1px rgba(255, 255, 255, 0.95),
      0 0 0 7px rgba(255, 255, 255, 0.3),
      0 20px 40px -24px rgba(74, 52, 110, 0.55);
  }
  .ph-lens::before {
    inset: 6px;
  }
}
@media (max-width: 380px) {
  .page-header--polarized .ph-title {
    font-size: 36px;
  }
}
</style>
