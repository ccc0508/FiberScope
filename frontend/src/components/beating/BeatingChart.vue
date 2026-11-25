<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { number } from "../../api";
import { interpolateAt, type CurvePoint } from "../../beating";
import { useElementWidth } from "../../composables/useElementWidth";
import { isGarden } from "../../mode";
import { materialColor, materialName, type BeatingRow, type Material } from "./types";

const props = defineProps<{
  metricKey: string;
  metricName: string;
  unit: string;
  digits: number;
  isSr: boolean;
  material: "all" | Material;
  shownMaterials: Material[];
  byMaterial: Record<Material, BeatingRow[]>;
  visible: BeatingRow[];
  valid: BeatingRow[];
  curves: Record<Material, CurvePoint[]>;
  xMax: number;
  yTicks: number[];
  target: number;
  reach: Record<Material, number | null>;
  selected: BeatingRow | null;
  inRange: (row: BeatingRow) => boolean;
}>();

const emit = defineEmits<{
  select: [row: BeatingRow];
  openDetail: [row: BeatingRow];
}>();

const round100 = (v: number) => Math.round(v / 100) * 100;
const value = (r: BeatingRow): number | null =>
  typeof r[props.metricKey] === "number" && Number.isFinite(r[props.metricKey])
    ? (r[props.metricKey] as number)
    : null;
const fmt = (v: number | null) => number(v, props.digits);

const plotBox = ref<HTMLElement>();
const plotWidth = useElementWidth(plotBox);
const narrow = computed(() => plotWidth.value < 520);
const plotH = computed(() => (narrow.value ? 300 : 420));
const directLabels = computed(() => isGarden.value && !narrow.value);
const X_PAD = 10;
const margin = computed(() => ({
  t: 34,
  r: directLabels.value ? 96 : narrow.value ? 14 : 26,
  b: 46,
  l: narrow.value ? 46 : 58,
}));
const xTicks = computed(() => {
  const step = plotWidth.value < 560 ? 10000 : 5000,
    out: number[] = [];
  for (let v = 0; v <= props.xMax; v += step) out.push(v);
  return out;
});
const xTickLabel = (t: number) =>
  t === 0
    ? "0"
    : isGarden.value
      ? `${number(t / 1000, t % 1000 ? 1 : 0)}k`
      : plotWidth.value < 560
        ? `${number(t / 1000, t % 1000 ? 1 : 0)}K`
        : number(t);
const yMin = computed(() => props.yTicks[0]!);
const yMax = computed(() => props.yTicks[props.yTicks.length - 1]!);
const plotInner = computed(
  () => plotWidth.value - margin.value.l - margin.value.r - X_PAD,
);
const px = (revs: number) =>
  margin.value.l + X_PAD + (revs / props.xMax) * plotInner.value;
const py = (v: number) =>
  margin.value.t +
  (1 - (v - yMin.value) / (yMax.value - yMin.value || 1)) *
    (plotH.value - margin.value.t - margin.value.b);

const series = computed(() =>
  props.shownMaterials.map((code) => {
    let connected = false;
    const path = props.byMaterial[code]
      .map((r) => {
        const v = value(r);
        if (v === null) {
          connected = false;
          return "";
        }
        const seg = `${connected ? "L" : "M"}${px(r.beating_revolutions).toFixed(1)},${py(v).toFixed(1)}`;
        connected = true;
        return seg;
      })
      .join(" ");
    return {
      code,
      path,
      points: props.byMaterial[code].filter((r) => value(r) !== null),
    };
  }),
);

