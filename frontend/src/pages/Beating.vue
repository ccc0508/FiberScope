<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { RefreshCw, TriangleAlert } from "lucide-vue-next";
import {
  get,
  number,
  type Metadata,
  type ListResult,
  type Sample,
} from "../api";
import {
  firstReach,
  interpolateAt,
  niceTicks,
  type CurvePoint,
} from "../beating";
import { isGarden } from "../mode";
import "../styles/beating.css";
import BeatingChart from "../components/beating/BeatingChart.vue";
import BeatingControls from "../components/beating/BeatingControls.vue";
import BeatingKpis from "../components/beating/BeatingKpis.vue";
import BeatingReadout from "../components/beating/BeatingReadout.vue";
import BeatingTable from "../components/beating/BeatingTable.vue";
import {
  MATERIALS,
  SR_KEY,
  TARGET_MAX,
  TARGET_MIN,
  materialName,
  type BeatingRow,
  type Material,
} from "../components/beating/types";
import FiberHero from "../components/FiberHero.vue";
import PageHeader from "../components/PageHeader.vue";
import SampleDetail from "../components/SampleDetail.vue";

/*
 * 打浆分析：一个模板服务两种显示模式。
 *  偏光（v1）：控制条 → 四格目标读数条 → 曲线（HUD 十字准星）+ 读数面板 → 明细表
 *  花园（v4）：控制瓦片 → 曲线 + 「达到目标所需转数」瓦片 → 明细表 + 读数瓦片
 * 布局差异只在作用域 CSS（:root[data-mode=…]）里表达；两套装饰层都渲染，按模式显隐。
 */
const route = useRoute(),
  router = useRouter();
const rows = ref<BeatingRow[]>([]),
  samples = ref<Sample[]>([]);
const metadata = ref<Metadata | null>(null);
const loading = ref(true),
  error = ref("");
const detailSample = ref<Sample | null>(null);
const selectedCode = ref<string | null>(null);

