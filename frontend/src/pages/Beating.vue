<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChartNoAxesCombined, RefreshCw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  type Metadata,
  type ListResult,
  type Sample,
} from "../api";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";

interface BeatingRow {
  canonical_code: string;
  material_code: "SW" | "HW";
  beating_revolutions: number;
  [key: string]: string | number | null;
}
const route = useRoute(),
  router = useRouter();
const rows = ref<BeatingRow[]>([]),
  samples = ref<Sample[]>([]);
const metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const selected = ref<Sample | null>(null),
  focused = ref<BeatingRow | null>(null);
const defaultMetric = {
  key: "beating_degree_sr",
  name: "打浆度",
  unit: "°SR",
  group: "condition",
  scope: ["core"],
  unit_status: "confirmed",
};
const metrics = computed(() => [
  defaultMetric,
  ...(metadata.value?.indicators.filter((i) => i.scope.includes("core")) ?? []),
]);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ?? defaultMetric,
);
const material = computed(() =>
  ["SW", "HW"].includes(String(route.query.material))
    ? String(route.query.material)
    : "all",
);
const materialOptions = [
  { value: "all", label: "全部原料" },
  { value: "SW", label: "针叶木浆", color: "#5796ce" },
  { value: "HW", label: "阔叶木浆", color: "#79b7ad" },
];
const metricOptions = computed(() =>
  metrics.value.map((i) => ({ value: i.key, label: i.name })),
);
const visible = computed(() =>
  rows.value
    .filter(
      (r) => material.value === "all" || r.material_code === material.value,
    )
    .sort(
      (a, b) =>
        a.beating_revolutions - b.beating_revolutions ||
        a.canonical_code.localeCompare(b.canonical_code),
    ),
);
const value = (r: BeatingRow): number | null =>
  typeof r[metric.value.key] === "number" &&
  Number.isFinite(r[metric.value.key])
    ? (r[metric.value.key] as number)
    : null;
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const unit = computed(() => metric.value.unit ?? "单位未确认");
const materialName = (code: string) =>
  code === "SW" ? "针叶木浆" : "阔叶木浆";
const color = (code: string) => (code === "SW" ? "#4386bf" : "#58a397");
const yDomain = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values),
    pad = (max - min || Math.abs(max) || 1) * 0.12;
  return [min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad];
});
const xMax = computed(() =>
  Math.max(1, ...visible.value.map((r) => r.beating_revolutions)),
);
const x = (r: BeatingRow) => 80 + (r.beating_revolutions / xMax.value) * 830;
const y = (r: BeatingRow) =>
  285 -
  ((value(r)! - yDomain.value[0]!) / (yDomain.value[1]! - yDomain.value[0]!)) *
    245;
