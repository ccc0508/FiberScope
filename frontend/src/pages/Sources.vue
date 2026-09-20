<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  FileSpreadsheet,
  RefreshCw,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-vue-next";
import { get, number, type ListResult, type Metadata } from "../api";
import {
  groupSources,
  matchesSource,
  usageLabel,
  type SourceUsage,
  type SourceObservation,
  type SourceRow,
} from "../sources";
import FilterSelect from "../components/FilterSelect.vue";

const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null),
  rows = ref<SourceRow[]>([]),
  loading = ref(true),
  error = ref("");
const selected = ref<SourceRow | null>(null),
  dialog = ref<HTMLDialogElement>();
const query = computed(() =>
  typeof route.query.q === "string" ? route.query.q.slice(0, 150) : "",
);
const search = ref(query.value);
const file = computed(() =>
  typeof route.query.file === "string" ? route.query.file : "",
);
const scope = computed(() =>
  ["core", "recycled"].includes(String(route.query.scope))
    ? String(route.query.scope)
    : "",
);
const fileSummary = computed(() => {
  const files = new Map<
    string,
    {
      name: string;
      sheets: Set<string>;
      count: number;
      samples: Set<string>;
      blocks: Set<string>;
    }
  >();
  for (const r of rows.value) {
    let f = files.get(r.file_name);
    if (!f) {
      f = {
        name: r.file_name,
        sheets: new Set(),
        count: 0,
        samples: new Set(),
        blocks: new Set(),
      };
      files.set(r.file_name, f);
    }
    f.sheets.add(r.sheet_name);
    f.count++;
    r.usages.forEach((u) => {
      if (u.canonical_code) f!.samples.add(u.canonical_code);
    });
    r.observations.forEach((o) => f!.blocks.add(o.block_code));
  }
  return [...files.values()];
});
const filtered = computed(() =>
  rows.value.filter(
    (r) =>
      (!file.value || r.file_name === file.value) &&
      (!scope.value ||
        (scope.value === "core" ? r.usages.length : r.observations.length)) &&
      matchesSource(r, query.value),
  ),
);
const pages = computed(() =>
  Math.max(1, Math.ceil(filtered.value.length / 25)),
);
const page = computed(() => {
  const n = Number(route.query.page);
  return Number.isInteger(n) && n > 0 ? Math.min(n, pages.value) : 1;
});
const visible = computed(() =>
  filtered.value.slice((page.value - 1) * 25, page.value * 25),
);
const coreSources = computed(
  () => rows.value.filter((r) => r.usages.length).length,
);
const recycledSources = computed(
  () => rows.value.filter((r) => r.observations.length).length,
);
const targets = (r: SourceRow) =>
  [
    ...new Set([
      ...r.usages.map((u) => u.canonical_code).filter(Boolean),
      ...r.observations.map((o) => `${o.block_code} · 第 ${o.cycle_no} 次循环`),
    ]),
  ].join("、") || "未关联样本";
const usages = (r: SourceRow) =>
  [
    ...new Set(r.usages.map(usageLabel)),
    ...(r.observations.length ? ["循环原始观测"] : []),
  ].join("、");
