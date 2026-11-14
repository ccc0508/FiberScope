<script setup lang="ts">
/*
 * 打浆页页头的数据签名（v4 beatingSig）：两条实测打浆度曲线、目标打浆度虚线，
 * 以及两种原料首次达到目标的转数（相邻实测点线性插值，取整到百转）。
 * 取代旧的显微图 WebGL 装饰：图形本身只做示意（aria-hidden），含义由图注文字承载。
 * 颜色来自 palette.ts（随模式切换），坐标轴与文字用令牌；无数据时显示骨架。
 */
import { computed } from "vue";
import { number } from "../api";
import { firstReach, type CurvePoint } from "../beating";
import { materialCodeColors } from "../palette";

type Material = "SW" | "HW";
const props = defineProps<{
  /** 打浆度曲线（x 转数，y °SR），已按转数升序、只含有效值 */
  sw: CurvePoint[];
  hw: CurvePoint[];
  /** 目标打浆度 °SR */
  target: number;
  /** 横轴终点（转） */
  xMax: number;
}>();

const W = 420,
  L = 34,
  R = W - 8,
  TOP = 8,
  BASE = 112;
const NAMES: Record<Material, string> = { SW: "针叶木浆", HW: "阔叶木浆" };
const X = (v: number) => L + (v / (props.xMax || 1)) * (R - L);
const Y = (v: number) => BASE + (Math.max(0, Math.min(100, v)) / 100) * (TOP - BASE);
const path = (points: CurvePoint[]) =>
  points
    .map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`)
    .join("");

const empty = computed(() => !props.sw.length && !props.hw.length);
const reach = computed(() => {
  const at = (points: CurvePoint[]) => {
    const x = firstReach(points, props.target);
    return x === null ? null : Math.round(x / 100) * 100;
  };
  return { SW: at(props.sw), HW: at(props.hw) } as Record<Material, number | null>;
});
// 先达到的标在交点左上，后达到的标在右下，两枚标签不会相撞
const marks = computed(() => {
  const hits = (["SW", "HW"] as const)
    .map((code) => ({ code, x: reach.value[code] }))
    .filter((h): h is { code: Material; x: number } => h.x !== null)
    .sort((a, b) => a.x - b.x);
  return hits.map((h, i) => {
    const px = X(h.x),
      py = Y(props.target);
    const first = hits.length > 1 && i === 0;
    const label = `${number(h.x)} r`;
    const startFits = px + 8 + label.length * 7 <= W;
    const left = first || !startFits;
    return {
      ...h,
      px,
      py,
      label,
      lx: left ? px - 8 : px + 8,
      ly: first ? py - 10 : py + 20,
      anchor: left ? "end" : "start",
    };
  });
});
const lines = computed(() => [
  { code: "HW" as const, d: path(props.hw) },
  { code: "SW" as const, d: path(props.sw) },
]);
const xMaxLabel = computed(() => `${number(props.xMax / 1000)}k r`);
</script>

<template>
  <figure class="beating-sig">
    <div v-if="empty" class="beating-sig-empty skeleton" aria-hidden="true"></div>
    <svg
      v-else
      viewBox="0 0 420 132"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      <line :x1="L" :x2="R" :y1="BASE" :y2="BASE" class="sg-base" />
      <text class="sg-m" :x="L" y="128">0</text>
      <text class="sg-m" :x="R" y="128" text-anchor="end">{{ xMaxLabel }}</text>
      <line :x1="L" :x2="R" :y1="Y(target)" :y2="Y(target)" class="sg-target" />
      <text class="sg-m" x="0" :y="Y(target) + 4">{{ target }}°</text>
      <path
        v-for="l in lines"
        :key="l.code"
        :d="l.d"
        class="sg-line"
        pathLength="1"
        :stroke="materialCodeColors[l.code]"
      />
      <g v-for="m in marks" :key="m.code">
        <line
          :x1="m.px"
          :x2="m.px"
          :y1="m.py"
          :y2="BASE"
          class="sg-drop"
          :stroke="materialCodeColors[m.code]"
        />
        <circle
          v-if="m.code === 'SW'"
          class="sg-pt"
          :cx="m.px"
          :cy="m.py"
          r="4.6"
          :fill="materialCodeColors.SW"
        />
        <rect
          v-else
          class="sg-pt"
          :x="m.px - 4.2"
          :y="m.py - 4.2"
          width="8.4"
          height="8.4"
          rx="2"
          :fill="materialCodeColors.HW"
        />
        <text class="sg-v" :x="m.lx" :y="m.ly" :text-anchor="m.anchor">
          {{ m.label }}
        </text>
      </g>
    </svg>
    <figcaption>
      达到 {{ target }} °SR（相邻实测点插值）：<span class="sg-nw"
        >{{ NAMES.HW }}
        <b>{{ reach.HW === null ? "未达到" : `≈ ${number(reach.HW)} r` }}</b></span
      >
      ·
      <span class="sg-nw"
        >{{ NAMES.SW }}
        <b>{{ reach.SW === null ? "未达到" : `≈ ${number(reach.SW)} r` }}</b></span
      >
    </figcaption>
  </figure>
</template>

<style scoped>
.beating-sig {
  position: relative;
  margin: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.beating-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.beating-sig-empty {
  height: 120px;
  border-radius: var(--radius-sm);
}
.beating-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
  text-wrap: pretty;
}
.beating-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.sg-nw {
  white-space: nowrap;
}
.sg-base {
  stroke: var(--chart-axis);
  stroke-width: 1;
}
.sg-target {
  stroke: var(--chart-target);
  stroke-width: 1.2;
  stroke-dasharray: 4 4;
}
.sg-line {
  fill: none;
  stroke-width: 2.1;
  stroke-linecap: round;
  stroke-linejoin: round;
  /* the curves draw in once (killed by the global reduced-motion rule) */
  stroke-dasharray: 1;
  animation: sg-draw 1.4s var(--ease) backwards;
}
.sg-line:nth-of-type(2) {
  animation-delay: 0.12s;
}
@keyframes sg-draw {
  from {
    stroke-dashoffset: 1;
  }
}
.sg-drop {
  stroke-width: 1.3;
  stroke-dasharray: 2 3;
}
.sg-pt {
  stroke: var(--chart-paper);
  stroke-width: 1.6;
}
.sg-m {
  font-family: var(--font-mono);
  font-size: 10.5px;
  fill: var(--text-2);
}
.sg-v {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 500;
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--chart-paper);
  stroke-width: 3px;
  stroke-linejoin: round;
}
</style>
