<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import { Check, RefreshCw, X } from "lucide-vue-next";
import "../styles/extraction.css";
import ExtractionOriginal from "../components/ExtractionOriginal.vue";
import ExtractionReviewPanel, {
  type ReviewDraft,
  type ReviewEventItem,
} from "../components/extraction/ExtractionReviewPanel.vue";
import ExtractionSummaryCard from "../components/extraction/ExtractionSummaryCard.vue";
import ExtractionTaskList from "../components/extraction/ExtractionTaskList.vue";
import ExtractionUploadCard from "../components/extraction/ExtractionUploadCard.vue";
import PageHeader from "../components/PageHeader.vue";
import { useAbortablePolling } from "../composables/useAbortablePolling";
import { isGarden, isPolarized } from "../mode";
import {
  extractionRequest,
  currentReview,
  groups,
  waffleLayout,
  reviewStates,
  scanReasonNames,
  taskStates,
  type ExtractionTask,
  type Measurement,
  type Review,
} from "../extraction";
import { apiPath } from "../urls";

const route = useRoute(),
  router = useRouter();
const { clearPoll, schedulePoll, nextVersion, isCurrent, isDisposed, createAbortable } =
  useAbortablePolling();

const file = ref<File>(),
  extractionMode = ref<"document" | "table">("document"),
  pdfPage = ref(1),
  tableNo = ref("3"),
  uploadOpen = ref(true),
  uploading = ref(false);
const list = ref<ExtractionTask[]>([]),
  listPage = ref(1),
  totalPages = ref(0),
  total = ref(0),
  search = ref("");
const loading = ref(false),
  sessionReady = ref(false),
  error = ref(""),
  notice = ref("");
const task = ref<ExtractionTask>(),
  selectedId = ref(""),
  groupName = ref(""),
  statusFilter = ref("all");
const sourceFilter = ref("all");
function sourceKey(r: Measurement) {
  return `${r.source_pdf_page}:${r.source_table}`;
}
const sourceOptions = computed(() => [
  { value: "all", label: "全部来源" },
  ...[
    ...new Map(
      measurements.value.map((r) => [
        sourceKey(r),
        { value: sourceKey(r), label: `第 ${r.source_pdf_page} 页 · ${r.source_table}` },
      ]),
    ).values(),
  ],
]);
const saving = ref(false),
  exporting = ref(false),
  draft = ref<ReviewDraft>();
const baseline = ref(""),
  events = ref<ReviewEventItem[]>([]),
  eventsOpen = ref(false),
  eventsLoading = ref(false),
  eventsError = ref("");
const measurements = computed(
  () => task.value?.snapshot?.result?.measurements ?? [],
);
const grouped = computed(() => groups(measurements.value));
const scanNotices = computed(() => {
  const result = task.value?.snapshot?.result;
  if (!result?.coverage) return [];
  const notices = new Set(result.warnings ?? []);
  for (const page of result.coverage) {
    if (page.status !== "scanned")
      notices.add(`第${page.page}页未完成扫描：${scanReasonNames[page.reason ?? ""] ?? "处理未完成"}`);
    for (const note of page.notes) notices.add(`第${page.page}页：${note}`);
  }
  const covered = new Set(result.coverage.map((p) => p.page));
  for (let p = 1; p <= (task.value?.snapshot?.evidence?.page_count ?? 0); p++)
    if (!covered.has(p)) notices.add(`第${p}页未处理：任务未完成`);
  return [...notices];
});
const chosen = computed(() =>
  measurements.value.find((r) => r.record_id === selectedId.value),
);
const review = computed(() =>
  task.value && chosen.value
    ? currentReview(task.value, chosen.value)
    : undefined,
);
const canReview = computed(() => task.value?.can_review === true);
const dirty = computed(
  () => !!draft.value && JSON.stringify(draft.value) !== baseline.value,
);
const visible = computed(() =>
  (grouped.value.find((g) => g.name === groupName.value)?.records ?? [])
    .filter(
      (r) =>
        statusFilter.value === "all" ||
        currentReview(task.value!, r).status === statusFilter.value,
    )
    .filter((r) => sourceFilter.value === "all" || sourceKey(r) === sourceFilter.value),
);
const summary = computed(() => {
  let confirmed = 0,
    rejected = 0,
    suitable = 0;
  for (const r of measurements.value) {
    const v = currentReview(task.value!, r);
    confirmed += Number(v.status === "confirmed");
    rejected += Number(v.status === "rejected");
    suitable += Number(v.approved_for_training);
  }
  return {
    total: measurements.value.length,
    confirmed,
    rejected,
    pending: measurements.value.length - confirmed - rejected,
    suitable,
  };
});
const visibleRows = computed(() =>
  task.value ? visible.value.map((r) => ({ r, v: currentReview(task.value!, r) })) : [],
);
const statusCounts = computed(() => {
  const counts = { all: 0, pending: 0, confirmed: 0, rejected: 0 };
  if (!task.value) return counts;
  for (const r of grouped.value.find((g) => g.name === groupName.value)?.records ?? []) {
    if (sourceFilter.value !== "all" && sourceKey(r) !== sourceFilter.value) continue;
    counts.all += 1;
    counts[currentReview(task.value, r).status] += 1;
  }
  return counts;
});
const hasResult = computed(
  () => !!task.value && (task.value.status === "completed" || !!task.value.has_reviewable_result),
);
const waffle = computed(() => (hasResult.value ? waffleLayout(summary.value) : null));
const sigPending = computed(() => !error.value && !task.value && (loading.value || list.value.length > 0));
function singleColumn() {
  try {
    return window.matchMedia(isPolarized.value ? "(max-width: 1100px)" : "(max-width: 980px)").matches;
  } catch {
    return true;
  }
}
const groupOptions = computed(() =>
  grouped.value
    .map((g) => ({
      value: g.name,
      label: g.name,
      count: g.records.filter(
        (r) => sourceFilter.value === "all" || sourceKey(r) === sourceFilter.value,
      ).length,
    }))
    .filter((g) => g.count > 0),
);