const relatedIndicators = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) =>
        i.scope.includes("core") &&
        selected.value?.usages.some(
          (u) =>
            (u.usage_type === "fiber_measurement" && i.group === "fiber") ||
            (u.usage_type === "paper_measurement" && i.group === "paper"),
        ),
    ) ?? [],
);
const recycledIndicators = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("recycled")) ??
    [],
);
function update(key: string, value: string) {
  router.replace({
    query: { ...route.query, [key]: value || undefined, page: undefined },
  });
}
function goPage(value: number) {
  router.replace({
    query: { ...route.query, page: value === 1 ? undefined : String(value) },
  });
}
function reset() {
  search.value = "";
  router.replace({ query: {} });
}
function close() {
  dialog.value?.close();
  selected.value = null;
}
async function show(row: SourceRow) {
  selected.value = row;
  await nextTick();
  dialog.value?.showModal();
}
watch(
  () => route.fullPath,
  () => {
    search.value = query.value;
    close();
  },
);
let controller: AbortController | undefined;
async function all<T>(path: string, signal: AbortSignal) {
  const first = await get<ListResult<T>>(path, { page_size: 500 }, signal);
  const data = [...first.data];
  for (let p = 2; p <= first.pagination.total_pages; p++)
    data.push(
      ...(await get<ListResult<T>>(path, { page_size: 500, page: p }, signal))
        .data,
    );
  return data;
}
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  close();
  try {
    const [m, u, o] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      all<SourceUsage>("lineage", current.signal),
      all<SourceObservation>("recycled/details", current.signal),
    ]);
    if (current.signal.aborted) return;
    metadata.value = m;
    rows.value = groupSources(u, o);
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "来源读取失败。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
onBeforeUnmount(() => controller?.abort());
load();
</script>