const selLabel = computed(() => {
  const s = props.selected,
    v = s ? value(s) : null;
  if (!s || v === null || !props.shownMaterials.includes(s.material_code))
    return null;
  const x = px(s.beating_revolutions),
    y = py(v);
  const text = `${fmt(v)} ${props.unit}`,
    w = text.length * 6.8 + 12;
  const otherCode: Material = s.material_code === "SW" ? "HW" : "SW";
  const perRev = props.xMax / plotInner.value;
  const otherY =
    props.material === "all"
      ? interpolateAt(
          props.curves[otherCode],
          s.beating_revolutions + (6 + w / 2) * perRev,
        )
      : null;
  const below = otherY === null ? y < plotH.value / 2 : otherY >= v;
  let ly = below ? y + 12 : y - 32;
  ly = Math.max(margin.value.t, Math.min(plotH.value - margin.value.b - 22, ly));
  const right = x + 6 + w <= plotWidth.value - margin.value.r;
  return { x: right ? x + 6 : x - 6 - w, y: ly, w, text };
});

const targetHits = computed(() =>
  props.isSr
    ? props.shownMaterials
        .map((code) => ({ code, x: props.reach[code] }))
        .filter((h): h is { code: Material; x: number } => h.x !== null)
    : [],
);
const reachMarks = computed(() => {
  const hits = targetHits.value
    .map((h) => ({ ...h, px: px(h.x), r: round100(h.x) }))
    .sort((a, b) => a.px - b.px);
  return hits.map((h, i) => {
    const label = `${number(h.r)} r`,
      w = label.length * 7 + 4;
    let anchor: "start" | "end" = hits.length > 1 && i === 0 ? "end" : "start";
    if (anchor === "start" && h.px + 6 + w > plotWidth.value - margin.value.r)
      anchor = "end";
    if (anchor === "end" && h.px - 6 - w < margin.value.l) anchor = "start";
    const lx = anchor === "start" ? h.px + 6 : h.px - 6;
    let ly = plotH.value - margin.value.b - 8;
    const sel = selLabel.value,
      x0 = anchor === "start" ? lx : lx - w;
    if (
      sel &&
      x0 < sel.x + sel.w &&
      x0 + w > sel.x &&
      ly - 12 < sel.y + 20 &&
      ly + 4 > sel.y
    )
      ly = sel.y - 7;
    return { ...h, label, anchor, lx, ly };
  });
});

const diamond = (x: number, y: number, s: number) =>
  `M${x},${y - s}L${x + s},${y}L${x},${y + s}L${x - s},${y}Z`;

const endLabels = computed(() => {
  if (!directLabels.value) return [];
  const labs = series.value
    .map((s) => {
      const last = s.points[s.points.length - 1];
      return last ? { code: s.code, y: py(value(last)!) } : null;
    })
    .filter((l): l is { code: Material; y: number } => l !== null)
    .sort((a, b) => a.y - b.y);
  const lo = margin.value.t + 6,
    hi = plotH.value - margin.value.b - 16;
  labs.forEach((l) => (l.y = Math.max(lo, Math.min(hi, l.y))));
  for (let k = 1; k < labs.length; k++)
    if (labs[k]!.y - labs[k - 1]!.y < 18) labs[k]!.y = labs[k - 1]!.y + 18;
  const last = labs[labs.length - 1];
  if (last && last.y > hi) {
    last.y = hi;
    for (let k = labs.length - 2; k >= 0; k--)
      if (labs[k + 1]!.y - labs[k]!.y < 18) labs[k]!.y = labs[k + 1]!.y - 18;
  }
  const x = plotWidth.value - margin.value.r + 12;
  return labs.map((l) => ({ ...l, x }));
});

const measuredRevs = computed(() =>
  [...new Set(props.valid.map((r) => r.beating_revolutions))].sort(
    (a, b) => a - b,
  ),
);

const hover = ref<{ revs: number; code: string } | null>(null);
const cursorRevs = computed(() => hover.value?.revs ?? null);

