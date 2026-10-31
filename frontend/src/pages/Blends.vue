<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Combine, RefreshCw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  type Metadata,
  type ListResult,
  type Sample,
} from "../api";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import { materialColors } from "../palette";

interface BlendRow {
  canonical_code: string;
  sw_proportion_pct: number;
  hw_proportion_pct: number;
  sw_beating_revolutions: number | null;
  hw_beating_revolutions: number | null;
  sw_beating_degree_sr: number | null;
  hw_beating_degree_sr: number | null;
  [key: string]: string | number | null;
}
const route = useRoute(),
  router = useRouter();
const rows = ref<BlendRow[]>([]),
  samples = ref<Sample[]>([]);
const metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const selected = ref<Sample | null>(null),
  focused = ref<BlendRow | null>(null);
const defaultMetric = {
  key: "tensile_index",
  name: "抗张指数",
  unit: "N·m/g",
  group: "condition",
  scope: ["core"],
  unit_status: "confirmed",
};
const metrics = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("core")) ?? [
      defaultMetric,
    ],
);
const metric = computed(
  () =>
    metrics.value.find((i) => i.key === route.query.metric) ?? defaultMetric,
);
const metricOptions = computed(() =>
  metrics.value.map((i) => ({ value: i.key, label: i.name })),
);
const visible = computed(() =>
  [...rows.value].sort(
    (a, b) =>
      a.sw_proportion_pct - b.sw_proportion_pct ||
      a.canonical_code.localeCompare(b.canonical_code),
  ),
);
const pointName = (r: BlendRow) =>
  r.sw_proportion_pct === 0
    ? "纯阔叶木端点"
    : r.sw_proportion_pct === 100
      ? "纯针叶木端点"
      : "复配样本";
const pointColor = (r: BlendRow) =>
  r.sw_proportion_pct === 0
    ? materialColors.hardwood
    : r.sw_proportion_pct === 100
      ? materialColors.softwood
      : materialColors.blend;
const value = (r: BlendRow): number | null =>
  typeof r[metric.value.key] === "number" &&
  Number.isFinite(r[metric.value.key])
    ? (r[metric.value.key] as number)
    : null;
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const unit = computed(() => metric.value.unit ?? "单位未确认");
const yDomain = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values),
    pad = (max - min || Math.abs(max) || 1) * 0.12;
  return [min >= 0 ? Math.max(0, min - pad) : min - pad, max + pad];
});
const xMax = 100;
const x = (r: BlendRow) => 80 + (r.sw_proportion_pct / 100) * 830;
const y = (r: BlendRow) =>
  285 -
  ((value(r)! - yDomain.value[0]!) / (yDomain.value[1]! - yDomain.value[0]!)) *
    245;