<template>
  <div class="sources-page overview">
    <div class="page-heading">
      <div>
        <h1>数据来源</h1>
        <p>从分析结果回到原始记录，了解每一行数据的用途。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </div>
    <p v-if="loading" class="card source-state" role="status">
      正在读取来源记录…
    </p>
    <div v-else-if="error" class="card source-state" role="alert">
      <p>{{ error }}</p>
      <button class="button" @click="load">重新加载</button>
    </div>
    <template v-else>
      <details class="card file-overview" open>
        <summary>
          已入库来源文件
          <span
            >{{ fileSummary.length }} 个文件 · {{ rows.length }} 条来源行</span
          >
        </summary>
        <p class="section-note">
          {{ coreSources }} 条核心实验来源行 +
          {{ recycledSources }} 条再生纸浆观测。仅统计已入库的来源，不代表 Excel
          的全部行。
        </p>
        <div class="file-grid">
          <button
            v-for="f in fileSummary"
            :key="f.name"
            class="file-card"
            :class="{ chosen: file === f.name }"
            :aria-pressed="file === f.name"
            @click="update('file', file === f.name ? '' : f.name)"
          >
            <FileSpreadsheet :size="20" /><span
              ><strong>{{ f.name }}</strong
              ><small
                >{{ [...f.sheets].join("、") }} · {{ f.count }} 条来源行</small
              ><small>{{
                f.samples.size
                  ? `${f.samples.size} 个关联样本`
                  : `${f.blocks.size} 个数据块`
              }}</small></span
            >
          </button>
        </div>
      </details>
      <section class="card source-records" aria-labelledby="source-list-title">
        <div class="source-heading">
          <div>
            <h2 id="source-list-title">来源记录</h2>
            <p>同一文件、工作表、版本和源行合并展示，用途在详情中展开。</p>
          </div>
          <span aria-live="polite">{{ filtered.length }} 条来源行</span>
        </div>
        <div class="source-filters">
          <FilterSelect
            id="source-file"
            :model-value="file"
            :options="[
              { value: '', label: '全部来源文件' },
              ...fileSummary.map((f) => ({
                value: f.name,
                label: f.name,
                count: f.count,
              })),
            ]"
            label="筛选来源文件"
            @update:model-value="update('file', $event)"
          />
          <FilterSelect
            id="source-scope"
            :model-value="scope"
            :options="[
              { value: '', label: '全部数据' },
              { value: 'core', label: '核心实验' },
              { value: 'recycled', label: '再生纸浆' },
            ]"
            label="筛选数据范围"
            @update:model-value="update('scope', $event)"
          />
          <form
            class="source-search"
            role="search"
            @submit.prevent="update('q', search.trim())"
          >
            <Search :size="16" /><input
              v-model="search"
              aria-label="搜索来源"
              placeholder="样本编号、G01、文件名或源行"
              maxlength="150"
            /><button class="button" type="submit">搜索</button>
          </form>
          <button
            v-if="file || scope || query"
            class="text-link"
            @click="reset"
          >
            清除筛选
          </button>
        </div>
        <p v-if="query" class="section-note">搜索：{{ query }}</p>
        <div class="table-scroll">
          <table class="sources-table">
            <thead>
              <tr>
                <th>Excel 来源</th>
                <th>关联样本 / 数据块</th>
                <th>用途</th>
                <th>查看</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in visible" :key="r.key">
                <td>
                  <strong>{{ r.file_name }}</strong
                  ><small
                    >{{ r.sheet_name }} · 第 {{ r.source_row }} 行 ·
                    {{ r.source_version }}</small
                  >
                </td>
                <td>{{ targets(r) }}</td>
                <td>{{ usages(r) }}</td>
                <td>
                  <button
                    class="text-link"
                    :aria-label="`查看${r.file_name}第${r.source_row}行的用途`"
                    @click="show(r)"
                  >
                    查看用途
                  </button>
                </td>
              </tr>
              <tr v-if="!visible.length">
                <td colspan="4" class="source-state">
                  没有匹配的来源记录。<button class="text-link" @click="reset">
                    清除筛选
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="source-pagination">
          <span>每页 25 行 · 第 {{ page }} / {{ pages }} 页</span>
          <div>
            <button
              class="icon-button"
              aria-label="上一页"
              :disabled="page <= 1"
              @click="goPage(page - 1)"
            >
              <ChevronLeft :size="18" /></button
            ><button
              class="icon-button"
              aria-label="下一页"
              :disabled="page >= pages"
              @click="goPage(page + 1)"
            >
              <ChevronRight :size="18" />
            </button>
          </div>
        </div>
      </section>
      <section class="card count-explainer" aria-labelledby="count-title">
        <h2 id="count-title">这些数量为什么不同？</h2>
        <div class="count-grid">
          <div>
            <strong
              >{{ metadata?.counts.samples }} <small>个核心样本</small></strong
            >
            <p>去重后的物理样本，同一个样本可以出现在不同实验中。</p>
          </div>
          <div>
            <strong
              >{{
                (metadata?.counts.beating ?? 0) + (metadata?.counts.blends ?? 0)
              }}
              <small>个实验展示点</small></strong
            >
            <p>
              打浆实验 {{ metadata?.counts.beating }} 个，加复配实验
              {{ metadata?.counts.blends }} 个。复配两端复用纯浆样本。
            </p>
          </div>
          <div>
            <strong
              >{{ metadata?.counts["recycled/details"] }}
              <small>条原始观测</small></strong
            >
            <p>
              再生纸浆逐行测量记录，独立于核心样本；同一循环可有多次重复观测。
            </p>
          </div>
          <div>
            <strong
              >{{ metadata?.counts["recycled/cycles"] }}
              <small>个循环汇总点</small></strong
            >
            <p>
              {{ metadata?.blocks.length }}
              个数据块按循环次数分别汇总。每项指标取该组非空观测的平均值。
            </p>
          </div>
        </div>
        <p class="section-note">
          来源行数、用途数量与样本数是不同口径。同一行同时用于实验展示、纤维测量和原料组分时，只算一条来源行。
        </p>
      </section>
    </template>
    <dialog
      ref="dialog"
      class="source-dialog"
      aria-labelledby="source-detail-title"
      @close="selected = null"
      @click="$event.target === dialog && close()"
    >
      <template v-if="selected"
        ><div class="dialog-heading">
          <div>
            <span class="eyebrow">原始记录的对应关系</span>
            <h2 id="source-detail-title">{{ selected.file_name }}</h2>
            <p>
              {{ selected.sheet_name }} · 第 {{ selected.source_row }} 行 ·
              {{ selected.source_version }}
            </p>
          </div>
          <button class="icon-button" aria-label="关闭来源详情" @click="close">
            <X :size="20" />
          </button>
        </div>
        <template v-if="selected.usages.length"
          ><p class="section-note">
            这是一条来源行，以下为它在数据库中记录的
            {{ selected.usages.length }} 项用途。
          </p>
          <ul class="usage-list">
            <li v-for="(u, index) in selected.usages" :key="index">
              <strong>{{ usageLabel(u) }}</strong
              ><template v-if="u.canonical_code"
                ><RouterLink
                  :to="{ path: '/', query: { q: u.canonical_code } }"
                  >{{ u.canonical_code }}</RouterLink
                ><small>{{ u.display_name }}</small></template
              >
              <p v-else>保留原始来源，当前没有关联到样本，不计为新增样本。</p>
              <small v-if="u.experiment_code"
                >实验 {{ u.experiment_code }} · 展示编号
                {{ u.display_code ?? "—" }}</small
              >
            </li>
          </ul>
          <div v-if="relatedIndicators.length" class="indicator-note">
            <h3>该来源提供的指标</h3>
            <p>{{ relatedIndicators.map((i) => i.name).join("、") }}。</p>
            <small
              >这里只列出用途对应的指标类别；测量值请从关联样本进入分析页面查看。</small
            >
          </div></template
        >
        <section
          v-for="o in selected.observations"
          :key="`${o.block_code}-${o.cycle_no}-${o.replicate_no}`"
          class="observation-section"
        >
          <h3>
            {{ o.block_code }} · 第 {{ o.cycle_no }} 次循环 · 重复
            {{ o.replicate_no }}
          </h3>
          <p>
            此记录参与 {{ o.block_code }} 第
            {{ o.cycle_no }}
            次循环的各项指标平均值计算；空值不参与相应指标的平均。
          </p>
          <RouterLink
            class="text-link"
            :to="{ path: '/recycled', query: { block: o.block_code } }"
            >查看所在数据块的循环趋势 →</RouterLink
          >
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>原始观测指标</th>
                  <th>数值</th>
                  <th>单位</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="i in recycledIndicators" :key="i.key">
                  <td>{{ i.name }}</td>
                  <td class="numeric">
                    {{
                      number(
                        typeof o[i.key] === "number"
                          ? (o[i.key] as number)
                          : null,
                        4,
                      )
                    }}
                  </td>
                  <td>{{ i.unit ?? "未确认" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </dialog>
  </div>
</template>

<style scoped>
.sources-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.file-overview {
  padding: 22px;
}
.file-overview summary {
  cursor: pointer;
  font-size: 16px;
  font-weight: 700;
}
.file-overview summary span {
  font-size: 12px;
  font-weight: 400;
  color: #8191a4;
  margin-left: 12px;
}
.section-note {
  font-size: 12px;
  color: #8191a4;
  line-height: 1.8;
}
.file-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.file-card {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  text-align: left;
  border: 1px solid #e5ebf1;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
  color: #516b82;
  cursor: pointer;
  font: inherit;
  transition:
    background 0.15s,
    border-color 0.15s;
}
.file-card:hover,
.file-card.chosen {
  background: #f0f6fc;
  border-color: #9abbd9;
}
.file-card svg {
  flex-shrink: 0;
  color: #58a397;
}
.file-card strong {
  display: block;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.file-card small {
  display: block;
  font-size: 11px;
  color: #8191a4;
  margin-top: 5px;
}
.source-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 22px 24px 10px;
}
.source-heading h2,
.count-explainer h2 {
  font-size: 16px;
  margin: 0 0 8px;
}
.source-heading p,
.source-heading > span {
  font-size: 12px;
  color: #8191a4;
  margin: 0;
  line-height: 1.7;
}
.source-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 24px 20px;
}
.source-filters > :first-child {
  max-width: 360px;
  min-width: 200px;
}
.source-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 280px;
}
.source-search > svg {
  color: #8191a4;
  flex-shrink: 0;
}
.source-search > button {
  flex-shrink: 0;
  white-space: nowrap;
}
.source-search input {
  width: 100%;
  min-width: 0;
  border: 1px solid #dce5ed;
  border-radius: 5px;
  padding: 9px 10px;
  font: inherit;
  font-size: 12px;
  background: white;
  color: #40566d;
}
.source-records > .section-note {
  padding: 0 24px;
}
.sources-table {
  min-width: 840px;
}
.sources-table td {
  vertical-align: top;
  max-width: 350px;
  white-space: normal;
  line-height: 1.7;
}
.sources-table strong {
  font-weight: 400;
}
.sources-table small {
  display: block;
  color: #8191a4;
  font-size: 11px;
  margin-top: 4px;
}
.sources-table td:nth-child(2) {
  font-family: monospace;
  font-size: 12px;
}
.text-link {
  border: 0;
  background: none;
  color: #4386bf;
  cursor: pointer;
  font: inherit;
  padding: 4px 0;
  text-decoration: none;
  white-space: nowrap;
}
.text-link:hover {
  text-decoration: underline;
}
.source-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  color: #8191a4;
  font-size: 12px;
}
.source-pagination > div {
  display: flex;
  gap: 8px;
}
.count-explainer {
  padding: 24px;
}
.count-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 24px;
  margin-top: 24px;
}
.count-grid strong {
  font-size: 28px;
  color: #40566d;
}
.count-grid small {
  display: block;
  font-size: 12px;
  margin-top: 8px;
  color: #718399;
  font-weight: 400;
}
.count-grid p {
  font-size: 12px;
  line-height: 1.8;
  color: #718399;
}
.source-state {
  padding: 32px;
  text-align: center;
  color: #718399;
}
.source-dialog {
  border: 1px solid #e1e8ef;
  border-radius: 12px;
  padding: 24px;
  width: min(780px, calc(100vw - 32px));
  max-height: 85vh;
  color: #40566d;
  box-shadow: 0 24px 80px #203e5b33;
}
.source-dialog::backdrop {
  background: #263e594d;
}
.source-dialog .dialog-heading {
  align-items: flex-start;
}
.source-dialog h2 {
  font-size: 17px;
  overflow-wrap: anywhere;
  line-height: 1.6;
}
.source-dialog .dialog-heading p {
  color: #8191a4;
  font-size: 12px;
}
.usage-list {
  list-style: none;
  padding: 0;
  margin: 20px 0;
}
.usage-list li {
  padding: 16px 0;
  border-bottom: 1px solid #eaf0f5;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}
.usage-list a {
  color: #4386bf;
  overflow-wrap: anywhere;
}
.usage-list small,
.indicator-note small {
  color: #8191a4;
  font-size: 12px;
}
.usage-list p {
  margin: 0;
  color: #718399;
}
.indicator-note,
.observation-section {
  font-size: 13px;
  line-height: 1.8;
}
.indicator-note h3,
.observation-section h3 {
  font-size: 14px;
}
.indicator-note {
  background: #f8fafc;
  border-radius: 8px;
  padding: 16px;
}
.observation-section table {
  min-width: 450px;
  margin-top: 16px;
}
@media (max-width: 1100px) {
  .file-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .count-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .file-grid,
  .count-grid {
    grid-template-columns: 1fr;
  }
  .file-overview,
  .count-explainer {
    padding: 18px;
  }
  .file-overview summary span {
    display: block;
    margin: 8px 0;
  }
  .source-filters {
    padding: 12px 18px;
  }
  .source-filters > * {
    width: 100%;
    min-width: 0 !important;
    max-width: none !important;
  }
  .source-heading {
    padding: 18px;
    align-items: flex-start;
  }
  .source-heading > span {
    white-space: nowrap;
  }
  .source-dialog {
    padding: 16px;
  }
  .count-grid {
    gap: 12px;
  }
  .source-pagination {
    padding: 14px 18px;
  }
}
</style>
