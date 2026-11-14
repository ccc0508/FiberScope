<script setup lang="ts">
/*
 * DEV ONLY (/__foundation, not in production builds): every shared building block in the
 * active mode, fed with live API data — PageHeader, global classes, FilterSelect,
 * SampleDetail and chart colours. Switch modes with the shell's switch to compare.
 */
import { computed, onMounted, ref } from "vue";
import { RefreshCw, Search, TriangleAlert, Layers3 } from "lucide-vue-next";
import PageHeader from "../components/PageHeader.vue";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import { get, number, typeKeys, typeNames, type ListResult, type Sample, type SampleType } from "../api";
import { chartColors, materialColors } from "../palette";
import { useCountUp, vSeg, vTilt } from "../motion";

const rows = ref<Sample[]>([]);
const counts = ref<Partial<Record<SampleType, number>>>({});
const total = ref<number | null>(null);
const error = ref("");
const loading = ref(true);
const type = ref("");
const selected = ref<Sample | null>(null);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const all = await get<ListResult<Sample>>("samples", { page_size: 100 });
    rows.value = all.data;
    total.value = all.pagination.total;
    const next: Partial<Record<SampleType, number>> = {};
    for (const s of all.data) next[s.sample_type] = (next[s.sample_type] ?? 0) + 1;
    counts.value = next;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "读取失败";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
const bigEl = ref<HTMLElement>();
const shownTotal = useCountUp(() => total.value, { el: bigEl });

const options = computed(() => [
  { value: "", label: "全部类型", count: rows.value.length },
  ...typeKeys.map((key) => ({
    value: key,
    label: typeNames[key],
    count: counts.value[key] ?? 0,
    color: materialColors[key],
  })),
]);
const visible = computed(() =>
  rows.value.filter((r) => !type.value || r.sample_type === type.value).slice(0, 8),
);
// a tiny bar chart bound to the reactive palette (SVG attributes need real colours)
const bars = computed(() => {
  const max = Math.max(1, ...typeKeys.map((k) => counts.value[k] ?? 0));
  return typeKeys.map((k, i) => ({
    key: k,
    x: 20 + i * 70,
    h: ((counts.value[k] ?? 0) / max) * 90,
    value: counts.value[k] ?? 0,
  }));
});
</script>

