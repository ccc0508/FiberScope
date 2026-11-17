<script setup lang="ts">
import { computed, useId } from "vue";
import { mode as currentMode } from "../mode";
import type { Mode } from "../modeResolve";

/*
 * FiberScope mark: a microscope field of view with three fibres drifting through it, one per
 * material (softwood, blend, hardwood). Polarized: dark field, interference-colour rim and
 * fibres. Garden: pale field, stain-colour rim and fibres. Same geometry as the favicons in
 * public/ (favicon-polarized.svg, favicon-garden.svg), so the tab icon and the logo match.
 */
const props = defineProps<{ mode?: Mode }>();
const id = useId();
const m = computed(() => props.mode ?? currentMode.value);
const colors = computed(() =>
  m.value === "polarized"
    ? {
        field: ["#211B3F", "#0B0C14", "#06070A"],
        rim: ["#F2C14E", "#E0479E", "#5B5BD6", "#2EC4D6"],
        fibres: ["#F2C14E", "#E0479E", "#2EC4D6"],
      }
    : {
        field: ["#FFFFFF", "#FBF5F8", "#F1EAF6"],
        rim: ["#DA6B3C", "#B07AB4", "#8B6CD9", "#4E9A6A"],
        fibres: ["#DA6B3C", "#8B6CD9", "#4E9A6A"],
      },
);
</script>

<template>
  <svg class="brand-mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient :id="`${id}-rim`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" :stop-color="colors.rim[0]" />
        <stop offset=".38" :stop-color="colors.rim[1]" />
        <stop offset=".68" :stop-color="colors.rim[2]" />
        <stop offset="1" :stop-color="colors.rim[3]" />
      </linearGradient>
      <radialGradient :id="`${id}-field`" cx=".42" cy=".36" r=".7">
        <stop offset="0" :stop-color="colors.field[0]" />
        <stop offset=".7" :stop-color="colors.field[1]" />
        <stop offset="1" :stop-color="colors.field[2]" />
      </radialGradient>
    </defs>
    <circle cx="32" cy="32" r="30" :fill="`url(#${id}-field)`" />
    <circle cx="32" cy="32" r="27.5" fill="none" :stroke="`url(#${id}-rim)`" stroke-width="5" />
    <g fill="none" stroke-linecap="round" stroke-width="6" transform="rotate(-12 32 32)">
      <path d="M15 24C21 18 28 25 34 20S44 15 49 18" :stroke="colors.fibres[0]" />
      <path d="M14 33C20 27 28 35 34 30S45 25 50 28" :stroke="colors.fibres[1]" />
      <path d="M16 42C22 37 29 44 35 39S44 35 48 38" :stroke="colors.fibres[2]" />
    </g>
  </svg>
</template>

<style scoped>
.brand-mark {
  display: block;
  flex: none;
}
</style>