let pending:
  | { file: File; page: number; table: string; mode: string; requestId: string }
  | undefined;

async function request<T>(path: string, options: RequestInit = {}) {
  const { signal, cleanup } = createAbortable(20000);
  try {
    return await extractionRequest<T>(path, {
      ...options,
      signal,
    });
  } finally {
    cleanup();
  }
}

function resetDraft() {
  if (!review.value) {
    draft.value = undefined;
    baseline.value = "";
    return;
  }
  draft.value = {
    ...review.value.current,
    status: review.value.status,
    suitability: review.value.suitability,
    note: review.value.note,
  };
  // The API may include a derived value; keep only editable fields in the form.
  delete (draft.value as unknown as Record<string, unknown>).value;
  baseline.value = JSON.stringify(draft.value);
}

function canSwitch() {
  if (saving.value || uploading.value) return false;
  if (dirty.value) {
    error.value = "当前修改尚未保存，请先保存或取消修改，再切换记录。";
    return false;
  }
  return true;
}

function selectMeasurement(r: Measurement) {
  if (!canSwitch()) return;
  selectedId.value = r.record_id;
  eventsOpen.value = false;
  events.value = [];
  eventsError.value = "";
  notice.value = "";
  error.value = "";
  resetDraft();
}

function chooseGroup(value: string) {
  if (!canSwitch()) return;
  groupName.value = value;
  const first = visible.value[0];
  selectedId.value = first?.record_id ?? "";
  eventsOpen.value = false;
  resetDraft();
}

function chooseFilter(value: string) {
  if (!canSwitch()) return;
  statusFilter.value = value;
  const first = visible.value[0];
  selectedId.value = first?.record_id ?? "";
  eventsOpen.value = false;
  resetDraft();
}

function chooseSource(value: string) {
  if (!canSwitch()) return;
  sourceFilter.value = value;
  if (!groupOptions.value.some((g) => g.value === groupName.value))
    groupName.value = groupOptions.value[0]?.value ?? "";
  selectedId.value = visible.value[0]?.record_id ?? "";
  eventsOpen.value = false;
  resetDraft();
}

async function loadList(initial = false) {
  loading.value = true;
  try {
    const query = new URLSearchParams({
      page: String(listPage.value),
      page_size: "5",
      q: search.value,
    });
    const result = await request<{
      data: ExtractionTask[];
      pagination: { total: number; total_pages: number };
    }>(`?${query}`);
    if (isDisposed()) return;
    list.value = result.data;
    total.value = result.pagination.total;
    totalPages.value = result.pagination.total_pages;
    sessionReady.value = true;
    if (initial) {
      const id =
        typeof route.query.task === "string"
          ? route.query.task
          : list.value[0]?.id;
      if (id) await openTask(id);
    }
  } catch (e) {
    if (!isDisposed())
      error.value = e instanceof Error ? e.message : "任务列表读取失败。";
  } finally {
    if (!isDisposed()) loading.value = false;
  }
}

