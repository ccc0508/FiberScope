<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { ChevronDown, Download, History, RefreshCw, Search } from "lucide-vue-next";
import { literatureRequest, secondsLabel, stateNames, timeLabel, type HistoryItem } from "../literature";
import { apiPath } from "../urls";

const props = defineProps<{ selected?: string }>();
const emit = defineEmits<{ select: [id: string]; ready: [latest?: HistoryItem] }>();
const items = ref<HistoryItem[]>([]), search = ref(""), page = ref(1), total = ref(0), pages = ref(0);
const loading = ref(false), error = ref("");
let controller: AbortController | undefined;
let disposed = false;
async function refresh(initial = false) {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  const timer = window.setTimeout(() => current.abort(), 15000);
  try {
    const query = new URLSearchParams({ page: String(page.value), page_size: "5", q: search.value });
    const result = await literatureRequest<{ data: HistoryItem[]; pagination: { total: number; total_pages: number } }>(`history?${query}`, undefined, current.signal);
    if (current.signal.aborted || disposed) return;
    items.value = result.data;
    total.value = result.pagination.total;
    pages.value = result.pagination.total_pages;
    if (initial) emit("ready", items.value[0]);
  } catch (e) {
    if (disposed || controller !== current) return;
    error.value = current.signal.aborted ? "历史读取超时，请重试。" : e instanceof Error ? e.message : "历史读取失败。";
  } finally {
    clearTimeout(timer);
    if (controller === current) loading.value = false;
  }
}
function find() { page.value = 1; refresh(); }
function move(offset: number) { page.value += offset; refresh(); }
function download() {
  error.value = "";
  try {
    window.location.assign(apiPath("literature/history/export"));
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : "导出失败。"; }
}
defineExpose({ refresh });
onBeforeUnmount(() => { disposed = true; controller?.abort(); });
refresh(true);
</script>

<template>
  <details class="card history-panel" open>
    <summary>
      <History class="lh-icon" :size="17" aria-hidden="true" />
      <span class="lh-title">问答历史</span>
      <span class="lh-count">{{ total }} 条</span>
      <ChevronDown class="lh-chevron" :size="17" aria-hidden="true" />
    </summary>
    <p class="history-note">记录长期保存在服务器，所有访问者均可查看和导出。清除 Cookie 或更换浏览器不影响查看。</p>
    <div class="history-tools">
      <form class="lh-search" role="search" @submit.prevent="find">
        <Search :size="15" aria-hidden="true" />
        <input v-model="search" aria-label="搜索历史问题" placeholder="搜索问题" maxlength="200" />
        <button class="lh-go" :disabled="loading">搜索</button>
      </form>
      <button class="button lh-export" :disabled="loading" @click="download"><Download :size="14" />导出全部记录</button>
    </div>
    <div v-if="error" class="history-error" role="alert"><p>{{ error }}</p> <button class="button" :disabled="loading" @click="refresh(true)">重试</button></div>
    <p v-else-if="loading && !items.length" class="history-state" role="status">正在读取历史…</p>
    <p v-else-if="!items.length" class="history-state">{{ search ? "没有匹配的问题。" : "暂无记录，开始提问后会自动保存。" }}</p>
    <ol v-else class="history-list" :class="{ refreshing: loading }" :aria-busy="loading">
      <li v-for="item in items" :key="item.id">
        <button
          type="button"
          :class="['history-row', { selected: props.selected === item.id }]"
          :aria-current="props.selected === item.id ? 'true' : undefined"
          @click="emit('select', item.id)"
        >
          <span class="lh-q">{{ item.question }}</span>
          <span class="lh-meta"
            ><span class="lh-state" :class="`s-${item.status}`"><i aria-hidden="true"></i>{{ stateNames[item.status] }}</span
            ><span class="nw"><span class="lh-sep">· </span>{{ timeLabel(item.created_at) }}</span
            ><span v-if="item.latency_ms != null" class="nw"><span class="lh-sep">· </span>用时 {{ secondsLabel(item.latency_ms) }}</span></span
          >
        </button>
      </li>
    </ol>
    <div class="history-pagination">
      <button class="button" :disabled="loading || page <= 1" @click="move(-1)">上一页</button
      ><span class="lh-page">{{ page }} / {{ Math.max(1, pages) }}</span
      ><button class="button" :disabled="loading || page >= pages" @click="move(1)">下一页</button
      ><button class="button lh-refresh" :disabled="loading" @click="refresh()">
        <RefreshCw :size="13" :class="{ spinning: loading }" aria-hidden="true" />刷新历史
      </button>
    </div>
  </details>
</template>

