<script setup lang="ts">
import { Download } from "lucide-vue-next";
import { number } from "../../api";
import { materialColor, materialName, type BeatingRow, type Material } from "./types";

const props = defineProps<{
  shownMaterials: Material[];
  listedBy: (code: Material) => BeatingRow[];
  listedCount: number;
  metricKey: string;
  metricName: string;
  unit: string;
  digits: number;
  isSr: boolean;
  target: number;
  selected: BeatingRow | null;
  checked: Set<string>;
  allChecked: boolean;
  someChecked: boolean;
  exportCount: number;
  srRange: { lo: number; hi: number };
  valueBar: (v: number | null) => number;
  deltaOf: (r: BeatingRow) => { d: number; estimated: boolean } | null;
  deltaMax: number;
}>();

const emit = defineEmits<{
  select: [row: BeatingRow];
  openDetail: [row: BeatingRow];
  toggle: [code: string, on: boolean];
  toggleAll: [on: boolean];
  exportCsv: [];
  resetRange: [];
}>();

const value = (r: BeatingRow): number | null =>
  typeof r[props.metricKey] === "number" && Number.isFinite(r[props.metricKey])
    ? (r[props.metricKey] as number)
    : null;

const signed = (d: number) =>
  `${d > 0 ? "+" : d < 0 ? "−" : ""}${number(Math.abs(d), props.digits)}`;
</script>

<template>
  <section class="card beating-table" aria-labelledby="beating-table-title">
    <div class="beating-table-head">
      <div>
        <h2 id="beating-table-title">
          实验明细 <span class="quiet-tag">{{ listedCount }}</span>
        </h2>
        <p>
          按原料分组、打浆转数升序；“—”表示缺失；“≈”表示另一种原料在该转数无实测、按插值比较。
        </p>
      </div>
      <div class="table-actions">
        <span class="checked-n">已勾选 {{ checked.size }}</span>
        <button
          class="button"
          type="button"
          :disabled="!listedCount"
          @click="emit('exportCsv')"
        >
          <Download :size="15" />{{
            exportCount === listedCount
              ? "导出筛选结果"
              : `导出已勾选 ${exportCount} 条`
          }}（CSV）
        </button>
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
            <th class="check-cell">
              <input
                type="checkbox"
                class="check"
                aria-label="勾选当前筛选的全部样本"
                :checked="allChecked"
                :indeterminate="someChecked"
                @change="
                  emit('toggleAll', ($event.target as HTMLInputElement).checked)
                "
              />
            </th>
            <th>样本编码</th>
            <th class="numeric">打浆转数 / r</th>
            <th class="value-head">{{ metricName }} / {{ unit }}</th>
            <th class="numeric">较另一种原料（同转数）</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody v-for="code in shownMaterials" :key="code">
          <tr
            v-if="listedBy(code).length"
            class="group-row"
            :class="`group-${code}`"
          >
            <td colspan="6">
              <i class="mk" :class="`mk-${code}`"></i
              ><strong>{{ materialName(code) }}</strong
              ><span>{{ listedBy(code).length }} 个样本</span>
            </td>
          </tr>
          <tr
            v-for="r in listedBy(code)"
            :key="r.canonical_code"
            :data-code="r.canonical_code"
            :class="{ on: selected?.canonical_code === r.canonical_code }"
            @click="emit('select', r)"
          >
            <td class="check-cell" @click.stop>
              <input
                type="checkbox"
                class="check"
                :aria-label="`勾选 ${r.canonical_code}`"
                :checked="checked.has(r.canonical_code)"
                @change="
                  emit(
                    'toggle',
                    r.canonical_code,
                    ($event.target as HTMLInputElement).checked,
                  )
                "
              />
            </td>
            <td>
              <button class="sample-code" @click.stop="emit('openDetail', r)">
                {{ r.canonical_code }}
              </button>
            </td>
            <td class="numeric">{{ number(r.beating_revolutions) }}</td>
            <td class="value-cell">
              <div class="value-wrap">
                <span class="numeric">{{ number(value(r), 4) }}</span>
                <span class="value-bar" aria-hidden="true"
                  ><i
                    :style="{
                      width: `${valueBar(value(r))}%`,
                      background: materialColor(code),
                    }"
                  ></i
                  ><b
                    v-if="isSr"
                    :style="{ left: `${valueBar(target)}%` }"
                  ></b
                ></span>
              </div>
            </td>
            <td class="delta-cell">
              <template v-if="deltaOf(r)"
                ><span
                  class="delta-value"
                  :title="
                    deltaOf(r)!.estimated
                      ? '另一种原料在该转数无实测，按相邻实测点线性插值'
                      : '两种原料在该转数都有实测'
                  "
                  >{{ deltaOf(r)!.estimated ? "≈" : ""
                  }}{{ signed(deltaOf(r)!.d) }}</span
                ><svg width="64" height="10" aria-hidden="true">
                  <line x1="32" x2="32" y1="0" y2="10" class="mid" />
                  <rect
                    :x="
                      deltaOf(r)!.d < 0
                        ? 32 - (Math.abs(deltaOf(r)!.d) / deltaMax) * 30
                        : 32
                    "
                    y="2.5"
                    :width="(Math.abs(deltaOf(r)!.d) / deltaMax) * 30"
                    height="5"
                    rx="1.5"
                    :fill="materialColor(code)"
                  /></svg
              ></template>
              <span v-else class="delta-none">—</span>
            </td>
            <td>
              <button
                class="text-button detail-link"
                @click.stop="emit('openDetail', r)"
              >
                查看详情
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!listedCount" class="beating-state">
      <p>没有打浆度在 {{ srRange.lo }}–{{ srRange.hi }} °SR 之间的样本。</p>
      <button class="button" type="button" @click="emit('resetRange')">
        重置区间
      </button>
    </div>
  </section>