async function openTask(id: string, polling = false) {
  if (!polling && !canSwitch()) return;
  clearPoll();
  const version = nextVersion();
  try {
    const value = await request<ExtractionTask>(`/${encodeURIComponent(id)}`);
    if (isDisposed() || !isCurrent(version)) return;
    const changed = task.value?.id !== id;
    task.value = value;
    if (changed) {
      groupName.value = "";
      selectedId.value = "";
      statusFilter.value = "all";
      sourceFilter.value = "all";
      eventsOpen.value = false;
      error.value = "";
      notice.value = "";
      draft.value = undefined;
      baseline.value = "";
    }
    if (value.status === "completed" || value.has_reviewable_result) {
      if (!grouped.value.some((g) => g.name === groupName.value))
        groupName.value = grouped.value[0]?.name ?? "";
      if (!chosen.value) selectedId.value = visible.value[0]?.record_id ?? "";
      if (!dirty.value) resetDraft();
      if (singleColumn()) uploadOpen.value = false;
    }
    await router.replace({ query: { ...route.query, task: id } });
    if (value.status === "processing")
      schedulePoll(() => openTask(id, true), 1500);
    else if (polling) loadList();
  } catch (e) {
    if (!isDisposed() && isCurrent(version))
      error.value =
        e instanceof Error
          ? e.message
          : "读取失败，已接收的任务会继续在后台处理。";
  }
}

function selectFile(selected: File | undefined) {
  file.value = selected;
  pending = undefined;
  error.value = "";
}

async function submit() {
  if (!sessionReady.value || !file.value || uploading.value || !canSwitch())
    return;
  const selected = file.value;
  if (selected.size > 12 * 1024 * 1024) {
    error.value = "PDF不能超过12MB。";
    return;
  }
  if (
    extractionMode.value === "table" &&
    (!Number.isInteger(pdfPage.value) ||
      pdfPage.value < 1 ||
      pdfPage.value > 200 ||
      !/^\d+[a-z]?$/i.test(tableNo.value.trim()))
  ) {
    error.value = "请输入1—200的页码和有效表格编号，例如3。";
    return;
  }
  const table = `Table ${tableNo.value.trim()}`;
  if (
    !pending ||
    pending.file !== selected ||
    pending.page !== pdfPage.value ||
    pending.table !== table ||
    pending.mode !== extractionMode.value
  )
    pending = {
      file: selected,
      page: pdfPage.value,
      table,
      mode: extractionMode.value,
      requestId: crypto.randomUUID(),
    };
  const query = new URLSearchParams({
    mode: extractionMode.value,
    request_id: pending.requestId,
    filename: selected.name,
  });
  if (extractionMode.value === "table") {
    query.set("page", String(pdfPage.value));
    query.set("table", table);
  }
  uploading.value = true;
  error.value = "";
  notice.value = "";
  try {
    const value = await request<ExtractionTask>(`?${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: selected,
    });
    if (isDisposed()) return;
    pending = undefined;
    uploading.value = false;
    await openTask(value.id);
    await loadList();
  } catch (e) {
    if (!isDisposed())
      error.value = `${e instanceof Error ? e.message : "提交失败。"} 若提交响应中断，请先刷新任务列表确认；重试会沿用本次提交编号。`;
  } finally {
    uploading.value = false;
  }
}

async function reextract() {
  if (!task.value || !canSwitch()) return;
  const source = task.value.source;
  try {
    const response = await fetch(
      apiPath(`literature/extractions/${task.value.id}/pdf`),
    );
    if (!response.ok) throw new Error("原文读取失败，请重新选择PDF。");
    file.value = new File([await response.blob()], source.filename, {
      type: "application/pdf",
    });
    extractionMode.value = source.mode ?? "table";
    pdfPage.value = source.page ?? 1;
    tableNo.value = source.table.replace(/^table\s+/i, "");
    pending = undefined;
    uploadOpen.value = true;
    await submit();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "重新提取失败。";
  }
}

function setStatus(value: Review["status"]) {
  if (!draft.value) return;
  draft.value.status = value;
  if (value !== "confirmed") draft.value.suitability = "unassessed";
}

async function saveReview() {
  if (!task.value || !chosen.value || !draft.value || saving.value || !canReview.value) return;
  const d = draft.value;
  const numeric = Number(d.raw_value.replaceAll(",", ""));
  if (
    !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(
      d.raw_value.replaceAll(",", ""),
    ) ||
    !Number.isFinite(numeric) ||
    Math.abs(numeric) > 1e100
  ) {
    error.value = "请输入有效数值，不包含单位或误差范围。";
    return;
  }
  if (!d.raw_material.trim() || !d.metric) {
    error.value = "请填写原料和指标。";
    return;
  }
  const changed = [
    "raw_material",
    "metric",
    "measurement_state",
    "raw_value",
    "raw_unit",
    "experiment_condition",
    "condition_source",
  ].some(
    (k) =>
      (d as unknown as Record<string, string>)[k] !==
      (review.value?.current as unknown as Record<string, string>)[k],
  );
  if (
    (changed || d.status === "rejected" || d.suitability !== "unassessed") &&
    !d.note.trim()
  ) {
    error.value = "修改、驳回或评估建模适用性时，请填写审核说明。";
    return;
  }
  if (d.experiment_condition.trim() && !d.condition_source.trim()) {
    error.value = "补充实验条件时，请注明原文页码或段落位置。";
    return;
  }
  const taskId = task.value.id,
    recordId = chosen.value.record_id;
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    const saved = await request<Review>(
      `/${taskId}/reviews/${encodeURIComponent(recordId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...d,
          expected_revision: review.value?.revision ?? 0,
        }),
      },
    );
    if (isDisposed()) return;
    task.value.reviews = { ...task.value.reviews, [recordId]: saved };
    resetDraft();
    notice.value = `已保存，当前状态：${reviewStates[saved.status]}。`;
    if (eventsOpen.value) loadEvents();
  } catch (e) {
    if (!isDisposed())
      error.value = e instanceof Error ? e.message : "审核保存失败。";
  } finally {
    saving.value = false;
  }
}

