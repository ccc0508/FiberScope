<script setup lang="ts">
import { vSeg } from "../../motion";
import FilterSelect from "../FilterSelect.vue";
import { MATERIALS, materialName, type Material } from "./types";

defineProps<{
  material: "all" | Material;
  metricKey: string;
  metricOptions: { value: string; label: string; hint?: string; group?: string }[];
  counts: { all: number; SW: number; HW: number };
  srRange: { lo: number; hi: number };
  histogram: { n: number; h: number; on: boolean; slice: Record<string, string> }[];
  listedCount: number;
  validCount: number;
  rangeActive: boolean;
}>();

const emit = defineEmits<{
  updateMaterial: [value: Material | undefined];
  updateMetric: [value: string];
  setRange: [lo: number, hi: number];
  resetRange: [];
}>();
</script>

<template>
  <section class="card beating-controls" aria-label="打浆分析筛选">
    <div class="ctl">
      <span class="field-label" id="beating-material-label">原料</span>
      <div
        v-seg
        class="seg beating-seg"
        role="radiogroup"
        aria-labelledby="beating-material-label"
      >
        <button
          v-for="opt in ['all', ...MATERIALS] as const"
          :key="opt"
          type="button"
          role="radio"
          :aria-checked="material === opt"
          :class="{ on: material === opt }"
          @click="emit('updateMaterial', opt === 'all' ? undefined : opt)"
        >
          <i v-if="opt !== 'all'" class="mk" :class="`mk-${opt}`"></i
          >{{ opt === "all" ? "全部" : materialName(opt)
          }}<span class="cnt">{{ counts[opt] }}</span>
        </button>
      </div>
    </div>
    <div class="ctl ctl-metric">
      <span class="field-label">分析指标</span
      ><FilterSelect
        id="beating-metric"
        label="分析指标"
        :model-value="metricKey"
        :options="metricOptions"
        @update:model-value="emit('updateMetric', $event)"
      />
    </div>
    <div class="ctl range-group">
      <div class="range-head">
        <span class="field-label" id="beating-sr-label">打浆度区间</span
        ><span class="range-val"
          >{{ srRange.lo }} – {{ srRange.hi }}<small>°SR</small></span
        >
      </div>
      <div class="hist" aria-hidden="true">
        <i
          v-for="(b, i) in histogram"
          :key="i"
          :class="{ out: !b.on }"
          :style="{ height: `${b.h}%`, ...b.slice }"
        ></i>
      </div>
      <div class="dual-range">
        <div class="dual-track">
          <i
            :style="{
              left: `${srRange.lo}%`,
              width: `${srRange.hi - srRange.lo}%`,
            }"
          ></i>
        </div>
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          :value="srRange.lo"
          aria-label="打浆度下限"
          @input="
            emit(
              'setRange',
              Math.min(+($event.target as HTMLInputElement).value, srRange.hi),
              srRange.hi,
            )
          "
        />
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          :value="srRange.hi"
          aria-label="打浆度上限"
          @input="
            emit(
              'setRange',
              srRange.lo,
              Math.max(+($event.target as HTMLInputElement).value, srRange.lo),
            )
          "
        />
      </div>
      <div class="ruler-labels">
        <span>0</span><span>50</span><span>100</span>
      </div>
    </div>
    <div class="count-group">
      <p class="beating-count" role="status">
        <span class="nw">{{ listedCount }} 个样本</span
        ><span class="sep" aria-hidden="true">·</span
        ><span class="nw">{{ validCount }} 个有效数据点</span>
      </p>
      <button
        v-if="rangeActive"
        class="text-button"
        type="button"
        @click="emit('resetRange')"
      >
        重置区间
      </button>
    </div>
  </section>
</template>

