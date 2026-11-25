<script setup lang="ts">
import { computed } from "vue";
import { Check, ChevronDown, Ellipsis, History, X } from "lucide-vue-next";
import FilterSelect from "../FilterSelect.vue";
import { vSeg } from "../../motion";
import {
  measurementStates,
  metricNames,
  reviewStates,
  type ExtractionTask,
  type Measurement,
  type Review,
  type ReviewData,
} from "../../extraction";
import { timeLabel } from "../../literature";

export type ReviewDraft = ReviewData & {
  status: Review["status"];
  suitability: Review["suitability"];
  note: string;
};

export type ReviewEventItem = {
  revision: number;
  created_at: string;
  previous: Review;
  current: Review;
};

const props = defineProps<{
  task: ExtractionTask;
  measurements: Measurement[];
  groupedCount: number;
  groupOptions: { value: string; label: string; count: number }[];
  sourceOptions: { value: string; label: string }[];
  sourceFilter: string;
  groupName: string;
  statusFilter: string;
  statusCounts: { all: number; pending: number; confirmed: number; rejected: number };
  visibleRows: { r: Measurement; v: Review }[];
  selectedId: string;
  chosen?: Measurement;
  review?: Review;
  canReview: boolean;
  saving: boolean;
  dirty: boolean;
  draft?: ReviewDraft;
  events: ReviewEventItem[];
  eventsOpen: boolean;
  eventsLoading: boolean;
  eventsError: string;
}>();

const emit = defineEmits<{
  chooseSource: [value: string];
  chooseGroup: [value: string];
  chooseFilter: [value: string];
  selectMeasurement: [measurement: Measurement];
  setStatus: [value: Review["status"]];
  saveReview: [];
  cancelEdit: [];
  reloadTask: [];
  toggleEvents: [];
}>();

const metricOptions = computed(() =>
  [...new Set([
    ...Object.keys(metricNames),
    ...props.measurements.map((r) => r.metric),
    props.draft?.metric ?? "",
  ])]
    .filter(Boolean)
    .map((v) => ({ value: v, label: metricNames[v] ?? v })),
);

const stateOptions = Object.entries(measurementStates).map(
  ([value, label]) => ({ value, label }),
);

const filterOptions = [
  { value: "all", label: "全部记录" },
  { value: "pending", label: "待核对" },
  { value: "confirmed", label: "已确认" },
  { value: "rejected", label: "已驳回" },
] as const;

const suitabilityNames = {
  unassessed: "未评估",
  suitable: "可用于建模",
  unsuitable: "不适合建模",
};

function changes(event: { previous: Review; current: Review }) {
  const labels: Record<keyof ReviewData, string> = {
    raw_material: "原料",
    metric: "指标",
    measurement_state: "测量状态",
    raw_value: "数值",
    raw_unit: "单位",
    experiment_condition: "实验条件",
    condition_source: "条件来源",
  };
  const named = (k: keyof ReviewData, v: string) =>
    (k === "metric" ? metricNames[v] : k === "measurement_state" ? measurementStates[v] : undefined) ?? v;
  return (Object.keys(labels) as (keyof ReviewData)[])
    .filter((k) => event.previous.current[k] !== event.current.current[k])
    .map((k) => ({
      label: labels[k],
      before: named(k, event.previous.current[k]) || "未说明",
      after: named(k, event.current.current[k]) || "未说明",
    }));
}
</script>

