<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { RefreshCw, X } from "lucide-vue-next";
import { get, number, type Metadata, type ListResult } from "../api";
import { axisDomain } from "../analysis";
import FilterSelect from "../components/FilterSelect.vue";

interface Cycle {
  block_code: string;
  cycle_no: number;
  replicate_count: number;
  [key: string]: string | number | null;
}
interface Observation extends Cycle {
  replicate_no: number;
  file_name: string;
  sheet_name: string;
  source_row: number;
}
const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null),
  rows = ref<Cycle[]>([]),
  originals = ref<Observation[]>([]);
const loading = ref(true),
  error = ref(""),
  focused = ref<Cycle | null>(null),
  selected = ref<Cycle | null>(null);
const dialog = ref<HTMLDialogElement>();
const metrics = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("recycled")) ??
    [],
);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ??
    metrics.value.find((i) => i.key === "fiber_length_weighted_mm") ??
    metrics.value[0],
);
const blocks = computed(() =>
  [...(metadata.value?.blocks ?? [])].sort(
    (a, b) => a.block_order - b.block_order,
  ),
);
const block = computed(
  () =>
    blocks.value.find((b) => b.block_code === route.query.block) ??
    blocks.value[0],
);
const visible = computed(() =>
  rows.value
    .filter((r) => r.block_code === block.value?.block_code)
    .sort((a, b) => a.cycle_no - b.cycle_no),
);
const details = computed(() =>
  originals.value
    .filter(
      (r) =>
        r.block_code === selected.value?.block_code &&
        r.cycle_no === selected.value?.cycle_no,
    )
    .sort((a, b) => a.replicate_no - b.replicate_no),
);
const total = computed(() =>
  visible.value.reduce((sum, r) => sum + r.replicate_count, 0),
);
const value = (r: Cycle) => {
  const v = metric.value ? r[metric.value.key] : null;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const domain = computed(() => axisDomain(valid.value.map((r) => value(r)!)));
const x = (r: Cycle) =>
  90 +
  ((r.cycle_no - (visible.value[0]?.cycle_no ?? 1)) /
    Math.max(
      1,
      (visible.value.at(-1)?.cycle_no ?? 1) - (visible.value[0]?.cycle_no ?? 1),
    )) *
    790;
const y = (v: number) =>
  280 - ((v - domain.value[0]) / (domain.value[1] - domain.value[0])) * 230;
const path = computed(() => {
  let connected = false;
  return visible.value
    .map((r) => {
      const v = value(r);
      if (v === null) {
        connected = false;
        return "";
      }
      const command = connected ? "L" : "M";
      connected = true;
      return `${command}${x(r)},${y(v)}`;
    })
    .join(" ");
});
const unit = computed(() => metric.value?.unit ?? "单位未确认");
function update(key: string, v: string) {
  router.replace({ query: { ...route.query, [key]: v } });
}
async function show(r: Cycle) {
  selected.value = r;
  await nextTick();
  dialog.value?.showModal();
}
function close() {
  dialog.value?.close();
  selected.value = null;
}
watch(
  () => [route.query.block, route.query.metric],
  () => {
    focused.value = null;
    close();
  },
);
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  close();
  focused.value = null;
  try {
    const [m, c, d] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      get<ListResult<Cycle>>(
        "recycled/cycles",
        { page_size: 500 },
        current.signal,
      ),
      get<ListResult<Observation>>(
        "recycled/details",
        { page_size: 500 },
        current.signal,
      ),
    ]);
    if (current.signal.aborted) return;
    metadata.value = m;
    rows.value = c.data;
    originals.value = d.data;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据加载失败，请重试。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
onBeforeUnmount(() => controller?.abort());
load();
</script>

