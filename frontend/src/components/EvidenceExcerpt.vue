<script setup lang="ts">
import { computed } from 'vue';
import EvidenceMath from './EvidenceMath.vue';

const props = defineProps<{ text: string }>();
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
  <div class="evidence-excerpt">
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
.evidence-excerpt { margin: 16px 0; min-width: 0; font-size: 13px; line-height: 1.75; }
.source-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.table-scroll { max-width: 100%; overflow-x: auto; margin: 12px 0; border: 1px solid var(--border, #ded8ce); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; text-align: left; background: var(--surface, #fff); }
th, td { padding: 9px 12px; border: 1px solid var(--border, #ded8ce); min-width: 80px; white-space: pre-wrap; overflow-wrap: anywhere; }
th, td[colspan]:not([colspan="1"]) { font-weight: 600; background: rgba(128, 128, 128, .07); }
</style>
