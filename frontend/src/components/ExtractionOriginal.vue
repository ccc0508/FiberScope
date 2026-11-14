<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ExternalLink, Minus, Plus, LocateFixed } from "lucide-vue-next";
import type { ExtractionTask, Measurement } from "../extraction";
import { reducedMotion } from "../mode";
import { apiPath } from "../urls";
const props = defineProps<{
  task: ExtractionTask;
  measurement?: Measurement;
}>();
const zoom = ref(1),
  error = ref(false),
  ready = ref(false);
const viewport = ref<HTMLElement>(),
  paper = ref<HTMLElement>();
const pageNumber = computed(() => props.measurement?.source_pdf_page ?? props.task.source.page ?? 1);
const sourceLabel = computed(() => props.measurement?.source_table ?? props.task.source.table);
const evidence = computed(() => props.task.snapshot?.evidence?.pages?.[String(pageNumber.value)] ?? props.task.snapshot?.evidence);
const dimensions = computed(() => [
  evidence.value?.width_pt ?? 612,
  evidence.value?.height_pt ?? 792,
]);
const box = computed(() => props.measurement?.source_bbox_pt);
const words = computed(() => {
  if (!props.measurement || !evidence.value) return [];
  const ids = new Set([
    ...props.measurement.label_word_ids,
    ...props.measurement.header_word_ids,
    ...props.measurement.unit_word_ids,
    ...props.measurement.state_word_ids,
    ...(props.measurement.context_word_ids ?? []),
  ]);
  return evidence.value.words?.filter((w) => ids.has(w.id)) ?? [];
});
/* the selected value in page points: its centre (polarized crosshair) and the four
   corner brackets of a reticle a few points outside it */
