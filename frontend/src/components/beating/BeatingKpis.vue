<script setup lang="ts">
import { computed, ref } from "vue";
import { Minus, Plus } from "lucide-vue-next";
import { number } from "../../api";
import type { CurvePoint } from "../../beating";
import { useCountUp, vTilt } from "../../motion";
import { MATERIALS, TARGET_MAX, TARGET_MIN, materialName, type Material } from "./types";

const props = defineProps<{
  isSr: boolean;
  target: number;
  material: "all" | Material;
  reach: Record<Material, number | null>;
  reachGap: number | null;
  xMax: number;
  metricName: string;
  unit: string;
  digits: number;
  validCount: number;
  visibleCount: number;
  changes: Record<Material, { from: CurvePoint; to: CurvePoint; pct: number | null } | null>;
}>();

const emit = defineEmits<{
  setTarget: [value: number];
}>();

const round100 = (v: number) => Math.round(v / 100) * 100;
const fmt = (v: number | null) => number(v, props.digits);

const kpiEl = ref<HTMLElement>();
const swReachShown = useCountUp(
  () => (props.isSr && props.reach.SW !== null ? round100(props.reach.SW) : null),
  { el: kpiEl },
);
const hwReachShown = useCountUp(
  () => (props.isSr && props.reach.HW !== null ? round100(props.reach.HW) : null),
  { el: kpiEl },
);
const gapShown = useCountUp(
  () =>
    props.isSr && props.reachGap !== null
      ? round100(Math.abs(props.reachGap))
      : null,
  { el: kpiEl },
);
const reachShown = computed<Record<Material, number | null>>(() => ({
  SW: swReachShown.value,
  HW: hwReachShown.value,
}));
</script>