/* ---------- 筛选：原料、指标、目标打浆度都放在 URL 上 ---------- */
const defaultMetric = {
  key: SR_KEY,
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
const isSr = computed(() => metric.value.key === SR_KEY);
const material = computed<"all" | Material>(() =>
  MATERIALS.includes(route.query.material as Material)
    ? (route.query.material as Material)
    : "all",
);
const target = computed(() => {
  const t = Number(route.query.target);
  return Number.isFinite(t) && t >= TARGET_MIN && t <= TARGET_MAX
    ? Math.round(t)
    : 45;
});
const METRIC_GROUPS: Record<string, string> = {
  condition: "打浆条件",
  fiber: "纤维特性",
  paper: "纸张性能",
};
const metricOptions = computed(() =>
  metrics.value.map((i) => ({
    value: i.key,
    label: i.name,
    hint: i.unit ?? undefined,
    group: METRIC_GROUPS[i.group] ?? i.group,
  })),
);
function update(key: string, next: string | undefined) {
  void router.replace({ query: { ...route.query, [key]: next } });
}
const setTarget = (t: number) =>
  update("target", String(Math.max(TARGET_MIN, Math.min(TARGET_MAX, t))));

/* ---------- 数据 ---------- */
const unit = computed(() => metric.value.unit ?? "单位未确认");
const value = (r: BeatingRow): number | null =>
  typeof r[metric.value.key] === "number" &&
  Number.isFinite(r[metric.value.key])
    ? (r[metric.value.key] as number)
    : null;
const digits = computed(() => {
  const values = rows.value.map(value).filter((v): v is number => v !== null);
  const span = values.length ? Math.max(...values) - Math.min(...values) : 1;
  return span >= 50 ? 1 : span >= 5 ? 2 : 3;
});

const byMaterial = computed(
  () =>
    Object.fromEntries(
      MATERIALS.map((code) => [
        code,
        rows.value
          .filter((r) => r.material_code === code)
          .sort(
            (a, b) =>
              a.beating_revolutions - b.beating_revolutions ||
              a.canonical_code.localeCompare(b.canonical_code),
          ),
      ]),
    ) as Record<Material, BeatingRow[]>,
);
const shownMaterials = computed(() =>
  material.value === "all" ? MATERIALS : [material.value],
);
const visible = computed(() =>
  shownMaterials.value.flatMap((code) => byMaterial.value[code]),
);
const valid = computed(() => visible.value.filter((r) => value(r) !== null));
const curve = (code: Material): CurvePoint[] =>
  byMaterial.value[code]
    .filter((r) => value(r) !== null)
    .map((r) => ({ x: r.beating_revolutions, y: value(r)! }));
const curves = computed<Record<Material, CurvePoint[]>>(() => ({
  SW: curve("SW"),
  HW: curve("HW"),
}));
const counts = computed(() => ({
  all: rows.value.filter(inRange).length,
  SW: byMaterial.value.SW.filter(inRange).length,
  HW: byMaterial.value.HW.filter(inRange).length,
}));

/* ---------- 打浆度区间：筛选表格与读数，曲线保留全部点、区间外淡化 ---------- */
const srOf = (r: BeatingRow) =>
  typeof r[SR_KEY] === "number" && Number.isFinite(r[SR_KEY])
    ? (r[SR_KEY] as number)
    : null;
const srRange = computed(() => {
  const m = /^(\d{1,3})-(\d{1,3})$/.exec(String(route.query.sr ?? ""));
  const lo = m ? Number(m[1]) : 0,
    hi = m ? Number(m[2]) : 100;
  return lo <= hi && hi <= 100 ? { lo, hi } : { lo: 0, hi: 100 };
});
const rangeActive = computed(
  () => srRange.value.lo > 0 || srRange.value.hi < 100,
);
// 区间未收窄时不按打浆度过滤，打浆度缺失的行照常显示
function inRange(r: BeatingRow) {
  if (!rangeActive.value) return true;
  const sr = srOf(r);
  return sr !== null && sr >= srRange.value.lo && sr <= srRange.value.hi;
}
function setRange(lo: number, hi: number) {
  const a = Math.min(lo, hi),
    b = Math.max(lo, hi);
  update("sr", a === 0 && b === 100 ? undefined : `${a}-${b}`);
}
const listedBy = (code: Material) => byMaterial.value[code].filter(inRange);
const listed = computed(() =>
  shownMaterials.value.flatMap((code) => listedBy(code)),
);
const histogram = computed(() => {
  const bins = Array.from({ length: 10 }, () => 0);
  for (const r of visible.value) {
    const sr = srOf(r);
    if (sr !== null) bins[Math.min(9, Math.floor(sr / 10))]!++;
  }
  const max = Math.max(1, ...bins);
  return bins.map((n, i) => ({
    n,
    h: n ? Math.max(8, (n / max) * 100) : 0,
    on: i * 10 + 10 > srRange.value.lo && i * 10 < srRange.value.hi,
    // 偏光：每根柱子取同一条干涉色带的相邻切片
    slice: { "--bs": "1000% 100%", "--bp": `${(i / 9) * 100}% 0` },
  }));
});

/* ---------- KPI & 坐标 ---------- */
const round100 = (v: number) => Math.round(v / 100) * 100;
const xMax = computed(
  () =>
    Math.ceil(
      Math.max(5000, ...rows.value.map((r) => r.beating_revolutions)) / 5000,
    ) * 5000,
);
const reach = computed(
  () =>
    Object.fromEntries(
      MATERIALS.map((code) => [code, firstReach(curves.value[code], target.value)]),
    ) as Record<Material, number | null>,
);
const reachGap = computed(() => {
  const { SW, HW } = reach.value;
  return SW !== null && HW !== null ? round100(SW) - round100(HW) : null;
});
const change = (code: Material) => {
  const c = curves.value[code];
  if (c.length < 2) return null;
  const first = c[0]!,
    last = c[c.length - 1]!;
  return {
    from: first,
    to: last,
    pct: first.y !== 0 ? ((last.y - first.y) / Math.abs(first.y)) * 100 : null,
  };
};
const changes = computed(() => ({
  SW: change("SW"),
  HW: change("HW"),
}));
const srCurve = (code: Material): CurvePoint[] =>
  byMaterial.value[code]
    .filter((r) => srOf(r) !== null)
    .map((r) => ({ x: r.beating_revolutions, y: srOf(r)! }));
const sigCurves = computed(() => ({ SW: srCurve("SW"), HW: srCurve("HW") }));

const yTicks = computed(() => {
  const values = valid.value.map((r) => value(r)!);
  if (isSr.value) values.push(target.value);
  if (!values.length) return [0, 1];
  const min = Math.min(...values),
    max = Math.max(...values);
  return niceTicks(min >= 0 ? Math.max(0, min - (max - min) * 0.08) : min, max);
});
const yMin = computed(() => yTicks.value[0]!),
  yMax = computed(() => yTicks.value[yTicks.value.length - 1]!);

/* ---------- 读数面板 ---------- */
const selected = computed(
  () =>
    listed.value.find((r) => r.canonical_code === selectedCode.value) ??
    listed.value[0] ??
    null,
);
const selectedIndex = computed(() =>
  selected.value ? listed.value.indexOf(selected.value) : -1,
);
function select(row: BeatingRow) {
  selectedCode.value = row.canonical_code;
}
async function step(delta: number) {
  const next = listed.value[selectedIndex.value + delta];
  if (!next) return;
  select(next);
  await nextTick();
  document
    .querySelector(`[data-code="${next.canonical_code}"]`)
    ?.scrollIntoView({ block: "nearest" });
}
function otherAt(row: BeatingRow) {
  const other: Material = row.material_code === "SW" ? "HW" : "SW";
  const exact = byMaterial.value[other].find(
    (r) => r.beating_revolutions === row.beating_revolutions,
  );
  const exactValue = exact ? value(exact) : null;
  if (exactValue !== null)
    return { code: other, value: exactValue, estimated: false };
  const estimated = interpolateAt(curves.value[other], row.beating_revolutions);
  return { code: other, value: estimated, estimated: estimated !== null };
}
const otherAtSameRevs = computed(() =>
  selected.value ? otherAt(selected.value) : null,
);
const toTarget = computed(() => {
  const s = selected.value,
    v = s ? value(s) : null;
  if (!isSr.value || !s || v === null) return null;
  const at = reach.value[s.material_code];
  return {
    gap: target.value - v,
    revs:
      at === null ? null : Math.max(0, round100(at - s.beating_revolutions)),
  };
});
const selectedReachPct = computed(() => {
  const s = selected.value;
  if (!isSr.value || !s) return null;
  const at = reach.value[s.material_code];
  return at === null ? null : Math.min(100, (at / xMax.value) * 100);
});
function deltaOf(row: BeatingRow) {
  const own = value(row),
    other = otherAt(row);
  return own === null || other.value === null
    ? null
    : { d: own - other.value, estimated: other.estimated };
}
const deltaMax = computed(() =>
  Math.max(1e-9, ...listed.value.map((r) => Math.abs(deltaOf(r)?.d ?? 0))),
);

/* ---------- 勾选与导出 ---------- */
const checked = ref(new Set<string>());
function toggle(code: string, on: boolean) {
  const next = new Set(checked.value);
  if (on) next.add(code);
  else next.delete(code);
  checked.value = next;
}
const allChecked = computed(
  () =>
    listed.value.length > 0 &&
    listed.value.every((r) => checked.value.has(r.canonical_code)),
);
const someChecked = computed(
  () =>
    !allChecked.value &&
    listed.value.some((r) => checked.value.has(r.canonical_code)),
);
function toggleAll(on: boolean) {
  const next = new Set(checked.value);
  for (const r of listed.value)
    if (on) next.add(r.canonical_code);
    else next.delete(r.canonical_code);
  checked.value = next;
}
const exportRows = computed(() => {
  const picked = listed.value.filter((r) =>
    checked.value.has(r.canonical_code),
  );
  return picked.length ? picked : listed.value;
});
function exportCsv() {
  const head = [
    "样本编码",
    "样本名称",
    "原料",
    "打浆转数(r)",
    "打浆度(°SR)",
    `${metric.value.name}(${unit.value})`,
    "较另一种原料(同转数)",
    "另一种原料取值方式",
  ];
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = exportRows.value.map((r) => {
    const delta = deltaOf(r);
    return [
      r.canonical_code,
      r.display_name,
      materialName(r.material_code),
      r.beating_revolutions,
      srOf(r) ?? "",
      value(r) ?? "",
      delta ? delta.d : "",
      delta
        ? delta.estimated
          ? "线性插值"
          : "实测"
        : "无（超出实测范围或缺失）",
    ];
  });
  const csv =
    "\uFEFF" + [head, ...lines].map((l) => l.map(cell).join(",")).join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  link.download = `打浆分析_${metric.value.key}_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function openDetail(row: BeatingRow) {
  detailSample.value =
    samples.value.find((s) => s.canonical_code === row.canonical_code) ?? null;
}
const valueBar = (v: number | null) =>
  v === null
    ? 0
    : Math.max(
        0,
        Math.min(
          100,
          ((v - yMin.value) / (yMax.value - yMin.value || 1)) * 100,
        ),
      );

/* ---------- 读取 ---------- */
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
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
void load();
onBeforeUnmount(() => {
  controller?.abort();
});
</script>

<template>
  <div class="overview beating-page">
    <PageHeader description="比较打浆转数变化下的纤维特性与纸张性能。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <FiberHero
          :sw="sigCurves.SW"
          :hw="sigCurves.HW"
          :target="target"
          :x-max="xMax"
        />
      </template>
    </PageHeader>

    <div v-if="error" class="card beating-state beating-status" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button primary" @click="load">重新加载</button>
    </div>
    <div
      v-else-if="loading"
      class="card beating-state beating-status"
      role="status"
    >
      正在读取打浆实验数据…
    </div>
    <template v-else>
      <BeatingControls
        :material="material"
        :metric-key="metric.key"
        :metric-options="metricOptions"
        :counts="counts"
        :sr-range="srRange"
        :histogram="histogram"
        :listed-count="listed.length"
        :valid-count="valid.length"
        :range-active="rangeActive"
        @update-material="update('material', $event)"
        @update-metric="update('metric', $event)"
        @set-range="setRange"
        @reset-range="setRange(0, 100)"
      />

      <p v-if="metric.unit_status !== 'confirmed'" class="unit-note">
        {{ metric.name }}的单位{{
          metric.unit_status === "tentative" ? "暂定，待确认" : "尚未确认"
        }}，数值保留原始口径。
      </p>

      <BeatingKpis
        :is-sr="isSr"
        :target="target"
        :material="material"
        :reach="reach"
        :reach-gap="reachGap"
        :x-max="xMax"
        :metric-name="metric.name"
        :unit="unit"
        :digits="digits"
        :valid-count="valid.length"
        :visible-count="visible.length"
        :changes="changes"
        @set-target="setTarget"
      />

      <BeatingChart
        :metric-key="metric.key"
        :metric-name="metric.name"
        :unit="unit"
        :digits="digits"
        :is-sr="isSr"
        :material="material"
        :shown-materials="shownMaterials"
        :by-material="byMaterial"
        :visible="visible"
        :valid="valid"
        :curves="curves"
        :x-max="xMax"
        :y-ticks="yTicks"
        :target="target"
        :reach="reach"
        :selected="selected"
        :in-range="inRange"
        @select="select"
        @open-detail="openDetail"
      />

      <BeatingReadout
        :selected="selected"
        :selected-index="selectedIndex"
        :listed-count="listed.length"
        :metric-key="metric.key"
        :metric-name="metric.name"
        :unit="unit"
        :digits="digits"
        :x-max="xMax"
        :target="target"
        :selected-reach-pct="selectedReachPct"
        :to-target="toTarget"
        :other-at-same-revs="otherAtSameRevs"
        :value-bar="valueBar"
        @open-detail="openDetail"
        @step="step"
      />

      <BeatingTable
        :shown-materials="shownMaterials"
        :listed-by="listedBy"
        :listed-count="listed.length"
        :metric-key="metric.key"
        :metric-name="metric.name"
        :unit="unit"
        :digits="digits"
        :is-sr="isSr"
        :target="target"
        :selected="selected"
        :checked="checked"
        :all-checked="allChecked"
        :some-checked="someChecked"
        :export-count="exportRows.length"
        :sr-range="srRange"
        :value-bar="valueBar"
        :delta-of="deltaOf"
        :delta-max="deltaMax"
        @select="select"
        @open-detail="openDetail"
        @toggle="toggle"
        @toggle-all="toggleAll"
        @export-csv="exportCsv"
        @reset-range="setRange(0, 100)"
      />
    </template>
    <SampleDetail :sample="detailSample" @close="detailSample = null" />
  </div>
</template>

<style scoped>
/* ================================================================ page grid
   DOM order: header · controls · (unit note) · KPI · chart · readout · table.
   Dense auto-flow pairs the side panels with their neighbours per mode:
   polarized (v1) chart | readout, garden (v4) chart | KPI tile and table | readout. */
.beating-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  grid-auto-flow: row dense;
  gap: 18px;
  align-items: start;
}
.beating-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.beating-page > .page-header {
  margin-bottom: 0;
}
.beating-page > .beating-chart {
  grid-column: 1;
}
.beating-page > .beating-readout {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}
:root[data-mode="garden"] .beating-page > .beating-kpis {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page > .beating-chart {
  align-self: stretch;
}
:root[data-mode="garden"] .beating-page > .beating-table {
  grid-column: 1;
}

.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.beating-state p {
  margin: 14px 0;
}
.beating-status {
  display: grid;
  justify-items: center;
  gap: 4px;
}
.unit-note {
  font-size: 12.5px;
  color: var(--warn);
  margin: -6px 0 -4px;
}

@media (max-width: 1280px) {
  .beating-page {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
}
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .beating-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="polarized"] .beating-page > *,
  :root[data-mode="polarized"] .beating-page > .beating-readout {
    grid-column: 1 / -1;
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .beating-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .beating-page > *,
  :root[data-mode="garden"] .beating-page > .beating-kpis,
  :root[data-mode="garden"] .beating-page > .beating-table {
    grid-column: 1 / -1;
  }
}
@media (max-width: 720px) {
  .beating-page {
    gap: 14px;
  }
}
</style>
