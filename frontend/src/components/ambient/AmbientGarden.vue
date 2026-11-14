<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { createPulp, type PulpController } from "../../ambient/pulp";
import { reducedMotion } from "../../mode";

/*
 * Decorative garden background: a CSS mesh gradient (always there, also the fallback),
 * the v4 pulp-suspension shader on top of it, and a soft-light grain.
 * The pointer stirs the pulp; scrolling gives a short "beating" pulse.
 */
const canvas = ref<HTMLCanvasElement>();
const on = ref(false);
/** while the GPU context is lost the canvas is hidden without a fade */
const lost = ref(false);
let pulp: PulpController | null = null;
let lastY = 0,
  raf = 0;

function onScroll() {
  if (!pulp || reducedMotion.value || raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    const y = window.scrollY;
    const v = Math.abs(y - lastY);
    lastY = y;
    pulp?.pulse(Math.min(0.12, v / 900));
  });
}

onMounted(() => {
  if (!canvas.value) return;
  lastY = window.scrollY;
  try {
    pulp = createPulp(canvas.value, {
      still: reducedMotion.value,
      // a lost context paints nothing (and an opaque black frame once restored but not yet
      // redrawn): hide the canvas at once so the CSS mesh shows, and fade it back in only
      // after the shader has been rebuilt and has drawn a frame
      onLost: () => {
        on.value = false;
        lost.value = true;
      },
      onRestored: () => {
        lost.value = false;
        on.value = true;
      },
      onFail: () => {
        pulp?.dispose();
        pulp = null;
        on.value = false;
        lost.value = true;
      },
      // workspace ambience: stains visible in the gutters, filaments faint; sleeps when calm
      target: {
        intensity: 0.8,
        fibers: 0.5,
        filA: 0.2,
        beat: 0.05,
        settle: 0.35,
        scale: 0.36,
        fps: 24,
        idle: 1200,
      },
    });
  } catch {
    pulp = null;
  }
  on.value = !!pulp;
  window.addEventListener("scroll", onScroll, { passive: true });
});
watch(reducedMotion, (value) => pulp?.setStill(value));
onBeforeUnmount(() => {
  window.removeEventListener("scroll", onScroll);
  cancelAnimationFrame(raf);
  pulp?.dispose();
  pulp = null;
});
</script>

<template>
  <div class="gd-ambient" aria-hidden="true">
    <div class="gd-mesh"></div>
    <canvas ref="canvas" class="gd-pulp" :class="{ on, lost }"></canvas>
    <div class="gd-veil"></div>
    <div class="gd-grain"></div>
  </div>
</template>

<style scoped>
.gd-ambient {
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  overflow: hidden;
}
.gd-mesh,
.gd-pulp,
.gd-veil,
.gd-grain {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.gd-mesh {
  background:
    radial-gradient(55% 45% at 8% 0%, #ffe6da 0%, transparent 62%),
    radial-gradient(45% 55% at 100% 18%, #e8e2fb 0%, transparent 62%),
    radial-gradient(60% 55% at 28% 100%, #e1f0e5 0%, transparent 62%),
    linear-gradient(155deg, #fff4ee 0%, #f1f0fa 52%, #eef6ef 100%);
}
.gd-pulp {
  display: block;
  opacity: 0;
  transition: opacity 1.4s cubic-bezier(0.22, 0.9, 0.25, 1);
}
.gd-pulp.on {
  opacity: 0.85;
}
.gd-pulp.lost {
  visibility: hidden;
  transition: none;
}
/* keeps the workspace calm: the stains read as light, not as content */
.gd-veil {
  background: linear-gradient(180deg, rgba(255, 250, 252, 0.12), rgba(255, 250, 252, 0.26));
}
.gd-grain {
  opacity: 0.45;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 .5  0 0 0 0 .45  0 0 0 0 .55  0 0 0 .35 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
}
</style>
