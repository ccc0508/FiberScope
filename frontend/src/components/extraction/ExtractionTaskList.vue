<script setup lang="ts">
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  History,
  RefreshCw,
  Search,
  X,
} from "lucide-vue-next";
import { taskStates, type ExtractionTask } from "../../extraction";
import { secondsLabel, timeLabel } from "../../literature";

defineProps<{
  list: ExtractionTask[];
  total: number;
  listPage: number;
  totalPages: number;
  search: string;
  loading: boolean;
  uploading: boolean;
  saving: boolean;
  selectedTaskId?: string;
}>();

const emit = defineEmits<{
  "update:search": [value: string];
  searchSubmit: [];
  refresh: [];
  openTask: [id: string];
  pageChange: [page: number];
}>();

function modeLabel(item: ExtractionTask) {
  return item.source.mode === "document"
    ? "整篇自动识别"
    : `第 ${item.source.page} 页 · ${item.source.table}`;
}
</script>

<template>
  <details class="card ld-tasks" open>
    <summary class="ld-head">
      <History class="ld-head-ic" :size="17" aria-hidden="true" />
      <span class="ld-title">提取记录</span>
      <span class="ld-count">{{ total }} 条</span>
      <ChevronDown class="ld-chevron" :size="17" aria-hidden="true" />
    </summary>
    <div class="task-toolbar">
      <form class="ld-search" role="search" @submit.prevent="emit('searchSubmit')">
        <Search :size="15" aria-hidden="true" /><input
          aria-label="搜索提取任务"
          placeholder="搜索文件名或表格"
          maxlength="200"
          :value="search"
          @input="emit('update:search', ($event.target as HTMLInputElement).value)"
        /><button class="ld-go" :disabled="loading">搜索</button>
      </form>
      <button type="button" class="button ld-refresh" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="14" :class="{ spinning: loading }" aria-hidden="true" />刷新
      </button>
    </div>
    <p v-if="loading && !list.length" class="ld-state" role="status">正在读取任务…</p>
    <p v-else-if="!list.length" class="ld-state">
      {{
        search ? "没有匹配的提取任务。" : "暂无任务，上传第一篇论文开始整理。"
      }}
    </p>
    <template v-else>
      <p v-if="loading" class="sr-only" role="status">正在读取任务…</p>
      <div class="task-cols" aria-hidden="true">
        <span>文件</span><span>方式</span><span>时间</span><span>用时</span><span>状态</span>
      </div>
      <ol class="task-list" :class="{ refreshing: loading }" :aria-busy="loading">
        <li v-for="item in list" :key="item.id">
          <button
            type="button"
            :class="['task-row', `s-${item.status}`, { selected: selectedTaskId === item.id }]"
            :aria-current="selectedTaskId === item.id ? 'true' : undefined"
            :disabled="uploading || saving"
            @click="emit('openTask', item.id)"
          >
            <span class="tr-ic" aria-hidden="true"
              ><Check v-if="item.status === 'completed'" :size="11" :stroke-width="3" /><RefreshCw
                v-else-if="item.status === 'processing'"
                :size="10"
                :stroke-width="3"
                class="spinning" /><X v-else :size="11" :stroke-width="3"
            /></span>
            <span class="tr-name">{{ item.source.filename }}</span>
            <span class="tr-meta"
              ><span class="tr-mode">{{ modeLabel(item) }}<span class="tr-sep"> ·</span></span> <span class="tr-time">{{ timeLabel(item.created_at) }}<span class="tr-sep"> ·</span></span> <span class="tr-ms">{{ item.latency_ms != null ? secondsLabel(item.latency_ms) : "—" }}</span></span
            >
            <span :class="['state-pill', item.status]">{{ taskStates[item.status] }}</span>
          </button>
        </li>
      </ol>
    </template>
    <div class="task-foot">
      <p class="ld-note privacy-note">
        记录长期保存在服务器，所有访问者均可查看、审核和导出。清除 Cookie 或更换浏览器不影响审核。
      </p>
      <div v-if="totalPages > 1" class="task-pagination">
        <button
          type="button"
          class="button ld-page"
          :disabled="loading || listPage <= 1"
          aria-label="上一页任务"
          @click="emit('pageChange', listPage - 1)"
        >
          <ChevronLeft :size="15" aria-hidden="true" /></button
        ><span class="ld-page-n">{{ listPage }} / {{ totalPages }}</span
        ><button
          type="button"
          class="button ld-page"
          :disabled="loading || listPage >= totalPages"
          aria-label="下一页任务"
          @click="emit('pageChange', listPage + 1)"
        >
          <ChevronRight :size="15" aria-hidden="true" />
        </button>
      </div>
    </div>
  </details>
</template>

