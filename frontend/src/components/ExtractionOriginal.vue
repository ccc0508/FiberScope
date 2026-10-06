<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ExternalLink, Minus, Plus, LocateFixed } from "lucide-vue-next";
import type { ExtractionTask, Measurement } from "../extraction";
const props = defineProps<{
  task: ExtractionTask;
  measurement?: Measurement;
}>();
const zoom = ref(1),
  error = ref(false),
  ready = ref(false);
const viewport = ref<HTMLElement>(),
  paper = ref<HTMLElement>();
const evidence = computed(() => props.task.snapshot?.evidence);
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
  ]);
  return evidence.value.words.filter((w) => ids.has(w.id));
});
const url = computed(() => `/api/v1/literature/extractions/${props.task.id}`);
async function locate() {
  await nextTick();
  if (!box.value || !viewport.value || !paper.value) return;
  const x = (box.value[0]! / dimensions.value[0]!) * paper.value.clientWidth;
  const y = (box.value[1]! / dimensions.value[1]!) * paper.value.clientHeight;
  viewport.value.scrollTo({
    top: Math.max(0, y - viewport.value.clientHeight * 0.38),
    left: Math.max(0, x - viewport.value.clientWidth * 0.45),
    behavior: "smooth",
  });
}
watch(
  () => props.task.id,
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
      <div>
        <h2>原文对照</h2>
        <p>第 {{ task.source.page }} 页 · {{ task.source.table }}</p>
      </div>
      <a
        :href="`${url}/pdf#page=${task.source.page}`"
        target="_blank"
        rel="noopener"
        class="button"
        ><ExternalLink :size="14" />完整 PDF</a
      >
    </div>
    <div class="original-tools">
      <button
        class="button"
        :disabled="zoom <= 1"
        aria-label="缩小原文"
        @click="zoom = Math.max(1, zoom - 0.25)"
      >
        <Minus :size="14" />
      </button>
      <span>{{ Math.round(zoom * 100) }}%</span
      ><button
        class="button"
        :disabled="zoom >= 2.5"
        aria-label="放大原文"
        @click="zoom = Math.min(2.5, zoom + 0.25)"
      >
        <Plus :size="14" />
      </button>
      <button
        class="button locate-button"
        :disabled="!box || !ready"
        @click="locate"
      >
        <LocateFixed :size="14" />定位所选数值
      </button>
    </div>
    <div v-if="error" class="original-error" role="alert">
      该页暂时无法预览，请查看完整 PDF。<button
        class="button"
        @click="
          error = false;
          ready = false;
        "
      >
        重试预览
      </button>
    </div>
    <div
      v-else
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
          :key="task.id"
          :src="`${url}/page`"
          :alt="`${task.source.filename} 第${task.source.page}页`"
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
          <rect
            v-for="word in words"
            :key="word.id"
            :x="word.bbox[0]! - 0.8"
            :y="word.bbox[1]! - 0.8"
            :width="word.bbox[2]! - word.bbox[0]! + 1.6"
            :height="word.bbox[3]! - word.bbox[1]! + 1.6"
            class="context-mark"
          />
          <rect
            :x="box[0]! - 1.5"
            :y="box[1]! - 1.5"
            :width="box[2]! - box[0]! + 3"
            :height="box[3]! - box[1]! + 3"
            class="number-mark"
          />
        </svg>
      </div>
    </div>
    <p class="original-legend">
      <i></i>所选数值 <i class="context"></i>原料、表头与单位
    </p>
  </section>
</template>
<style scoped>
.original-panel {
  padding: 18px;
  min-width: 0;
  align-self: start;
  position: sticky;
  top: 20px;
}
.original-heading,
.original-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.original-heading p {
  color: var(--muted);
  font-size: 12px;
  margin-top: 5px;
}
.original-heading .button {
  font-size: 12px;
  padding: 7px;
  white-space: nowrap;
}
.original-tools {
  justify-content: flex-start;
  margin: 15px 0 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
}
.original-tools .button {
  padding: 6px 9px;
}
.locate-button {
  margin-left: auto;
}
.original-viewport {
  height: 66vh;
  min-height: 390px;
  max-height: 840px;
  overflow: auto;
  border: 1px solid var(--border);
  background: #e9edf1;
  border-radius: 5px;
  position: relative;
}
.original-paper {
  position: relative;
  margin: 0 auto;
  background: white;
}
.original-paper.loading {
  min-height: 340px;
}
.original-paper img {
  display: block;
  width: 100%;
  height: auto;
}
.original-loading {
  padding: 20px;
  color: var(--muted);
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
}
.number-mark {
  fill: #ffbf4760;
  stroke: #c38317;
  stroke-width: 1.2;
}
.context-mark {
  fill: #4386bf24;
  stroke: #4386bf77;
  stroke-width: 0.5;
}
.original-legend {
  font-size: 11px;
  color: var(--muted);
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 12px;
  flex-wrap: wrap;
}
.original-legend i {
  width: 11px;
  height: 11px;
  background: #ffbf4770;
  border: 1px solid #c38317;
  border-radius: 2px;
}
.original-legend .context {
  background: #4386bf24;
  border-color: #4386bf77;
  margin-left: 10px;
}
.original-error {
  font-size: 13px;
  line-height: 1.8;
  color: #a55d31;
  padding: 20px;
  background: #fff8ed;
}
.original-error .button {
  display: block;
  margin-top: 12px;
}
@media (max-width: 1000px) {
  .original-panel {
    position: static;
  }
  .original-viewport {
    height: 48vh;
    min-height: 290px;
  }
}
</style>