const series = computed(() =>
  ["SW", "HW"].map((code) => {
    const points = visible.value.filter((r) => r.material_code === code);
    let connected = false;
    const path = points
      .map((r) => {
        if (value(r) === null) {
          connected = false;
          return "";
        }
        const segment = `${connected ? "L" : "M"}${x(r)},${y(r)}`;
        connected = true;
        return segment;
      })
      .join(" ");
    return { code, points: points.filter((r) => value(r) !== null), path };
  }),
);
function update(key: string, next: string) {
  void router.replace({ query: { ...route.query, [key]: next } });
}
function detail(row: BeatingRow) {
  selected.value =
    samples.value.find((s) => s.canonical_code === row.canonical_code) ?? null;
}
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  focused.value = null;
  try {
    const [data, meta, sampleData] = await Promise.all([
      get<ListResult<BeatingRow>>(
        "beating",
        { page_size: 500 },
        current.signal,
      ),
      get<Metadata>("metadata", {}, current.signal),
      get<ListResult<Sample>>("samples", { page_size: 500 }, current.signal),
    ]);
    if (current.signal.aborted) return;
    rows.value = data.data;
    metadata.value = meta;
    samples.value = sampleData.data;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据读取失败";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
watch(
  () => [material.value, metric.value.key],
  () => {
    focused.value = null;
  },
);
void load();
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="overview beating-page">
    <section class="page-heading">
      <div>
        <span class="eyebrow"><ChartNoAxesCombined :size="14" /> 实验分析</span>
        <h1>打浆分析</h1>
        <p>比较打浆转数变化下的纤维特性与纸张性能。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </section>
    <div v-if="error" class="card beating-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card beating-state" role="status">
      正在读取打浆实验数据…
    </div>
    <template v-else>
      <section class="card beating-controls" aria-label="打浆分析筛选">
        <div>
          <span class="control-caption">原料</span
          ><FilterSelect
            id="beating-material"
            label="原料"
            :model-value="material"
            :options="materialOptions"
            @update:model-value="update('material', $event)"
          />
        </div>
        <div>
          <span class="control-caption">分析指标</span
          ><FilterSelect
            id="beating-metric"
            label="分析指标"
            :model-value="metric.key"
            :options="metricOptions"
            @update:model-value="update('metric', $event)"
          />
        </div>
        <p class="beating-count" role="status">
          {{ visible.length }} 个样本 <span>·</span>
          {{ valid.length }} 个有效数据点
        </p>
      </section>
      <section class="card beating-chart">
        <div class="beating-chart-heading">
          <div>
            <h2>{{ metric.name }}随打浆转数的变化</h2>
            <p>纵轴：{{ metric.name }}（{{ unit }}）</p>
          </div>
          <div class="beating-legend">
            <span
              v-for="s in series.filter((s) => s.points.length)"
              :key="s.code"
              ><i :style="{ background: color(s.code) }"></i
              >{{ materialName(s.code) }}</span
            >
          </div>
        </div>
        <p v-if="metric.unit_status !== 'confirmed'" class="unit-note">
          {{ metric.name }}的单位{{
            metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
          }}，数值保留原始口径。
        </p>
        <div v-if="!valid.length" class="beating-state" role="status">
          当前原料没有该指标的有效数据，请切换指标或原料。
        </div>
        <div
          v-else
          class="beating-plot-scroll"
          role="region"
          aria-label="打浆趋势图，可横向滚动"
          tabindex="0"
        >
          <svg
            class="beating-plot"
            viewBox="0 0 960 345"
            aria-label="打浆趋势图；可用Tab定位数据点，Enter查看样本详情"
          >
            <g v-for="i in 6" :key="`y${i}`">
              <line
                x1="80"
                x2="910"
                :y1="40 + (i - 1) * 49"
                :y2="40 + (i - 1) * 49"
                stroke="#edf0f4"
              />
              <text x="68" :y="44 + (i - 1) * 49" text-anchor="end">
                {{
                  number(
                    yDomain[1]! - ((i - 1) / 5) * (yDomain[1]! - yDomain[0]!),
                    2,
                  )
                }}
              </text>
            </g>
            <g v-for="i in 6" :key="`x${i}`">
              <text :x="80 + (i - 1) * 166" y="309" text-anchor="middle">
                {{ number(((i - 1) / 5) * xMax, 0) }}
              </text>
            </g>
            <text x="495" y="337" text-anchor="middle">打浆转数 / r</text>
            <g v-for="s in series" :key="s.code">
              <path
                :d="s.path"
                fill="none"
                :stroke="color(s.code)"
                stroke-width="2"
              />
              <g
                v-for="r in s.points"
                :key="r.canonical_code"
                class="plot-point"
                role="button"
                tabindex="0"
                :aria-label="`${r.canonical_code}，${r.beating_revolutions}转，${metric.name}${value(r)} ${unit}，查看详情`"
                @mouseenter="focused = r"
                @mouseleave="focused = null"
                @focus="focused = r"
                @blur="focused = null"
                @click="detail(r)"
                @keydown.enter.prevent="detail(r)"
                @keydown.space.prevent="detail(r)"
              >
                <circle :cx="x(r)" :cy="y(r)" r="10" fill="transparent" />
                <circle
                  :cx="x(r)"
                  :cy="y(r)"
                  :r="focused?.canonical_code === r.canonical_code ? 6 : 3.5"
                  :fill="color(s.code)"
                  stroke="white"
                  stroke-width="1.5"
                />
                <title>
                  {{ r.canonical_code }} · {{ number(r.beating_revolutions) }} r
                  · {{ metric.name }} {{ number(value(r), 4) }} {{ unit }}
                </title>
              </g>
            </g>
          </svg>
        </div>
        <div class="beating-tooltip" aria-live="polite">
          <template v-if="focused"
            ><strong
              >{{ materialName(focused.material_code) }} ·
              {{ focused.canonical_code }}</strong
            ><span>{{ number(focused.beating_revolutions) }} r</span
            ><span
              >{{ metric.name }}：{{ number(value(focused), 4) }}
              {{ unit }}</span
            ></template
          ><span v-else
            >悬停或聚焦查看数值，点击数据点查看样本详情与来源。</span
          >
        </div>
        <p class="beating-note">
          线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。
        </p>
      </section>
      <section class="card beating-table">
        <div class="beating-chart-heading">
          <div>
            <h2>
              实验明细 <span class="quiet-tag">{{ visible.length }}</span>
            </h2>
            <p>按打浆转数升序排列；“—”表示缺失。</p>
          </div>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="打浆实验明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th>样本编码</th>
                <th>原料</th>
                <th class="numeric">打浆转数 / r</th>
                <th class="numeric">{{ metric.name }} / {{ unit }}</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in visible" :key="r.canonical_code">
                <td>
                  <button class="sample-code" @click="detail(r)">
                    {{ r.canonical_code }}
                  </button>
                </td>
                <td>{{ materialName(r.material_code) }}</td>
                <td class="numeric">{{ number(r.beating_revolutions) }}</td>
                <td class="numeric">{{ number(value(r), 4) }}</td>
                <td>
                  <button class="text-button" @click="detail(r)">
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!visible.length" class="beating-state">暂无匹配数据。</p>
      </section>
    </template>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
.beating-controls {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 18px 22px;
  margin-bottom: 22px;
  position: relative;
  z-index: 3;
  flex-wrap: wrap;
}
.control-caption {
  display: block;
  font-size: 12px;
  color: #788697;
  margin-bottom: 8px;
}
.beating-count {
  margin-left: auto;
  font-size: 13px;
  color: #68798c;
}
.beating-count span {
  margin: 0 10px;
  color: #adb7c4;
}
.beating-chart {
  padding: 24px;
  margin-bottom: 24px;
}
.beating-chart-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.beating-chart-heading p {
  font-size: 13px;
  color: #8491a2;
  margin-top: 8px;
}
.beating-legend {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: #64758a;
}
.beating-legend span {
  display: flex;
  align-items: center;
  gap: 7px;
}
.beating-legend i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.beating-plot-scroll {
  overflow-x: auto;
  margin-top: 16px;
}
.beating-plot {
  width: 100%;
  min-width: 640px;
  display: block;
}
.beating-plot text {
  font-size: 12px;
  fill: #8592a4;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.plot-point:focus circle:last-of-type {
  stroke: #263f61;
  stroke-width: 2.5;
}
.beating-tooltip {
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  background: #f7fafc;
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 13px;
  color: #677a90;
}
.beating-tooltip strong {
  color: #3b536e;
}
.beating-note,
.unit-note {
  font-size: 12px;
  color: #7e8d9f;
  margin-top: 14px;
  line-height: 1.7;
}
.unit-note {
  color: #986f31;
}
.beating-table .beating-chart-heading {
  padding: 22px;
}
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: #73849a;
}
.beating-state p {
  margin: 14px 0;
}
@media (max-width: 720px) {
  .beating-controls > div {
    width: 100%;
  }
  .beating-controls {
    gap: 14px;
    padding: 16px;
  }
  .beating-count {
    margin-left: 0;
    width: 100%;
  }
  .beating-chart {
    padding: 16px;
  }
  .beating-tooltip {
    min-height: 90px;
    gap: 8px;
  }
  .beating-chart-heading h2 {
    line-height: 1.6;
  }
}
</style>
