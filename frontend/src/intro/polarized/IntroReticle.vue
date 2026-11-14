<script setup lang="ts">
import { reticleTicks } from "./content";
// Eyepiece reticle (decorative): graduated ring, crosshair, micrometer scale, "P ⟂ A".
</script>

<template>
  <svg class="pzi-reticle" viewBox="0 0 400 400" aria-hidden="true" focusable="false">
    <circle cx="200" cy="200" r="190" class="r-ring" />
    <circle cx="200" cy="200" r="150" class="r-ring2" />
    <path :d="reticleTicks.ticks" class="r-ticks" />
    <line x1="40" y1="200" x2="360" y2="200" class="r-cross" />
    <line x1="200" y1="40" x2="200" y2="360" class="r-cross" />
    <path :d="reticleTicks.scale" class="r-scale" />
    <text x="200" y="232" class="r-txt" text-anchor="middle">P ⟂ A</text>
  </svg>
</template>

<style scoped>
.pzi-reticle {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.r-ring {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 26%, transparent);
  stroke-width: 1;
}
.r-ring2 {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 8%, transparent);
  stroke-width: 1;
  stroke-dasharray: 2 6;
}
.r-ticks {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 30%, transparent);
  stroke-width: 1;
}
.r-cross {
  stroke: color-mix(in srgb, var(--text) 12%, transparent);
  stroke-width: 1;
}
.r-scale {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 40%, transparent);
  stroke-width: 1;
}
.r-txt {
  fill: color-mix(in srgb, var(--text) 45%, transparent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.2em;
}
</style>
