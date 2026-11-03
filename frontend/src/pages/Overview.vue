<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  LayoutDashboard as LayoutIcon,
  ArrowDownAZ,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Layers3,
  ListFilter,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-vue-next";
import {
  ApiError,
  get,
  number,
  typeKeys,
  typeNames,
  type ListResult,
  type Metadata,
  type Sample,
  type SampleType,
} from "../api";
import SampleDetail from "../components/SampleDetail.vue";
import FilterSelect from "../components/FilterSelect.vue";
import OverviewDials from "../components/OverviewDials.vue";
import { materialColors } from "../palette";

const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null);
const typeCounts = ref<Record<SampleType, number>>({
  softwood: 0,
  hardwood: 0,
  blend: 0,
});
const summaryLoading = ref(true),
  summaryError = ref(""),
  lastRead = ref("");
const rows = ref<Sample[]>([]),
  total = ref(0),
  totalPages = ref(0);
const loading = ref(true),
  error = ref(""),
  requestId = ref("");
const selected = ref<Sample | null>(null);
const page = computed(() => {
  const value = Number(route.query.page);
  return Number.isInteger(value) && value >= 1 && value <= 100000 ? value : 1;
});
const size = computed(() =>
  [10, 25, 50].includes(Number(route.query.size))
    ? Number(route.query.size)
    : 10,
);
const kind = computed(() =>
  typeKeys.includes(route.query.type as SampleType)
    ? (route.query.type as SampleType)
    : "",
);
const query = computed(() => String(route.query.q ?? "").slice(0, 100));
const search = ref(query.value);
const filterCount = computed(
  () => Number(!!query.value) + Number(!!kind.value),
);
const counts = computed(() => metadata.value?.counts);
const filterOptions = computed(() => [
  { value: "", label: "全部样本类型", count: counts.value?.samples },
  ...typeKeys.map((type, index) => ({
    value: type,
    label: typeNames[type],
    count: counts.value ? typeCounts.value[type] : undefined,
    color: materialColors[type],
  })),
]);
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
let summaryController: AbortController | undefined;
async function loadSummary() {
  summaryController?.abort();
  const current = new AbortController();
  summaryController = current;
  summaryLoading.value = true;
  summaryError.value = "";
  metadata.value = null;
  try {
    const [meta, ...groups] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      ...typeKeys.map((type) =>
        get<ListResult<Sample>>(
          "samples",
          { sample_type: type, page_size: 1 },
          current.signal,
        ),
      ),
    ]);
    if (current.signal.aborted) return;
    metadata.value = meta;
    groups.forEach((group, i) => {
      typeCounts.value[typeKeys[i]!] = group.pagination.total;
    });
    lastRead.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch (e) {
    if (!current.signal.aborted)
      summaryError.value =
        e instanceof Error ? e.message : "统计信息读取失败。";
  } finally {
    if (!current.signal.aborted) summaryLoading.value = false;
  }
}
async function loadRows() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  requestId.value = "";
  try {
    const result = await get<ListResult<Sample>>(
      "samples",
      {
        q: query.value,
        sample_type: kind.value,
        page: page.value,
        page_size: size.value,
      },
      current.signal,
    );
    if (current.signal.aborted) return;
    rows.value = result.data;
    total.value = result.pagination.total;
    totalPages.value = result.pagination.total_pages;
    if (page.value > Math.max(1, totalPages.value)) update({ page: 1 });
  } catch (e) {
    if (!current.signal.aborted) {
      rows.value = [];
      error.value = e instanceof Error ? e.message : "样本读取失败。";
      requestId.value = e instanceof ApiError ? (e.requestId ?? "") : "";
    }
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
function update(values: {
  q?: string;
  type?: string;
  page?: number;
  size?: number;
}) {
  const next = {
    q: query.value,
    type: kind.value,
    page: page.value,
    size: size.value,
    ...values,
  };
  void router.replace({
    query: {
      ...(next.q ? { q: next.q } : {}),
      ...(next.type ? { type: next.type } : {}),
      ...(next.page > 1 ? { page: next.page } : {}),
      ...(next.size !== 10 ? { size: next.size } : {}),
    },
  });
}
function chooseType(type: string) {
  clearTimeout(timer);
  update({ type, q: search.value.trim(), page: 1 });
}
function submitSearch() {
  clearTimeout(timer);
  update({ q: search.value.trim(), page: 1 });
}
function queueSearch() {
  clearTimeout(timer);
  timer = setTimeout(submitSearch, 350);
}
function clearFilters() {
  clearTimeout(timer);
  search.value = "";
  update({ q: "", type: "", page: 1 });
}
const dials = ref<InstanceType<typeof OverviewDials>>();
function refresh() {
  void loadSummary();
  void dials.value?.load();
  void loadRows();
}
watch(
  () => route.query,
  () => {
    search.value = query.value;
    void loadRows();
  },
  { immediate: true },
);
void loadSummary();
onBeforeUnmount(() => {
  clearTimeout(timer);
  controller?.abort();
  summaryController?.abort();
});
</script>

<template>
  <div class="overview">
    <section class="page-heading">
      <div>
        <div class="heading-kicker">
          <span class="blue-square"><LayoutIcon /></span>研究数据
        </div>
        <h1>数据总览</h1>
        <p>选一组数据查看刻度盘，悬停清单行在盘上定位。</p>
      </div>
      <div class="heading-actions">
        <span
          class="connection"
          :class="{ offline: summaryError }"
          role="status"
          ><span></span
          >{{
            summaryLoading
              ? "正在读取"
              : summaryError
                ? "连接待检查"
                : "数据已连接"
          }}</span
        ><button
          class="button"
          :disabled="summaryLoading || loading"
          @click="refresh"
        >
          <RefreshCw :size="15" :class="{ spinning: summaryLoading }" />刷新数据
        </button>
      </div>
    </section>
    <div v-if="summaryError" class="error-banner" role="alert">
      <TriangleAlert :size="18" /><span>{{ summaryError }}</span
      ><button class="text-button" @click="loadSummary">重新读取统计</button>
    </div>
    <OverviewDials ref="dials" />

    <section class="card sample-card" aria-labelledby="samples-title">
      <div class="sample-title">
        <div>
          <h2 id="samples-title">
            <span class="table-symbol"><Layers3 :size="18" /></span>样本库
            <span class="count-badge">{{
              error || loading ? "…" : total
            }}</span>
          </h2>
          <p>每行代表一个唯一物理样本，点击编码查看详情与来源。</p>
        </div>
        <span class="sort-note"><ArrowDownAZ :size="15" />按样本编码排序</span>
      </div>
      <div class="table-toolbar">
        <form class="search-field" role="search" @submit.prevent="submitSearch">
          <Search :size="17" /><input
            v-model="search"
            aria-label="搜索样本编码或名称"
            placeholder="搜索样本编码或名称…"
            maxlength="100"
            @input="queueSearch"
          /><button
            v-if="search"
            type="button"
            class="icon-button clear-search"
            aria-label="清空搜索"
            @click="
              search = '';
              submitSearch();
            "
          >
            <X :size="14" />
          </button>
        </form>
        <FilterSelect
          id="sample-type"
          label="样本类型"
          :model-value="kind"
          :options="filterOptions"
          @update:model-value="chooseType"
        />
        <span class="toolbar-spacer"></span
        ><span class="result-label"
          ><ListFilter :size="15" />{{
            filterCount ? `已应用 ${filterCount} 项筛选` : "全部样本"
          }}</span
        >
      </div>
      <div v-if="filterCount" class="filter-chips">
        <span>筛选条件</span
        ><button v-if="kind" @click="chooseType('')">
          {{ typeNames[kind] }}<X :size="12" /></button
        ><button
          v-if="query"
          @click="
            search = '';
            update({ q: '', page: 1 });
          "
        >
          关键词：{{ query }}<X :size="12" /></button
        ><button class="clear-all" @click="clearFilters">清除全部</button>
      </div>
      <div v-if="error" class="table-state" role="alert">
        <TriangleAlert :size="30" />
        <h3>暂时无法读取样本</h3>
        <p>{{ error }}</p>
        <small v-if="requestId">请求编号：{{ requestId }}</small
        ><button class="button primary" @click="loadRows">重新加载</button>
      </div>
      <div
        v-else-if="!loading && !rows.length"
        class="table-state"
        role="status"
      >
        <Search :size="32" />
        <h3>没有找到匹配的样本</h3>
        <p>试试其他编码、名称，或清除筛选条件。</p>
        <button class="button" @click="clearFilters">清除筛选</button>
      </div>
      <div
        v-else
        class="table-scroll"
        role="region"
        aria-label="样本数据表，可横向滚动"
        tabindex="0"
        :aria-busy="loading"
      >
        <table>
          <thead>
            <tr>
              <th class="row-index">#</th>
              <th>样本编码</th>
              <th>样本名称</th>
              <th>样本类型</th>
              <th class="numeric">针叶木 / 阔叶木</th>
              <th class="numeric">打浆转数 <small>r</small></th>
              <th class="numeric">打浆度 <small>°SR</small></th>
              <th><span class="sr-only">查看详情</span></th>
            </tr>
          </thead>
          <tbody v-if="loading && !rows.length">
            <tr v-for="i in 6" :key="i">
              <td v-for="j in 8" :key="j">
                <span class="skeleton cell-skeleton"></span>
              </td>
            </tr>
          </tbody>
          <tbody v-else :class="{ 'table-refreshing': loading }">
            <tr v-for="(sample, index) in rows" :key="sample.canonical_code">
              <td class="row-index">{{ (page - 1) * size + index + 1 }}</td>
              <td>
                <button
                  class="sample-code"
                  :disabled="loading"
                  @click="selected = sample"
                >
                  {{ sample.canonical_code }}
                </button>
              </td>
              <td class="sample-name">{{ sample.display_name }}</td>
              <td>
                <span class="type-tag" :class="sample.sample_type"
                  ><i></i>{{ typeNames[sample.sample_type] }}</span
                >
              </td>
              <td class="numeric ratio-cell">
                {{ number(sample.sw_proportion_pct) }}% <span>/</span>
                {{ number(sample.hw_proportion_pct) }}%
              </td>
              <td class="numeric">
                <template v-if="sample.sample_type === 'blend'"
                  ><span title="针叶木 / 阔叶木"
                    >{{ number(sample.sw_beating_revolutions) }} /
                    {{ number(sample.hw_beating_revolutions) }}</span
                  ></template
                ><template v-else>{{
                  number(
                    sample.sample_type === "softwood"
                      ? sample.sw_beating_revolutions
                      : sample.hw_beating_revolutions,
                  )
                }}</template>
              </td>
              <td class="numeric">
                <template v-if="sample.sample_type === 'blend'"
                  >{{ number(sample.sw_beating_degree_sr, 1) }} /
                  {{ number(sample.hw_beating_degree_sr, 1) }}</template
                ><template v-else>{{
                  number(
                    sample.sample_type === "softwood"
                      ? sample.sw_beating_degree_sr
                      : sample.hw_beating_degree_sr,
                    1,
                  )
                }}</template>
              </td>
              <td>
                <button
                  class="icon-button row-detail"
                  :disabled="loading"
                  :aria-label="`查看${sample.canonical_code}详情`"
                  @click="selected = sample"
                >
                  <ChevronRight :size="16" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-footer">
        <span role="status" aria-live="polite">{{
          loading
            ? "正在读取样本…"
            : error
              ? "读取失败"
              : total === 0
                ? "共 0 个样本"
                : `显示 ${(page - 1) * size + 1}–${Math.min(page * size, total)}，共 ${total} 个样本`
        }}</span>
        <div class="pagination">
          <label
            >每页
            <select
              aria-label="每页条数"
              :value="size"
              @change="
                update({
                  size: Number(($event.target as HTMLSelectElement).value),
                  page: 1,
                })
              "
            >
              <option :value="10">10</option>
              <option :value="25">25</option>
              <option :value="50">50</option>
            </select>
            条</label
          >
          <div class="page-buttons">
            <button
              class="icon-button"
              aria-label="上一页"
              :disabled="loading || !!error || page <= 1"
              @click="update({ page: page - 1 })"
            >
              <ChevronLeft :size="17" /></button
            ><span
              >{{ page }} <span>/ {{ Math.max(1, totalPages) }}</span></span
            ><button
              class="icon-button"
              aria-label="下一页"
              :disabled="loading || !!error || page >= totalPages"
              @click="update({ page: page + 1 })"
            >
              <ChevronRight :size="17" />
            </button>
          </div>
        </div>
      </div>
    </section>
    <footer class="page-foot">
      <span
        ><CircleHelp :size="14" />复配样本的打浆条件按“针叶木 /
        阔叶木”显示；“—”表示无对应记录。</span
      ><span>{{ lastRead ? `最近读取 ${lastRead}` : "等待读取数据" }}</span>
    </footer>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>
