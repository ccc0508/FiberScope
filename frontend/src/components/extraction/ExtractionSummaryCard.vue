<script setup lang="ts">
import { computed, ref } from "vue";
import { Check, ChevronDown, Download, Ellipsis, Info, X } from "lucide-vue-next";
import type { ExtractionTask } from "../../extraction";
import { useCountUp, vTilt } from "../../motion";

const props = defineProps<{
  task: ExtractionTask;
  summary: {
    total: number;
    confirmed: number;
    rejected: number;
    pending: number;
    suitable: number;
  };
  measurementsCount: number;
  scanNotices: string[];
  exporting: boolean;
}>();

const emit = defineEmits<{
  download: [format: "csv" | "jsonl"];
}>();

const totalEl = ref<HTMLElement>();
const shownTotal = useCountUp(() => props.summary.total, { el: totalEl });
const pageCount = computed(() => props.task.snapshot?.evidence?.page_count ?? null);

function share(n: number) {
  return props.summary.total ? `${((n / props.summary.total) * 100).toFixed(1)}%` : "—";
}
</script>

<template>
  <section class="card ld-sum" aria-labelledby="ld-sum-title">
    <div class="ld-sum-top">
      <div class="ld-sum-id">
        <p class="eyebrow" aria-hidden="true">Current extraction</p>
        <h2 id="ld-sum-title">{{ task.source.filename }}</h2>
        <p class="ld-sum-meta">
          {{ summary.total }} 条候选 · 已确认 {{ summary.confirmed }} ·
          待核对 {{ summary.pending }} · 已驳回 {{ summary.rejected
          }}<template v-if="pageCount != null"> · PDF 共 {{ pageCount }} 页</template>
        </p>
      </div>
      <div class="export-actions" role="group" aria-label="导出已确认数据">
        <button
          type="button"
          class="button"
          :disabled="!summary.confirmed || exporting"
          @click="emit('download', 'csv')"
        >
          <Download :size="14" aria-hidden="true" />导出已确认 CSV</button
        ><button
          type="button"
          class="button"
          :disabled="!summary.confirmed || exporting"
          @click="emit('download', 'jsonl')"
        >
          JSONL
        </button>
      </div>
    </div>
    <div class="ld-sum-big">
      <p class="ld-sum-n">
        <span ref="totalEl" class="big-number"
          ><span aria-hidden="true">{{ shownTotal ?? "—" }}</span
          ><span class="sr-only">{{ summary.total }}</span></span
        ><span class="ld-sum-unit">条候选</span>
      </p>
      <div
        class="ld-sum-bar"
        role="img"
        :aria-label="`已确认 ${summary.confirmed}，待核对 ${summary.pending}，已驳回 ${summary.rejected}`"
      >
        <i v-if="summary.confirmed" class="sb-ok" :style="{ flexGrow: summary.confirmed }"></i
        ><i v-if="summary.pending" class="sb-wait" :style="{ flexGrow: summary.pending }"></i
        ><i v-if="summary.rejected" class="sb-bad" :style="{ flexGrow: summary.rejected }"></i>
      </div>
      <ul class="ld-sum-legend">
        <li class="lg-ok">
          <span class="st-ic" aria-hidden="true"><Check :size="11" :stroke-width="3" /></span
          ><span class="lg-l">已确认</span><b class="lg-n">{{ summary.confirmed }}</b
          ><span class="lg-p">{{ share(summary.confirmed) }}</span>
        </li>
        <li class="lg-wait">
          <span class="st-ic" aria-hidden="true"><Ellipsis :size="11" :stroke-width="3" /></span
          ><span class="lg-l">待核对</span><b class="lg-n">{{ summary.pending }}</b
          ><span class="lg-p">{{ share(summary.pending) }}</span>
        </li>
        <li class="lg-bad">
          <span class="st-ic" aria-hidden="true"><X :size="11" :stroke-width="3" /></span
          ><span class="lg-l">已驳回</span><b class="lg-n">{{ summary.rejected }}</b
          ><span class="lg-p">{{ share(summary.rejected) }}</span>
        </li>
      </ul>
    </div>
    <details v-if="task.snapshot?.result?.coverage" class="ld-scan" open>
      <summary>
        <Info class="ld-scan-ic" :size="16" aria-hidden="true" />
        <span>自动发现结果 · {{ task.snapshot.result.coverage_complete ? '逐页扫描已完成' : '部分内容未完成，请查看说明' }}</span>
        <ChevronDown class="ld-chevron" :size="16" aria-hidden="true" />
      </summary>
      <p class="ld-scan-note">扫描完成表示各页已处理，不保证发现全部数据；所有候选仍需核对，不自动认可建模适用性。</p>
      <p v-if="!measurementsCount" class="ld-scan-note">本次没有得到通过证据校验的候选数据。可查看扫描说明，或切换指定表格模式重新提取。</p>
      <ul
        v-if="task.snapshot.result.discovered_tables?.length"
        :class="['ld-tables', { few: task.snapshot.result.discovered_tables.length < 3 }]"
      >
        <li
          v-for="(t, index) in task.snapshot.result.discovered_tables"
          :key="index"
          v-tilt
          :class="['ld-tcard', { failed: t.status !== 'extracted' }]"
        >
          <strong class="tc-h"
            ><span class="tc-page">第 {{ t.page }} 页</span><span class="tc-sep"> · </span
            ><span class="tc-table">{{ t.table }}</span></strong
          >
          <span v-if="t.status === 'extracted'" class="tc-n"
            ><b>{{ t.measurement_count ?? "—" }}</b><span>条已提取</span></span
          >
          <span v-else class="tc-n tc-fail">未提取成功</span>
          <span class="tc-bar" aria-hidden="true"
            ><i
              :style="{
                width: `${summary.total && t.status === 'extracted' ? Math.min(100, ((t.measurement_count ?? 0) / summary.total) * 100) : 0}%`,
              }"
            ></i
          ></span>
          <p>{{ t.reason }}</p>
        </li>
      </ul>
      <details v-if="scanNotices.length" class="scan-notes">
        <summary>
          <span>扫描说明与未提取内容（{{ scanNotices.length }}）</span>
          <ChevronDown class="ld-chevron" :size="16" aria-hidden="true" />
        </summary>
        <ul><li v-for="(warning, index) in scanNotices" :key="index">{{ warning }}</li></ul>
      </details>
    </details>
  </section>