</template>

<style scoped>
.beating-table {
  padding: 22px 22px 8px;
}
.beating-state {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-2);
}
.beating-state p {
  margin: 14px 0;
}
.beating-table-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 14px;
}
.beating-table-head h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
}
.beating-table-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-2);
}
.table-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: var(--text-2);
}
.check-cell {
  width: 40px;
  padding-right: 0;
}
.check {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--accent);
  cursor: pointer;
}
.delta-cell {
  text-align: right;
  white-space: nowrap;
}
.delta-cell svg {
  vertical-align: middle;
  margin-left: 10px;
}
.delta-cell .mid {
  stroke: var(--line-strong);
}
.delta-value {
  font: 500 13px var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.delta-none {
  color: var(--text-3);
}
.group-row td {
  height: 36px;
  padding-top: 6px;
  padding-bottom: 6px;
  color: var(--text);
  background: var(--surface-2);
}
.group-row td > * {
  vertical-align: middle;
}
.group-row .mk {
  margin-right: 9px;
}
.group-row strong {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.group-row span {
  margin-left: 10px;
  font: 400 12px var(--font-mono);
  color: var(--text-2);
}
tbody tr.on td {
  background: var(--accent-tint);
}
tbody tr.on td:first-child {
  box-shadow: inset 2px 0 0 var(--accent);
}
tbody tr:not(.group-row) {
  cursor: pointer;
}
.value-head,
.value-cell {
  padding-left: 24px;
}
.value-wrap {
  display: flex;
  align-items: center;
  gap: 14px;
}
.value-wrap .numeric {
  min-width: 64px;
}
.value-bar {
  position: relative;
  flex: 1;
  min-width: 80px;
  max-width: 240px;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.value-bar i {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  opacity: 0.9;
}
.value-bar b {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 1px;
  background: var(--text-2);
}

:root[data-mode="polarized"] .group-row td {
  background: var(--surface-2);
}
:root[data-mode="polarized"] .group-row strong {
  font-weight: 500;
}

:root[data-mode="garden"] .beating-table {
  padding: 22px 24px 24px;
}
:root[data-mode="garden"] .beating-table-head h2 {
  font-size: 19px;
}
:root[data-mode="garden"] .beating-table .table-scroll {
  max-height: 560px;
  border-radius: 18px;
  background: var(--surface-glass);
  box-shadow: inset 0 0 0 1px var(--line-soft);
}
:root[data-mode="garden"] .group-row td {
  background: linear-gradient(90deg, var(--sw-tint), var(--surface) 70%);
}
:root[data-mode="garden"] .group-HW td {
  background: linear-gradient(90deg, var(--hw-tint), var(--surface) 70%);
}
:root[data-mode="garden"] .group-row strong {
  font-weight: 500;
}
:root[data-mode="garden"] tbody tr.on td {
  background: var(--bl-tint);
}
:root[data-mode="garden"] tbody tr.on td:first-child {
  box-shadow: inset 3px 0 0 var(--bl);
}
:root[data-mode="garden"] .detail-link {
  padding: 4px 11px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  background: var(--surface);
  box-shadow:
    inset 0 0 0 1px var(--line),
    var(--shadow-sm);
}
:root[data-mode="garden"] .detail-link:hover {
  text-decoration: none;
  color: var(--accent-ink);
}

@media (max-width: 980px) {
  :root[data-mode="garden"] .beating-table .table-scroll {
    max-height: none;
  }
}
@media (max-width: 720px) {
  .beating-table {
    padding: 16px;
  }
  .table-actions .checked-n {
    display: none;
  }
  .value-bar {
    display: none;
  }
}
</style>
