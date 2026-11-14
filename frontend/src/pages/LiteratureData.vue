<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import {
  Upload,
  History,
  Download,
  RefreshCw,
  Check,
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Ellipsis,
  Info,
  X,
} from "lucide-vue-next";
import FilterSelect from "../components/FilterSelect.vue";
import ExtractionOriginal from "../components/ExtractionOriginal.vue";
import PageHeader from "../components/PageHeader.vue";
import { isGarden, isPolarized } from "../mode";
import { useCountUp, vSeg, vTilt } from "../motion";
import {
  extractionRequest,
  currentReview,
  groups,
  waffleLayout,
  metricNames,
  measurementStates,
  taskStates,
  reviewStates,
  scanReasonNames,
  type ExtractionTask,
  type Measurement,
  type Review,
  type ReviewData,
} from "../extraction";
import { secondsLabel, timeLabel } from "../literature";
import { apiPath } from "../urls";

const route = useRoute(),
  router = useRouter();
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
function sourceKey(r: Measurement) { return `${r.source_pdf_page}:${r.source_table}`; }
const sourceOptions = computed(() => [
  {value: "all", label: "全部来源"},
  ...[...new Map(measurements.value.map(r => [sourceKey(r), {value: sourceKey(r), label: `第 ${r.source_pdf_page} 页 · ${r.source_table}`}])).values()],
]);
const saving = ref(false),
  exporting = ref(false),
  draft = ref<
    ReviewData & {
      status: Review["status"];
      suitability: Review["suitability"];
      note: string;
    }
  >();
const baseline = ref(""),
  events = ref<
    {
      revision: number;
      created_at: string;
      previous: Review;
      current: Review;
    }[]
  >([]),
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
    if (page.status !== 'scanned') notices.add(`第${page.page}页未完成扫描：${scanReasonNames[page.reason ?? ''] ?? '处理未完成'}`);
    for (const note of page.notes) notices.add(`第${page.page}页：${note}`);
  }
  const covered = new Set(result.coverage.map(p => p.page));
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
  (grouped.value.find((g) => g.name === groupName.value)?.records ?? []).filter(
    (r) =>
      statusFilter.value === "all" ||
      currentReview(task.value!, r).status === statusFilter.value,
  ).filter(r => sourceFilter.value === "all" || sourceKey(r) === sourceFilter.value),
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
/* review state of every visible record, read once per render */
const visibleRows = computed(() =>
  task.value ? visible.value.map((r) => ({ r, v: currentReview(task.value!, r) })) : [],
);
/* counts for the status filter: the current material group within the source filter */
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
function share(n: number) {
  return summary.value.total ? `${((n / summary.value.total) * 100).toFixed(1)}%` : "—";
}
/* garden hero signature: every candidate as one dot, by review state */
const waffle = computed(() => (hasResult.value ? waffleLayout(summary.value) : null));
/* while the first task is still on its way, hold the hero's visual column */
const sigPending = computed(() => !error.value && !task.value && (loading.value || list.value.length > 0));
const totalEl = ref<HTMLElement>();
const shownTotal = useCountUp(() => (hasResult.value ? summary.value.total : null), { el: totalEl });
const pageCount = computed(() => task.value?.snapshot?.evidence?.page_count ?? null);
function modeLabel(item: ExtractionTask) {
  return item.source.mode === "document"
    ? "整篇自动识别"
    : `第 ${item.source.page} 页 · ${item.source.table}`;
}
/* the upload card pairs with the task list on wide screens; on one column it folds away once
   a task opens, so the review is one scroll closer (the same breakpoints as the CSS) */