<template>
  <div class="overview">
    <PageHeader
      title="打浆分析"
      title-strong="打浆"
      title-light="分析"
      index="02"
      english="Beating"
      group="分析与探索"
      magnification="20×"
      description="DEV 预览：PageHeader 与全局样式在当前模式下的外观，数据来自实时接口。"
    >
      <template #actions>
        <span class="connection"><span></span>数据已连接</span>
        <button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>

      <template #visual>
        <svg width="240" height="130" viewBox="0 0 240 130" role="img" aria-label="样本类型数量">
          <line x1="10" x2="230" y1="110" y2="110" :stroke="chartColors.axis" />
          <line x1="10" x2="230" y1="65" y2="65" :stroke="chartColors.grid" />
          <line x1="10" x2="230" y1="40" y2="40" :stroke="chartColors.target" stroke-dasharray="4 4" />
          <g v-for="bar in bars" :key="bar.key">
            <rect :x="bar.x" :y="110 - bar.h" width="44" :height="bar.h" rx="6" :fill="materialColors[bar.key]" />
            <text :x="bar.x + 22" :y="104 - bar.h" text-anchor="middle" :fill="chartColors.textStrong" font-size="12">{{ bar.value }}</text>
            <text :x="bar.x + 22" y="125" text-anchor="middle" :fill="chartColors.text" font-size="11">{{ typeNames[bar.key] }}</text>
          </g>
        </svg>
      </template>
    </PageHeader>

    <div v-if="error" class="error-banner" role="alert">
      <TriangleAlert :size="18" /><span>{{ error }}</span
      ><button class="text-button" @click="load">重新读取</button>
    </div>

    <section class="metrics">
      <div v-tilt class="metric">
        <div class="metric-label">唯一物理样本</div>
        <div class="metric-value">{{ total ?? "—" }}<small>个</small></div>
        <p>samples 接口 pagination.total</p>
      </div>
      <div v-for="key in typeKeys" :key="key" class="metric">
        <div class="metric-label">{{ typeNames[key] }}</div>
        <div class="metric-value">{{ loading ? "—" : (counts[key] ?? 0) }}<small>个</small></div>
        <p><span class="type-tag" :class="key"><i></i>{{ typeNames[key] }}</span></p>
      </div>
    </section>

    <section v-tilt class="card pv-primitives" aria-label="共享控件">
      <div>
        <span class="field-label">field-label · seg</span>
        <div v-seg class="seg" role="group" aria-label="样本类型">
          <button type="button" :aria-pressed="!type" @click="type = ''">全部 <span class="cnt">{{ rows.length }}</span></button>
          <button v-for="key in typeKeys" :key="key" type="button" :aria-pressed="type === key" @click="type = key">
            {{ typeNames[key] }} <span class="cnt">{{ counts[key] ?? 0 }}</span>
          </button>
        </div>
      </div>
      <div>
        <span class="field-label">big-number (useCountUp) · chip</span>
        <div ref="bigEl" class="big-number pv-big">
          <span aria-hidden="true">{{ shownTotal ?? "—" }}</span
          ><span class="sr-only">{{ total ?? "—" }}</span><small>个</small>
        </div>
        <span class="chip">samples <span class="cnt">{{ rows.length }}</span></span>
      </div>
      <p class="caveat">caveat：图表展示对应关系，不代表因果关系。</p>
    </section>

    <section class="card sample-card" aria-labelledby="pv-title">
      <div class="sample-title">
        <div>
          <h2 id="pv-title">
            <span class="table-symbol"><Layers3 :size="18" /></span>样本库
            <span class="count-badge">{{ loading ? "…" : rows.length }}</span>
          </h2>
          <p>点击编码打开 SampleDetail 抽屉（实时来源数据）。</p>
        </div>
        <span class="quiet-tag">quiet-tag</span>
      </div>
      <div class="table-toolbar">
        <label class="search-field"><Search :size="17" /><input placeholder="search-field…" aria-label="示例搜索框" /></label>
        <FilterSelect id="pv-type" v-model="type" :options="options" label="样本类型" />
        <span class="toolbar-spacer"></span>
        <button class="button primary">button.primary</button>
        <button class="icon-button" aria-label="icon-button"><RefreshCw :size="16" /></button>
      </div>
      <div v-if="type" class="filter-chips">
        当前筛选 <button @click="type = ''">{{ typeNames[type as SampleType] }} ×</button
        ><button class="clear-all" @click="type = ''">清除</button>
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th class="row-index">#</th>
              <th>样本编码</th>
              <th>类型</th>
              <th>名称</th>
              <th class="numeric">针叶木 <small>%</small></th>
              <th class="numeric">打浆度 <small>°SR</small></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td v-for="i in 6" :key="i"><span class="skeleton cell-skeleton"></span></td>
            </tr>
            <tr v-for="(row, i) in visible" :key="row.sample_id">
              <td class="row-index">{{ i + 1 }}</td>
              <td><button class="sample-code" @click="selected = row">{{ row.canonical_code }}</button></td>
              <td><span class="type-tag" :class="row.sample_type"><i></i>{{ typeNames[row.sample_type] }}</span></td>
              <td class="sample-name">{{ row.display_name }}</td>
              <td class="numeric">{{ number(row.sw_proportion_pct) }}</td>
              <td class="numeric">{{ number(row.sw_beating_degree_sr ?? row.hw_beating_degree_sr, 1) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-footer">
        <span>显示前 {{ visible.length }} 行</span>
        <div class="pagination">
          <label>每页 <select aria-label="每页条数"><option>10</option><option>25</option></select></label>
          <div class="page-buttons">
            <button class="icon-button" disabled aria-label="上一页">‹</button><span>1 <span>/ 1</span></span
            ><button class="icon-button" disabled aria-label="下一页">›</button>
          </div>
        </div>
      </div>
    </section>
    <div class="page-foot"><span>page-foot · text-3</span><span>只读数据</span></div>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
.pv-primitives {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: end;
  gap: 18px 32px;
  padding: 20px 22px;
  margin-bottom: 21px;
}
.pv-big {
  font-size: 56px;
  margin-bottom: 8px;
}
@media (max-width: 980px) {
  .pv-primitives {
    grid-template-columns: 1fr;
  }
}
</style>