<template>
  <div class="overview recycled-page">
    <div class="page-heading">
      <div>
        <h1>再生纸浆循环</h1>
        <p>观察循环回用中的指标变化，追溯每一个平均值。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </div>
    <p v-if="loading" class="card state" role="status">正在加载循环数据…</p>
    <div v-else-if="error" class="card state" role="alert">
      {{ error }} <button class="button" @click="load">重新加载</button>
    </div>
    <template v-else>
      <div class="card filters">
        <div class="filter-field">
          <span>数据块</span
          ><FilterSelect
            id="recycled-block"
            :model-value="block?.block_code ?? ''"
            :options="
              blocks.map((b) => ({
                value: b.block_code,
                label: `${b.block_code} · ${b.block_name}`,
              }))
            "
            label="选择数据块"
            @update:model-value="update('block', $event)"
          />
        </div>
        <div class="filter-field">
          <span>观察指标</span
          ><FilterSelect
            id="recycled-metric"
            :model-value="metric?.key ?? ''"
            :options="metrics.map((m) => ({ value: m.key, label: m.name }))"
            label="选择循环指标"
            @update:model-value="update('metric', $event)"
          />
        </div>
        <span class="dataset-count"
          >全库 {{ blocks.length }} 个数据块 · {{ rows.length }} 个循环汇总点 ·
          {{ originals.length }} 条原始观测</span
        >
      </div>
      <div class="block-summary">
        <span
          >原料
          <strong>{{ block?.raw_material_grade ?? "未记录" }}</strong></span
        ><span
          >处理条件
          <strong>{{ block?.condition_label ?? "未确认" }}</strong></span
        ><span
          >当前数据块
          <strong
            >{{ visible.length }} 个循环 · {{ total }} 条原始观测</strong
          ></span
        >
      </div>
      <section class="card trend" aria-labelledby="cycle-title">
        <div class="section-head">
          <div>
            <h2 id="cycle-title">{{ metric?.name ?? "循环趋势" }}</h2>
            <p>{{ block?.block_code }} · 各循环原始观测的平均值</p>
          </div>
          <span>{{ unit }}</span>
        </div>
        <p v-if="!valid.length" class="state">
          当前数据块没有此指标的有效数值。
        </p>
        <div v-else class="chart-scroll">
          <svg
            class="cycle-chart"
            viewBox="0 0 960 340"
            role="group"
            :aria-label="`${metric?.name}随循环次数变化，点击数据点查看原始观测`"
          >
            <g v-for="i in 6" :key="i">
              <line
                x1="90"
                x2="880"
                :y1="50 + (i - 1) * 46"
                :y2="50 + (i - 1) * 46"
                stroke="#f5f2ed"
              />
              <text x="76" :y="55 + (i - 1) * 46" text-anchor="end">
                {{
                  number(domain[1] - ((i - 1) * (domain[1] - domain[0])) / 5, 3)
                }}
              </text>
            </g>
            <path :d="path" fill="none" stroke="#0b6e68" stroke-width="3" />
            <g v-for="r in visible" :key="r.cycle_no">
              <text :x="x(r)" y="305" text-anchor="middle">
                {{ r.cycle_no }}
              </text>
            </g>
            <text x="485" y="334" text-anchor="middle">循环次数</text>
            <g
              v-for="r in valid"
              :key="r.cycle_no"
              class="cycle-point"
              role="button"
              tabindex="0"
              :aria-label="`第${r.cycle_no}次循环，${number(value(r), 3)} ${unit}，查看${r.replicate_count}条原始观测`"
              @pointerenter="focused = r"
              @pointerleave="focused = null"
              @focus="focused = r"
              @blur="focused = null"
              @click="show(r)"
              @keydown.enter.prevent="show(r)"
              @keydown.space.prevent="show(r)"
            >
              <circle :cx="x(r)" :cy="y(value(r)!)" r="13" fill="transparent" />
              <circle
                :cx="x(r)"
                :cy="y(value(r)!)"
                :r="focused === r ? 7 : 5"
                fill="#0b6e68"
                stroke="white"
                stroke-width="2"
              />
            </g>
          </svg>
        </div>
        <div class="point-summary" aria-live="polite">
          {{
            focused
              ? `第 ${focused.cycle_no} 次循环 · ${number(value(focused), 3)} ${unit} · ${focused.replicate_count} 条原始观测`
              : "悬停查看数值，点击数据点或下方表格查看原始观测。"
          }}
        </div>
      </section>
      <section class="card">
        <div class="section-head">
          <div>
            <h2>循环明细</h2>
            <p>按循环次数排序 · 缺失值显示为 —，曲线不跨缺失点连接</p>
          </div>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>循环次数</th>
                <th>{{ metric?.name }} / {{ unit }}</th>
                <th>原始观测数</th>
                <th>来源追溯</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in visible" :key="r.cycle_no">
                <td>第 {{ r.cycle_no }} 次</td>
                <td class="numeric">{{ number(value(r), 3) }}</td>
                <td class="numeric">{{ r.replicate_count }}</td>
                <td>
                  <button class="text-link" @click="show(r)">
                    查看原始观测
                  </button>
                </td>
              </tr>
              <tr v-if="!visible.length">
                <td colspan="4">暂无循环记录。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <p class="method-note">
        每个点是同一数据块、同一次循环内该指标非空观测的算术平均值，原始观测数为该循环的记录总数。数据块保留原始分组；未确认的处理条件不推断。该数据集独立于总览中的
        61 个核心样本。
      </p>
    </template>
    <dialog
      ref="dialog"
      class="observations-dialog"
      aria-labelledby="original-title"
      @close="selected = null"
      @click="$event.target === dialog && close()"
    >
      <template v-if="selected"
        ><div class="dialog-heading">
          <div>
            <h2 id="original-title">
              {{ selected.block_code }} · 第 {{ selected.cycle_no }} 次循环
            </h2>
            <p>
              {{ metric?.name }} · 平均值 {{ number(value(selected), 3) }}
              {{ unit }}
            </p>
          </div>
          <button class="icon-button" aria-label="关闭原始观测" @click="close">
            <X :size="20" />
          </button>
        </div>
        <p class="original-note">
          {{ details.length }} 条原始观测 · 该指标有效值
          {{ details.filter((r) => value(r) !== null).length }} 条
        </p>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>重复序号</th>
                <th>原始值 / {{ unit }}</th>
                <th>Excel 来源</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in details"
                :key="`${r.file_name}-${r.sheet_name}-${r.source_row}`"
              >
                <td>{{ r.replicate_no }}</td>
                <td class="numeric">{{ number(value(r), 4) }}</td>
                <td>
                  {{ r.file_name
                  }}<small>{{ r.sheet_name }} · 第 {{ r.source_row }} 行</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </dialog>
  </div>