const target = computed(() => {
  const b = box.value;
  if (!b || b.length < 4) return null;
  const [x0, y0, x1, y1] = b as [number, number, number, number];
  const pad = 4,
    leg = 5;
  const l = x0 - pad,
    t = y0 - pad,
    r = x1 + pad,
    btm = y1 + pad;
  return {
    cx: (x0 + x1) / 2,
    cy: (y0 + y1) / 2,
    reticle:
      `M${l},${t + leg}V${t}H${l + leg}` +
      `M${r - leg},${t}H${r}V${t + leg}` +
      `M${r},${btm - leg}V${btm}H${r - leg}` +
      `M${l + leg},${btm}H${l}V${btm - leg}`,
  };
});
const url = computed(() => apiPath(`literature/extractions/${props.task.id}`));
async function locate() {
  await nextTick();
  if (!box.value || !viewport.value || !paper.value) return;
  const x = (box.value[0]! / dimensions.value[0]!) * paper.value.clientWidth;
  const y = (box.value[1]! / dimensions.value[1]!) * paper.value.clientHeight;
  viewport.value.scrollTo({
    top: Math.max(0, y - viewport.value.clientHeight * 0.38),
    left: Math.max(0, x - viewport.value.clientWidth * 0.45),
    behavior: reducedMotion.value ? "auto" : "smooth",
  });
}
watch(
  () => `${props.task.id}:${pageNumber.value}`,
  () => {
    zoom.value = 1;
    error.value = false;
    ready.value = false;
  },
);
watch(() => props.measurement?.record_id, locate);
watch(zoom, locate);
</script>
<template>
  <section class="card original-panel" aria-label="论文原文对照">
    <div class="original-heading">
      <div class="original-id">
        <h2>原文对照</h2>
        <p class="original-src">第 {{ pageNumber }} 页 · {{ sourceLabel }}</p>
      </div>
      <a
        :href="`${url}/pdf#page=${pageNumber}`"
        target="_blank"
        rel="noopener"
        class="button original-pdf"
        ><ExternalLink :size="14" aria-hidden="true" />完整 PDF</a
      >
    </div>
    <div class="original-tools">
      <div class="original-zoom">
        <button
          type="button"
          class="zoom-step"
          :disabled="zoom <= 1"
          aria-label="缩小原文"
          @click="zoom = Math.max(1, zoom - 0.25)"
        >
          <Minus :size="14" aria-hidden="true" />
        </button>
        <span class="zoom-read">{{ Math.round(zoom * 100) }}%</span
        ><button
          type="button"
          class="zoom-step"
          :disabled="zoom >= 2.5"
          aria-label="放大原文"
          @click="zoom = Math.min(2.5, zoom + 0.25)"
        >
          <Plus :size="14" aria-hidden="true" />
        </button>
      </div>
      <button
        type="button"
        class="button locate-button"
        :disabled="!box || !ready"
        @click="locate"
      >
        <LocateFixed :size="14" aria-hidden="true" />定位所选数值
      </button>
    </div>
    <div v-if="error" class="original-error" role="alert">
      <p>该页暂时无法预览，请查看完整 PDF。</p>
      <button
        type="button"
        class="button"
        @click="
          error = false;
          ready = false;
        "
      >
        重试预览
      </button>
    </div>
    <div v-else class="original-stage">
      <div
        ref="viewport"
        class="original-viewport"
        tabindex="0"
        aria-label="可滚动的原文页"
      >
        <p v-if="!ready" class="original-loading" role="status">正在加载原文…</p>
        <div
          ref="paper"
          class="original-paper"
          :style="{
            width: `${zoom * 100}%`,
            aspectRatio: `${dimensions[0]}/${dimensions[1]}`,
          }"
          :class="{ loading: !ready }"
        >
          <img
            :key="`${task.id}:${pageNumber}`"
            :src="`${url}/page?page=${pageNumber}`"
            :alt="`${task.source.filename} 第${pageNumber}页`"
            @load="
              ready = true;
              locate();
            "
            @error="error = true"
          />
          <svg
            v-if="ready && evidence && box"
            class="evidence-overlay"
            :viewBox="`0 0 ${dimensions[0]} ${dimensions[1]}`"
            aria-hidden="true"
          >
            <g v-if="target" class="hud">
              <line class="hud-line" x1="0" :x2="dimensions[0]" :y1="target.cy" :y2="target.cy" />
              <line class="hud-line" :x1="target.cx" :x2="target.cx" y1="0" :y2="dimensions[1]" />
            </g>
            <rect
              v-for="word in words"
              :key="word.id"
              :x="word.bbox[0]! - 0.8"
              :y="word.bbox[1]! - 0.8"
              :width="word.bbox[2]! - word.bbox[0]! + 1.6"
              :height="word.bbox[3]! - word.bbox[1]! + 1.6"
              rx="1"
              class="context-mark"
            />
            <rect
              :x="box[0]! - 3.5"
              :y="box[1]! - 3.5"
              :width="box[2]! - box[0]! + 7"
              :height="box[3]! - box[1]! + 7"
              rx="4"
              class="number-halo"
            />
            <rect
              :x="box[0]! - 1.5"
              :y="box[1]! - 1.5"
              :width="box[2]! - box[0]! + 3"
              :height="box[3]! - box[1]! + 3"
              rx="1.5"
              class="number-mark"
            />
            <path v-if="target" class="reticle" :d="target.reticle" />
          </svg>
        </div>
      </div>
      <span class="original-frame" aria-hidden="true"></span>
    </div>
    <p class="original-legend">
      <span><i></i>所选数值</span> <span><i class="context"></i>原料、表头与单位</span>
    </p>
  </section>
</template>
<style scoped>
/* v1: dark HUD panel, specimen on a measuring grid, magenta reticle + crosshair on the value
   v4: glass tile, the page as a soft sheet, a peach stain on the value, lilac on its context
   The page image is always white paper, so the highlight colours are chosen per mode for
   the paper, not for the panel: --mk-* are set below. */