function nearestRow(event: MouseEvent): BeatingRow | null {
  const box = (event.currentTarget as SVGElement).getBoundingClientRect();
  const x = event.clientX - box.left,
    y = event.clientY - box.top;
  if (x < margin.value.l - 8 || x > plotWidth.value - margin.value.r + 8)
    return null;
  let best: number | null = null;
  for (const r of measuredRevs.value)
    if (best === null || Math.abs(px(r) - x) < Math.abs(px(best) - x)) best = r;
  if (best === null) return null;
  const candidates = props.shownMaterials.flatMap((code) =>
    props.byMaterial[code].filter(
      (r) => r.beating_revolutions === best && value(r) !== null,
    ),
  );
  return candidates.reduce<BeatingRow | null>(
    (a, b) =>
      !a || Math.abs(py(value(b)!) - y) < Math.abs(py(value(a)!) - y) ? b : a,
    null,
  );
}

function pointer(event: PointerEvent) {
  const r = nearestRow(event);
  hover.value = r
    ? { revs: r.beating_revolutions, code: r.canonical_code }
    : null;
}

function pickAt(event: MouseEvent) {
  if ((event.target as Element).closest(".plot-point")) return;
  const r = nearestRow(event);
  if (r) emit("select", r);
}

function focusPoint(r: BeatingRow) {
  emit("select", r);
  hover.value = { revs: r.beating_revolutions, code: r.canonical_code };
}

function blurPoint(r: BeatingRow) {
  if (hover.value?.code === r.canonical_code) hover.value = null;
}

function pointKey(event: KeyboardEvent, r: BeatingRow) {
  const own = props.byMaterial[r.material_code].filter((x) => value(x) !== null);
  const i = own.indexOf(r);
  let next: BeatingRow | undefined;
  if (event.key === "ArrowRight") next = own[i + 1];
  else if (event.key === "ArrowLeft") next = own[i - 1];
  else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    const other: Material = r.material_code === "SW" ? "HW" : "SW";
    if (props.shownMaterials.includes(other))
      next = props.byMaterial[other]
        .filter((x) => value(x) !== null)
        .reduce<BeatingRow | undefined>(
          (a, b) =>
            !a ||
            Math.abs(b.beating_revolutions - r.beating_revolutions) <
              Math.abs(a.beating_revolutions - r.beating_revolutions)
              ? b
              : a,
          undefined,
        );
  } else return;
  event.preventDefault();
  if (next)
    document
      .querySelector<SVGGElement>(`[data-point="${next.canonical_code}"]`)
      ?.focus();
}

const hoverPoint = computed(() => {
  const h = hover.value;
  const r = h
    ? (props.visible.find((x) => x.canonical_code === h.code) ?? null)
    : null;
  const v = r ? value(r) : null;
  if (!r || v === null) return null;
  return { row: r, v, x: px(r.beating_revolutions), y: py(v) };
});

const cursorRows = computed(() => {
  const revs = cursorRevs.value;
  if (revs === null) return [];
  return props.shownMaterials.map((code) => {
    const row =
      props.byMaterial[code].find((r) => r.beating_revolutions === revs) ?? null;
    const exact = row ? value(row) : null;
    if (exact !== null) return { code, value: exact, estimated: false };
    const est = interpolateAt(props.curves[code], revs);
    return { code, value: est, estimated: est !== null };
  });
});

const hotPoints = computed(() => {
  const revs = cursorRevs.value;
  if (revs === null) return [];
  return series.value.flatMap((s) =>
    s.points
      .filter((r) => r.beating_revolutions === revs)
      .map((r) => ({ code: s.code, x: px(revs), y: py(value(r)!) })),
  );
});

const hud = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  const xl = `${number(p.row.beating_revolutions)} r`,
    yl = fmt(p.v);
  const xw = xl.length * 6.4 + 12,
    yw = yl.length * 6.4 + 12;
  const cx = Math.max(
    margin.value.l + xw / 2,
    Math.min(plotWidth.value - margin.value.r - xw / 2, p.x),
  );
  return { xl, yl, xw, yw, cx, base: plotH.value - margin.value.b };
});