<style scoped>
.beating-controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 18px 28px;
  padding: 18px 22px;
  position: relative;
  z-index: 3;
}
.ctl {
  min-width: 0;
}
.beating-seg > button {
  gap: 8px;
}
.beating-seg > button.on .cnt {
  color: var(--text-2);
}
.count-group {
  margin-left: auto;
  align-self: center;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.beating-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
.beating-count .sep {
  margin: 0 10px;
  color: var(--text-3);
}
.range-group {
  width: 240px;
}
.range-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.range-head .field-label {
  margin-bottom: 4px;
}
.range-val {
  font: 500 13px var(--font-mono);
  color: var(--text);
}
.range-val small {
  margin-left: 3px;
  font-size: 11px;
  color: var(--text-3);
}
.hist {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 26px;
  padding: 0 4px;
}
.hist i {
  flex: 1;
  border-radius: 1px 1px 0 0;
  background: var(--text-3);
  transition: opacity 0.2s;
}
.hist i.out {
  opacity: 0.28;
}
.dual-range {
  position: relative;
  height: 18px;
}
.dual-track {
  position: absolute;
  left: 4px;
  right: 4px;
  top: 8px;
  height: 2px;
  background: var(--line-strong);
}
.dual-track i {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--accent);
}
.dual-range input {
  position: absolute;
  inset: 0;
  width: 100%;
  margin: 0;
  background: none;
  pointer-events: none;
  appearance: none;
  -webkit-appearance: none;
}
.dual-range input::-webkit-slider-runnable-track {
  height: 18px;
  background: none;
}
.dual-range input::-moz-range-track {
  height: 18px;
  background: none;
}
.dual-range input::-webkit-slider-thumb {
  -webkit-appearance: none;
  pointer-events: auto;
  width: 8px;
  height: 18px;
  border-radius: 1px;
  background: var(--accent);
  cursor: ew-resize;
}
.dual-range input::-moz-range-thumb {
  pointer-events: auto;
  width: 8px;
  height: 18px;
  border: 0;
  border-radius: 1px;
  background: var(--accent);
  cursor: ew-resize;
}
.dual-range input:focus-visible {
  outline: none;
}
.dual-range input:focus-visible::-webkit-slider-thumb {
  outline: 2.5px solid var(--focus);
  outline-offset: 2px;
}
.dual-range input:focus-visible::-moz-range-thumb {
  outline: 2.5px solid var(--focus);
  outline-offset: 2px;
}

:root[data-mode="polarized"] .beating-controls .field-label {
  margin-bottom: 8px;
}
:root[data-mode="polarized"] .range-head .field-label {
  margin-bottom: 4px;
}
:root[data-mode="polarized"] .hist i {
  background: var(--ifl);
  background-size: var(--bs);
  background-position: var(--bp);
  opacity: 0.85;
}
:root[data-mode="polarized"] .hist i.out {
  opacity: 0.22;
}
:root[data-mode="polarized"] .dual-track i {
  background: var(--ifl);
}
:root[data-mode="polarized"] .dual-range input::-webkit-slider-thumb {
  background: var(--text);
  box-shadow: 0 0 10px var(--accent-tint);
}
:root[data-mode="polarized"] .dual-range input::-moz-range-thumb {
  background: var(--text);
}

:root[data-mode="garden"] .beating-controls {
  padding: 22px 24px;
}
:root[data-mode="garden"] .beating-count {
  font-family: var(--font-body);
  font-size: 13px;
}
:root[data-mode="garden"] .hist i {
  border-radius: 4px 4px 1px 1px;
  background: var(--rc);
  opacity: 0.75;
}
:root[data-mode="garden"] .hist i.out {
  opacity: 0.22;
}
:root[data-mode="garden"] .dual-range {
  height: 22px;
}
:root[data-mode="garden"] .dual-track {
  top: 8px;
  height: 6px;
  border-radius: 999px;
  background: var(--accent-tint);
}
:root[data-mode="garden"] .dual-track i {
  border-radius: 999px;
  background: var(--accent);
}
:root[data-mode="garden"] .dual-range input::-webkit-slider-runnable-track {
  height: 22px;
}
:root[data-mode="garden"] .dual-range input::-moz-range-track {
  height: 22px;
}
:root[data-mode="garden"] .dual-range input::-webkit-slider-thumb {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow:
    inset 0 0 0 4px var(--accent),
    var(--shadow-sm);
}
:root[data-mode="garden"] .dual-range input::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow: inset 0 0 0 4px var(--accent);
}

@media (max-width: 720px) {
  .beating-controls {
    gap: 14px;
    padding: 16px;
  }
  .beating-controls > .ctl,
  .range-group {
    width: 100%;
  }
  .count-group {
    margin-left: 0;
    width: 100%;
    align-items: flex-start;
  }
  :root[data-mode="garden"] .beating-controls {
    padding: 18px;
  }
  :root[data-mode="garden"] .beating-seg > button {
    padding: 0 10px;
  }
}
</style>