async function loadEvents() {
  if (!task.value || !chosen.value) return;
  const taskId = task.value.id,
    recordId = chosen.value.record_id;
  eventsError.value = "";
  eventsLoading.value = true;
  try {
    const result = await request<{ data: typeof events.value }>(
      `/${taskId}/reviews/${encodeURIComponent(recordId)}/events`,
    );
    if (
      !isDisposed() &&
      task.value?.id === taskId &&
      chosen.value?.record_id === recordId
    )
      events.value = result.data;
  } catch (e) {
    eventsError.value = e instanceof Error ? e.message : "审核历史读取失败。";
  } finally {
    eventsLoading.value = false;
  }
}

function toggleEvents() {
  eventsOpen.value = !eventsOpen.value;
  if (eventsOpen.value) loadEvents();
}

async function download(format: "jsonl" | "csv") {
  if (!task.value || !summary.value.confirmed) return;
  // A server attachment works in both normal browsers and the in-app browser.
  window.location.assign(apiPath(`literature/extractions/${task.value.id}/confirmed?format=${format}`));
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}

onBeforeRouteLeave(
  () => !dirty.value || window.confirm("当前审核修改尚未保存，是否离开？"),
);
onMounted(() => {
  loadList(true);
  window.addEventListener("beforeunload", beforeUnload);
});
onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>