<template>
  <section
    ref="kpiEl"
    class="card beating-kpis"
    :class="{ 'is-sr': isSr }"
    aria-label="关键指标"
  >
    <template v-if="isSr">
      <div class="kpi kpi-target">
        <div class="kpi-label">
          <label for="beating-target">目标打浆度</label>
        </div>
        <div class="kpi-target-row">
          <button
            type="button"
            class="step-btn"
            aria-label="目标打浆度降低 5"
            :disabled="target <= TARGET_MIN"
            @click="emit('setTarget', target - 5)"
          >
            <Minus :size="14" />
          </button>
          <output class="kpi-value" for="beating-target"
            ><strong>{{ target }}</strong><small>°SR</small></output
          >
          <button
            type="button"
            class="step-btn"
            aria-label="目标打浆度提高 5"
            :disabled="target >= TARGET_MAX"
            @click="emit('setTarget', target + 5)"
          >
            <Plus :size="14" />
          </button>
        </div>
        <input
          id="beating-target"
          class="beating-range"
          type="range"
          :min="TARGET_MIN"
          :max="TARGET_MAX"
          step="1"
          :value="target"
          :aria-valuetext="`${target} °SR`"
          @input="emit('setTarget', +($event.target as HTMLInputElement).value)"
        />
        <div class="ruler-labels">
          <span>{{ TARGET_MIN }}</span><span>{{ TARGET_MAX }}</span>
        </div>
      </div>
      <h3 class="kpi-reach-h">
        达到 <b>{{ target }}</b> °SR 所需转数
      </h3>
      <div
        v-for="code in MATERIALS"
        :key="code"
        v-tilt
        class="kpi kpi-mat"
        :class="[`kpi-${code}`, { dim: material !== 'all' && material !== code }]"
      >
        <div class="kpi-label">
          <i class="mk" :class="`mk-${code}`"></i
          ><span>{{ materialName(code) }}</span
          ><span class="kpi-label-target nw"> · 达到 {{ target }} °SR</span>
        </div>
        <div class="kpi-value">
          <template v-if="reach[code] !== null"
            ><strong
              ><span aria-hidden="true">{{
                number(reachShown[code] ?? round100(reach[code]!))
              }}</span
              ><span class="sr-only">{{
                number(round100(reach[code]!))
              }}</span></strong
            ><small>转</small></template
          ><strong v-else class="na">未达到</strong>
        </div>
        <div class="kpi-track" aria-hidden="true">
          <i
            v-if="reach[code] !== null"
            :style="{
              '--at': `${Math.min(100, (reach[code]! / xMax) * 100)}%`,
            }"
          ></i>
        </div>
        <div class="ruler-labels kpi-scale-row">
          <span>0</span><span>{{ number(xMax) }}</span>
        </div>
      </div>
      <div class="ruler-labels kpi-scale" aria-hidden="true">
        <span>0</span><span>{{ number(xMax) }} r</span>
      </div>
      <div class="kpi kpi-diff">
        <div class="kpi-label">两种原料相差</div>
        <div class="kpi-value">
          <template v-if="reachGap !== null"
            ><strong
              ><span aria-hidden="true">{{
                number(gapShown ?? round100(Math.abs(reachGap)))
              }}</span
              ><span class="sr-only">{{
                number(round100(Math.abs(reachGap)))
              }}</span></strong
            ><small>转</small></template
          ><strong v-else class="na">—</strong>
        </div>
        <p class="kpi-note">
          <template v-if="reachGap !== null"
            >{{
              reachGap > 0 ? "阔叶木浆" : "针叶木浆"
            }}更早达到目标。</template
          >按相邻实测点线性插值估算，取整到百转。
        </p>
      </div>
    </template>
    <template v-else>
      <div
        v-for="code in MATERIALS"
        :key="code"
        v-tilt
        class="kpi kpi-mat wide"
        :class="[`kpi-${code}`, { dim: material !== 'all' && material !== code }]"
      >
        <div class="kpi-label">
          <i class="mk" :class="`mk-${code}`"></i
          ><span>{{ materialName(code) }} · {{ metricName }}</span>
        </div>
        <div v-if="changes[code]" class="kpi-value">
          <strong>{{ fmt(changes[code]!.to.y) }}</strong
          ><small>{{ unit }}</small>
          <span v-if="changes[code]!.pct !== null" class="delta"
            >{{ changes[code]!.pct! >= 0 ? "+" : "−"
            }}{{ number(Math.abs(changes[code]!.pct!), 1) }}%</span
          >
        </div>
        <div v-else class="kpi-value"><strong class="na">—</strong></div>
        <p v-if="changes[code]" class="kpi-note">
          <span class="nw"
            >{{ number(changes[code]!.from.x) }} 转时
            {{ fmt(changes[code]!.from.y) }}</span
          >
          →
          <span class="nw"
            >{{ number(changes[code]!.to.x) }} 转时
            {{ fmt(changes[code]!.to.y) }}</span
          >
        </p>
      </div>
      <div class="kpi kpi-valid">
        <div class="kpi-label">有效数据点</div>
        <div class="kpi-value">
          <strong>{{ validCount }}</strong
          ><small>/ {{ visibleCount }}</small>
        </div>
        <p class="kpi-note">缺失值不计入，曲线在缺失处断开。</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.beating-kpis {
  display: grid;
  grid-template-columns: 1fr 1fr 0.8fr;
  padding: 0;
}
.beating-kpis.is-sr {
  grid-template-columns: 1.15fr 1fr 1fr 1fr;
}
.kpi {
  position: relative;
  min-width: 0;
  padding: 20px 22px;
  transition: opacity 0.15s;
}
.kpi.dim .kpi-value,
.kpi.dim .kpi-value strong {
  color: var(--text-2);
}
.kpi.dim .mk,
.kpi.dim .kpi-track {
  opacity: 0.35;
}
.kpi-label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 6px;
  font-size: 12.5px;
  color: var(--text-2);
}
.kpi-label .mk {
  margin-right: 2px;
}
.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 8px 0 10px;
  min-height: 46px;
  color: var(--text);
}
.kpi-value strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.05;
  white-space: nowrap;
}
.kpi-value strong.na {
  font-family: var(--font-body);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-2);
}
.kpi-value small {
  font-size: 13px;
  color: var(--text-2);
}
.kpi-value .delta {
  margin-left: 6px;
  font: 500 13px var(--font-mono);
  color: var(--text-2);
}
.kpi-target-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.kpi-target-row .kpi-value {
  margin: 4px 0 6px;
}
.step-btn {
  width: 34px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  color: var(--text);
  transition:
    background 0.15s,
    border-color 0.15s,
    transform 0.3s var(--spring);
}
.step-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--text-3);
}
.beating-range {
  display: block;
  width: 100%;
  height: 24px;
  border-radius: 999px;
  margin: 2px 0 2px;
  background: transparent;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
}
.beating-range::-webkit-slider-runnable-track {
  height: 3px;
  border-radius: 2px;
  background: var(--line-strong);
}
.beating-range::-moz-range-track {
  height: 3px;
  border-radius: 2px;
  background: var(--line-strong);
}
.beating-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin-top: -6.5px;
  border-radius: 50%;
  background: var(--text);
}
.beating-range::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: var(--text);
}
.kpi-track {
  position: relative;
  height: 3px;
  margin: 8px 0 6px;
  border-radius: 2px;
  background: var(--line);
}
.kpi-track i {
  position: absolute;
  top: -4px;
  left: var(--at);
  width: 3px;
  height: 11px;
  border-radius: 2px;
  transform: translateX(-1px);
  transition:
    left 0.3s var(--ease),
    width 0.8s var(--ease);
}
.kpi-SW .kpi-track i {
  background: var(--sw);
}
.kpi-HW .kpi-track i {
  background: var(--hw);
}
.kpi-reach-h,
.kpi-scale {
  display: none;
}