<template>
  <section class="card review-panel" aria-label="候选数据审核">
    <div class="review-toolbar">
      <h2>候选数据</h2>
      <span class="ld-count">{{ groupedCount }} 个原料 / 处理组</span>
    </div>
    <div class="review-filters">
      <FilterSelect
        id="review-source"
        label="筛选原文来源"
        eyebrow="来源"
        reset-value="all"
        :model-value="sourceFilter"
        :options="sourceOptions"
        @update:model-value="emit('chooseSource', $event)"
      />
      <FilterSelect
        id="review-material"
        label="选择原料"
        eyebrow="原料"
        :model-value="groupName"
        :options="groupOptions"
        @update:model-value="emit('chooseGroup', $event)"
      />
    </div>
    <div v-seg class="seg ld-status" role="group" aria-label="筛选审核状态">
      <button
        v-for="option in filterOptions"
        :key="option.value"
        type="button"
        :class="`f-${option.value}`"
        :aria-pressed="statusFilter === option.value"
        @click="emit('chooseFilter', option.value)"
      >
        {{ option.label }}<span class="cnt">{{ statusCounts[option.value] }}</span>
      </button>
    </div>
    <ul class="measurement-list" aria-label="候选指标列表">
      <li v-for="{ r, v } in visibleRows" :key="r.record_id">
        <button
          type="button"
          :class="['measurement-row', `s-${v.status}`, { selected: r.record_id === selectedId }]"
          :aria-current="r.record_id === selectedId ? 'true' : undefined"
          :disabled="saving"
          @click="emit('selectMeasurement', r)"
        >
          <span class="mr-main">
            <span class="mr-name"
              ><strong>{{ metricNames[v.current.metric] ?? v.current.metric }}</strong
              ><span v-if="metricNames[v.current.metric]" class="mr-key">{{ v.current.metric }}</span></span
            >
            <span class="mr-meta"
              ><span>{{ measurementStates[v.current.measurement_state] ?? "未说明" }}</span
              ><small v-if="task.source.mode === 'document'" class="record-source"
                ><span class="mr-sep"> · </span>第 {{ r.source_pdf_page }} 页 · {{ r.source_table }}{{ r.value_qualifier === 'approximate' ? ' · 原文约数' : '' }}</small
              ></span
            >
          </span>
          <span class="measurement-value"
            ><span class="mv-num">{{ v.current.raw_value }}</span
            ><small>{{ v.current.raw_unit || "单位未说明" }}</small></span
          >
          <span :class="['review-pill', v.status]"
            ><span class="st-ic" aria-hidden="true"
              ><Check v-if="v.status === 'confirmed'" :size="10" :stroke-width="3" /><X
                v-else-if="v.status === 'rejected'"
                :size="10"
                :stroke-width="3" /><Ellipsis v-else :size="10" :stroke-width="3" /></span
            >{{ reviewStates[v.status] }}</span
          >
        </button>
      </li>
      <li v-if="!visibleRows.length" class="ld-state">当前原料没有匹配的记录。</li>
    </ul>
    <form
      v-if="chosen && draft"
      class="review-editor"
      aria-labelledby="ld-editor-title"
      @submit.prevent="emit('saveReview')"
    >
      <div class="editor-heading">
        <h3 id="ld-editor-title">核对所选记录</h3>
        <span :class="['editor-state', { dirty }]">{{
          dirty
            ? "有未保存修改"
            : review?.revision
              ? `审核版本 ${review.revision}`
              : "尚未审核"
        }}</span>
      </div>
      <div class="original-value">
        <span class="ov-k">原文提取</span
        ><strong class="ov-v"
          ><span class="ov-num">{{ chosen.raw_value }}</span> <span class="ov-unit">{{ chosen.raw_unit }}</span></strong
        ><small
          >{{ metricNames[chosen.metric] ?? chosen.metric }} ·
          {{ measurementStates[chosen.measurement_state] }} ·
          {{ chosen.raw_material }}</small
        >
      </div>
      <p class="ld-note">所有访问者均可审核。修改需填写依据，保存后保留审核版本记录。</p>
      <fieldset class="editable-review" :disabled="saving || !canReview">
        <div class="editor-fields">
          <label class="ld-field full-field"
            ><span class="ld-label">原料</span
            ><input
              v-model="draft.raw_material"
              class="ld-input"
              aria-label="审核原料"
              maxlength="200"
              required
          /></label>
          <div class="ld-field select-field">
            <span class="ld-label">指标</span><FilterSelect
              id="review-metric"
              v-model="draft.metric"
              label="审核指标"
              block
              :options="metricOptions"
          /></div>
          <div class="ld-field select-field">
            <span class="ld-label">测量状态</span><FilterSelect
              id="review-measurement-state"
              v-model="draft.measurement_state"
              label="审核测量状态"
              block
              :options="stateOptions"
          /></div>
          <label class="ld-field"
            ><span class="ld-label">数值</span
            ><input
              v-model="draft.raw_value"
              class="ld-input ld-num"
              aria-label="审核数值"
              inputmode="decimal"
              maxlength="60"
              required
          /></label>
          <label class="ld-field"
            ><span class="ld-label">单位</span
            ><input
              v-model="draft.raw_unit"
              class="ld-input"
              aria-label="审核单位"
              maxlength="60"
              placeholder="原文未说明则留空"
          /></label>
        </div>
        <details class="conditions">
          <summary>
            <span>补充原文中的实验条件（可选）</span>
            <ChevronDown class="ld-chevron" :size="15" aria-hidden="true" />
          </summary>
          <div class="conditions-body">
            <label class="ld-field"
              ><span class="ld-label">实验条件</span
              ><textarea
                v-model="draft.experiment_condition"
                class="ld-input"
                aria-label="实验条件"
                maxlength="600"
                rows="2"
                placeholder="只填写原文明确报告的条件"
              /></label
            ><label class="ld-field"
              ><span class="ld-label">条件来源</span
              ><input
                v-model="draft.condition_source"
                class="ld-input"
                aria-label="条件来源"
                maxlength="300"
                placeholder="例如：第3页，方法2.4节"
            /></label>
          </div>
        </details>
        <fieldset class="decision">
          <legend class="ld-label">原文抄录核对</legend>
          <div class="ld-opts">
            <label
              v-for="(name, key) in reviewStates"
              :key="key"
              :class="['ld-opt', `o-${key}`, { on: draft.status === key }]"
              ><input
                class="ld-radio"
                type="radio"
                name="review-status"
                :value="key"
                :checked="draft.status === key"
                @change="emit('setStatus', key)"
              /><span class="st-ic" aria-hidden="true"
                ><Check v-if="key === 'confirmed'" :size="10" :stroke-width="3" /><X
                  v-else-if="key === 'rejected'"
                  :size="10"
                  :stroke-width="3" /><Ellipsis v-else :size="10" :stroke-width="3" /></span
              >{{ key === "confirmed" ? "确认抄录" : name }}</label
            >
          </div>
        </fieldset>
        <fieldset
          class="decision"
          :disabled="draft.status !== 'confirmed'"
        >
          <legend class="ld-label">建模适用性</legend>
          <div class="ld-opts">
            <label
              v-for="(name, key) in suitabilityNames"
              :key="key"
              :class="['ld-opt', { on: draft.suitability === key }]"
              ><input
                v-model="draft.suitability"
                class="ld-radio"
                type="radio"
                name="review-suitability"
                :value="key"
              />{{ name }}</label
            >
          </div>
        </fieldset>
        <p class="ld-note">
          确认抄录只表示与原文一致。建模适用性需结合实验条件另行判断。
        </p>
        <label class="ld-field note-field"
          ><span class="ld-label">审核说明</span
          ><textarea
            v-model="draft.note"
            class="ld-input"
            aria-label="审核说明"
            maxlength="1200"
            rows="3"
            placeholder="修改、驳回或评估建模适用性时，请说明依据。"
          />
        </label>
      </fieldset>
      <div class="editor-actions">
        <button v-if="canReview" class="button primary" :disabled="saving || !dirty">
          <Check :size="15" aria-hidden="true" />{{
            saving ? "正在保存…" : "保存审核"
          }}</button
        ><button
          v-if="canReview"
          class="button"
          type="button"
          :disabled="saving || !dirty"
          @click="emit('cancelEdit')"
        >
          取消修改</button
        ><button
          class="button"
          type="button"
          :disabled="saving || dirty"
          @click="emit('reloadTask')"
        >
          重新读取</button
        ><button
          class="button audit-toggle"
          type="button"
          :aria-expanded="eventsOpen"
          aria-controls="ld-audit"
          @click="emit('toggleEvents')"
        >
          <History :size="14" aria-hidden="true" />审核记录
        </button>
      </div>
      <div v-if="eventsOpen" id="ld-audit" class="audit-list">
        <p v-if="eventsError" class="audit-error" role="alert">{{ eventsError }}</p>
        <p v-else-if="eventsLoading && !events.length" class="ld-state" role="status">正在读取审核记录…</p>
        <p v-else-if="!events.length" class="ld-state">
          尚无审核记录。
        </p>
        <article
          v-for="event in events"
          :key="event.revision"
          :class="['audit-item', `s-${event.current.status}`]"
        >
          <div class="audit-head">
            <strong
              >版本 {{ event.revision }} ·
              {{ reviewStates[event.current.status] }}</strong
            ><span>{{ timeLabel(event.created_at) }}</span>
          </div>
          <p v-for="change in changes(event)" :key="change.label" class="audit-change">
            {{ change.label }}：{{ change.before }} → {{ change.after }}
          </p>
          <p>
            原料：{{ event.current.current.raw_material }} ·
            {{
              metricNames[event.current.current.metric] ??
              event.current.current.metric
            }}
            ·
            {{
              measurementStates[event.current.current.measurement_state]
            }}
          </p>
          <p>
            建模适用性：{{
              suitabilityNames[event.previous.suitability]
            }}
            → {{ suitabilityNames[event.current.suitability] }}
          </p>
          <p v-if="event.current.note" class="audit-note">{{ event.current.note }}</p>
        </article>
      </div>
    </form>
  </section>
