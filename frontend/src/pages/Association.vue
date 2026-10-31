<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ScatterChart, RefreshCw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  typeNames,
  typeKeys,
  type Metadata,
  type Sample,
  type ListResult,
} from "../api";
import { pearson, axisDomain } from "../analysis";
import FilterSelect from "../components/FilterSelect.vue";
import SampleDetail from "../components/SampleDetail.vue";
import { materialColors } from "../palette";
interface Row extends Sample {
  [key: string]: string | number | null;
}
type Indicator = Metadata["indicators"][number];
const route = useRoute(),
  router = useRouter();
const rows = ref<Row[]>([]),
  metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const selected = ref<Row | null>(null),
  focused = ref<Row | null>(null);
const xDefault: Indicator = {
  key: "fiber_length_weighted_mm",
  name: "纤维长度（长度加权）",
  unit: "mm",
  group: "fiber",
  scope: ["core"],
  unit_status: "confirmed",
};
const yDefault: Indicator = {
  key: "tensile_index",
  name: "抗张指数",
  unit: "N·m/g",
  group: "paper",
  scope: ["core"],
  unit_status: "confirmed",
};
const xOptions = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) => i.group === "fiber" && i.scope.includes("core"),
    ) ?? [xDefault],
);
const yOptions = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) => i.group === "paper" && i.scope.includes("core"),
    ) ?? [yDefault],
);
const xMetric = computed(
  () => xOptions.value.find((i) => i.key === route.query.x) ?? xDefault,
);
const yMetric = computed(
  () => yOptions.value.find((i) => i.key === route.query.y) ?? yDefault,
);
const kind = computed(() =>
  typeKeys.includes(route.query.type as Sample["sample_type"])
    ? String(route.query.type)
    : "all",
);
const colors = materialColors;
const types = [
  { value: "all", label: "全部样本类型" },
  ...typeKeys.map((t) => ({ value: t, label: typeNames[t], color: colors[t] })),
];
const options = (items: Indicator[]) =>
  items.map((i) => ({ value: i.key, label: i.name }));
const value = (r: Row, i: Indicator): number | null =>
  typeof r[i.key] === "number" && Number.isFinite(r[i.key])
    ? (r[i.key] as number)
    : null;
const unit = (i: Indicator) => i.unit ?? "单位未确认";
const visible = computed(() =>
  rows.value
    .filter((r) => kind.value === "all" || r.sample_type === kind.value)
    .sort((a, b) => a.canonical_code.localeCompare(b.canonical_code)),
);
const valid = computed(() =>
  visible.value.filter(
    (r) => value(r, xMetric.value) !== null && value(r, yMetric.value) !== null,
  ),
);
const xDomain = computed(() =>
  axisDomain(valid.value.map((r) => value(r, xMetric.value)!)),
);
const yDomain = computed(() =>
  axisDomain(valid.value.map((r) => value(r, yMetric.value)!)),
);
const x = (r: Row) =>
  90 +
  ((value(r, xMetric.value)! - xDomain.value[0]) /
    (xDomain.value[1] - xDomain.value[0])) *
    800;
const y = (r: Row) =>
  290 -
  ((value(r, yMetric.value)! - yDomain.value[0]) /
    (yDomain.value[1] - yDomain.value[0])) *
    250;
