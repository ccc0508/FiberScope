<script setup lang="ts">
import { ChevronLeft, ChevronRight } from "lucide-vue-next";
import { number } from "../../api";
import { materialColor, materialName, typeOfMaterial, type BeatingRow, type Material } from "./types";

const props = defineProps<{
  selected: BeatingRow | null;
  selectedIndex: number;
  listedCount: number;
  metricKey: string;
  metricName: string;
  unit: string;
  digits: number;
  xMax: number;
  target: number;
  selectedReachPct: number | null;
  toTarget: { gap: number; revs: number | null } | null;
  otherAtSameRevs: { code: Material; value: number | null; estimated: boolean } | null;
  valueBar: (v: number | null) => number;
}>();

const emit = defineEmits<{
  openDetail: [row: BeatingRow];
  step: [delta: number];
}>();

const value = (r: BeatingRow): number | null =>
  typeof r[props.metricKey] === "number" && Number.isFinite(r[props.metricKey])
    ? (r[props.metricKey] as number)
    : null;
const fmt = (v: number | null) => number(v, props.digits);
</script>

<template>
  <section class="card beating-readout" aria-labelledby="beating-readout-title">
    <div class="readout-head">
      <h2 id="beating-readout-title">样本读数</h2>
      <span v-if="selected" class="readout-pos"
        >{{ selectedIndex + 1 }} / {{ listedCount }}</span
      >
    </div>
    <div v-if="selected" class="readout-body">
      <div class="readout-id">
        <div class="readout-code">{{ selected.canonical_code }}</div>
        <div class="readout-name-row">
          <span class="readout-name">{{ selected.display_name }}</span>
          <span class="type-tag" :class="typeOfMaterial(selected.material_code)"
            ><i></i>{{ materialName(selected.material_code) }}</span
          >
        </div>
      </div>
      <div class="readout-big">
        <div class="readout-cell">
          <span class="readout-k">{{ metricName }}</span>
          <p class="readout-num">
            <strong>{{ fmt(value(selected)) }}</strong
            ><small>{{ unit }}</small>
          </p>
        </div>
        <div class="readout-cell">
          <span class="readout-k">打浆转数</span>
          <p class="readout-num sm">
            <strong>{{ number(selected.beating_revolutions) }}</strong
            ><small>r</small>
          </p>
        </div>
      </div>
      <div class="readout-block readout-prog">
        <div class="block-head">
          <span>打浆进程</span
          ><span class="mono"
            ><b>{{ number(selected.beating_revolutions) }}</b> /
            {{ number(xMax) }} r</span
          >
        </div>
        <div class="track">
          <i
            :style="{
              width: `${(selected.beating_revolutions / xMax) * 100}%`,
              background: materialColor(selected.material_code),
            }"
          ></i
          ><b
            v-if="selectedReachPct !== null"
            :style="{ left: `${selectedReachPct}%` }"
            :title="`${materialName(selected.material_code)}达到目标的转数`"
          ></b>
        </div>
      </div>
      <div v-if="toTarget" class="readout-block readout-target">
        <div class="block-head">
          <span>距目标 {{ target }} °SR</span
          ><span v-if="toTarget.gap <= 0">已达到</span>
        </div>
        <div class="target-gap">
          <div>
            <strong>{{
              toTarget.gap > 0 ? number(toTarget.gap, 1) : "0"
            }}</strong
            ><small>°SR</small>
            <span>还差</span>
          </div>
          <div>
            <strong>{{
              toTarget.gap <= 0
                ? "—"
                : toTarget.revs === null
                  ? "未达到"
                  : number(toTarget.revs)
            }}</strong
            ><small v-if="toTarget.gap > 0 && toTarget.revs !== null"
              >r</small
            >
            <span>约需再打浆</span>
          </div>
        </div>
        <p class="kpi-note">
          {{
            toTarget.gap > 0 && toTarget.revs === null
              ? `${materialName(selected.material_code)}在实测范围内没有达到目标。`
              : "转数按本原料相邻实测点线性插值估算，取整到百转。"
          }}
        </p>
      </div>
      <div v-if="otherAtSameRevs" class="readout-block readout-cmp">
        <div class="block-head">
          <span>同转数下另一种原料</span
          ><span class="mono">{{ number(selected.beating_revolutions) }} r</span>
        </div>
        <div class="compare-row me">
          <span
            ><i class="mk" :class="`mk-${selected.material_code}`"></i
            >{{ materialName(selected.material_code) }}</span
          >
          <div class="track">
            <i
              :style="{
                width: `${valueBar(value(selected))}%`,
                background: materialColor(selected.material_code),
              }"
            ></i>
          </div>
          <b>{{ fmt(value(selected)) }}</b>
        </div>
        <div class="compare-row">
          <span
            ><i class="mk" :class="`mk-${otherAtSameRevs.code}`"></i
            >{{ materialName(otherAtSameRevs.code) }}</span
          >
          <div class="track">
            <i
              :style="{
                width: `${valueBar(otherAtSameRevs.value)}%`,
                background: materialColor(otherAtSameRevs.code),
              }"
            ></i>
          </div>
          <b
            >{{ otherAtSameRevs.estimated ? "≈" : ""
            }}{{ fmt(otherAtSameRevs.value) }}</b
          >
        </div>
        <p class="kpi-note">
          <template v-if="otherAtSameRevs.value === null"
            >该转数超出{{
              materialName(otherAtSameRevs.code)
            }}的实测范围，不外推。</template
          ><template v-else-if="otherAtSameRevs.estimated"
            >{{
              materialName(otherAtSameRevs.code)
            }}在该转数无实测，按相邻实测点线性插值。</template
          ><template v-else>两种原料在该转数都有实测。</template>
        </p>
      </div>
      <div class="readout-actions">
        <button
          class="button primary readout-open"
          type="button"
          @click="emit('openDetail', selected)"
        >
          查看样本详情与来源
        </button>
        <div class="readout-nav">
          <button
            class="button"
            type="button"
            :disabled="selectedIndex <= 0"
            aria-label="上一个样本"
            @click="emit('step', -1)"
          >
            <ChevronLeft :size="15" />上一个
          </button>
          <button
            class="button"
            type="button"
            :disabled="selectedIndex >= listedCount - 1"
            aria-label="下一个样本"
            @click="emit('step', 1)"
          >
            下一个<ChevronRight :size="15" />
          </button>
        </div>
      </div>
    </div>
    <p v-else class="beating-state">暂无匹配数据。</p>
  </section>