<template>
  <div class="literature-data">
    <PageHeader
      title="文献数据提取与审核"
      title-strong="文献数据"
      title-light="提取与审核"
      description="上传论文，自动发现工艺、纤维特性和纸张性能数据，核对后再使用。"
    >
      <template v-if="isGarden && (waffle || sigPending)" #visual>
        <div v-if="!waffle" class="ld-sig ld-sig-empty skeleton" aria-hidden="true"></div>
        <figure v-else class="ld-sig">
          <svg
            :viewBox="`0 0 ${waffle.width} ${waffle.height}`"
            :width="waffle.width"
            :height="waffle.height"
            aria-hidden="true"
            focusable="false"
          >
            <path class="wf-wait" :d="waffle.wait" />
            <path class="wf-dot wf-ok" :d="waffle.ok" />
            <path class="wf-dot wf-bad" :d="waffle.bad" />
          </svg>
          <figcaption>
            <span class="nw">1 点 = {{ waffle.per }} 条候选 ·</span> <span class="nw">共 <b>{{ summary.total }}</b> ·</span> <span class="nw"><i class="wk wk-ok" aria-hidden="true"></i>已确认 <b>{{ summary.confirmed }}</b> ·</span> <span class="nw"><i class="wk wk-wait" aria-hidden="true"></i>待核对 <b>{{ summary.pending }}</b> ·</span> <span class="nw"><i class="wk wk-bad" aria-hidden="true"></i>已驳回 <b>{{ summary.rejected }}</b></span>
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <div v-if="error" class="ld-alert" role="alert">
      <p>{{ error }}</p>
      <button
        type="button"
        class="button"
        @click="
          error = '';
          loadList();
        "
      >
        刷新任务
      </button>
    </div>
    <p v-if="notice" class="ld-notice" role="status">
      <Check :size="15" aria-hidden="true" />{{ notice }}
    </p>

    <ExtractionUploadCard
      v-model:open="uploadOpen"
      v-model:extraction-mode="extractionMode"
      v-model:pdf-page="pdfPage"
      v-model:table-no="tableNo"
      :file="file"
      :session-ready="sessionReady"
      :uploading="uploading"
      :saving="saving"
      @select-file="selectFile"
      @invalid-file="error = $event"
      @submit="submit"
    />

    <ExtractionTaskList
      v-model:search="search"
      :list="list"
      :total="total"
      :list-page="listPage"
      :total-pages="totalPages"
      :loading="loading"
      :uploading="uploading"
      :saving="saving"
      :selected-task-id="task?.id"
      @search-submit="listPage = 1; loadList()"
      @refresh="loadList()"
      @open-task="openTask"
      @page-change="listPage = $event; loadList()"
    />

    <template v-if="task">
      <section
        v-if="task.status === 'processing'"
        class="card task-state"
        role="status"
      >
        <span class="ts-ic" aria-hidden="true"><RefreshCw :size="20" class="spinning" /></span>
        <div class="ts-body">
          <h2>{{ task.source.mode === 'document' ? '正在扫描整篇论文' : `正在提取 ${task.source.table}` }}</h2>
          <p v-if="task.progress">第 {{ task.progress.page }} / {{ task.progress.page_count }} 页 · {{ task.progress.stage }} · 已保存 {{ task.progress.measurement_count }} 条候选</p>
          <span v-if="task.progress" class="ts-prog" aria-hidden="true"
            ><i
              :style="{
                width: `${Math.min(100, (task.progress.page / Math.max(1, task.progress.page_count)) * 100)}%`,
              }"
            ></i
          ></span>
          <p>完成后会自动显示候选数据。你可以离开页面，稍后从任务列表查看。</p>
        </div>
      </section>
      <section
        v-else-if="task.status !== 'completed'"
        class="card task-state failure"
      >
        <span class="ts-ic" aria-hidden="true"><X :size="20" /></span>
        <div class="ts-body">
          <h2>{{ taskStates[task.status] }}</h2>
          <p>{{ task.message }}</p>
          <p v-if="task.has_reviewable_result">下方保留了已通过原文证据校验的部分候选，可继续核对；本次整篇提取未完成。</p>
        </div>
        <button type="button" class="button" :disabled="uploading" @click="reextract">
          重新提取
        </button>
      </section>

      <template v-if="hasResult">
        <ExtractionSummaryCard
          :task="task"
          :summary="summary"
          :measurements-count="measurements.length"
          :scan-notices="scanNotices"
          :exporting="exporting"
          @download="download"
        />

        <div class="review-layout">
          <ExtractionOriginal :task="task" :measurement="chosen" />
          <ExtractionReviewPanel
            :task="task"
            :measurements="measurements"
            :grouped-count="grouped.length"
            :group-options="groupOptions"
            :source-options="sourceOptions"
            :source-filter="sourceFilter"
            :group-name="groupName"
            :status-filter="statusFilter"
            :status-counts="statusCounts"
            :visible-rows="visibleRows"
            :selected-id="selectedId"
            :chosen="chosen"
            :review="review"
            :can-review="canReview"
            :saving="saving"
            :dirty="dirty"
            :draft="draft"
            :events="events"
            :events-open="eventsOpen"
            :events-loading="eventsLoading"
            :events-error="eventsError"
            @choose-source="chooseSource"
            @choose-group="chooseGroup"
            @choose-filter="chooseFilter"
            @select-measurement="selectMeasurement"
            @set-status="setStatus"
            @save-review="saveReview"
            @cancel-edit="resetDraft(); error = ''; notice = ''"
            @reload-task="task && openTask(task.id)"
            @toggle-events="toggleEvents"
          />
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* =================================================================== page grid
   polarized (v1 .lx-grid): upload and task list side by side in equal halves
   garden (v4 bento): upload s-5 beside the task list s-7
   Everything else spans the row. Collapse per mode: polarized ≤1100px, garden ≤980px. */