<style scoped>
/* v1 side card (dark HUD list) / v4 glass history tile with pill rows */
.history-panel {
  padding: 22px;
  min-width: 0;
}
:root[data-mode="garden"] .history-panel {
  padding: 22px 24px;
}
summary {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 10px;
  padding-right: 30px;
  cursor: pointer;
  list-style: none;
  border-radius: var(--radius-xs);
}
summary::-webkit-details-marker {
  display: none;
}
.lh-icon {
  align-self: center;
  color: var(--text-3);
}
.lh-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
:root[data-mode="garden"] .lh-icon {
  display: none;
}
:root[data-mode="garden"] .lh-title {
  font-size: 19px;
  font-weight: 500;
  letter-spacing: 0.03em;
}
.lh-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
:root[data-mode="polarized"] .lh-count {
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
}
:root[data-mode="garden"] .lh-count {
  font-size: 14px;
}
.lh-chevron {
  position: absolute;
  right: 0;
  top: 2px;
  color: var(--text-2);
  transition: transform 0.25s var(--ease);
}
.history-panel:not([open]) .lh-chevron {
  transform: rotate(-90deg);
}
.history-note,
.history-state {
  margin-top: 8px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.history-state {
  margin: 16px 0 4px;
  color: var(--text-3);
}

/* ------------------------------------------------ search + export */
.history-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 14px 0 12px;
}
.lh-search {
  flex: 1 1 200px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 38px;
  padding: 0 4px 0 12px;
  color: var(--text-3);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
.lh-search input {
  flex: 1;
  min-width: 0;
  padding: 8px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}
.lh-search input::placeholder {
  color: var(--text-3);
}
.lh-search input:focus-visible {
  outline: none;
}
.lh-search:has(input:focus-visible) {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 28%, transparent);
}
.lh-go {
  flex-shrink: 0;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  white-space: nowrap;
  transition: background 0.2s;
}
.lh-go:focus-visible {
  outline-offset: 1px;
}
.lh-export {
  flex-shrink: 0;
}
:root[data-mode="polarized"] .lh-search {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .lh-search:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .lh-go {
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
:root[data-mode="polarized"] .lh-go:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 13%, transparent);
}
:root[data-mode="polarized"] .lh-export {
  min-height: 38px;
  padding: 0 12px;
  font-size: 13px;
}
:root[data-mode="garden"] .lh-search {
  border: 1px solid transparent;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
:root[data-mode="garden"] .lh-go {
  background: var(--accent-tint);
}
:root[data-mode="garden"] .lh-go:hover:not(:disabled) {
  background: color-mix(in oklab, var(--accent) 16%, var(--surface));
}
:root[data-mode="garden"] .lh-export {
  min-height: 34px;
  font-size: 13px;
}

/* ------------------------------------------------ rows */
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  transition: opacity 0.2s;
}
.history-list.refreshing {
  opacity: 0.6;
}
.history-row {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid transparent;
  text-align: left;
  color: var(--text);
  transition:
    background 0.2s,
    border-color 0.2s,
    box-shadow 0.25s;
}
.lh-q {
  font-size: 13px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.lh-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.nw {
  white-space: nowrap;
}
.lh-state {
  --st: var(--text-3);
  --st-tint: var(--surface-2);
  --st-ink: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-body);
  white-space: nowrap;
}
.lh-state i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--st);
}
.lh-state.s-answered {
  --st: var(--ok);
  --st-tint: var(--ok-tint);
  --st-ink: var(--ok);
}
.lh-state.s-refused {
  --st: var(--warn);
  --st-tint: var(--warn-tint);
  --st-ink: var(--warn);
}
.lh-state.s-failed,
.lh-state.s-interrupted {
  --st: var(--bad);
  --st-tint: var(--bad-tint);
  --st-ink: var(--bad);
}
.lh-state.s-processing {
  --st: var(--accent);
  --st-tint: var(--accent-tint);
  --st-ink: var(--accent-ink);
}
.lh-state.s-processing i {
  animation: lh-pulse 1s ease-in-out infinite alternate;
}
@keyframes lh-pulse {
  to {
    opacity: 0.3;
  }
}
/* v1 .hist-i: transparent rows, a hairline frame on the open record */
:root[data-mode="polarized"] .history-row:hover {
  background: color-mix(in srgb, var(--text) 4%, transparent);
}
:root[data-mode="polarized"] .history-row.selected {
  border-color: var(--line-strong);
  background: color-mix(in srgb, var(--text) 5%, transparent);
  box-shadow: inset 2px 0 0 var(--accent);
}
/* v4 .hist: glass pills, the open record white with a lilac ring, status as a badge */
:root[data-mode="garden"] .history-list {
  gap: 8px;
}
:root[data-mode="garden"] .history-row {
  padding: 12px 14px;
  border: 0;
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .history-row:hover {
  background: var(--surface);
}
:root[data-mode="garden"] .history-row.selected {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--bl),
    var(--shadow-sm);
}
:root[data-mode="garden"] .lh-q {
  font-size: 13.5px;
}
:root[data-mode="garden"] .lh-meta {
  font-size: 12px;
  gap: 4px 8px;
}
:root[data-mode="garden"] .lh-sep {
  display: none;
}
:root[data-mode="garden"] .lh-state {
  padding: 1px 9px;
  border-radius: 999px;
  background: var(--st-tint);
  color: var(--st-ink);
}
:root[data-mode="garden"] .lh-state i {
  width: 6px;
  height: 6px;
  background: currentColor;
}

/* ------------------------------------------------ footer */
.history-pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
  font-size: 12px;
  color: var(--text-2);
}
.history-pagination .button {
  min-height: 32px;
  padding: 0 12px;
  font-size: 12.5px;
}
.lh-page {
  min-width: 40px;
  text-align: center;
  font-family: var(--font-mono);
  color: var(--text);
}
.lh-refresh {
  margin-left: auto;
}
:root[data-mode="garden"] .history-pagination {
  border-top: 0;
  padding-top: 0;
}
.history-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin: 4px 0 10px;
  padding: 10px 12px;
  border-radius: var(--radius-xs);
  background: var(--bad-tint);
  color: var(--bad);
  font-size: 13px;
  line-height: 1.7;
}
.history-error p {
  flex: 1 1 160px;
}
@media (max-width: 720px) {
  .history-panel,
  :root[data-mode="garden"] .history-panel {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .history-panel {
    border-radius: 24px;
  }
}
</style>