</template>

<style scoped>
.recycled-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.filters {
  display: flex;
  align-items: end;
  gap: 24px;
  padding: 20px;
  flex-wrap: wrap;
}
.filters .filter-field {
  display: grid;
  gap: 9px;
  font-size: 12px;
  color: #998c71;
  min-width: 230px;
}
.dataset-count {
  margin-left: auto;
  font-size: 12px;
  color: #998c71;
  padding-bottom: 10px;
}
.block-summary {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  color: #998c71;
  font-size: 13px;
}
.block-summary strong {
  margin-left: 8px;
  color: #0b5f5a;
  font-weight: 700;
}
.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 22px 24px;
}
.section-head h2,
.dialog-heading h2 {
  font-size: 16px;
  margin: 0 0 8px;
}
.section-head p,
.dialog-heading p {
  margin: 0;
  color: #a49881;
  font-size: 12px;
}
.section-head > span {
  font-size: 12px;
  color: #998c71;
}
.chart-scroll {
  overflow-x: auto;
  padding: 0 16px;
}
.cycle-chart {
  display: block;
  width: 100%;
  min-width: 620px;
  max-height: 430px;
}
.cycle-chart text {
  fill: #a49881;
  font-size: 12px;
}
.cycle-point {
  cursor: pointer;
  outline: none;
}
.cycle-point:focus circle:last-child {
  stroke: #0a4f4b;
  stroke-width: 3;
}
.point-summary {
  background: #fcfbf8;
  padding: 14px 24px;
  color: #998c71;
  font-size: 12px;
  min-height: 46px;
  border-top: 1px solid #f5f2ed;
  border-radius: 0 0 8px 8px;
}
.text-link {
  border: 0;
  background: none;
  color: #0b6e68;
  cursor: pointer;
  font: inherit;
  padding: 5px 0;
}
.text-link:hover {
  text-decoration: underline;
}
.method-note {
  font-size: 12px;
  line-height: 1.8;
  color: #a49881;
  margin: 0;
}
.state {
  padding: 36px;
  text-align: center;
  color: #998c71;
}
.observations-dialog {
  border: 1px solid #dcebe7;
  border-radius: 12px;
  padding: 24px;
  width: min(760px, calc(100vw - 32px));
  max-height: 85vh;
  color: #0b5f5a;
  box-shadow: 0 24px 80px #0a4f4b33;
}
.observations-dialog::backdrop {
  background: #0a4f4b4d;
}
.original-note {
  font-size: 13px;
  color: #998c71;
}
.observations-dialog small {
  display: block;
  color: #a49881;
  margin-top: 6px;
}
.observations-dialog table {
  min-width: 540px;
}
@media (max-width: 720px) {
  .filters {
    gap: 16px;
  }
  .filters .filter-field {
    width: 100%;
    min-width: 0;
  }
  .dataset-count {
    margin-left: 0;
    line-height: 1.8;
    padding: 0;
  }
  .block-summary {
    gap: 12px;
    flex-direction: column;
  }
  .section-head {
    padding: 18px;
  }
  .observations-dialog {
    padding: 16px;
  }
  .point-summary {
    line-height: 1.7;
  }
}
</style>