const tip = computed(() => {
  const p = hoverPoint.value;
  if (!p) return null;
  return {
    style: { "--x": `${p.x}px`, "--y": `${p.y}px` },
    left: p.x + 16 + 236 > plotWidth.value,
    below: p.y < 124,
  };
});

watch(
  () => [props.material, props.metricKey],
  () => {
    hover.value = null;
  },
);
</script>

<template>
  <section class="card beating-chart" aria-labelledby="beating-chart-title">
    <div class="beating-chart-head">
      <h2 id="beating-chart-title">{{ metricName }}随打浆转数的变化</h2>
      <p>纵轴：{{ metricName }}（{{ unit }}）</p>
    </div>
    <ul class="beating-legend" aria-label="图例">
      <li class="legend-title" aria-hidden="true">图例</li>
      <li v-for="code in shownMaterials" :key="code">
        <svg width="24" height="10" aria-hidden="true">
          <line
            x1="0"
            x2="24"
            y1="5"
            y2="5"
            :stroke="materialColor(code)"
            stroke-width="2"
            stroke-linecap="round"
          />
          <circle
            v-if="code === 'SW'"
            cx="12"
            cy="5"
            r="3.6"
            :fill="materialColor(code)"
          />
          <rect
            v-else
            x="8.6"
            y="1.6"
            width="6.8"
            height="6.8"
            rx="1.6"
            :fill="materialColor(code)"
          />
        </svg>
        {{ materialName(code) }}
      </li>
      <li v-if="isSr">
        <svg width="24" height="10" aria-hidden="true">
          <line x1="0" x2="24" y1="5" y2="5" class="target-key" />
        </svg>
        目标打浆度
      </li>
    </ul>
    <div v-if="!valid.length" class="beating-state beating-plot-state" role="status">
      当前原料没有该指标的有效数据，请切换指标或原料。
    </div>
    <div v-else ref="plotBox" class="plot-box">
      <svg
        class="beating-plot"
        role="group"
        :width="plotWidth"
        :height="plotH"
        :viewBox="`0 0 ${plotWidth} ${plotH}`"
        aria-label="打浆趋势图；可用Tab定位数据点，方向键切换，Enter选中样本"
        @pointermove="pointer"
        @pointerleave="hover = null"
        @click="pickAt"
      >
        <g class="grid">
          <line
            v-for="t in yTicks"
            :key="`gy${t}`"
            :x1="margin.l"
            :x2="plotWidth - margin.r"
            :y1="py(t)"
            :y2="py(t)"
          />
        </g>
        <g class="axis">
          <line
            :x1="margin.l"
            :x2="plotWidth - margin.r"
            :y1="plotH - margin.b"
            :y2="plotH - margin.b"
          />
          <g v-for="t in yTicks" :key="`ty${t}`">
            <text :x="margin.l - 10" :y="py(t) + 4" text-anchor="end">
              {{ number(t, t % 1 ? digits : 0) }}
            </text>
          </g>
          <g v-for="t in xTicks" :key="`tx${t}`">
            <line
              :x1="px(t)"
              :x2="px(t)"
              :y1="plotH - margin.b"
              :y2="plotH - margin.b + 5"
            />
            <text
              :x="px(t)"
              :y="plotH - margin.b + 20"
              :text-anchor="t === xMax && !directLabels ? 'end' : 'middle'"
            >
              {{ xTickLabel(t) }}
            </text>
          </g>
          <text class="axis-title" x="4" :y="margin.t - 16">
            {{ isGarden ? "↑ " : "" }}{{ metricName }} / {{ unit }}
          </text>
          <text
            class="axis-title"
            :x="plotWidth - margin.r"
            :y="plotH - 6"
            text-anchor="end"
          >
            打浆转数 / r{{ isGarden ? " →" : "" }}
          </text>
        </g>
        <g v-if="isSr" class="target">
          <line
            :x1="margin.l"
            :x2="plotWidth - margin.r"
            :y1="py(target)"
            :y2="py(target)"
          />
          <text
            class="target-t"
            :x="plotWidth - margin.r - 4"
            :y="py(target) - 7"
            text-anchor="end"
          >
            目标 {{ target }} °SR
          </text>
        </g>
        <g
          v-for="h in reachMarks"
          :key="`reach${h.code}`"
          class="reach"
          :style="{ '--c': materialColor(h.code) }"
        >
          <line
            class="reach-drop"
            :x1="h.px"
            :x2="h.px"
            :y1="py(target)"
            :y2="plotH - margin.b"
          />
          <path class="reach-dia" :d="diamond(h.px, py(target), 4.4)" />
          <circle class="reach-ring" :cx="h.px" :cy="py(target)" r="6.5" />
        </g>
        <g
          v-for="s in series"
          :key="s.code"
          class="series"
          :style="{ '--c': materialColor(s.code) }"
        >
          <path :d="s.path" class="line" />
          <g
            v-for="r in s.points"
            :key="r.canonical_code"
            class="plot-point"
            :data-point="r.canonical_code"
            :class="{
              on: selected?.canonical_code === r.canonical_code,
              out: !inRange(r),
            }"
            role="button"
            tabindex="0"
            :aria-label="`${r.canonical_code}，${r.beating_revolutions}转，${metricName}${value(r)} ${unit}，选中查看读数`"
            @click="emit('select', r)"
            @focus="focusPoint(r)"
            @blur="blurPoint(r)"
            @keydown="pointKey($event, r)"
            @keydown.enter.prevent="emit('openDetail', r)"
            @keydown.space.prevent="emit('openDetail', r)"
          >
            <circle
              class="hit"
              :cx="px(r.beating_revolutions)"
              :cy="py(value(r)!)"
              r="10"
            />
            <circle
              v-if="s.code === 'SW'"
              class="mark"
              :cx="px(r.beating_revolutions)"
              :cy="py(value(r)!)"
              r="4.2"
            />
            <rect
              v-else
              class="mark"
              :x="px(r.beating_revolutions) - 3.9"
              :y="py(value(r)!) - 3.9"
              width="7.8"
              height="7.8"
              rx="2"
            />
            <circle
              v-if="selected?.canonical_code === r.canonical_code"
              class="ring"
              :cx="px(r.beating_revolutions)"
              :cy="py(value(r)!)"
              r="10.5"
            />
            <title>
              {{ r.canonical_code }} ·
              {{ number(r.beating_revolutions) }} r · {{ metricName }}
              {{ fmt(value(r)) }} {{ unit }}
            </title>
          </g>
        </g>
        <g v-if="reachMarks.length" class="reach-labels" aria-hidden="true">
          <text
            v-for="h in reachMarks"
            :key="`reach-t${h.code}`"
            class="reach-t"
            :x="h.lx"
            :y="h.ly"
            :text-anchor="h.anchor"
          >
            {{ h.label }}
          </text>
        </g>
        <g v-if="endLabels.length" class="end-labels" aria-hidden="true">
          <g v-for="l in endLabels" :key="`end${l.code}`">
            <circle
              v-if="l.code === 'SW'"
              :cx="l.x"
              :cy="l.y"
              r="3.6"
              :fill="materialColor(l.code)"
            />
            <rect
              v-else
              :x="l.x - 3.4"
              :y="l.y - 3.4"
              width="6.8"
              height="6.8"
              rx="1.6"
              :fill="materialColor(l.code)"
            />
            <text :x="l.x + 9" :y="l.y + 4">{{ materialName(l.code) }}</text>
          </g>
        </g>
        <g v-if="selLabel && !hoverPoint" class="sel-label" aria-hidden="true">
          <rect
            :x="selLabel.x"
            :y="selLabel.y"
            :width="selLabel.w"
            height="20"
          />
          <text :x="selLabel.x + 6" :y="selLabel.y + 14">
            {{ selLabel.text }}
          </text>
        </g>
        <g v-if="hoverPoint" class="guide" aria-hidden="true">
          <line
            class="guide-l"
            :x1="hoverPoint.x"
            :x2="hoverPoint.x"
            :y1="margin.t"
            :y2="plotH - margin.b"
          />
          <g
            v-for="p in hotPoints"
            :key="`hot${p.code}`"
            :style="{ '--c': materialColor(p.code) }"
          >
            <circle v-if="p.code === 'SW'" class="hot" :cx="p.x" :cy="p.y" r="6" />
            <rect
              v-else
              class="hot"
              :x="p.x - 5.6"
              :y="p.y - 5.6"
              width="11.2"
              height="11.2"
              rx="2.5"
            />
          </g>
          <circle
            class="guide-focus"
            :cx="hoverPoint.x"
            :cy="hoverPoint.y"
            r="12"
          />
        </g>
        <g v-if="hoverPoint && hud" class="hud" aria-hidden="true">
          <line
            class="hud-l"
            :x1="hoverPoint.x"
            :x2="hoverPoint.x"
            :y1="margin.t"
            :y2="hud.base"
          />
          <line
            class="hud-l"
            :x1="margin.l"
            :x2="plotWidth - margin.r"
            :y1="hoverPoint.y"
            :y2="hoverPoint.y"
          />
          <path
            class="hud-tk"
            :d="`M${hoverPoint.x - 6},${hoverPoint.y}h12M${hoverPoint.x},${hoverPoint.y - 6}v12`"
          />
          <circle
            class="hud-ring"
            :cx="hoverPoint.x"
            :cy="hoverPoint.y"
            r="9"
          />
          <rect
            class="hud-box"
            :x="hud.cx - hud.xw / 2"
            :y="hud.base + 4"
            :width="hud.xw"
            height="17"
            rx="3"
          />
          <text
            class="hud-t"
            :x="hud.cx"
            :y="hud.base + 16.5"
            text-anchor="middle"
          >
            {{ hud.xl }}
          </text>
          <rect
            class="hud-box"
            :x="margin.l - 4 - hud.yw"
            :y="hoverPoint.y - 8.5"
            :width="hud.yw"
            height="17"
            rx="3"
          />
          <text
            class="hud-t"
            :x="margin.l - 10"
            :y="hoverPoint.y + 4"
            text-anchor="end"
          >
            {{ hud.yl }}
          </text>
        </g>
      </svg>
      <div
        class="beating-tip"
        :class="{ on: tip, left: tip?.left, below: tip?.below }"
        :style="tip?.style"
        role="status"
        aria-live="polite"
      >
        <template v-if="hoverPoint">
          <div class="tip-head">
            <b>{{ number(hoverPoint.row.beating_revolutions) }} r</b
            ><span>{{ hoverPoint.row.canonical_code }}</span>
          </div>
          <div v-for="c in cursorRows" :key="c.code" class="tip-row">
            <span
              ><i class="mk" :class="`mk-${c.code}`"></i
              >{{ materialName(c.code) }}</span
            ><b>{{
              c.value === null
                ? "该转数无实测"
                : `${c.estimated ? "≈ " : ""}${fmt(c.value)}`
            }}</b>
          </div>
          <div class="tip-foot">
            {{ metricName }} / {{ unit
            }}<template v-if="cursorRows.some((c) => c.estimated)">
              · ≈ 为相邻实测点插值</template
            >
          </div>
        </template>
      </div>
    </div>
    <p class="beating-hint">
      移到曲线上逐个转数读数；点击或用 Tab 选中数据点，方向键切换，Enter
      打开样本来源。
    </p>
    <p class="caveat beating-note">
      线段仅连接相邻有效观测，不作拟合或因果推断。缺失值断开显示；不同指标的纵轴范围独立计算。<template
        v-if="isSr"
        >“达到目标”的转数是相邻两个实测点之间的线性插值估算。</template
      >
    </p>
  </section>
