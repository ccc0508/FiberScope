<script setup lang="ts">
import { computed } from 'vue';
import EvidenceMath from './EvidenceMath.vue';
import { cellText, parseQueryExcerpt, timeLabel } from '../literature';

const props = defineProps<{
  text: string;
  /** an experiment-database citation: show its SQL snapshot as a table (raw JSON stays one click away) */
  query?: boolean;
  /** citation token, e.g. "[1]", for the accessible names of the query regions */
  label?: string;
}>();
const snapshot = computed(() => (props.query ? parseQueryExcerpt(props.text) : null));
const unitOf = (column: string) => snapshot.value?.fields.find((f) => f.name === column)?.unit ?? null;
// Parse table structure only. Never insert source HTML into the live document:
// cells are rendered through Vue text interpolation, without source attributes.
const parts = computed(() => props.text.split(/(<table\b[^>]*>[\s\S]*?<\/table\s*>)/gi).filter(Boolean).map(text => {
  if (!/^<table\b/i.test(text)) return { text, rows: null };
  const template = document.createElement('template');
  template.innerHTML = text;
  const table = template.content.querySelector('table');
  if (!table) return { text, rows: null };
  const span = (value: string | null) => Math.min(100, Math.max(1, Number.parseInt(value ?? '1', 10) || 1));
  const rows = Array.from(table.rows).map(row => Array.from(row.cells).map(cell => ({
    text: cell.textContent ?? '',
    colspan: span(cell.getAttribute('colspan')),
    rowspan: span(cell.getAttribute('rowspan')),
    header: cell.tagName === 'TH',
  })));
  return rows.length ? { text: '', rows } : { text, rows: null };
}));
</script>

<template>
  <div v-if="snapshot" class="evidence-excerpt evidence-query">
    <p class="eq-meta">
      <span class="nw">{{ snapshot.views.join(' · ') || '实验数据库' }} ·</span>
      <span class="nw">{{ snapshot.rowCount ?? snapshot.rows.length }} 行<template v-if="snapshot.truncated"> · 结果已截断</template><template v-if="snapshot.queriedAt"> ·</template></span
      ><span v-if="snapshot.queriedAt" class="nw">查询于 {{ timeLabel(snapshot.queriedAt) }}</span>
    </p>
    <span class="field-label">查询结果</span>
    <div class="table-scroll eq-table" tabindex="0" role="region" :aria-label="`${label ?? ''} 查询结果，可横向滚动`.trim()">
      <table>
        <thead>
          <tr>
            <th v-for="column in snapshot.columns" :key="column" scope="col">
              {{ column }}<small v-if="unitOf(column)">（{{ unitOf(column) }}）</small>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in snapshot.rows" :key="r">
            <td v-for="(cell, k) in row" :key="k" :class="{ numeric: typeof cell === 'number' }">{{ cellText(cell) }}</td>
          </tr>
          <tr v-if="!snapshot.rows.length">
            <td :colspan="Math.max(1, snapshot.columns.length)">查询未返回数据行</td>
          </tr>
        </tbody>
      </table>
    </div>
    <template v-if="snapshot.sql">
      <span class="field-label">SQL</span>
      <pre class="eq-sql"><code>{{ snapshot.sql }}</code></pre>
    </template>
    <template v-if="snapshot.fields.length">
      <span class="field-label">字段说明</span>
      <dl class="eq-fields">
        <div v-for="(field, f) in snapshot.fields" :key="f">
          <dt>{{ field.name || '—' }}</dt>
          <dd>{{ field.description || '—' }}<span v-if="field.unit" class="eq-unit">单位 {{ field.unit }}</span></dd>
        </div>
      </dl>
    </template>
    <details class="eq-raw">
      <summary>查看原始 JSON</summary>
      <pre>{{ text }}</pre>
    </details>
  </div>
  <div v-else class="evidence-excerpt">
    <template v-for="(part, index) in parts" :key="index">
      <div v-if="part.rows" class="table-scroll" tabindex="0" role="region" aria-label="论文原文表格，可横向滚动">
        <table>
          <tbody>
            <tr v-for="(row, rowIndex) in part.rows" :key="rowIndex">
              <component :is="cell.header ? 'th' : 'td'" v-for="(cell, cellIndex) in row" :key="cellIndex"
                :colspan="cell.colspan" :rowspan="cell.rowspan"><EvidenceMath :text="cell.text" /></component>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="source-text"><EvidenceMath :text="part.text" /></div>
    </template>
  </div>
</template>

<style scoped>
.evidence-excerpt { min-width: 0; font-size: 13px; line-height: 1.75; color: var(--text-2); }
.source-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.table-scroll {
  max-width: 100%;
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-xs);
}
table { border-collapse: collapse; width: 100%; text-align: left; background: var(--surface); font-size: 12.5px; }
th, td {
  height: auto;
  padding: 8px 12px;
  border: 1px solid var(--line-soft);
  min-width: 80px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--text);
  vertical-align: top;
}
/* paper tables come as plain <td>; a spanning cell is a section label (e.g. "Dependent Variables") */
th, td[colspan]:not([colspan="1"]) {
  position: static;
  font-weight: 600;
  color: var(--text);
  background: var(--surface-2);
}
:root[data-mode="polarized"] th,
:root[data-mode="polarized"] td[colspan]:not([colspan="1"]) {
  font-family: var(--font-body);
  font-size: 12.5px;
  letter-spacing: 0;
  background: color-mix(in srgb, var(--text) 5%, var(--surface));
}

/* ------------------------------------------------ experiment database snapshot */
.evidence-query { display: grid; gap: 8px; }
.evidence-query .field-label { margin: 4px 0 0; }
.nw { white-space: nowrap; }
.eq-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0 6px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-3);
}
.eq-table { max-height: 260px; margin: 0; overflow: auto; }
.eq-table th,
.eq-table td {
  min-width: 0;
  white-space: nowrap;
  border-width: 0 0 1px;
  border-color: var(--line-soft);
}
.eq-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  font-family: var(--font-mono);
  font-weight: 500;
  font-size: 11.5px;
  color: var(--text-2);
  background: var(--surface);
  border-bottom-color: var(--line);
}
:root[data-mode="polarized"] .eq-table th {
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: var(--surface);
}
.eq-table th small {
  margin-left: 2px;
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
}
.eq-table td.numeric { text-align: right; font-family: var(--font-mono); }
.eq-sql {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
:root[data-mode="polarized"] .eq-sql {
  background: color-mix(in srgb, var(--bg) 60%, transparent);
  border: 1px solid var(--line-soft);
}
.eq-fields { display: grid; gap: 6px; margin: 0; }
.eq-fields > div {
  display: grid;
  grid-template-columns: minmax(96px, auto) minmax(0, 1fr);
  gap: 2px 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--text) 3%, transparent);
}
/* --k-ink comes from the citation card (gold in polarized, green in garden), else plain text */
.eq-fields dt {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--k-ink, var(--text));
  overflow-wrap: anywhere;
}
.eq-fields dd { margin: 0; font-size: 12.5px; line-height: 1.6; color: var(--text-2); }
.eq-unit { display: inline-block; margin-left: 8px; font-size: 11.5px; color: var(--text-3); }
.eq-raw summary {
  width: fit-content;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--text-2);
  border-radius: var(--radius-xs);
}
.eq-raw summary:hover { color: var(--text); }
.eq-raw pre {
  margin: 8px 0 0;
  max-height: 320px;
  overflow: auto;
  padding: 10px 12px;
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
@media (max-width: 720px) {
  .eq-fields > div { grid-template-columns: minmax(0, 1fr); }
}
</style>