</template>

<style scoped>
.review-panel {
  min-width: 0;
}
.review-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px 12px;
}
.review-toolbar h2 {
  font-size: 17px;
  color: var(--text);
}
:root[data-mode="garden"] .review-toolbar h2 {
  font-size: 19px;
}
.review-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 10px;
}
.ld-status {
  margin-bottom: 12px;
}
:root[data-mode="polarized"] .ld-status > button[aria-pressed="true"] .cnt {
  color: var(--text-2);
}
.measurement-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 336px;
  overflow: auto;
  overscroll-behavior: contain;
}
.measurement-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 84px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  text-align: left;
  color: var(--text);
  transition:
    background 0.15s,
    box-shadow 0.2s;
}
.mr-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.mr-name {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 8px;
  min-width: 0;
}
.mr-name strong {
  font-size: 13.5px;
  font-weight: 500;
}
.mr-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.mr-meta {
  font-size: 12px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.record-source {
  font-family: var(--font-mono);
  font-size: 11px;
}
.measurement-value {
  display: grid;
  justify-items: end;
  text-align: right;
  min-width: 64px;
}
.mv-num {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.measurement-value small {
  max-width: 120px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.review-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-self: start;
  font-size: 12.5px;
  white-space: nowrap;
  color: var(--text-2);
}
.review-pill.confirmed {
  color: var(--ok);
}
.review-pill.rejected {
  color: var(--bad);
}
:root[data-mode="polarized"] .measurement-list {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
:root[data-mode="polarized"] .measurement-list > li + li {
  border-top: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .measurement-row:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 4.5%, transparent);
}
:root[data-mode="polarized"] .measurement-row.selected {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: inset 3px 0 0 var(--accent);
}
:root[data-mode="garden"] .measurement-list {
  display: grid;
  gap: 6px;
  padding: 4px;
  margin: 0 -4px;
}
:root[data-mode="garden"] .measurement-row {
  padding: 11px 14px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .measurement-row:hover:not(:disabled) {
  background: var(--surface);
}
:root[data-mode="garden"] .measurement-row.selected {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--bl),
    var(--shadow-sm);
}
:root[data-mode="garden"] .mv-num {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 72;
  font-weight: 420;
  font-size: 19px;
  line-height: 1.1;
}
:root[data-mode="garden"] .review-pill {
  padding: 2px 10px 2px 4px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--surface-2);
}
:root[data-mode="garden"] .review-pill.confirmed {
  background: var(--ok-tint);
}
:root[data-mode="garden"] .review-pill.rejected {
  background: var(--bad-tint);
}
:root[data-mode="garden"] .review-pill .st-ic {
  width: 16px;
  height: 16px;
  background: var(--surface);
}

.review-editor {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
:root[data-mode="garden"] .review-editor {
  border-top-color: var(--line-soft);
}
.editor-heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.editor-heading h3 {
  font-size: 15px;
  color: var(--text);
}
.editor-state {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-2);
}
.editor-state.dirty {
  color: var(--review);
}
:root[data-mode="garden"] .editor-state {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--surface-2);
}
:root[data-mode="garden"] .editor-state.dirty {
  background: var(--review-tint);
}
.original-value {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  gap: 4px 14px;
  margin: 14px 0 12px;
  padding: 14px 16px;
}
.ov-k {
  font-size: 12px;
  color: var(--text-2);
}
.ov-v {
  min-width: 0;
  font-weight: 400;
  overflow-wrap: anywhere;
}
.ov-num {
  font-family: var(--font-display);
  font-size: 34px;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.ov-unit {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--text-2);
}
.original-value small {
  grid-column: 1 / -1;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
}
:root[data-mode="polarized"] .original-value {
  border-left: 2px solid var(--bl);
  background: linear-gradient(90deg, color-mix(in srgb, var(--bl) 9%, transparent), transparent 70%);
}
:root[data-mode="polarized"] .ov-k {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
}
:root[data-mode="polarized"] .ov-num {
  font-weight: 200;
  letter-spacing: -0.04em;
}
:root[data-mode="garden"] .original-value {
  border-radius: 20px;
  background: var(--sw-tint);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface) 70%, transparent);
}
:root[data-mode="garden"] .ov-k {
  font-family: var(--font-display), var(--font-body);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 14px;
}
:root[data-mode="garden"] .ov-num {
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-weight: 380;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.03em;
}
.editable-review {
  border: 0;
  padding: 0;
  margin: 14px 0 0;
  min-width: 0;
}
.editor-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.full-field {
  grid-column: 1 / -1;
}
.editor-fields :deep(.filter-trigger) {
  height: 40px;
}
.conditions {
  margin-top: 16px;
}
.conditions > summary {
  position: relative;
  display: inline-flex;
  padding-right: 26px;
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  color: var(--accent-ink);
}
.conditions > summary .ld-chevron {
  top: 1px;
}
.conditions-body {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}
.decision {
  margin-top: 18px;
}
.note-field {
  margin-top: 16px;
}
.editable-review > .ld-note {
  margin-top: 10px;
}
.editor-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.audit-toggle {
  margin-left: auto;
}
.audit-toggle[aria-expanded="true"] {
  color: var(--text);
  border-color: var(--line-strong);
  background: var(--surface-hover);
}
:root[data-mode="polarized"] .editor-actions .button {
  min-height: 36px;
  padding: 0 14px;
  font-size: 13.5px;
}