<style scoped>
.ld-tasks {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
}
.task-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 16px 0 12px;
}
.ld-search {
  flex: 1 1 220px;
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
.ld-search input {
  flex: 1;
  min-width: 0;
  padding: 8px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}
.ld-search input::placeholder {
  color: var(--text-3);
}
.ld-search input:focus-visible {
  outline: none;
}
.ld-search:has(input:focus-visible) {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 28%, transparent);
}
.ld-go {
  flex-shrink: 0;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
  white-space: nowrap;
  transition: background 0.2s;
}
.ld-go:focus-visible {
  outline-offset: 1px;
}
:root[data-mode="polarized"] .ld-search {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
:root[data-mode="polarized"] .ld-search:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .ld-go {
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
:root[data-mode="polarized"] .ld-go:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 13%, transparent);
}
:root[data-mode="polarized"] .ld-refresh {
  min-height: 38px;
  padding: 0 12px;
  font-size: 13px;
}
:root[data-mode="garden"] .ld-search {
  border: 1px solid transparent;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
:root[data-mode="garden"] .ld-go {
  background: var(--accent-tint);
}
:root[data-mode="garden"] .ld-go:hover:not(:disabled) {
  background: color-mix(in oklab, var(--accent) 16%, var(--surface));
}
.task-cols {
  display: none;
}
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
  transition: opacity 0.2s;
}
.task-list.refreshing {
  opacity: 0.6;
}
.task-row {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  grid-template-areas:
    "ic name state"
    "ic meta state";
  align-items: center;
  gap: 3px 12px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  text-align: left;
  color: var(--text);
  transition:
    background 0.2s,
    border-color 0.2s,
    box-shadow 0.25s;
}
.tr-ic {
  grid-area: ic;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--text-2);
  background: color-mix(in srgb, var(--text-2) 16%, transparent);
}
.task-row.s-completed .tr-ic {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 16%, transparent);
}
.task-row.s-failed .tr-ic,
.task-row.s-interrupted .tr-ic {
  color: var(--bad);
  background: color-mix(in srgb, var(--bad) 16%, transparent);
}
.task-row.s-processing .tr-ic {
  color: var(--accent-ink);
  background: var(--accent-tint);
}
.tr-name {
  grid-area: name;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.tr-meta {
  grid-area: meta;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.tr-mode,
.tr-time,
.tr-ms {
  white-space: nowrap;
}
.state-pill {
  grid-area: state;
  justify-self: end;
  font-size: 12px;
  white-space: nowrap;
  color: var(--text-2);
}
.state-pill.completed {
  color: var(--ok);
}
.state-pill.failed,
.state-pill.interrupted {
  color: var(--bad);
}
.state-pill.processing {
  color: var(--accent-ink);
}
:root[data-mode="polarized"] .task-row {
  background: color-mix(in srgb, var(--text) 2%, transparent);
}
:root[data-mode="polarized"] .task-row:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) 5%, transparent);
}
:root[data-mode="polarized"] .task-row.selected {
  border-color: var(--line-strong);
  background: color-mix(in srgb, var(--text) 5%, transparent);
  box-shadow: inset 2px 0 0 var(--accent);
}
:root[data-mode="garden"] .task-list {
  gap: 6px;
}
:root[data-mode="garden"] .task-row {
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "name state"
    "meta state";
  padding: 11px 14px;
  border: 0;
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .task-row:hover:not(:disabled) {
  background: var(--surface);
}
:root[data-mode="garden"] .task-row.selected {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--bl),
    var(--shadow-sm);
}
:root[data-mode="garden"] .tr-ic {
  display: none;
}
:root[data-mode="garden"] .tr-meta {
  font-size: 12px;
}
:root[data-mode="garden"] .state-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
}
:root[data-mode="garden"] .state-pill::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
:root[data-mode="garden"] .state-pill.completed {
  color: var(--ok);
  background: var(--ok-tint);
}
:root[data-mode="garden"] .state-pill.failed,
:root[data-mode="garden"] .state-pill.interrupted {
  color: var(--bad);
  background: var(--bad-tint);
}
:root[data-mode="garden"] .state-pill.processing {
  color: var(--accent-ink);
  background: var(--accent-tint);
}
@container (min-width: 640px) {
  :root[data-mode="garden"] .task-cols,
  :root[data-mode="garden"] .task-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 116px 140px 64px 86px;
    grid-template-areas: none;
    gap: 0 12px;
    align-items: center;
  }
  :root[data-mode="garden"] .task-cols {
    padding: 0 14px 8px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 6px;
    font-size: 12.5px;
    color: var(--text-2);
  }
  :root[data-mode="garden"] .task-cols > span:nth-child(4) {
    text-align: right;
  }
  :root[data-mode="garden"] .task-row > * {
    grid-area: auto;
  }
  :root[data-mode="garden"] .tr-meta {
    display: contents;
  }
  :root[data-mode="garden"] .tr-meta > * {
    min-width: 0;
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text);
  }
  :root[data-mode="garden"] .tr-time,
  :root[data-mode="garden"] .tr-ms {
    font-family: var(--font-mono) !important;
    font-size: 12.5px !important;
  }
  :root[data-mode="garden"] .tr-ms {
    text-align: right;
  }
  :root[data-mode="garden"] .tr-sep {
    display: none;
  }
  :root[data-mode="garden"] .state-pill {
    justify-self: start;
  }
}
.task-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  margin-top: auto;
  padding-top: 14px;
}
.privacy-note {
  flex: 1 1 260px;
  font-size: 12px;
}
.task-pagination {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ld-page {
  width: 34px;
  min-height: 34px !important;
  padding: 0 !important;
}
.ld-page-n {
  min-width: 44px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text);
}
:root[data-mode="polarized"] .task-foot {
  border-top: 1px solid var(--line-soft);
  margin-top: 14px;
}
:root[data-mode="polarized"] .ld-tasks .task-foot {
  margin-top: auto;
}
</style>