</template>

<style scoped>
.ld-sum-top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px 20px;
}
.ld-sum-id {
  min-width: 0;
}
.ld-sum-id h2 {
  margin: 6px 0 4px;
  font-size: 18px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.ld-sum-meta {
  font-size: 12.5px;
  color: var(--text-2);
}
.export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
:root[data-mode="polarized"] .ld-sum-id h2 {
  font-family: var(--font-mono);
  font-weight: 400;
  letter-spacing: 0;
}
:root[data-mode="polarized"] .ld-sum-meta {
  font-family: var(--font-mono);
  font-size: 12px;
}
:root[data-mode="polarized"] .export-actions .button {
  min-height: 34px;
  padding: 0 14px;
  font-size: 13px;
}
:root[data-mode="garden"] .ld-sum-id h2 {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-weight: 420;
  font-size: 26px;
  letter-spacing: 0;
}
.ld-sum-big {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "n bar"
    "n legend";
  align-items: center;
  gap: 12px 28px;
  margin: 22px 0 20px;
}
.ld-sum-n {
  grid-area: n;
  display: grid;
  margin: 0;
}
.ld-sum-n .big-number {
  font-size: clamp(64px, 7vw, 104px);
  line-height: 0.95;
}
.ld-sum-unit {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-2);
}
.ld-sum-bar {
  grid-area: bar;
  display: flex;
  gap: 2px;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
.ld-sum-bar i {
  display: block;
  flex: 1 1 0;
  min-width: 4px;
  height: 100%;
}
.sb-ok {
  background: var(--ok);
}
.sb-bad {
  background: var(--bad);
}
.sb-wait {
  background: color-mix(in srgb, var(--text-2) 58%, transparent);
}
.ld-sum-legend {
  grid-area: legend;
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  font-size: 13px;
  color: var(--text-2);
}
.ld-sum-legend li {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.lg-n {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.lg-p {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
:root[data-mode="polarized"] .ld-sum-n .big-number {
  font-weight: 200;
  letter-spacing: -0.05em;
}
:root[data-mode="polarized"] .lg-n {
  font-weight: 400;
}
:root[data-mode="garden"] .ld-sum-big {
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "n legend"
    "bar bar";
  gap: 18px 36px;
  align-items: end;
}
:root[data-mode="garden"] .ld-sum-n {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
:root[data-mode="garden"] .ld-sum-n .big-number {
  font-size: clamp(60px, 6vw, 88px);
}
:root[data-mode="garden"] .ld-sum-unit {
  font-size: 14px;
}
:root[data-mode="garden"] .ld-sum-bar {
  height: 14px;
  gap: 3px;
  background: var(--accent-tint);
}
:root[data-mode="garden"] .sb-ok {
  border-radius: 999px;
}
:root[data-mode="garden"] .sb-wait {
  background: repeating-linear-gradient(
    45deg,
    color-mix(in srgb, var(--accent) 16%, var(--surface)) 0 6px,
    color-mix(in srgb, var(--accent) 7%, var(--surface)) 6px 12px
  );
}
:root[data-mode="garden"] .sb-bad {
  border-radius: 999px;
}
:root[data-mode="garden"] .ld-sum-legend {
  justify-content: flex-end;
  gap: 10px 34px;
}
:root[data-mode="garden"] .ld-sum-legend li {
  display: grid;
  grid-template-columns: auto auto;
  grid-template-areas:
    "n n"
    "l p";
  align-items: center;
  gap: 4px 8px;
}
:root[data-mode="garden"] .ld-sum-legend .st-ic {
  display: none;
}
:root[data-mode="garden"] .lg-n {
  grid-area: n;
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  font-size: 38px;
  line-height: 1;
  letter-spacing: -0.03em;
}
:root[data-mode="garden"] .lg-l {
  grid-area: l;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
}
:root[data-mode="garden"] .lg-l::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
:root[data-mode="garden"] .lg-ok .lg-l {
  color: var(--ok);
  background: var(--ok-tint);
}
:root[data-mode="garden"] .lg-bad .lg-l {
  color: var(--bad);
  background: var(--bad-tint);
}
:root[data-mode="garden"] .lg-p {
  grid-area: p;
}

.ld-scan > summary {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-right: 30px;
  cursor: pointer;
  list-style: none;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.ld-scan-ic {
  flex: none;
  color: var(--text-2);
}
.ld-scan > summary .ld-chevron {
  top: 50%;
  margin-top: -8px;
}
.ld-scan-note {
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-2);
}
:root[data-mode="polarized"] .ld-scan > summary,
:root[data-mode="polarized"] .ld-scan > .ld-scan-note {
  border-left: 2px solid color-mix(in srgb, var(--bl) 60%, transparent);
  padding-left: 12px;
}
:root[data-mode="polarized"] .ld-scan > summary {
  padding-top: 2px;
}
:root[data-mode="polarized"] .ld-scan > .ld-scan-note {
  padding-top: 4px;
  padding-bottom: 2px;
}
:root[data-mode="polarized"] .ld-scan-ic {
  display: none;
}
:root[data-mode="garden"] .ld-scan > summary,
:root[data-mode="garden"] .ld-scan > .ld-scan-note {
  padding-left: 16px;
  padding-right: 16px;
  background: color-mix(in srgb, var(--surface) 45%, transparent);
  box-shadow:
    inset 1px 0 0 var(--surface),
    inset -1px 0 0 var(--surface);
}
:root[data-mode="garden"] .ld-scan > summary {
  padding-top: 12px;
  padding-bottom: 4px;
  padding-right: 42px;
  border-radius: 16px 16px 0 0;
  box-shadow:
    inset 1px 0 0 var(--surface),
    inset -1px 0 0 var(--surface),
    inset 0 1px 0 var(--surface);
  font-weight: 500;
}
:root[data-mode="garden"] .ld-scan > summary .ld-chevron {
  right: 14px;
}
:root[data-mode="garden"] .ld-scan:not([open]) > summary {
  padding-bottom: 12px;
  border-radius: 16px;
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .ld-scan > .ld-scan-note {
  padding-left: 40px;
  padding-bottom: 12px;
}
:root[data-mode="garden"] .ld-scan > .ld-scan-note:last-of-type,
:root[data-mode="garden"] .ld-scan > .ld-scan-note + .ld-tables,
:root[data-mode="garden"] .ld-scan > .ld-scan-note:has(+ .ld-tables),
:root[data-mode="garden"] .ld-scan > .ld-scan-note:has(+ .scan-notes) {
  border-radius: 0 0 16px 16px;
  box-shadow:
    inset 1px 0 0 var(--surface),
    inset -1px 0 0 var(--surface),
    inset 0 -1px 0 var(--surface);
}
:root[data-mode="garden"] .ld-scan > .ld-scan-note:has(+ .ld-scan-note) {
  border-radius: 0;
  box-shadow:
    inset 1px 0 0 var(--surface),
    inset -1px 0 0 var(--surface);
  padding-bottom: 4px;
}
.ld-tables {
  list-style: none;
  margin: 18px 0 14px;
  padding: 0;
  display: grid;
  --tc-gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: var(--tc-gap);
}
.ld-tables.few {
  grid-template-columns: repeat(auto-fill, minmax(max(250px, calc((100% - 2 * var(--tc-gap) - 1px) / 3)), 1fr));
}
.ld-tcard {
  display: grid;
  align-content: start;
  gap: 9px;
  min-width: 0;
  padding: 16px;
}
.tc-h {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 4px 10px;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-2);
}
.tc-table {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}
.tc-sep {
  display: none;
}
.tc-n {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.tc-n b {
  font-family: var(--font-display);
  font-size: 44px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.tc-n span {
  font-size: 12.5px;
  color: var(--text-2);
}
.tc-fail {
  min-height: 44px;
  align-items: center;
  font-size: 14px;
  color: var(--bad);
}
.tc-bar {
  display: block;
  height: 3px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
.tc-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
}
.ld-tcard p {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
:root[data-mode="polarized"] .ld-tcard {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: color-mix(in srgb, var(--text) 2.5%, transparent);
}
:root[data-mode="polarized"] .tc-page {
  font-family: var(--font-mono);
}
:root[data-mode="polarized"] .tc-n b {
  font-weight: 200;
  letter-spacing: -0.04em;
}
:root[data-mode="polarized"] .tc-bar i {
  background: var(--ifl);
}
:root[data-mode="garden"] .ld-tables {
  --tc-gap: 16px;
}
:root[data-mode="garden"] .ld-tcard {
  padding: 18px 20px;
  border-radius: 22px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .tc-h {
  justify-content: flex-start;
  align-self: start;
  justify-self: start;
  padding: 3px 12px;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
}
:root[data-mode="garden"] .tc-h .tc-table {
  font-size: 12px;
  font-weight: 500;
}
:root[data-mode="garden"] .tc-sep {
  display: inline;
  margin: 0 -6px;
}
:root[data-mode="garden"] .tc-n b {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
}
:root[data-mode="garden"] .tc-bar {
  height: 8px;
  background: var(--accent-tint);
}
:root[data-mode="garden"] .tc-bar i {
  background: linear-gradient(90deg, color-mix(in oklab, var(--accent) 72%, var(--surface)), var(--accent));
}
.scan-notes {
  border-top: 1px solid var(--line-soft);
  padding-top: 12px;
}
.scan-notes > summary {
  position: relative;
  padding-right: 30px;
  cursor: pointer;
  list-style: none;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text);
}
.scan-notes ul {
  margin: 10px 0 0;
  padding-left: 1.2em;
  display: grid;
  gap: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
:root[data-mode="polarized"] .scan-notes li::marker {
  color: var(--bl);
}
:root[data-mode="garden"] .scan-notes {
  border-top: 0;
  padding-top: 4px;
}
:root[data-mode="garden"] .scan-notes li::marker {
  color: var(--accent);
}

@media (max-width: 1280px) {
  :root[data-mode="polarized"] .ld-sum-big {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "n"
      "bar"
      "legend";
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .ld-sum-big {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "n"
      "legend"
      "bar";
  }
  :root[data-mode="garden"] .ld-sum-legend {
    justify-content: flex-start;
  }
}
@media (max-width: 720px) {
  .ld-tables {
    grid-template-columns: minmax(0, 1fr);
  }
  .ld-sum-n .big-number,
  :root[data-mode="garden"] .ld-sum-n .big-number {
    font-size: 64px;
  }
  :root[data-mode="garden"] .ld-sum-legend {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, auto));
    justify-content: start;
    gap: 10px 20px;
  }
  :root[data-mode="garden"] .ld-sum-legend li {
    grid-template-columns: auto;
    grid-template-areas:
      "n"
      "l"
      "p";
    justify-items: start;
  }
  :root[data-mode="garden"] .lg-n {
    font-size: 32px;
  }
}
</style>