const stats = computed(() =>
  [
    ...(kind.value === "all" ? [{ key: "all", name: "全部类型（合并）" }] : []),
    ...typeKeys
      .filter((t) => kind.value === "all" || kind.value === t)
      .map((t) => ({ key: t, name: typeNames[t] })),
  ].map((g) => {
    const group = valid.value.filter(
      (r) => g.key === "all" || r.sample_type === g.key,
    );
    return {
      ...g,
      n: group.length,
      r: pearson(
        group.map((row) => [
          value(row, xMetric.value)!,
          value(row, yMetric.value)!,
        ]),
      ),
    };
  }),
);
function update(key: string, v: string) {
  void router.replace({ query: { ...route.query, [key]: v } });
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
    const [data, meta] = await Promise.all([
      get<ListResult<Row>>("fiber-paper", { page_size: 500 }, current.signal),
      get<Metadata>("metadata", {}, current.signal),
    ]);
    if (current.signal.aborted) return;
    rows.value = data.data;
    metadata.value = meta;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "数据读取失败";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
watch(
  () => [kind.value, xMetric.value.key, yMetric.value.key],
  () => (focused.value = null),
);
void load();
onBeforeUnmount(() => controller?.abort());
</script>
<template>
  <div class="overview association-page">
    <section class="page-heading">
      <div>
        <span class="eyebrow"><ScatterChart :size="14" /> 实验分析</span>
        <h1>纤维—纸张关联</h1>
        <p>探索纤维特性与纸张性能的对应关系。</p>
      </div>
      <button class="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />刷新数据
      </button>
    </section>
    <div v-if="error" class="card association-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div v-else-if="loading" class="card association-state" role="status">
      正在读取纤维与纸张数据…
    </div>
    <template v-else>
      <section class="card association-controls" aria-label="关联分析筛选">
        <div>
          <label>样本类型</label
          ><FilterSelect
            id="association-type"
            label="样本类型"
            :model-value="kind"
            :options="types"
            @update:model-value="update('type', $event)"
          />
        </div>
        <div>
          <label>横轴 · 纤维特性</label
          ><FilterSelect
            id="association-x"
            label="纤维特性"
            :model-value="xMetric.key"
            :options="options(xOptions)"
            @update:model-value="update('x', $event)"
          />
        </div>
        <div>
          <label>纵轴 · 纸张性能</label
          ><FilterSelect
            id="association-y"
            label="纸张性能"
            :model-value="yMetric.key"
            :options="options(yOptions)"
            @update:model-value="update('y', $event)"
          />
        </div>
      </section>
      <section class="card association-chart">
        <div class="association-heading">
          <div>
            <h2>{{ xMetric.name }}与{{ yMetric.name }}</h2>
            <p class="pair-count" role="status">
              {{ visible.length }} 个样本 · {{ valid.length }} 对有效数据 ·
              {{ visible.length - valid.length }} 个缺失配对
            </p>
          </div>
          <div class="association-legend">
            <span
              v-for="t in typeKeys.filter((t) => kind === 'all' || kind === t)"
              :key="t"
              ><i :style="{ background: colors[t] }"></i
              >{{ typeNames[t] }}</span
            >
          </div>
        </div>
        <p class="axis-caption">
          横轴：{{ xMetric.name }}（{{ unit(xMetric) }}）　纵轴：{{
            yMetric.name
          }}（{{ unit(yMetric) }}）
        </p>
        <p v-if="yMetric.unit_status !== 'confirmed'" class="unit-note">
          {{ yMetric.name }}单位{{
            yMetric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
          }}，数值保留原始口径。
        </p>
        <div v-if="!valid.length" class="association-state" role="status">
          当前没有成对的有效数据，请切换指标或样本类型。
        </div>
        <div
          v-else
          class="association-plot-scroll"
          role="region"
          aria-label="关联散点图，可横向滚动"
          tabindex="0"
        >
          <svg
            class="association-plot"
            viewBox="0 0 960 355"
            aria-label="每点代表一个样本；Tab聚焦，Enter或空格查看详情"
          >
            <g v-for="i in 6" :key="i">
              <line
                x1="90"
                x2="890"
                :y1="40 + (i - 1) * 50"
                :y2="40 + (i - 1) * 50"
                stroke="#f5f2ec"
              />
              <text x="77" :y="44 + (i - 1) * 50" text-anchor="end">
                {{
                  number(
                    yDomain[1] - ((i - 1) / 5) * (yDomain[1] - yDomain[0]),
                    2,
                  )
                }}
              </text>
              <text :x="90 + (i - 1) * 160" y="315" text-anchor="middle">
                {{
                  number(
                    xDomain[0] + ((i - 1) / 5) * (xDomain[1] - xDomain[0]),
                    3,
                  )
                }}
              </text>
            </g>
            <text x="490" y="345" text-anchor="middle">
              {{ xMetric.name }} / {{ unit(xMetric) }}
            </text>
            <g
              v-for="r in valid"
              :key="r.canonical_code"
              class="association-point"
              role="button"
              tabindex="0"
              :aria-label="`${r.canonical_code}，${typeNames[r.sample_type]}，${xMetric.name}${value(r, xMetric)}，${yMetric.name}${value(r, yMetric)}，查看详情`"
              @mouseenter="focused = r"
              @mouseleave="focused = null"
              @focus="focused = r"
              @blur="focused = null"
              @click="selected = r"
              @keydown.enter.prevent="selected = r"
              @keydown.space.prevent="selected = r"
            >
              <circle :cx="x(r)" :cy="y(r)" r="11" fill="transparent" />
              <circle
                :cx="x(r)"
                :cy="y(r)"
                :r="focused?.canonical_code === r.canonical_code ? 7 : 5"
                :fill="colors[r.sample_type]"
                fill-opacity=".8"
                stroke="white"
                stroke-width="1.5"
              />
              <title>
                {{ r.canonical_code }} · {{ xMetric.name }}
                {{ number(value(r, xMetric), 4) }} {{ unit(xMetric) }} ·
                {{ yMetric.name }} {{ number(value(r, yMetric), 4) }}
                {{ unit(yMetric) }}
              </title>
            </g>
          </svg>
        </div>
        <div class="association-tooltip" aria-live="polite">
          <template v-if="focused"
            ><strong
              >{{ focused.canonical_code }} ·
              {{ typeNames[focused.sample_type] }}</strong
            ><span
              >{{ xMetric.name }}：{{ number(value(focused, xMetric), 4) }}
              {{ unit(xMetric) }}</span
            ><span
              >{{ yMetric.name }}：{{ number(value(focused, yMetric), 4) }}
              {{ unit(yMetric) }}</span
            ></template
          ><span v-else
            >悬停或聚焦查看数值，点击查看样本详情与来源。重合的数据点也可通过明细表逐一查看。</span
          >
        </div>
      </section>
      <section class="card association-statistics">
        <div class="association-heading">
          <div>
            <h2>线性相关性</h2>
            <p>
              Pearson r 范围为 −1 至 1；正值表示同向变化，负值表示反向变化，接近
              0 表示线性关联较弱。
            </p>
          </div>
        </div>
        <div class="correlation-grid">
          <article v-for="s in stats" :key="s.key">
            <h3>{{ s.name }}</h3>
            <strong :data-group="s.key">{{ number(s.r, 3) }}</strong>
            <p>{{ s.n }} 对有效数据</p>
            <small v-if="s.r === null">{{
              s.n < 3 ? "少于3对数据，暂不计算" : "至少一个指标无变化，无法计算"
            }}</small>
          </article>
        </div>
        <p class="association-note">
          仅使用两个指标均有效的样本，缺失值不补零。相关不等于因果；合并不同类型可能受原料、打浆条件和配比影响，请结合分组结果判断。此处不作显著性检验。
        </p>
      </section>
      <section class="card association-table">
        <div class="association-heading">
          <div>
            <h2>配对数据明细</h2>
            <p>每个唯一样本一行，按样本编码排序；“—”表示缺失。</p>
          </div>
        </div>
        <div
          class="table-scroll"
          role="region"
          aria-label="配对数据明细，可横向滚动"
          tabindex="0"
        >
          <table>
            <thead>
              <tr>
                <th>样本编码</th>
                <th>样本类型</th>
                <th class="numeric">
                  {{ xMetric.name }} / {{ unit(xMetric) }}
                </th>
                <th class="numeric">
                  {{ yMetric.name }} / {{ unit(yMetric) }}
                </th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in visible" :key="r.canonical_code">
                <td>
                  <button class="sample-code" @click="selected = r">
                    {{ r.canonical_code }}
                  </button>
                </td>
                <td>{{ typeNames[r.sample_type] }}</td>
                <td class="numeric">{{ number(value(r, xMetric), 4) }}</td>
                <td class="numeric">{{ number(value(r, yMetric), 4) }}</td>
                <td>
                  <button class="text-button" @click="selected = r">
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <SampleDetail :sample="selected" @close="selected = null" />
  </div>
</template>
<style scoped>
.association-controls {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  padding: 20px 24px;
  margin-bottom: 24px;
  position: relative;
  z-index: 3;
}
.association-controls label {
  display: block;
  color: #978d78;
  font-size: 12px;
  margin-bottom: 8px;
}
.association-chart,
.association-statistics {
  padding: 24px;
  margin-bottom: 24px;
}
.association-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.association-heading p,
.axis-caption {
  font-size: 13px;
  color: #9e9178;
  margin-top: 9px;
  line-height: 1.7;
}
.association-legend {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #8a7d64;
}
.association-legend span {
  display: flex;
  align-items: center;
  gap: 7px;
}
.association-legend i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.association-plot-scroll {
  overflow-x: auto;
  margin-top: 14px;
}
.association-plot {
  width: 100%;
  min-width: 640px;
  display: block;
}
.association-plot text {
  font-size: 12px;
  fill: #a49a85;
}
.association-point {
  cursor: pointer;
}
.association-point:focus {
  outline: none;
}
.association-point:focus circle:last-of-type {
  stroke: #0a4f4b;
  stroke-width: 2.5;
}
.association-tooltip {
  min-height: 52px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #fcfaf7;
  border-radius: 6px;
  color: #908267;
  font-size: 13px;
}
.association-tooltip strong {
  color: #0b5f5a;
}
.correlation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 16px;
  margin-top: 22px;
}
.correlation-grid article {
  padding: 18px;
  background: #fcfbf9;
  border-radius: 7px;
}
.correlation-grid h3 {
  color: #8a7d64;
  font-size: 13px;
}
.correlation-grid strong {
  display: block;
  font-size: 30px;
  color: #0b5f5a;
  margin: 10px 0;
}
.correlation-grid p,
.correlation-grid small {
  font-size: 12px;
  color: #9e9178;
  line-height: 1.7;
}
.association-note,
.unit-note {
  font-size: 12px;
  line-height: 1.8;
  color: #9e9178;
  margin-top: 16px;
}
.unit-note {
  color: #986f31;
}
.association-table .association-heading {
  padding: 22px;
}
.association-state {
  text-align: center;
  padding: 64px 24px;
  color: #9a8d73;
}
.association-state p {
  margin: 14px 0;
}
@media (max-width: 900px) {
  .association-controls > div {
    width: 100%;
  }
}
@media (max-width: 720px) {
  .association-chart,
  .association-statistics,
  .association-controls {
    padding: 16px;
  }
  .association-heading h2 {
    line-height: 1.7;
  }
  .association-tooltip {
    min-height: 100px;
  }
  .correlation-grid {
    grid-template-columns: 1fr 1fr;
  }
  .association-page h1 {
    font-size: 24px;
  }
}
</style>