.literature-data {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-auto-flow: row dense;
  gap: 18px;
  max-width: var(--page-max);
}
.literature-data > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.literature-data > .page-header {
  margin-bottom: 4px;
}
.literature-data > .ld-upload {
  grid-column: 1;
}
.literature-data > .ld-tasks {
  grid-column: 2;
}
.literature-data > .ld-upload:not([open]) {
  align-self: start;
}
:root[data-mode="garden"] .literature-data {
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 22px;
  margin: 0 auto;
}
.nw {
  white-space: nowrap;
}

/* =================================================================== alerts */
.ld-alert,
.ld-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
  border-radius: var(--radius-sm);
}
.ld-alert {
  justify-content: space-between;
  color: var(--text);
  background: var(--bad-tint);
}
.ld-alert p {
  flex: 1 1 260px;
}
.ld-notice {
  color: var(--text);
  background: var(--ok-tint);
}
.ld-notice svg {
  color: var(--ok);
}
:root[data-mode="polarized"] .ld-alert {
  border-left: 2px solid var(--bad);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
:root[data-mode="polarized"] .ld-notice {
  border-left: 2px solid var(--ok);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
:root[data-mode="garden"] .ld-alert,
:root[data-mode="garden"] .ld-notice {
  border-radius: 18px;
  box-shadow: inset 0 0 0 1px var(--surface);
}

/* =================================================================== task state */
.task-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px 18px;
}
.ts-ic {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  color: var(--accent-ink);
  background: var(--accent-tint);
}
.failure .ts-ic {
  color: var(--bad);
  background: var(--bad-tint);
}
.ts-body {
  flex: 1 1 320px;
  min-width: 0;
}
.task-state h2 {
  font-size: 17px;
  color: var(--text);
}
.task-state p {
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.8;
  margin-top: 6px;
}
.ts-prog {
  display: block;
  height: 4px;
  margin-top: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: color-mix(in srgb, var(--text) 9%, transparent);
}
.ts-prog i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 0.4s;
}
:root[data-mode="polarized"] .ts-prog i {
  background: var(--ifl);
}
:root[data-mode="garden"] .ts-prog {
  height: 8px;
}

.review-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 18px;
  align-items: start;
}
:root[data-mode="garden"] .review-layout {
  gap: 22px;
}

/* =================================================================== garden hero signature (v4 waffleSig) */
.ld-sig {
  margin: 0;
  width: 420px;
  max-width: 100%;
  display: grid;
  gap: 8px;
}
.ld-sig svg {
  display: block;
  max-width: 100%;
  height: auto;
  max-height: 160px;
  overflow: visible;
}
.wf-dot {
  fill: none;
  stroke-width: 6.4;
  stroke-linecap: round;
}
.wf-ok {
  stroke: var(--ok);
}
.wf-bad {
  stroke: var(--bad);
}
.wf-wait {
  fill: none;
  stroke: var(--text-3);
  stroke-width: 0.9;
}
.ld-sig-empty {
  aspect-ratio: 420 / 176;
}
.ld-sig figcaption {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}
.ld-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.wk {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 4px;
  border-radius: 50%;
  vertical-align: 0;
}
.wk-ok {
  background: var(--ok);
}
.wk-bad {
  background: var(--bad);
}
.wk-wait {
  box-shadow: inset 0 0 0 1px var(--text-3);
}

/* =================================================================== responsive */
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .literature-data {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="polarized"] .literature-data > .ld-upload,
  :root[data-mode="polarized"] .literature-data > .ld-tasks {
    grid-column: 1 / -1;
  }
  :root[data-mode="polarized"] .review-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .literature-data {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .literature-data > .ld-upload,
  :root[data-mode="garden"] .literature-data > .ld-tasks {
    grid-column: 1 / -1;
  }
  :root[data-mode="garden"] .review-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 720px) {
  .literature-data,
  :root[data-mode="garden"] .literature-data {
    gap: 14px;
  }
}
</style>