.audit-list {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--text-2);
}
.audit-error {
  padding: 10px 12px;
  border-radius: var(--radius-xs);
  color: var(--text);
  background: var(--bad-tint);
}
.audit-item {
  position: relative;
  padding: 10px 0 12px 22px;
  overflow-wrap: anywhere;
}
.audit-item::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--line);
}
.audit-item::after {
  content: "";
  position: absolute;
  left: 0;
  top: 16px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--text-2);
  box-shadow: 0 0 0 3px var(--surface);
}
.audit-item.s-confirmed::after {
  background: var(--ok);
}
.audit-item.s-rejected::after {
  background: var(--bad);
}
.audit-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 2px 12px;
}
.audit-head strong {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.audit-head span {
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.audit-item p {
  margin-top: 4px;
}
.audit-change {
  color: var(--text);
}
.audit-note {
  color: var(--text);
}
:root[data-mode="polarized"] .audit-item:first-of-type::before {
  top: 16px;
}
:root[data-mode="polarized"] .audit-item:last-of-type::before {
  bottom: auto;
  height: 16px;
}
:root[data-mode="polarized"] .audit-item:only-of-type::before {
  display: none;
}
:root[data-mode="polarized"] .audit-head strong {
  font-family: var(--font-mono);
  font-weight: 500;
}
:root[data-mode="garden"] .audit-list {
  display: grid;
  gap: 8px;
  border-top-color: var(--line-soft);
}
:root[data-mode="garden"] .audit-item {
  padding: 12px 16px 14px 34px;
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .audit-item::before {
  display: none;
}
:root[data-mode="garden"] .audit-item::after {
  left: 14px;
  top: 19px;
  box-shadow: none;
}
:root[data-mode="garden"] .audit-head strong {
  font-weight: 500;
}

@media (max-width: 720px) {
  .ld-status {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
  :root[data-mode="garden"] .ld-status {
    border-radius: 22px;
  }
  .ld-status > button {
    justify-content: center;
    padding: 0 10px;
    font-size: 13px;
  }
  .review-filters :deep(.filter-select) {
    width: 100%;
  }
  .measurement-list {
    max-height: 300px;
  }
  .measurement-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "main value"
      "pill value";
    gap: 6px 10px;
  }
  .mr-main {
    grid-area: main;
  }
  .measurement-value {
    grid-area: value;
  }
  .review-pill {
    grid-area: pill;
  }
  .editor-fields {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
  .audit-toggle {
    margin-left: 0;
  }
}
</style>