:root[data-mode="polarized"] .kpi:not(:first-child) {
  border-left: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .kpi-label {
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .kpi-value strong {
  font-weight: 200;
  font-size: 46px;
  letter-spacing: -0.04em;
}
:root[data-mode="polarized"] .kpi-value strong.na {
  font-weight: 700;
  font-size: 22px;
  letter-spacing: 0.02em;
}
:root[data-mode="polarized"] .kpi-value small {
  font-size: 13px;
}
:root[data-mode="polarized"] .kpi-target-row .kpi-value {
  min-width: 0;
}
:root[data-mode="polarized"] .beating-range::-webkit-slider-runnable-track {
  background: var(--ifl);
  opacity: 0.9;
}
:root[data-mode="polarized"] .beating-range::-moz-range-track {
  background: var(--ifl);
}
:root[data-mode="polarized"] .beating-range::-webkit-slider-thumb {
  box-shadow:
    0 0 0 4px var(--bg),
    0 0 16px var(--text-3);
}
:root[data-mode="polarized"] .beating-range::-moz-range-thumb {
  box-shadow:
    0 0 0 4px var(--bg),
    0 0 16px var(--text-3);
}
:root[data-mode="polarized"] .beating-range:focus-visible {
  outline-offset: 4px;
}

:root[data-mode="garden"] .beating-kpis {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 22px 24px;
}
:root[data-mode="garden"] .kpi {
  padding: 0;
}
:root[data-mode="garden"] .kpi-value strong {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  line-height: 0.92;
}
:root[data-mode="garden"] .kpi-value strong.na {
  font-variation-settings: normal;
  font-weight: 500;
  font-size: 20px;
  letter-spacing: 0.02em;
}
:root[data-mode="garden"] .kpi-value small {
  font-size: 14px;
}
:root[data-mode="garden"] .kpi-target {
  padding-bottom: 6px;
}
:root[data-mode="garden"] .kpi-target-row {
  gap: 6px;
}
:root[data-mode="garden"] .kpi-target-row .kpi-value {
  order: -1;
  margin: 6px auto 4px 0;
  min-height: 0;
}
:root[data-mode="garden"] .kpi-target-row .kpi-value strong {
  font-size: 42px;
}
:root[data-mode="garden"] .step-btn {
  width: 32px;
  height: 32px;
  border: 0;
  background: var(--surface);
  box-shadow:
    inset 0 0 0 1px var(--line),
    var(--shadow-sm);
}
:root[data-mode="garden"] .step-btn:hover:not(:disabled) {
  background: var(--surface);
  transform: translateY(-1px);
}
:root[data-mode="garden"] .step-btn:active:not(:disabled) {
  transform: scale(0.94);
}
:root[data-mode="garden"] .beating-range {
  height: 26px;
}
:root[data-mode="garden"] .beating-range::-webkit-slider-runnable-track {
  height: 8px;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--accent-tint), var(--rc));
}
:root[data-mode="garden"] .beating-range::-moz-range-track {
  height: 8px;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--accent-tint), var(--rc));
}
:root[data-mode="garden"] .beating-range::-webkit-slider-thumb {
  width: 24px;
  height: 24px;
  margin-top: -8px;
  background: var(--surface);
  box-shadow:
    var(--shadow-sm),
    inset 0 0 0 6px var(--text);
}
:root[data-mode="garden"] .beating-range::-moz-range-thumb {
  width: 22px;
  height: 22px;
  background: var(--surface);
  box-shadow: inset 0 0 0 6px var(--text);
}
:root[data-mode="garden"] .kpi-reach-h {
  display: block;
  margin-top: 6px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 15px;
  line-height: 1.35;
  color: var(--text);
}
:root[data-mode="garden"] .kpi-reach-h b {
  font-family: var(--font-mono);
  font-weight: 500;
}
:root[data-mode="garden"] .kpi-label-target,
:root[data-mode="garden"] .kpi-scale-row {
  display: none;
}
:root[data-mode="garden"] .kpi-mat {
  flex: 1;
  display: grid;
  align-content: center;
  gap: 6px;
  padding: 12px 16px 14px;
  border-radius: 18px;
  background: linear-gradient(150deg, var(--surface), var(--sw-tint));
}
:root[data-mode="garden"] .kpi-mat.kpi-HW {
  background: linear-gradient(150deg, var(--surface), var(--hw-tint));
}
:root[data-mode="garden"] .kpi-mat.dim {
  background: var(--surface-2);
}
:root[data-mode="garden"] .kpi-mat .kpi-label {
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .kpi-mat .kpi-value {
  margin: 2px 0 0;
}
:root[data-mode="garden"] .kpi-mat .kpi-value strong {
  font-size: 56px;
}
:root[data-mode="garden"] .kpi-mat.wide .kpi-value strong {
  font-size: 46px;
}
:root[data-mode="garden"] .kpi-track {
  height: 10px;
  margin: 4px 0 2px;
  border-radius: 9px;
  background: var(--line-soft);
  overflow: hidden;
}
:root[data-mode="garden"] .kpi-track i {
  top: 0;
  bottom: 0;
  left: 0;
  height: auto;
  width: var(--at);
  border-radius: 9px;
  transform: none;
}
:root[data-mode="garden"] .kpi-scale {
  display: flex;
  font-size: 11px;
  color: var(--text-2);
}
:root[data-mode="garden"] .kpi-diff,
:root[data-mode="garden"] .kpi-valid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 4px 10px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
:root[data-mode="garden"] .kpi-diff .kpi-label,
:root[data-mode="garden"] .kpi-valid .kpi-label {
  font-size: 13.5px;
}
:root[data-mode="garden"] .kpi-diff .kpi-value,
:root[data-mode="garden"] .kpi-valid .kpi-value {
  margin: 0;
  min-height: 0;
}
:root[data-mode="garden"] .kpi-diff .kpi-value strong,
:root[data-mode="garden"] .kpi-valid .kpi-value strong {
  font-size: 40px;
  color: var(--accent-ink);
}
:root[data-mode="garden"] .kpi-diff .kpi-note,
:root[data-mode="garden"] .kpi-valid .kpi-note {
  grid-column: 1 / -1;
}

@media (max-width: 1100px) {
  :root[data-mode="polarized"] .beating-kpis.is-sr {
    grid-template-columns: 1fr 1fr;
  }
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-target,
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-HW {
    border-left: 0;
  }
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-target,
  :root[data-mode="polarized"] .beating-kpis.is-sr .kpi-SW {
    border-bottom: 1px solid var(--line-soft);
  }
}
@media (max-width: 720px) {
  :root[data-mode="polarized"] .beating-kpis,
  :root[data-mode="polarized"] .beating-kpis.is-sr {
    grid-template-columns: 1fr 1fr;
  }
  :root[data-mode="polarized"] .kpi {
    padding: 16px 14px;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi {
    border-left: 0;
    border-bottom: 0;
    border-top: 1px solid var(--line-soft);
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi:first-child {
    border-top: 0;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi-target,
  :root[data-mode="polarized"] .beating-kpis .kpi-diff,
  :root[data-mode="polarized"] .beating-kpis .kpi-valid {
    grid-column: 1 / -1;
  }
  :root[data-mode="polarized"] .beating-kpis .kpi.kpi-HW {
    border-left: 1px solid var(--line-soft);
  }
  :root[data-mode="polarized"] .kpi-value strong {
    font-size: 32px;
  }
  :root[data-mode="polarized"] .kpi-target .kpi-value strong {
    font-size: 46px;
  }
  :root[data-mode="garden"] .beating-kpis {
    padding: 18px;
  }
  :root[data-mode="garden"] .kpi-mat .kpi-value strong {
    font-size: 44px;
  }
}
</style>