</template>

<style scoped>
.beating-readout {
  padding: 22px;
  display: flex;
  flex-direction: column;
}
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.readout-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.readout-head h2 {
  font-size: 17px;
}
.readout-pos {
  font: 400 13px var(--font-mono);
  color: var(--text-2);
}
.readout-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
  flex: 1;
}
.readout-code {
  font: 400 12px var(--font-mono);
  color: var(--text-2);
}
.readout-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  margin-top: 4px;
}
.readout-name {
  color: var(--text);
}
.readout-big {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.readout-k {
  font-size: 12px;
  color: var(--text-2);
}
.readout-num {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 2px;
  color: var(--text);
}
.readout-num strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 400;
  line-height: 1.05;
  white-space: nowrap;
}
.readout-num small {
  font-size: 12px;
  color: var(--text-2);
}
.readout-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--text-2);
}
.block-head b {
  font-weight: 500;
  color: var(--text);
}
.track {
  position: relative;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.track i {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  transition: width 0.3s var(--ease);
}
.track b {
  position: absolute;
  top: -4px;
  width: 2px;
  height: 12px;
  margin-left: -1px;
  border-radius: 1px;
  background: var(--text);
}
.target-gap {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.target-gap div {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-wrap: wrap;
}
.target-gap strong {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  font-weight: 300;
  font-size: 26px;
  line-height: 1.1;
  color: var(--text);
}
.target-gap small {
  font-size: 12px;
  color: var(--text-2);
}
.target-gap span {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--text-2);
}
.compare-row {
  display: grid;
  grid-template-columns: 84px 1fr 56px;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-2);
}
.compare-row > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}
.compare-row b {
  font: 500 12.5px var(--font-mono);
  color: var(--text-2);
  text-align: right;
}
.compare-row.me,
.compare-row.me b {
  color: var(--text);
}
.compare-row:not(.me) .track i {
  opacity: 0.6;
}
.readout-actions {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.readout-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

:root[data-mode="polarized"] .readout-name {
  display: block;
  width: 100%;
  font-size: 22px;
  font-weight: 900;
  line-height: 1.3;
}
:root[data-mode="polarized"] .readout-num strong {
  font-weight: 200;
  font-size: 40px;
  letter-spacing: -0.04em;
}
:root[data-mode="polarized"] .readout-num.sm strong {
  font-size: 30px;
  font-weight: 300;
}
:root[data-mode="polarized"] .readout-target {
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .target-gap strong {
  letter-spacing: -0.03em;
}
:root[data-mode="polarized"] .readout-cmp {
  padding: 12px;
  border-radius: 12px;
  background: var(--surface-2);
}
:root[data-mode="polarized"] .readout-open {
  width: 100%;
}

:root[data-mode="garden"] .beating-readout {
  padding: 22px 24px;
}
:root[data-mode="garden"] .readout-head {
  justify-content: space-between;
}
:root[data-mode="garden"] .readout-head h2 {
  font-size: 18px;
}
:root[data-mode="garden"] .readout-code {
  font-size: 20px;
  color: var(--text);
}
:root[data-mode="garden"] .readout-name {
  font-size: 14px;
}
:root[data-mode="garden"] .readout-num strong {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  font-size: 60px;
  line-height: 0.95;
}
:root[data-mode="garden"] .readout-num small {
  font-size: 14px;
}
:root[data-mode="garden"] .readout-num.sm strong {
  font-family: var(--font-mono);
  font-variation-settings: normal;
  font-weight: 400;
  font-size: 22px;
  letter-spacing: 0;
}
:root[data-mode="garden"] .readout-big {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
}
:root[data-mode="garden"] .readout-prog,
:root[data-mode="garden"] .target-gap > div {
  padding: 12px 14px;
  border-radius: 18px;
  background: var(--surface-2);
}
:root[data-mode="garden"] .readout-target {
  gap: 10px;
}
:root[data-mode="garden"] .target-gap strong {
  font-family: var(--font-mono);
  font-weight: 400;
  font-size: 18px;
}
:root[data-mode="garden"] .track {
  height: 8px;
  border-radius: 9px;
}
:root[data-mode="garden"] .compare-row .track {
  height: 10px;
  background: var(--line-soft);
}
:root[data-mode="garden"] .compare-row {
  grid-template-columns: 92px 1fr 64px;
  font-size: 13px;
}
:root[data-mode="garden"] .readout-actions {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
}
:root[data-mode="garden"] .readout-nav {
  display: flex;
  gap: 8px;
}
:root[data-mode="garden"] .readout-actions .button {
  min-height: 34px;
  padding: 0 14px;
  font-size: 13px;
}

@media (max-width: 720px) {
  .beating-readout {
    padding: 16px;
  }
  :root[data-mode="polarized"] .readout-num strong {
    font-size: 34px;
  }
  :root[data-mode="polarized"] .readout-num.sm strong {
    font-size: 28px;
  }
  :root[data-mode="garden"] .readout-num strong {
    font-size: 50px;
  }
}
</style>