.original-panel {
  --mk-num: var(--bl);
  --mk-num-fill: color-mix(in srgb, var(--bl) 24%, transparent);
  --mk-ctx: color-mix(in oklab, var(--accent) 68%, var(--bg));
  --mk-ctx-fill: color-mix(in srgb, var(--accent) 16%, transparent);
  padding: 20px;
  min-width: 0;
  align-self: start;
  position: sticky;
  top: calc(var(--chrome-top) + 16px);
}
:root[data-mode="garden"] .original-panel {
  --mk-num: var(--sw-ink);
  --mk-num-fill: color-mix(in srgb, var(--sw) 30%, transparent);
  --mk-ctx: var(--bl);
  --mk-ctx-fill: color-mix(in srgb, var(--bl) 16%, transparent);
  padding: 22px 22px 20px;
}
.original-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.original-id {
  min-width: 0;
}
.original-heading h2 {
  font-size: 17px;
  color: var(--text);
}
:root[data-mode="garden"] .original-heading h2 {
  font-size: 19px;
}
.original-src {
  margin-top: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
:root[data-mode="garden"] .original-src {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
.original-pdf {
  flex-shrink: 0;
}
:root[data-mode="polarized"] .original-pdf {
  min-height: 34px;
  padding: 0 12px;
  font-size: 13px;
}
.original-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 16px 0 12px;
}
.original-zoom {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
}
.zoom-step {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: var(--text);
  transition:
    background 0.15s,
    color 0.15s;
}
.zoom-step:hover:not(:disabled) {
  background: var(--surface-hover);
}
.zoom-read {
  min-width: 50px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
:root[data-mode="polarized"] .original-zoom {
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--text) 3%, transparent);
}
:root[data-mode="garden"] .original-zoom {
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    inset 0 2px 6px color-mix(in srgb, var(--accent) 8%, transparent);
}
:root[data-mode="garden"] .zoom-step:not(:disabled) {
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
:root[data-mode="polarized"] .locate-button {
  min-height: 34px;
  padding: 0 12px;
  font-size: 13px;
}

/* ------------------------------------------------ the page */
.original-stage {
  position: relative;
}
.original-viewport {
  /* the whole panel stays on screen while it sticks: chrome + heading, tools and legend */
  height: clamp(360px, calc(100vh - var(--chrome-top) - var(--chrome-bottom) - 236px), 840px);
  overflow: auto;
  position: relative;
  border-radius: var(--radius-sm);
  overscroll-behavior: contain;
}
.original-viewport:focus-visible {
  outline-offset: 2px;
}
:root[data-mode="polarized"] .original-viewport {
  padding: 14px;
  border: 1px solid var(--line);
  background-color: var(--surface-2);
  background-image:
    linear-gradient(var(--line-soft) 1px, transparent 1px),
    linear-gradient(90deg, var(--line-soft) 1px, transparent 1px);
  background-size: 24px 24px;
  background-position: -1px -1px;
}
:root[data-mode="garden"] .original-viewport {
  padding: 12px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--surface-2) 85%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    inset 0 8px 22px -14px color-mix(in srgb, var(--accent) 40%, transparent);
}
/* v1 reticle corners on the measuring field (polarized only) */
.original-frame {
  display: none;
}
:root[data-mode="polarized"] .original-frame {
  display: block;
  position: absolute;
  inset: 5px;
  pointer-events: none;
  --c: color-mix(in srgb, var(--accent) 70%, transparent);
  background:
    linear-gradient(var(--c), var(--c)) left top / 14px 1px no-repeat,
    linear-gradient(var(--c), var(--c)) left top / 1px 14px no-repeat,
    linear-gradient(var(--c), var(--c)) right top / 14px 1px no-repeat,
    linear-gradient(var(--c), var(--c)) right top / 1px 14px no-repeat,
    linear-gradient(var(--c), var(--c)) left bottom / 14px 1px no-repeat,
    linear-gradient(var(--c), var(--c)) left bottom / 1px 14px no-repeat,
    linear-gradient(var(--c), var(--c)) right bottom / 14px 1px no-repeat,
    linear-gradient(var(--c), var(--c)) right bottom / 1px 14px no-repeat;
}
.original-paper {
  position: relative;
  margin: 0 auto;
  background: var(--surface);
}
:root[data-mode="polarized"] .original-paper {
  box-shadow:
    0 0 0 1px var(--line-strong),
    0 18px 40px -18px color-mix(in srgb, var(--bg) 90%, transparent);
}
/* the white page is the brightest thing on a dark panel: take a little glare off */
:root[data-mode="polarized"] .original-paper img {
  filter: brightness(0.9);
}
:root[data-mode="garden"] .original-paper {
  border-radius: 6px;
  overflow: hidden;
  box-shadow:
    0 0 0 1px var(--line-soft),
    var(--shadow-sm);
}
.original-paper.loading {
  min-height: 340px;
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-hover) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.6s infinite;
}
.original-paper.loading img {
  visibility: hidden;
}
.original-paper img {
  display: block;
  width: 100%;
  height: auto;
}
.original-loading {
  padding: 20px;
  color: var(--text-2);
  font-size: 13px;
  position: absolute;
  z-index: 2;
}
.evidence-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;
}
.number-mark {
  fill: var(--mk-num-fill);
  stroke: var(--mk-num);
  stroke-width: 1.2;
}
.context-mark {
  fill: var(--mk-ctx-fill);
  stroke: var(--mk-ctx);
  stroke-width: 0.6;
}
.number-halo,
.reticle,
.hud {
  display: none;
}
:root[data-mode="polarized"] .hud,
:root[data-mode="polarized"] .reticle {
  display: inline;
}
.hud-line {
  stroke: var(--mk-num);
  stroke-width: 0.6;
  stroke-dasharray: 2 3;
  opacity: 0.55;
}
.reticle {
  fill: none;
  stroke: var(--mk-num);
  stroke-width: 1.2;
  stroke-linecap: square;
}
/* v4 stain: a soft peach ring around the value */
:root[data-mode="garden"] .number-halo {
  display: inline;
  fill: none;
  stroke: color-mix(in srgb, var(--sw) 45%, transparent);
  stroke-width: 3;
}