</template>

<style scoped>
.beating-chart {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "head" "plot" "legend" "hint" "note";
  align-content: start;
  padding: 22px;
}
.beating-chart-head {
  grid-area: head;
  margin-bottom: 14px;
}
.beating-chart-head h2 {
  font-size: 17px;
}
.beating-chart-head p {
  font-size: 13px;
  color: var(--text-2);
  margin-top: 6px;
}
.beating-legend {
  grid-area: legend;
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
  font-size: 12.5px;
  color: var(--text-2);
}
.beating-legend li {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.legend-title {
  color: var(--text-3);
  font-size: 11px;
}
.target-key {
  stroke: var(--chart-target);
  stroke-width: 1.4;
  stroke-dasharray: 3 3;
}
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.plot-box,
.beating-plot-state {
  grid-area: plot;
}
.plot-box {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow-x: clip;
}
.beating-plot {
  display: block;
  touch-action: pan-y;
}
.beating-plot text {
  font: 400 11px var(--font-mono);
  fill: var(--chart-text);
}
.beating-plot .axis-title {
  font-family: var(--font-body);
  font-size: 12px;
}
.grid line {
  stroke: var(--chart-grid);
  shape-rendering: crispEdges;
}
.axis line {
  stroke: var(--chart-axis);
  shape-rendering: crispEdges;
}
.line {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.mark {
  fill: var(--c);
  stroke: var(--chart-paper);
  stroke-width: 2;
  paint-order: stroke;
}
.hit {
  fill: transparent;
}
.plot-point {
  cursor: pointer;
}
.plot-point:focus {
  outline: none;
}
.plot-point:focus-visible .hit {
  stroke: var(--focus);
  stroke-width: 2.5;
}
.plot-point.out .mark {
  opacity: 0.25;
}
.ring {
  fill: none;
  stroke: var(--text);
  stroke-width: 1.5;
  stroke-dasharray: 2 3;
}
.target line {
  stroke: var(--chart-target);
  stroke-width: 1;
  stroke-dasharray: 4 5;
}
.beating-plot .target-t {
  fill: var(--text);
}
.reach-drop {
  stroke: var(--c);
  stroke-width: 1.3;
  stroke-dasharray: 2 4;
  opacity: 0.7;
}
.reach-dia {
  fill: var(--text);
}
.reach-ring {
  display: none;
  fill: var(--chart-paper);
  stroke: var(--c);
  stroke-width: 2.2;
}
.beating-plot .reach-t {
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--chart-paper);
  stroke-width: 4px;
  stroke-linejoin: round;
}
.beating-plot .end-labels text {
  font: 400 12.5px var(--font-body);
  fill: var(--text);
}
.sel-label rect {
  fill: var(--surface);
  stroke: var(--line-strong);
  rx: 3px;
}
.beating-plot .sel-label text {
  fill: var(--text);
  font-weight: 500;
}
.guide,
.hud {
  display: none;
  pointer-events: none;
}
.hud-l {
  stroke: var(--text-2);
  stroke-opacity: 0.55;
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.hud-tk {
  stroke: var(--text);
  stroke-width: 1;
  fill: none;
}
.hud-ring {
  fill: none;
  stroke: var(--text);
  stroke-width: 1.5;
}
.hud-box {
  fill: var(--surface);
  stroke: var(--line-strong);
  stroke-width: 1;
}
.beating-plot .hud-t {
  font-size: 10.5px;
  fill: var(--text);
}
.guide-l {
  stroke: var(--chart-guide);
  stroke-dasharray: 3 4;
}
.hot {
  fill: var(--c);
  stroke: var(--chart-paper);
  stroke-width: 2.5;
}
.guide-focus {
  fill: none;
  stroke: var(--text);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}
.beating-tip {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 5;
  min-width: 168px;
  max-width: 240px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  box-shadow: var(--shadow-pop);
  pointer-events: none;
  opacity: 0;
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) - 100% - 12px));
  transition: opacity 0.12s;
}
.beating-tip.left {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) - 100% - 12px));
}
.beating-tip.below {
  transform: translate(calc(var(--x, 0px) + 16px), calc(var(--y, 0px) + 16px));
}
.beating-tip.left.below {
  transform: translate(calc(var(--x, 0px) - 100% - 16px), calc(var(--y, 0px) + 16px));
}
.beating-tip.on {
  opacity: 1;
}
.tip-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.tip-head b {
  font-weight: 500;
  font-size: 12px;
  color: var(--text);
}
.tip-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
}
.tip-row span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-2);
}
.tip-row b {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.tip-foot {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-3);
}
.beating-hint {
  grid-area: hint;
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--text-3);
}
.beating-note {
  grid-area: note;
  margin-top: 12px;
}