function singleColumn() {
  try {
    return window.matchMedia(isPolarized.value ? "(max-width: 1100px)" : "(max-width: 980px)").matches;
  } catch {
    return true;
  }
}
const dragOver = ref(false);
function takeFile(selected: File | undefined) {
  if (!selected) return;
  if (!/\.pdf$/i.test(selected.name) && selected.type !== "application/pdf") {
    error.value = "请选择 PDF 文件。";
    return;
  }
  file.value = selected;
  pending = undefined;
  error.value = "";
}
function dropFile(event: DragEvent) {
  dragOver.value = false;
  if (uploading.value) return;
  takeFile(event.dataTransfer?.files?.[0]);
}
function fileSize(f: File) {
  return `${(f.size / 1024 / 1024).toFixed(2)} MB`;
}
const groupOptions = computed(() =>
  grouped.value.map((g) => ({
    value: g.name,
    label: g.name,
    count: g.records.filter(r => sourceFilter.value === 'all' || sourceKey(r) === sourceFilter.value).length,
  })).filter(g => g.count > 0),
);
const metricOptions = computed(() =>
  [...new Set([
    ...Object.keys(metricNames),
    ...measurements.value.map((r) => r.metric),
    draft.value?.metric ?? "",
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
let poll: number | undefined,
  disposed = false,
  selectionVersion = 0;
let pending:
  { file: File; page: number; table: string; mode: string; requestId: string } | undefined;
const controllers = new Set<AbortController>();
async function request<T>(path: string, options: RequestInit = {}) {
  const controller = new AbortController();
  controllers.add(controller);
  const timer = window.setTimeout(() => controller.abort(), 20000);
  try {
    return await extractionRequest<T>(path, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
    controllers.delete(controller);
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
  if (!groupOptions.value.some(g => g.value === groupName.value))
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
    if (disposed) return;
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
    if (!disposed)
      error.value = e instanceof Error ? e.message : "任务列表读取失败。";
  } finally {
    if (!disposed) loading.value = false;
  }
}
async function openTask(id: string, polling = false) {
  if (!polling && !canSwitch()) return;
  clearTimeout(poll);
  const version = ++selectionVersion;
  try {
    const value = await request<ExtractionTask>(`/${encodeURIComponent(id)}`);
    if (disposed || version !== selectionVersion) return;
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
      poll = window.setTimeout(() => openTask(id, true), 1500);
    else if (polling) loadList();
  } catch (e) {
    if (!disposed && version === selectionVersion)
      error.value =
        e instanceof Error
          ? e.message
          : "读取失败，已接收的任务会继续在后台处理。";
  }
}
function fileChanged(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0];
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
  if (extractionMode.value === "table" && (
    !Number.isInteger(pdfPage.value) ||
    pdfPage.value < 1 ||
    pdfPage.value > 200 ||
    !/^\d+[a-z]?$/i.test(tableNo.value.trim())
  )) {
    error.value = "请输入1—200的页码和有效表格编号，例如3。";
    return;
  }
  const table = `Table ${tableNo.value.trim()}`;
  if (
    !pending ||
    pending.file !== selected ||
    pending.page !== pdfPage.value ||
    pending.table !== table
    || pending.mode !== extractionMode.value
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
    if (disposed) return;
    pending = undefined;
    uploading.value = false;
    await openTask(value.id);
    await loadList();
  } catch (e) {
    if (!disposed)
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
    if (disposed) return;
    task.value.reviews = { ...task.value.reviews, [recordId]: saved };
    resetDraft();
    notice.value = `已保存，当前状态：${reviewStates[saved.status]}。`;
    if (eventsOpen.value) loadEvents();
  } catch (e) {
    if (!disposed)
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
      !disposed &&
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
  // metric and state are stored as keys: show their names, as the editor does
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
  disposed = true;
  selectionVersion++;
  clearTimeout(poll);
  controllers.forEach((c) => c.abort());
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

    <!-- ============================================================ upload -->
    <details
      class="card ld-upload"
      :open="uploadOpen"
      @toggle="uploadOpen = ($event.target as HTMLDetailsElement).open"
    >
      <summary class="ld-head">
        <Upload class="ld-head-ic" :size="17" aria-hidden="true" />
        <span class="ld-title">新增提取</span>
        <span class="ld-sub">可复制文字的 PDF · 最大 12MB</span>
        <ChevronDown class="ld-chevron" :size="17" aria-hidden="true" />
      </summary>
      <form class="upload-form" @submit.prevent="submit">
        <fieldset class="extraction-mode">
          <legend class="ld-label">提取方式</legend>
          <div class="ld-opts">
            <label :class="['ld-opt', { on: extractionMode === 'document' }]"
              ><input v-model="extractionMode" class="ld-radio" type="radio" value="document" />整篇自动识别</label
            ><label :class="['ld-opt', { on: extractionMode === 'table' }]"
              ><input v-model="extractionMode" class="ld-radio" type="radio" value="table" />指定表格</label
            >
          </div>
        </fieldset>
        <label
          class="ld-drop"
          :class="{ over: dragOver, ready: !!file }"
          @dragenter.prevent="dragOver = true"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="dropFile"
        >
          <span class="ld-drop-lens" aria-hidden="true"></span>
          <span class="ld-drop-ic" aria-hidden="true"><Upload :size="20" /></span>
          <span class="ld-drop-t">选择论文 PDF</span>
          <small v-if="file" class="ld-drop-file">{{ file.name }} · {{ fileSize(file) }}</small>
          <span v-else class="ld-drop-hint">点击选择，或将文件拖到此处</span>
          <input
            class="sr-only"
            type="file"
            accept=".pdf,application/pdf"
            aria-label="选择论文PDF"
            @change="fileChanged"
          />
        </label>
        <div v-if="extractionMode === 'table'" class="ld-table-fields">
          <label class="ld-field"
            ><span class="ld-label">PDF 页码</span
            ><input
              v-model.number="pdfPage"
              class="ld-input"
              type="number"
              min="1"
              max="200"
              aria-label="PDF页码"
              required
          /></label>
          <label class="ld-field"
            ><span class="ld-label">表格编号</span>
            <span class="table-input">
              <span>Table</span
              ><input
                v-model="tableNo"
                aria-label="表格编号"
                maxlength="8"
                placeholder="3"
                required
              /></span
          ></label>
        </div>
        <button
          class="button primary ld-run"
          :disabled="!file || !sessionReady || uploading || saving"
        >
          <Upload :size="15" aria-hidden="true" />{{ uploading ? "正在提交…" : "开始提取" }}
        </button>
      </form>
      <p class="ld-note upload-note">
        {{ extractionMode === 'document' ? '无需填写页码或表格编号。模型逐页寻找相关表格和正文数值，结果保留原文出处；图中读数和扫描件暂不支持。' : '页码按 PDF 文件中的实际页序填写。' }}提取在后台继续，刷新页面后可从任务列表恢复。上传的论文、提取结果和审核记录长期保存，所有访问者可查看和审核。
      </p>
    </details>

    <!-- ============================================================ task list -->
    <details class="card ld-tasks" open>
      <summary class="ld-head">
        <History class="ld-head-ic" :size="17" aria-hidden="true" />
        <span class="ld-title">提取记录</span>
        <span class="ld-count">{{ total }} 条</span>
        <ChevronDown class="ld-chevron" :size="17" aria-hidden="true" />
      </summary>
      <div class="task-toolbar">
        <form
          class="ld-search"
          role="search"
          @submit.prevent="
            listPage = 1;
            loadList();
          "
        >
          <Search :size="15" aria-hidden="true" /><input
            v-model="search"
            aria-label="搜索提取任务"
            placeholder="搜索文件名或表格"
            maxlength="200"
          /><button class="ld-go" :disabled="loading">搜索</button>
        </form>
        <button type="button" class="button ld-refresh" :disabled="loading" @click="loadList()">
          <RefreshCw :size="14" :class="{ spinning: loading }" aria-hidden="true" />刷新
        </button>
      </div>
      <p v-if="loading && !list.length" class="ld-state" role="status">正在读取任务…</p>
      <p v-else-if="!list.length" class="ld-state">
        {{
          search ? "没有匹配的提取任务。" : "暂无任务，上传第一篇论文开始整理。"
        }}
      </p>
      <template v-else>
        <p v-if="loading" class="sr-only" role="status">正在读取任务…</p>
        <div class="task-cols" aria-hidden="true">
          <span>文件</span><span>方式</span><span>时间</span><span>用时</span><span>状态</span>
        </div>
        <ol class="task-list" :class="{ refreshing: loading }" :aria-busy="loading">
          <li v-for="item in list" :key="item.id">
            <button
              type="button"
              :class="['task-row', `s-${item.status}`, { selected: task?.id === item.id }]"
              :aria-current="task?.id === item.id ? 'true' : undefined"
              :disabled="uploading || saving"
              @click="openTask(item.id)"
            >
              <span class="tr-ic" aria-hidden="true"
                ><Check v-if="item.status === 'completed'" :size="11" :stroke-width="3" /><RefreshCw
                  v-else-if="item.status === 'processing'"
                  :size="10"
                  :stroke-width="3"
                  class="spinning" /><X v-else :size="11" :stroke-width="3"
              /></span>
              <span class="tr-name">{{ item.source.filename }}</span>
              <span class="tr-meta"
                ><span class="tr-mode">{{ modeLabel(item) }}<span class="tr-sep"> ·</span></span> <span class="tr-time">{{ timeLabel(item.created_at) }}<span class="tr-sep"> ·</span></span> <span class="tr-ms">{{ item.latency_ms != null ? secondsLabel(item.latency_ms) : "—" }}</span></span
              >
              <span :class="['state-pill', item.status]">{{ taskStates[item.status] }}</span>
            </button>
          </li>
        </ol>
      </template>
      <div class="task-foot">
        <p class="ld-note privacy-note">
          记录长期保存在服务器，所有访问者均可查看、审核和导出。清除 Cookie 或更换浏览器不影响审核。
        </p>
        <div v-if="totalPages > 1" class="task-pagination">
          <button
            type="button"
            class="button ld-page"
            :disabled="loading || listPage <= 1"
            aria-label="上一页任务"
            @click="
              listPage--;
              loadList();
            "
          >
            <ChevronLeft :size="15" aria-hidden="true" /></button
          ><span class="ld-page-n">{{ listPage }} / {{ totalPages }}</span
          ><button
            type="button"
            class="button ld-page"
            :disabled="loading || listPage >= totalPages"
            aria-label="下一页任务"
            @click="
              listPage++;
              loadList();
            "
          >
            <ChevronRight :size="15" aria-hidden="true" />
          </button>
        </div>
      </div>
    </details>

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

      <template v-if="task.status === 'completed' || task.has_reviewable_result">
        <!-- ======================================================== current extraction -->
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
                @click="download('csv')"
              >
                <Download :size="14" aria-hidden="true" />导出已确认 CSV</button
              ><button
                type="button"
                class="button"
                :disabled="!summary.confirmed || exporting"
                @click="download('jsonl')"
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
            <p v-if="!measurements.length" class="ld-scan-note">本次没有得到通过证据校验的候选数据。可查看扫描说明，或切换指定表格模式重新提取。</p>
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

        <!-- ======================================================== original + review -->
        <div class="review-layout">
          <ExtractionOriginal :task="task" :measurement="chosen" />
          <section class="card review-panel" aria-label="候选数据审核">
            <div class="review-toolbar">
              <h2>候选数据</h2>
              <span class="ld-count">{{ grouped.length }} 个原料 / 处理组</span>
            </div>
            <div class="review-filters">
              <FilterSelect id="review-source" label="筛选原文来源" :model-value="sourceFilter" :options="sourceOptions" @update:model-value="chooseSource" />
              <FilterSelect
                id="review-material"
                label="选择原料"
                :model-value="groupName"
                :options="groupOptions"
                @update:model-value="chooseGroup"
              />
            </div>
            <div v-seg class="seg ld-status" role="group" aria-label="筛选审核状态">
              <button
                v-for="option in filterOptions"
                :key="option.value"
                type="button"
                :class="`f-${option.value}`"
                :aria-pressed="statusFilter === option.value"
                @click="chooseFilter(option.value)"
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
                  @click="selectMeasurement(r)"
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
              @submit.prevent="saveReview"
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
                      :options="metricOptions"
                  /></div>
                  <div class="ld-field select-field">
                    <span class="ld-label">测量状态</span><FilterSelect
                      id="review-measurement-state"
                      v-model="draft.measurement_state"
                      label="审核测量状态"
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
                        @change="setStatus(key)"
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
                  @click="
                    resetDraft();
                    error = '';
                    notice = '';
                  "
                >
                  取消修改</button
                ><button
                  class="button"
                  type="button"
                  :disabled="saving || dirty"
                  @click="task && openTask(task.id)"
                >
                  重新读取</button
                ><button
                  class="button audit-toggle"
                  type="button"
                  :aria-expanded="eventsOpen"
                  aria-controls="ld-audit"
                  @click="toggleEvents"
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
/* a folded upload card keeps its own height next to the list */
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

/* =================================================================== shared card parts */
.card {
  padding: 22px 24px;
}
:root[data-mode="garden"] .card {
  padding: 24px 26px;
}
.ld-head {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 10px;
  padding-right: 30px;
  cursor: pointer;
  list-style: none;
  border-radius: var(--radius-xs);
}
.ld-head::-webkit-details-marker,
.ld-scan > summary::-webkit-details-marker,
.scan-notes > summary::-webkit-details-marker,
.conditions > summary::-webkit-details-marker {
  display: none;
}
.ld-head-ic {
  align-self: center;
  color: var(--text-3);
}
.ld-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
.ld-sub {
  flex-basis: 100%;
  font-size: 12.5px;
  color: var(--text-2);
}
.ld-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
.ld-chevron {
  position: absolute;
  right: 0;
  top: 2px;
  color: var(--text-2);
  transition: transform 0.25s var(--ease);
}
details:not([open]) > summary > .ld-chevron {
  transform: rotate(-90deg);
}
:root[data-mode="polarized"] .ld-head .ld-count {
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
}
:root[data-mode="garden"] .ld-head-ic {
  display: none;
}
:root[data-mode="garden"] .ld-title {
  font-size: 19px;
  font-weight: 500;
  letter-spacing: 0.03em;
}
:root[data-mode="garden"] .ld-head .ld-count {
  font-size: 14px;
}
.ld-note {
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-2);
}
.ld-state {
  margin: 14px 0 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.ld-label {
  display: block;
  font-size: 12.5px;
  color: var(--text-2);
}
:root[data-mode="polarized"] .ld-label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
}
/* text inputs (fields on a card) */
.ld-input,
.table-input {
  width: 100%;
  min-width: 0;
  min-height: 40px;
  padding: 9px 12px;
  font: inherit;
  font-size: 13.5px;
  color: var(--text);
  transition:
    border-color 0.15s,
    box-shadow 0.15s,
    background 0.15s;
}
textarea.ld-input {
  resize: vertical;
  line-height: 1.7;
}
.ld-input::placeholder,
.table-input input::placeholder {
  color: var(--text-3);
}
.ld-num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
:root[data-mode="polarized"] .ld-input,
:root[data-mode="polarized"] .table-input {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .ld-input:hover:not(:disabled),
:root[data-mode="polarized"] .table-input:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .ld-input:focus-visible {
  outline: none;
  border-color: var(--focus);
  box-shadow: 0 0 0 3px var(--accent-tint);
}
:root[data-mode="garden"] .ld-input,
:root[data-mode="garden"] .table-input {
  border: 1px solid transparent;
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface) 78%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    0 6px 16px -12px color-mix(in srgb, var(--accent) 45%, transparent);
}
:root[data-mode="garden"] .ld-input:focus-visible {
  outline: none;
  border-color: var(--focus);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    0 0 0 3px color-mix(in srgb, var(--focus) 22%, transparent);
}
.ld-input:disabled {
  color: var(--text-2);
  cursor: not-allowed;
}
.ld-field {
  display: grid;
  gap: 7px;
  min-width: 0;
}
/* radio pills (native radios kept for arrow-key behaviour, drawn as v1 chips / a v4 seg) */
.extraction-mode,
.decision {
  margin: 0;
  padding: 0;
  border: 0;
  min-width: 0;
}
.extraction-mode legend,
.decision legend {
  padding: 0;
  margin-bottom: 9px;
}
.ld-opts {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 100%;
}
.ld-opt {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 13.5px;
  color: var(--text-2);
  white-space: nowrap;
  cursor: pointer;
  transition:
    color 0.18s,
    background 0.18s,
    border-color 0.18s,
    box-shadow 0.25s;
}
.ld-opt:hover {
  color: var(--text);
}
.ld-opt.on {
  color: var(--text);
}
.ld-radio {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: inherit;
}
.ld-opt:has(.ld-radio:focus-visible) {
  outline: 2.5px solid var(--focus);
  outline-offset: 2px;
}
:root[data-mode="polarized"] .ld-opt {
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--text) 2.5%, transparent);
}
:root[data-mode="polarized"] .ld-opt:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .ld-opt.on {
  border-color: color-mix(in srgb, var(--text) 34%, transparent);
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
:root[data-mode="garden"] .ld-opts {
  gap: 2px;
  padding: 4px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 50%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    inset 0 2px 6px color-mix(in srgb, var(--accent) 7%, transparent);
}
:root[data-mode="garden"] .ld-opt {
  min-height: 32px;
}
:root[data-mode="garden"] .ld-opt.on {
  font-weight: 500;
  background: var(--surface);
  box-shadow:
    0 6px 14px -8px color-mix(in srgb, var(--accent) 50%, transparent),
    inset 0 0 0 1px var(--surface);
}
fieldset:disabled .ld-opt {
  color: var(--text-3);
  cursor: not-allowed;
}
fieldset:disabled .ld-opt.on {
  color: var(--text-2);
}
/* review state glyph (✓ … ✕ in a tinted disc, v1 .st-ic) */
.st-ic {
  --st: var(--text-2);
  display: inline-grid;
  place-items: center;
  flex: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--st);
  background: color-mix(in srgb, var(--st) 16%, transparent);
}
.s-confirmed .st-ic,
.review-pill.confirmed .st-ic,
.lg-ok .st-ic,
.o-confirmed .st-ic {
  --st: var(--ok);
}
.s-rejected .st-ic,
.review-pill.rejected .st-ic,
.lg-bad .st-ic,
.o-rejected .st-ic {
  --st: var(--bad);
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

/* =================================================================== upload (v1 .up / v4 upload tile) */
.ld-upload {
  display: flex;
  flex-direction: column;
}
.upload-form {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}
.ld-drop {
  position: relative;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 6px;
  min-height: 150px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition:
    border-color 0.2s,
    background 0.2s;
}
.ld-drop:has(input:focus-visible) {
  outline: 2.5px solid var(--focus);
  outline-offset: 3px;
}
.ld-drop-t {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
.ld-drop-hint {
  font-size: 12.5px;
  color: var(--text-2);
}
.ld-drop-file {
  max-width: 100%;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.ld-drop-lens,
.ld-drop-ic {
  display: none;
}
:root[data-mode="polarized"] .ld-drop {
  border: 1px dashed var(--line-strong);
  border-radius: 16px;
  background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--rc) 13%, transparent), transparent 70%);
}
:root[data-mode="polarized"] .ld-drop:hover,
:root[data-mode="polarized"] .ld-drop.over {
  border-color: color-mix(in srgb, var(--accent) 80%, transparent);
  background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 70%);
}
:root[data-mode="polarized"] .ld-drop.ready {
  border-style: solid;
}
:root[data-mode="polarized"] .ld-drop-lens {
  display: block;
  width: 46px;
  height: 46px;
  margin-bottom: 4px;
  border-radius: 50%;
  background: var(--ifc);
  -webkit-mask: radial-gradient(circle, transparent 54%, currentColor 56%);
  mask: radial-gradient(circle, transparent 54%, currentColor 56%);
  opacity: 0.85;
}
:root[data-mode="garden"] .ld-drop {
  border: 1.5px dashed color-mix(in srgb, var(--accent) 26%, transparent);
  border-radius: 22px;
  background: color-mix(in srgb, var(--surface) 55%, transparent);
}
:root[data-mode="garden"] .ld-drop:hover,
:root[data-mode="garden"] .ld-drop.over {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: var(--accent-tint);
}
:root[data-mode="garden"] .ld-drop.ready {
  border-style: solid;
  background: var(--surface);
}
:root[data-mode="garden"] .ld-drop-ic {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 2px;
  border-radius: 50%;
  color: var(--text);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
:root[data-mode="garden"] .ld-drop-t {
  font-weight: 500;
}
.ld-table-fields {
  display: grid;
  grid-template-columns: minmax(96px, 0.6fr) minmax(0, 1fr);
  gap: 12px;
}
.table-input {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 0;
  padding-bottom: 0;
}
.table-input:focus-within {
  border-color: var(--focus) !important;
}
.table-input > span {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.table-input input {
  flex: 1;
  min-width: 0;
  padding: 9px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 13.5px;
}
.table-input input:focus-visible {
  outline: none;
}
.ld-run {
  min-height: 44px;
}
:root[data-mode="garden"] .ld-run {
  justify-self: start;
  padding: 0 22px;
}
.upload-note {
  margin-top: 14px;
}

/* =================================================================== task list (v1 .xlist / v4 history table) */
.ld-tasks {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
}
.task-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 16px 0 12px;
}
.ld-search {
  flex: 1 1 220px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 38px;
  padding: 0 4px 0 12px;
  color: var(--text-3);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
.ld-search input {
  flex: 1;
  min-width: 0;
  padding: 8px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}
.ld-search input::placeholder {
  color: var(--text-3);
}
.ld-search input:focus-visible {
  outline: none;
}
.ld-search:has(input:focus-visible) {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 28%, transparent);
}
.ld-go {
  flex-shrink: 0;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  white-space: nowrap;
  transition: background 0.2s;
}
.ld-go:focus-visible {
  outline-offset: 1px;
}
:root[data-mode="polarized"] .ld-search {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .ld-search:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .ld-go {
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
:root[data-mode="polarized"] .ld-go:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 13%, transparent);
}
:root[data-mode="polarized"] .ld-refresh {
  min-height: 38px;
  padding: 0 12px;
  font-size: 13px;
}
:root[data-mode="garden"] .ld-search {
  border: 1px solid transparent;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
:root[data-mode="garden"] .ld-go {
  background: var(--accent-tint);
}
:root[data-mode="garden"] .ld-go:hover:not(:disabled) {
  background: color-mix(in oklab, var(--accent) 16%, var(--surface));
}
.task-cols {
  display: none;
}
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  transition: opacity 0.2s;
}
.task-list.refreshing {
  opacity: 0.6;
}
.task-row {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  grid-template-areas:
    "ic name state"
    "ic meta state";
  align-items: center;
  gap: 3px 12px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  text-align: left;
  color: var(--text);
  transition:
    background 0.2s,
    border-color 0.2s,
    box-shadow 0.25s;
}
.tr-ic {
  grid-area: ic;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--text-2);
  background: color-mix(in srgb, var(--text-2) 16%, transparent);
}
.task-row.s-completed .tr-ic {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 16%, transparent);
}
.task-row.s-failed .tr-ic,
.task-row.s-interrupted .tr-ic {
  color: var(--bad);
  background: color-mix(in srgb, var(--bad) 16%, transparent);
}
.task-row.s-processing .tr-ic {
  color: var(--accent-ink);
  background: var(--accent-tint);
}
.tr-name {
  grid-area: name;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.tr-meta {
  grid-area: meta;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.tr-mode,
.tr-time,
.tr-ms {
  white-space: nowrap;
}
.state-pill {
  grid-area: state;
  justify-self: end;
  font-size: 12px;
  white-space: nowrap;
  color: var(--text-2);
}
.state-pill.completed {
  color: var(--ok);
}
.state-pill.failed,
.state-pill.interrupted {
  color: var(--bad);
}
.state-pill.processing {
  color: var(--accent-ink);
}
:root[data-mode="polarized"] .task-row {
  background: color-mix(in srgb, var(--text) 2%, transparent);
}
:root[data-mode="polarized"] .task-row:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 5%, transparent);
}
:root[data-mode="polarized"] .task-row.selected {
  border-color: var(--line-strong);
  background: color-mix(in srgb, var(--text) 5%, transparent);
  box-shadow: inset 2px 0 0 var(--accent);
}
/* garden: soft table rows (v4 history table); a narrow tile keeps two lines per row */
:root[data-mode="garden"] .task-list {
  gap: 6px;
}
:root[data-mode="garden"] .task-row {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "name state"
    "meta state";
  padding: 11px 14px;
  border: 0;
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .task-row:hover:not(:disabled) {
  background: var(--surface);
}
:root[data-mode="garden"] .task-row.selected {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--bl),
    var(--shadow-sm);
}
:root[data-mode="garden"] .tr-ic {
  display: none;
}
:root[data-mode="garden"] .tr-meta {
  font-size: 12px;
}
:root[data-mode="garden"] .state-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
}
:root[data-mode="garden"] .state-pill::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
:root[data-mode="garden"] .state-pill.completed {
  color: var(--ok);
  background: var(--ok-tint);
}
:root[data-mode="garden"] .state-pill.failed,
:root[data-mode="garden"] .state-pill.interrupted {
  color: var(--bad);
  background: var(--bad-tint);
}
:root[data-mode="garden"] .state-pill.processing {
  color: var(--accent-ink);
  background: var(--accent-tint);
}
@container (min-width: 640px) {
  :root[data-mode="garden"] .task-cols,
  :root[data-mode="garden"] .task-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 116px 140px 64px 86px;
    grid-template-areas: none;
    gap: 0 12px;
    align-items: center;
  }
  :root[data-mode="garden"] .task-cols {
    padding: 0 14px 8px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 6px;
    font-size: 12.5px;
    color: var(--text-2);
  }
  :root[data-mode="garden"] .task-cols > span:nth-child(4) {
    text-align: right;
  }
  :root[data-mode="garden"] .task-row > * {
    grid-area: auto;
  }
  :root[data-mode="garden"] .tr-meta {
    display: contents;
  }
  :root[data-mode="garden"] .tr-meta > * {
    min-width: 0;
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text);
  }
  :root[data-mode="garden"] .tr-time,
  :root[data-mode="garden"] .tr-ms {
    font-family: var(--font-mono) !important;
    font-size: 12.5px !important;
  }
  :root[data-mode="garden"] .tr-ms {
    text-align: right;
  }
  :root[data-mode="garden"] .tr-sep {
    display: none;
  }
  :root[data-mode="garden"] .state-pill {
    justify-self: start;
  }
}
.task-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  margin-top: auto;
  padding-top: 14px;
}
.privacy-note {
  flex: 1 1 260px;
  font-size: 12px;
}
.task-pagination {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ld-page {
  width: 34px;
  min-height: 34px !important;
  padding: 0 !important;
}
.ld-page-n {
  min-width: 44px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text);
}
:root[data-mode="polarized"] .task-foot {
  border-top: 1px solid var(--line-soft);
  margin-top: 14px;
}
:root[data-mode="polarized"] .ld-tasks .task-foot {
  margin-top: auto;
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

/* =================================================================== current extraction (v1 .ex-sum / v4 summary tile) */
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
  /* the remainder still reads as a segment (≥3:1 on the card) */
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
/* garden: v4 sumrow (big number + three stat numerals with badges), the bar full width below */
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

/* scan report: caveat (v1 magenta rule / v4 glass note), discovered tables, notes */
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
/* one or two tables keep the card proportions of a three-card row */
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

/* =================================================================== original page + review */
.review-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 18px;
  align-items: start;
}
:root[data-mode="garden"] .review-layout {
  gap: 22px;
}
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
.review-filters :deep(.filter-select) {
  max-width: 100%;
}
.review-filters :deep(.filter-trigger) {
  max-width: 100%;
}
.review-filters :deep(.filter-trigger > span) {
  overflow: hidden;
  text-overflow: ellipsis;
}
.ld-status {
  margin-bottom: 12px;
}
/* lit polarized chip: the count steps up to --text-2 on the pressed fill */
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
/* garden: v4 review rows as soft pills, the selected one white with a lilac ring */
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

/* ------------------------------------------------ editor */
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
/* the extracted value as a readout, in the colour of the 所选数值 mark on the page */
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
.editor-fields :deep(.filter-select) {
  width: 100%;
}
.editor-fields :deep(.filter-trigger) {
  width: 100%;
  height: 40px;
  justify-content: space-between;
}
.editor-fields :deep(.filter-trigger > span) {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
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

/* ------------------------------------------------ review history (v1 timeline / v4 glass cards) */
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
@media (max-width: 1280px) {
  :root[data-mode="polarized"] .ld-sum-big {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "n"
      "bar"
      "legend";
  }
}
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
  .literature-data,
  :root[data-mode="garden"] .literature-data {
    gap: 14px;
  }
  .card,
  :root[data-mode="garden"] .card {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .card {
    border-radius: 24px;
  }
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
  /* four status chips as an even 2 × 2 grid instead of a ragged wrap */
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
  .review-filters :deep(.filter-select),
  .review-filters :deep(.filter-trigger) {
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
  .ld-table-fields {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  :root[data-mode="garden"] .ld-run {
    justify-self: stretch;
  }
}
</style>