/* ------------------------------------------------ legend */
.original-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-2);
}
.original-legend > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.original-legend i {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  background: var(--mk-num-fill);
  box-shadow: inset 0 0 0 1.5px var(--mk-num);
}
.original-legend i.context {
  background: var(--mk-ctx-fill);
  box-shadow: inset 0 0 0 1px var(--mk-ctx);
}
/* the swatches sit on the card, not on the paper: polarized repeats the paper under them */
:root[data-mode="polarized"] .original-legend i {
  background:
    linear-gradient(var(--mk-num-fill), var(--mk-num-fill)),
    var(--text);
}
:root[data-mode="polarized"] .original-legend i.context {
  background:
    linear-gradient(var(--mk-ctx-fill), var(--mk-ctx-fill)),
    var(--text);
}
:root[data-mode="garden"] .original-legend i {
  border-radius: 50%;
}
:root[data-mode="garden"] .original-legend i.context {
  border-radius: 4px;
}

.original-error {
  display: grid;
  justify-items: start;
  gap: 12px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text);
  padding: 20px;
  border-radius: var(--radius-sm);
  background: var(--warn-tint);
}
:root[data-mode="polarized"] .original-error {
  border-left: 2px solid var(--warn);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}
/* one column (LiteratureData collapses the review layout at these widths) */
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .original-panel {
    position: static;
  }
  :root[data-mode="polarized"] .original-viewport {
    height: 56vh;
    min-height: 300px;
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .original-panel {
    position: static;
  }
  :root[data-mode="garden"] .original-viewport {
    height: 56vh;
    min-height: 300px;
  }
}
@media (max-width: 720px) {
  .original-panel,
  :root[data-mode="garden"] .original-panel {
    padding: 18px 16px;
  }
  .original-viewport,
  :root[data-mode="polarized"] .original-viewport,
  :root[data-mode="garden"] .original-viewport {
    height: 48vh;
    min-height: 280px;
    padding: 8px;
  }
  .locate-button {
    margin-left: auto;
  }
}
</style>