:root[data-mode="polarized"] .hud {
  display: inline;
}
:root[data-mode="polarized"] .line {
  opacity: 0.95;
}
:root[data-mode="polarized"] .beating-tip {
  border-radius: 12px;
  background: var(--surface-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
:root[data-mode="polarized"] .beating-legend {
  margin-top: 14px;
}

:root[data-mode="garden"] .beating-chart {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto auto 1fr;
  grid-template-areas: "head legend" "plot plot" "hint hint" "note note";
  padding: 22px 24px;
}
:root[data-mode="garden"] .beating-chart .beating-note {
  align-self: end;
}
:root[data-mode="garden"] .beating-chart-head h2 {
  font-size: 19px;
}
:root[data-mode="garden"] .beating-legend {
  margin: 4px 0 0;
  align-self: start;
  justify-content: flex-end;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="garden"] .legend-title {
  color: var(--text-2);
}
:root[data-mode="garden"] .beating-plot .axis-title {
  font-size: 11.5px;
  fill: var(--text-2);
}
:root[data-mode="garden"] .line {
  stroke-width: 2.2;
}
:root[data-mode="garden"] .ring {
  stroke: var(--c);
  stroke-width: 2;
  stroke-dasharray: 3 3;
}
:root[data-mode="garden"] .target line,
:root[data-mode="garden"] .target-key {
  stroke-width: 1.4;
  stroke-dasharray: 6 5;
}
:root[data-mode="garden"] .beating-plot .target-t {
  font: 400 12px var(--font-body);
}
:root[data-mode="garden"] .reach-drop {
  stroke-width: 1.4;
  opacity: 1;
}
:root[data-mode="garden"] .reach-dia {
  display: none;
}
:root[data-mode="garden"] .reach-ring {
  display: inline;
}
:root[data-mode="garden"] .beating-plot .reach-t {
  font-size: 11.5px;
}
:root[data-mode="garden"] .sel-label rect {
  fill: var(--chart-paper);
  stroke: var(--accent);
  rx: 10px;
}
:root[data-mode="garden"] .beating-plot .sel-label text {
  fill: var(--accent-ink);
}
:root[data-mode="garden"] .guide {
  display: inline;
}
:root[data-mode="garden"] .beating-tip {
  padding: 10px 13px;
  border: 0;
  border-radius: 16px;
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow);
  transition:
    opacity 0.18s,
    transform 0.18s var(--ease);
}
:root[data-mode="garden"] .tip-head {
  font-family: var(--font-body);
}
:root[data-mode="garden"] .tip-head b {
  font-family: var(--font-mono);
}
:root[data-mode="garden"] .beating-hint {
  color: var(--text-2);
  font-size: 13px;
}
:root[data-mode="garden"] .beating-note {
  margin-top: 10px;
}

@media (max-width: 720px) {
  .beating-chart {
    padding: 16px;
  }
  :root[data-mode="garden"] .beating-chart {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "head" "legend" "plot" "hint" "note";
  }
  :root[data-mode="garden"] .beating-legend {
    justify-content: flex-start;
    margin-bottom: 8px;
  }
}
</style>
