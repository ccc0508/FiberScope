<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import {
  FileSpreadsheet,
  Upload,
  History,
  Download,
  RefreshCw,
  Check,
  Search,
  ChevronLeft,
  ChevronRight,
} from "lucide-vue-next";
import FilterSelect from "../components/FilterSelect.vue";
import ExtractionOriginal from "../components/ExtractionOriginal.vue";
import {
  extractionRequest,
  currentReview,
  groups,
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
import { timeLabel } from "../literature";

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
];
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
      uploadOpen.value = false;
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
      `/api/v1/literature/extractions/${task.value.id}/pdf`,
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
  return (Object.keys(labels) as (keyof ReviewData)[])
    .filter((k) => event.previous.current[k] !== event.current.current[k])
    .map((k) => ({
      label: labels[k],
      before: event.previous.current[k] || "未说明",
      after: event.current.current[k] || "未说明",
    }));
}
async function download(format: "jsonl" | "csv") {
  if (!task.value || !summary.value.confirmed) return;
  // A server attachment works in both normal browsers and the in-app browser.
  window.location.assign(`/api/v1/literature/extractions/${task.value.id}/confirmed?format=${format}`);
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
    <div class="data-heading">
      <div>
        <div class="eyebrow">科研助手</div>
        <h1>文献数据提取与审核</h1>
        <p>上传论文，自动发现工艺、纤维特性和纸张性能数据，核对后再使用。</p>
      </div>
      <FileSpreadsheet :size="30" />
    </div>
    <div v-if="error" class="data-alert" role="alert">
      {{ error
      }}<button
        class="button"
        @click="
          error = '';
          loadList();
        "
      >
        刷新任务
      </button>
    </div>
    <p v-if="notice" class="data-notice" role="status">
      <Check :size="15" />{{ notice }}
    </p>
    <details
      class="card upload-panel"
      :open="uploadOpen"
      @toggle="uploadOpen = ($event.target as HTMLDetailsElement).open"
    >
      <summary>
        <Upload :size="17" />新增提取<span>可复制文字的 PDF · 最大 12MB</span>
      </summary>
      <form class="upload-form" @submit.prevent="submit">
        <fieldset class="extraction-mode" aria-label="提取方式">
          <legend>提取方式</legend>
          <label><input v-model="extractionMode" type="radio" value="document" />整篇自动识别</label>
          <label><input v-model="extractionMode" type="radio" value="table" />指定表格</label>
        </fieldset>
        <label class="file-field"
          >选择论文 PDF<input
            type="file"
            accept=".pdf,application/pdf"
            aria-label="选择论文PDF"
            @change="fileChanged"
          /><small v-if="file">{{ file.name }}</small></label
        >
        <label v-if="extractionMode === 'table'"
          >PDF 页码<input
            v-model.number="pdfPage"
            type="number"
            min="1"
            max="200"
            aria-label="PDF页码"
            required
        /></label>
        <label v-if="extractionMode === 'table'"
          >表格编号
          <div class="table-input">
            <span>Table</span
            ><input
              v-model="tableNo"
              aria-label="表格编号"
              maxlength="8"
              placeholder="3"
              required
            /></div
        ></label>
        <button
          class="button primary"
          :disabled="!file || !sessionReady || uploading || saving"
        >
          <Upload :size="15" />{{ uploading ? "正在提交…" : "开始提取" }}
        </button>
      </form>
      <p class="upload-note">
        {{ extractionMode === 'document' ? '无需填写页码或表格编号。模型逐页寻找相关表格和正文数值，结果保留原文出处；图中读数和扫描件暂不支持。' : '页码按 PDF 文件中的实际页序填写。' }}
        提取在后台继续，刷新页面后可从任务列表恢复。
        上传的论文、提取结果和审核记录长期保存，所有访问者可查看。
      </p>
    </details>
    <details class="card task-panel" open>
      <summary>
        <History :size="17" />提取记录<span>{{ total }} 条</span>
      </summary>
      <div class="task-toolbar">
        <form
          @submit.prevent="
            listPage = 1;
            loadList();
          "
        >
          <Search :size="15" /><input
            v-model="search"
            aria-label="搜索提取任务"
            placeholder="搜索文件名或表格"
            maxlength="200"
          /><button class="button" :disabled="loading">搜索</button>
        </form>
        <button class="button" :disabled="loading" @click="loadList()">
          <RefreshCw :size="14" />刷新
        </button>
      </div>
      <p v-if="loading" class="muted-note" role="status">正在读取任务…</p>
      <p v-else-if="!list.length" class="muted-note">
        {{
          search ? "没有匹配的提取任务。" : "暂无任务，上传第一篇论文开始整理。"
        }}
      </p>
      <div v-else class="task-list">
        <button
          v-for="item in list"
          :key="item.id"
          :class="['task-row', { selected: task?.id === item.id }]"
          :disabled="uploading || saving"
          @click="openTask(item.id)"
        >
          <div>
            <strong>{{ item.source.filename }}</strong
            ><span
              >{{ item.source.mode === 'document' ? '整篇自动识别' : `第 ${item.source.page} 页 · ${item.source.table}` }} ·
              {{ timeLabel(item.created_at) }}</span
            >
          </div>
          <span :class="['state-pill', item.status]">{{
            taskStates[item.status]
          }}</span>
        </button>
      </div>
      <div v-if="totalPages > 1" class="task-pagination">
        <button
          class="button"
          :disabled="loading || listPage <= 1"
          aria-label="上一页任务"
          @click="
            listPage--;
            loadList();
          "
        >
          <ChevronLeft :size="15" /></button
        ><span>{{ listPage }} / {{ totalPages }}</span
        ><button
          class="button"
          :disabled="loading || listPage >= totalPages"
          aria-label="下一页任务"
          @click="
            listPage++;
            loadList();
          "
        >
          <ChevronRight :size="15" />
        </button>
      </div>
      <p class="muted-note privacy-note">
        记录长期保存在服务器，所有访问者均可查看和导出。清除 Cookie 或更换浏览器不影响查看。
      </p>
    </details>
    <template v-if="task">
      <section
        v-if="task.status === 'processing'"
        class="card task-state"
        role="status"
      >
        <RefreshCw :size="20" class="spinning" />
        <div>
          <h2>{{ task.source.mode === 'document' ? '正在扫描整篇论文' : `正在提取 ${task.source.table}` }}</h2>
          <p v-if="task.progress">第 {{ task.progress.page }} / {{ task.progress.page_count }} 页 · {{ task.progress.stage }} · 已保存 {{ task.progress.measurement_count }} 条候选</p>
          <p>完成后会自动显示候选数据。你可以离开页面，稍后从任务列表查看。</p>
        </div>
      </section>
      <section
        v-else-if="task.status !== 'completed'"
        class="card task-state failure"
      >
        <div>
          <h2>{{ taskStates[task.status] }}</h2>
          <p>{{ task.message }}</p>
          <p v-if="task.has_reviewable_result">下方保留了已通过原文证据校验的部分候选，可继续核对；本次整篇提取未完成。</p>
        </div>
        <button class="button" :disabled="uploading" @click="reextract">
          重新提取
        </button>
      </section>
      <template v-if="task.status === 'completed' || task.has_reviewable_result">
        <div class="review-heading">
          <div>
            <h2>{{ task.source.filename }}</h2>
            <p>
              {{ summary.total }} 条候选 · 已确认 {{ summary.confirmed }} ·
              待核对 {{ summary.pending }} · 已驳回 {{ summary.rejected }}
            </p>
          </div>
          <div class="export-actions">
            <button
              class="button"
              :disabled="!summary.confirmed || exporting"
              @click="download('csv')"
            >
              <Download :size="14" />导出已确认 CSV</button
            ><button
              class="button"
              :disabled="!summary.confirmed || exporting"
              @click="download('jsonl')"
            >
              JSONL
            </button>
          </div>
        </div>
        <details v-if="task.snapshot?.result?.coverage" class="card scan-report" open>
          <summary>自动发现结果 · {{ task.snapshot.result.coverage_complete ? '逐页扫描已完成' : '部分内容未完成，请查看说明' }}</summary>
          <p class="muted-note">扫描完成表示各页已处理，不保证发现全部数据；所有候选仍需核对，不自动认可建模适用性。</p>
          <p v-if="!measurements.length" class="muted-note">本次没有得到通过证据校验的候选数据。可查看扫描说明，或切换指定表格模式重新提取。</p>
          <ul class="discovered-tables">
            <li v-for="(t, index) in task.snapshot.result.discovered_tables" :key="index">
              <strong>第 {{ t.page }} 页 · {{ t.table }}</strong>
              <span>{{ t.status === 'extracted' ? `已提取 ${t.measurement_count} 条` : '未提取成功' }} · {{ t.reason }}</span>
            </li>
          </ul>
          <details v-if="scanNotices.length" class="scan-notes">
            <summary>扫描说明与未提取内容（{{ scanNotices.length }}）</summary>
            <ul><li v-for="(warning, index) in scanNotices" :key="index">{{ warning }}</li></ul>
          </details>
        </details>
        <div class="review-layout">
          <ExtractionOriginal :task="task" :measurement="chosen" />
          <section class="card review-panel" aria-label="候选数据审核">
            <div class="review-toolbar">
              <h2>候选数据</h2>
              <span>{{ grouped.length }} 个原料 / 处理组</span>
            </div>
            <div class="review-filters">
              <FilterSelect id="review-source" label="筛选原文来源" :model-value="sourceFilter" :options="sourceOptions" @update:model-value="chooseSource" />
              <FilterSelect
                id="review-material"
                label="选择原料"
                :model-value="groupName"
                :options="groupOptions"
                @update:model-value="chooseGroup"
              /><FilterSelect
                id="review-filter"
                label="筛选审核状态"
                :model-value="statusFilter"
                :options="filterOptions"
                @update:model-value="chooseFilter"
              />
            </div>
            <div class="measurement-list" aria-label="候选指标列表">
              <button
                v-for="r in visible"
                :key="r.record_id"
                :class="[
                  'measurement-row',
                  { selected: r.record_id === selectedId },
                ]"
                :disabled="saving"
                @click="selectMeasurement(r)"
              >
                <div>
                  <strong>{{
                    metricNames[currentReview(task, r).current.metric] ??
                    currentReview(task, r).current.metric
                  }}</strong
                  ><span>{{
                    measurementStates[
                      currentReview(task, r).current.measurement_state
                    ] ?? "未说明"
                  }}</span><small v-if="task.source.mode === 'document'" class="record-source">第 {{ r.source_pdf_page }} 页 · {{ r.source_table }}{{ r.value_qualifier === 'approximate' ? ' · 原文约数' : '' }}</small>
                </div>
                <div class="measurement-value">
                  {{ currentReview(task, r).current.raw_value
                  }}<small>{{
                    currentReview(task, r).current.raw_unit || "单位未说明"
                  }}</small>
                </div>
                <span :class="['review-pill', currentReview(task, r).status]">{{
                  reviewStates[currentReview(task, r).status]
                }}</span>
              </button>
              <p v-if="!visible.length" class="muted-note">
                当前原料没有匹配的记录。
              </p>
            </div>
            <form
              v-if="chosen && draft"
              class="review-editor"
              @submit.prevent="saveReview"
            >
              <div class="editor-heading">
                <h3>核对所选记录</h3>
                <span>{{
                  dirty
                    ? "有未保存修改"
                    : review?.revision
                      ? `审核版本 ${review.revision}`
                      : "尚未审核"
                }}</span>
              </div>
              <div class="original-value">
                <span>原文提取</span
                ><strong>{{ chosen.raw_value }} {{ chosen.raw_unit }}</strong
                ><small
                  >{{ metricNames[chosen.metric] ?? chosen.metric }} ·
                  {{ measurementStates[chosen.measurement_state] }} ·
                  {{ chosen.raw_material }}</small
                >
              </div>
              <p v-if="!canReview" class="muted-note">公开记录可查看、下载和查看审核历史；修改仅限原提交浏览器。</p>
              <fieldset class="editable-review" :disabled="saving || !canReview">
                <div class="editor-fields">
                  <label class="full-field"
                    >原料<input
                      v-model="draft.raw_material"
                      aria-label="审核原料"
                      maxlength="200"
                      required
                  /></label>
                  <div class="select-field">
                    <span>指标</span><FilterSelect
                      id="review-metric"
                      label="审核指标"
                      v-model="draft.metric"
                      :options="metricOptions"
                  /></div>
                  <div class="select-field">
                    <span>测量状态</span><FilterSelect
                      id="review-measurement-state"
                      label="审核测量状态"
                      v-model="draft.measurement_state"
                      :options="stateOptions"
                  /></div>
                  <label
                    >数值<input
                      v-model="draft.raw_value"
                      aria-label="审核数值"
                      inputmode="decimal"
                      maxlength="60"
                      required
                  /></label>
                  <label
                    >单位<input
                      v-model="draft.raw_unit"
                      aria-label="审核单位"
                      maxlength="60"
                      placeholder="原文未说明则留空"
                  /></label>
                </div>
                <details class="conditions">
                  <summary>补充原文中的实验条件（可选）</summary>
                  <label
                    >实验条件<textarea
                      v-model="draft.experiment_condition"
                      aria-label="实验条件"
                      maxlength="600"
                      rows="2"
                      placeholder="只填写原文明确报告的条件"
                    /></label
                  ><label
                    >条件来源<input
                      v-model="draft.condition_source"
                      aria-label="条件来源"
                      maxlength="300"
                      placeholder="例如：第3页，方法2.4节"
                  /></label>
                </details>
                <fieldset class="decision">
                  <legend>原文抄录核对</legend>
                  <label v-for="(name, key) in reviewStates" :key="key"
                    ><input
                      type="radio"
                      name="review-status"
                      :value="key"
                      :checked="draft.status === key"
                      @change="setStatus(key)"
                    />{{ key === "confirmed" ? "确认抄录" : name }}</label
                  >
                </fieldset>
                <fieldset
                  class="decision"
                  :disabled="draft.status !== 'confirmed'"
                >
                  <legend>建模适用性</legend>
                  <label v-for="(name, key) in suitabilityNames" :key="key"
                    ><input
                      v-model="draft.suitability"
                      type="radio"
                      name="review-suitability"
                      :value="key"
                    />{{ name }}</label
                  >
                </fieldset>
                <p class="muted-note">
                  确认抄录只表示与原文一致。建模适用性需结合实验条件另行判断。
                </p>
                <label class="note-field"
                  >审核说明<textarea
                    v-model="draft.note"
                    aria-label="审核说明"
                    maxlength="1200"
                    rows="3"
                    placeholder="修改、驳回或评估建模适用性时，请说明依据。"
                  />
                </label>
              </fieldset>
              <div class="editor-actions">
                <button v-if="canReview" class="button primary" :disabled="saving || !dirty">
                  <Check :size="15" />{{
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
                  @click="toggleEvents"
                >
                  审核记录
                </button>
              </div>
              <div v-if="eventsOpen" class="audit-list">
                <p v-if="eventsError" role="alert">{{ eventsError }}</p>
                <p v-else-if="!events.length" class="muted-note">
                  尚无审核记录。
                </p>
                <article v-for="event in events" :key="event.revision">
                  <strong
                    >版本 {{ event.revision }} ·
                    {{ reviewStates[event.current.status] }}</strong
                  ><span>{{ timeLabel(event.created_at) }}</span>
                  <p v-for="change in changes(event)" :key="change.label">
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
                  <p v-if="event.current.note">{{ event.current.note }}</p>
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
.literature-data {
  max-width: 1500px;
  margin: 0 auto;
}
.data-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  color: var(--blue);
}
.eyebrow {
  font-size: 12px;
  margin-bottom: 7px;
  color: var(--muted);
}
h1 {
  font-size: 26px;
  color: #344358;
  font-weight: 700;
}
.data-heading p {
  margin-top: 10px;
  color: var(--muted);
  line-height: 1.7;
  font-size: 13px;
}
.upload-panel,
.task-panel {
  padding: 20px 22px;
  margin-bottom: 18px;
}
summary {
  display: flex;
  align-items: center;
  gap: 9px;
  font-weight: 700;
  cursor: pointer;
  font-size: 15px;
}
summary > span {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.upload-form {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 105px 125px auto;
  align-items: end;
  gap: 16px;
  margin-top: 20px;
}
label,
.select-field {
  display: grid;
  gap: 7px;
  font-size: 12px;
  color: #64758b;
  min-width: 0;
}
input,
textarea {
  border: 1px solid #dce5ed;
  border-radius: 6px;
  background: white;
  color: #354052;
  padding: 10px;
  font: inherit;
  min-width: 0;
  width: 100%;
}
textarea {
  resize: vertical;
  font-size: 13px;
  line-height: 1.7;
}
.file-field small {
  font-size: 11px;
  overflow-wrap: anywhere;
}
input[type="file"] {
  padding: 6px;
  font-size: 12px;
}
input[type="file"]::file-selector-button {
  background: var(--blue-light);
  color: var(--blue);
  border: 0;
  padding: 7px 10px;
  border-radius: 4px;
  margin-right: 8px;
  cursor: pointer;
}
.table-input {
  display: flex;
  align-items: center;
  border: 1px solid #dce5ed;
  border-radius: 6px;
  overflow: hidden;
}
.table-input span {
  padding-left: 10px;
  color: var(--muted);
}
.table-input input {
  border: 0;
  width: 70px;
  padding-left: 7px;
}
.upload-note,
.muted-note {
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
}
.upload-note {
  margin-top: 12px;
}
.extraction-mode {
  grid-column: 1 / -1;
  border: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  min-width: 0;
}
.extraction-mode legend {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}
.extraction-mode label {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
}
.extraction-mode input {
  width: auto;
  accent-color: var(--blue);
}
.scan-report {
  padding: 18px;
  margin-bottom: 18px;
  font-size: 13px;
  line-height: 1.8;
}
.scan-report summary { cursor: pointer; color: var(--text); }
.discovered-tables { margin: 12px 0; padding-left: 20px; }
.discovered-tables li { margin: 8px 0; }
.discovered-tables span { display: block; color: var(--muted); }
.scan-notes ul { padding-left: 20px; overflow-wrap: anywhere; }
.record-source { display: block; color: var(--muted); font-size: 10px; margin-top: 3px; }
.button {
  white-space: nowrap;
  font-size: 12px;
  flex-shrink: 0;
}
.task-toolbar,
.task-toolbar form {
  display: flex;
  align-items: center;
  gap: 10px;
}
.task-toolbar {
  justify-content: space-between;
  margin: 16px 0;
}
.task-toolbar form {
  flex: 1;
  max-width: 430px;
  min-width: 0;
}
.task-toolbar input {
  font-size: 13px;
  padding: 8px;
}
.task-list {
  display: grid;
  gap: 5px;
}
.task-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  text-align: left;
  gap: 12px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 10px 12px;
  background: #f8fafc;
  min-width: 0;
}
.task-row.selected,
.task-row:hover {
  background: #eef5fb;
  border-color: #cddfed;
}
.task-row div {
  min-width: 0;
}
.task-row strong {
  font-size: 13px;
  font-weight: 400;
  display: block;
  overflow-wrap: anywhere;
}
.task-row div > span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  margin-top: 5px;
}
.state-pill,
.review-pill {
  font-size: 11px;
  padding: 4px 7px;
  border-radius: 4px;
  background: #f0f3f6;
  color: var(--muted);
  white-space: nowrap;
}
.state-pill.processing {
  color: var(--blue);
  background: var(--blue-light);
}
.state-pill.completed,
.review-pill.confirmed {
  color: #438675;
  background: #edf6f2;
}
.state-pill.failed,
.state-pill.interrupted,
.review-pill.rejected {
  color: #a77745;
  background: #fff4e6;
}
.privacy-note {
  margin-top: 12px;
  font-size: 11px;
}
.task-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  font-size: 12px;
  color: var(--muted);
  margin-top: 12px;
}
.task-state {
  padding: 24px;
  display: flex;
  gap: 16px;
  align-items: center;
  margin-top: 20px;
}
.task-state p {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.8;
  margin-top: 7px;
}
.task-state .button {
  margin-left: auto;
}
.failure h2 {
  color: #a77745;
}
.data-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #fff6e9;
  border: 1px solid #efddc3;
  color: #a26635;
  border-radius: 7px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.8;
  margin-bottom: 16px;
  overflow-wrap: anywhere;
}
.data-notice {
  display: flex;
  gap: 8px;
  color: #438675;
  background: #edf6f2;
  padding: 12px 16px;
  border-radius: 7px;
  font-size: 13px;
  margin-bottom: 16px;
}
.review-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  margin: 26px 0 16px;
}
.review-heading h2 {
  font-size: 16px;
  overflow-wrap: anywhere;
}
.review-heading p {
  font-size: 12px;
  color: var(--muted);
  margin-top: 7px;
}
.export-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.review-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 18px;
  align-items: start;
}
.review-panel {
  padding: 20px;
  min-width: 0;
}
.review-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.review-toolbar > span {
  font-size: 12px;
  color: var(--muted);
}
.review-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 16px 0;
}
.review-filters :deep(.filter-select) {
  max-width: 100%;
}
.measurement-list {
  max-height: 315px;
  overflow: auto;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.measurement-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 11px 9px;
  text-align: left;
  border-bottom: 1px solid #f0f2f5;
  font-size: 12px;
  transition: background 0.15s;
}
.measurement-row:hover,
.measurement-row.selected {
  background: #eef5fb;
}
.measurement-row div:first-child {
  flex: 1;
  min-width: 0;
}
.measurement-row strong {
  font-size: 12px;
  font-weight: 400;
  display: block;
}
.measurement-row div > span {
  color: var(--muted);
  font-size: 10px;
  display: block;
  margin-top: 5px;
}
.measurement-value {
  text-align: right;
  font-size: 15px;
  font-weight: 700;
  min-width: 65px;
}
.measurement-value small {
  display: block;
  font-size: 10px;
  font-weight: 400;
  color: var(--muted);
  margin-top: 3px;
  max-width: 110px;
  overflow-wrap: anywhere;
}
.review-editor {
  margin-top: 20px;
}
.editor-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.editor-heading > span {
  font-size: 11px;
  color: var(--muted);
}
.original-value {
  background: #f8fafc;
  border-radius: 6px;
  padding: 12px;
  margin: 12px 0 16px;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
}
.original-value > span {
  color: var(--muted);
}
.original-value strong {
  font-weight: 700;
}
.original-value small {
  flex-basis: 100%;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.7;
}
.editor-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 13px;
}
.editable-review {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.full-field {
  grid-column: 1/-1;
}
.editor-fields :deep(.filter-select) {
  width: 100%;
}
.editor-fields :deep(.filter-trigger) {
  width: 100%;
  justify-content: space-between;
}
.conditions {
  margin-top: 16px;
}
.conditions summary {
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.conditions label {
  margin-top: 12px;
}
.decision {
  border: 0;
  margin: 16px 0 8px;
  padding: 0;
  display: flex;
  gap: 13px;
  flex-wrap: wrap;
}
.decision legend {
  font-size: 12px;
  color: #64758b;
  margin-bottom: 10px;
}
.decision label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  white-space: nowrap;
}
.decision input {
  width: auto;
  accent-color: var(--blue);
}
.decision:disabled {
  opacity: 0.5;
}
.note-field {
  margin-top: 16px;
}
.editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.audit-toggle {
  margin-left: auto;
}
.audit-list {
  border-top: 1px solid var(--border);
  margin-top: 17px;
  padding-top: 14px;
  font-size: 12px;
  line-height: 1.8;
}
.audit-list article {
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
.audit-list strong {
  font-size: 12px;
  font-weight: 700;
}
.audit-list article > span {
  display: block;
  font-size: 11px;
  color: var(--muted);
}
.audit-list p {
  margin-top: 5px;
}
.spinning {
  animation: spin 2s linear infinite;
  color: var(--blue);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1100px) {
  .upload-form {
    grid-template-columns: minmax(150px, 1fr) 90px 110px;
  }
  .upload-form > .button {
    grid-column: 1/-1;
    justify-self: end;
  }
  .review-heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }
}
@media (max-width: 1000px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
  .review-panel {
    padding: 18px;
  }
  .measurement-list {
    max-height: 260px;
  }
}
@media (max-width: 720px) {
  .data-heading h1 {
    font-size: 22px;
  }
  .data-heading > svg {
    display: none;
  }
  .upload-panel,
  .task-panel {
    padding: 16px;
  }
  summary {
    flex-wrap: wrap;
  }
  summary > span {
    font-size: 11px;
  }
  .upload-form {
    grid-template-columns: 1fr 1fr;
  }
  .file-field {
    grid-column: 1/-1;
  }
  .upload-form > .button {
    width: 100%;
    justify-content: center;
  }
  .task-toolbar form {
    flex: 1;
  }
  .task-toolbar {
    gap: 6px;
  }
  .task-row {
    padding: 10px 8px;
  }
  .review-heading {
    margin-top: 20px;
  }
  .export-actions {
    flex-wrap: wrap;
  }
  .review-panel {
    padding: 15px;
  }
  .data-alert {
    flex-direction: column;
    align-items: flex-start;
  }
  .editor-fields {
    gap: 10px;
  }
  .editor-actions .button {
    font-size: 11px;
  }
  .decision {
    gap: 10px;
  }
  .review-filters {
    gap: 6px;
  }
  .review-filters :deep(.filter-select) {
    width: 100%;
  }
  .review-filters :deep(.filter-trigger) {
    width: 100%;
  }
  .original-value {
    gap: 7px;
  }
  .review-pill {
    font-size: 10px;
    padding: 4px;
  }
  .measurement-row {
    gap: 8px;
  }
  .measurement-value {
    font-size: 14px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spinning {
    animation: none;
  }
}
</style>
