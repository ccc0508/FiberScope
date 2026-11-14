<script setup lang="ts">
import { computed } from "vue";
import type { CurvePoint } from "../../beating";
import { number } from "../../api";
import { chartColors, materialColors } from "../../palette";

/*
 * Chapter 02 spark line (v4 charts.js · sparkSVG): °SR against beating revolutions for the
 * two pure pulps, on a fixed 0–100 °SR scale, with the target as a dashed line. Segments
 * only join neighbouring valid observations; nothing is fitted.
 */
const props = defineProps<{
  softwood: CurvePoint[];
  hardwood: CurvePoint[];
  target: number;
  maxRev: number | null;
}>();

const W = 420,
  H = 110,
  PAD = 6;
const xMax = computed(() => props.maxRev || Math.max(1, ...props.softwood.map((p) => p.x), ...props.hardwood.map((p) => p.x)));
const X = (x: number) => PAD + (x / xMax.value) * (W - PAD * 2);
const Y = (y: number) => H - 8 - (Math.min(100, Math.max(0, y)) / 100) * (H - 16);
const path = (points: CurvePoint[]) =>
  points.map((p, k) => `${k ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
const grid = [25, 50, 75].map(Y);
const label = computed(
  () =>
    `针叶木浆与阔叶木浆的打浆度随打浆转数变化（0–${number(props.maxRev)} r，纵轴 0–100 °SR），虚线为目标 ${props.target} °SR`,
);
</script>

<template>
  <svg class="gi-spark-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="label">
    <line
      v-for="(y, i) in grid"
      :key="i"
      :x1="PAD"
      :x2="W - PAD"
      :y1="y"
      :y2="y"
      :stroke="chartColors.grid"
      vector-effect="non-scaling-stroke"
    />
    <line
      :x1="PAD"
      :x2="W - PAD"
      :y1="Y(target)"
      :y2="Y(target)"
      :stroke="chartColors.target"
      stroke-dasharray="4 4"
      stroke-width="1.2"
      vector-effect="non-scaling-stroke"
    />
    <path
      v-if="softwood.length"
      :d="path(softwood)"
      fill="none"
      :stroke="materialColors.softwood"
      stroke-width="2.2"
      stroke-linecap="round"
      stroke-linejoin="round"
      vector-effect="non-scaling-stroke"
    />
    <path
      v-if="hardwood.length"
      :d="path(hardwood)"
      fill="none"
      :stroke="materialColors.hardwood"
      stroke-width="2.2"
      stroke-linecap="round"
      stroke-linejoin="round"
      vector-effect="non-scaling-stroke"
    />
  </svg>
</template>

<style scoped>
.gi-spark-svg {
  display: block;
  width: 100%;
  height: 110px;
  overflow: visible;
}
</style>