const series = computed(() =>
  ["blend"].map((code) => {
    const points = visible.value;
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
function detail(row: BlendRow) {
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
      get<ListResult<BlendRow>>("blends", { page_size: 500 }, current.signal),
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
  () => [metric.value.key],
  () => {
    focused.value = null;
  },
);
void load();
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="overview blend-page">
    <section class="page-heading">
      <div>
        <span class="eyebrow"><Combine :size="14" /> 实验分析</span>
        <h1>复配分析</h1>
        <p>观察针阔配比变化下的纤维特性与纸张性能。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </section>
    <div v-if="error" class="card blend-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card blend-state" role="status">
      正在读取复配实验数据…
    </div>
    <template v-else>
      <section class="card blend-controls" aria-label="复配分析筛选">
        <div>
          <span class="control-caption">分析指标</span
          ><FilterSelect
            id="blend-metric"
            label="分析指标"
            :model-value="metric.key"
            :options="metricOptions"
            @update:model-value="update('metric', $event)"
          />
        </div>
        <p class="blend-count" role="status">
          {{ visible.length }} 个展示点（含2个纯浆端点） <span>·</span>
          {{ valid.length }} 个有效数据点
        </p>
      </section>
      <section class="card blend-chart">
        <div class="blend-chart-heading">
          <div>
            <h2>{{ metric.name }}随针叶木比例的变化</h2>
            <p>纵轴：{{ metric.name }}（{{ unit }}）</p>
          </div>
          <div class="blend-legend">
            <span
              ><i :style="{ background: materialColors.hardwood }"></i
              >纯阔叶木端点</span
            ><span
              ><i :style="{ background: materialColors.blend }"></i
              >复配样本</span
            ><span
              ><i :style="{ background: materialColors.softwood }"></i
              >纯针叶木端点</span
            >
          </div>
        </div>
        <p class="blend-note">
          9个复配样本与2个复用纯浆端点；端点不计为新增样本。具体打浆条件见下方明细。
        </p>
        <p v-if="metric.unit_status !== 'confirmed'" class="unit-note">
          {{ metric.name }}的单位{{
            metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
          }}，数值保留原始口径。
        </p>
        <div v-if="!valid.length" class="blend-state" role="status">
          当前没有该指标的有效数据，请切换指标。
        </div>
        <div
          v-else
          class="blend-plot-scroll"
          role="region"
          aria-label="复配趋势图，可横向滚动"
          tabindex="0"
        >
          <svg
            class="blend-plot"
            viewBox="0 0 960 345"
            aria-label="复配趋势图；可用Tab定位数据点，Enter查看样本详情"
          >
            <g v-for="i in 6" :key="`y${i}`">
              <line
                x1="80"
                x2="910"
                :y1="40 + (i - 1) * 49"
                :y2="40 + (i - 1) * 49"
                stroke="#f5f2ec"
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
            <text x="495" y="337" text-anchor="middle">
              针叶木比例 / %（阔叶木比例 = 100% − 针叶木比例）
            </text>
            <g v-for="s in series" :key="s.code">
              <path
                :d="s.path"
                fill="none"
                :stroke="materialColors.blend"
                stroke-width="2"
              />
              <g
                v-for="r in s.points"
                :key="r.canonical_code"
                class="plot-point"
                role="button"
                tabindex="0"
                :aria-label="`${r.canonical_code}，针叶木${r.sw_proportion_pct}%，阔叶木${r.hw_proportion_pct}%，${pointName(r)}，${metric.name}${value(r)} ${unit}，查看详情`"
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
                  :fill="pointColor(r)"
                  stroke="white"
                  stroke-width="1.5"
                />
                <title>
                  {{ r.canonical_code }} · 针叶木
                  {{ number(r.sw_proportion_pct) }}% / 阔叶木
                  {{ number(r.hw_proportion_pct) }}% · {{ metric.name }}
                  {{ number(value(r), 4) }} {{ unit }}
                </title>
              </g>
            </g>
          </svg>
        </div>
        <div class="blend-tooltip" aria-live="polite">
          <template v-if="focused"
            ><strong
              >{{ pointName(focused) }} · {{ focused.canonical_code }}</strong
            ><span
              >针叶木 {{ number(focused.sw_proportion_pct) }}% / 阔叶木
              {{ number(focused.hw_proportion_pct) }}%</span
            ><span
              >{{ metric.name }}：{{ number(value(focused), 4) }}
              {{ unit }}</span
            ></template
          ><span v-else
            >悬停或聚焦查看数值，点击数据点查看样本详情与来源。</span
          >
        </div>
        <p class="blend-note">
          线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。
        </p>
      </section>
      <section class="card blend-table">
        <div class="blend-chart-heading">
          <div>
            <h2>
              实验明细 <span class="quiet-tag">{{ visible.length }}</span>
            </h2>
            <p>
              按针叶木比例升序排列；条件按针叶木 / 阔叶木显示，“—”表示无对应值。
            </p>
          </div>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="复配实验明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th>样本编码</th>
                <th>类型</th>
                <th class="numeric">配比 / %</th>
                <th class="numeric">打浆转数 / r</th>
                <th class="numeric">打浆度 / °SR</th>
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
                <td>{{ pointName(r) }}</td>
                <td class="numeric">
                  {{ number(r.sw_proportion_pct) }} /
                  {{ number(r.hw_proportion_pct) }}
                </td>
                <td class="numeric">
                  {{ number(r.sw_beating_revolutions) }} /
                  {{ number(r.hw_beating_revolutions) }}
                </td>
                <td class="numeric">
                  {{ number(r.sw_beating_degree_sr, 1) }} /
                  {{ number(r.hw_beating_degree_sr, 1) }}
                </td>
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
        <p v-if="!visible.length" class="blend-state">暂无匹配数据。</p>
      </section>
    </template>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
.blend-controls {
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
  color: #978d78;
  margin-bottom: 8px;
}
.blend-count {
  margin-left: auto;
  font-size: 13px;
  color: #8c8068;
}
.blend-count span {
  margin: 0 10px;
  color: #c4bcad;
}
.blend-chart {
  padding: 24px;
  margin-bottom: 24px;
}
.blend-chart-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.blend-chart-heading p {
  font-size: 13px;
  color: #a29884;
  margin-top: 8px;
}
.blend-legend {
  flex-wrap: wrap;
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: #8a7d64;
}
.blend-legend span {
  display: flex;
  align-items: center;
  gap: 7px;
}
.blend-legend i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.blend-plot-scroll {
  overflow-x: auto;
  margin-top: 16px;
}
.blend-plot {
  width: 100%;
  min-width: 640px;
  display: block;
}
.blend-plot text {
  font-size: 12px;
  fill: #a49a85;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.plot-point:focus circle:last-of-type {
  stroke: #0a4f4b;
  stroke-width: 2.5;
}
.blend-tooltip {
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  background: #fcfaf7;
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 13px;
  color: #908267;
}
.blend-tooltip strong {
  color: #0b5f5a;
}
.blend-note,
.unit-note {
  font-size: 12px;
  color: #9f947e;
  margin-top: 14px;
  line-height: 1.7;
}
.unit-note {
  color: #986f31;
}
.blend-table .blend-chart-heading {
  padding: 22px;
}
.blend-state {
  padding: 64px 24px;
  text-align: center;
  color: #9a8d73;
}
.blend-state p {
  margin: 14px 0;
}
@media (max-width: 720px) {
  .blend-controls > div {
    width: 100%;
  }
  .blend-controls {
    gap: 14px;
    padding: 16px;
  }
  .blend-count {
    margin-left: 0;
    width: 100%;
  }
  .blend-chart {
    padding: 16px;
  }
  .blend-tooltip {
    min-height: 90px;
    gap: 8px;
  }
  .blend-chart-heading h2 {
    line-height: 1.6;
  }
}
</style>
