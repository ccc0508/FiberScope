<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { History, Download, Search } from "lucide-vue-next";
import { literatureRequest, stateNames, timeLabel, type HistoryItem } from "../literature";
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
    <summary><History :size="17" />问答历史 <span>{{ total }} 条</span></summary>
    <p class="history-note">记录长期保存在服务器，所有访问者均可查看和导出。清除 Cookie 或更换浏览器不影响查看。</p>
    <div class="history-tools">
      <form @submit.prevent="find"><Search :size="15" /><input v-model="search" aria-label="搜索历史问题" placeholder="搜索问题" maxlength="200" /><button class="button" :disabled="loading">搜索</button></form>
      <button class="button" :disabled="loading" @click="download"><Download :size="14" />导出全部记录</button>
    </div>
    <div v-if="error" class="history-error" role="alert">{{ error }} <button class="button" :disabled="loading" @click="refresh(true)">重试</button></div>
    <p v-else-if="loading" class="history-note" role="status">正在读取历史…</p>
    <p v-else-if="!items.length" class="history-note">{{ search ? "没有匹配的问题。" : "暂无记录，开始提问后会自动保存。" }}</p>
    <div v-else class="history-list">
      <button v-for="item in items" :key="item.id" :class="['history-row', { selected: props.selected === item.id }]" @click="emit('select', item.id)">
        <strong>{{ item.question }}</strong><span>{{ stateNames[item.status] }} · {{ timeLabel(item.created_at) }}</span>
      </button>
    </div>
    <div class="history-pagination"><button class="button" :disabled="loading || page <= 1" @click="move(-1)">上一页</button><span>{{ page }} / {{ Math.max(1, pages) }}</span><button class="button" :disabled="loading || page >= pages" @click="move(1)">下一页</button><button class="button" :disabled="loading" @click="refresh()">刷新历史</button></div>
  </details>
</template>

<style scoped>
.history-panel { padding: 22px 24px; }
summary { display: flex; align-items: center; gap: 9px; cursor: pointer; font-weight: 700; font-size: 16px; }
summary span { font-size: 12px; font-weight: 400; color: var(--muted); margin-left: auto; }
.history-note, .history-pagination { font-size: 12px; color: var(--muted); line-height: 1.8; }
.history-tools, .history-tools form { display: flex; align-items: center; gap: 10px; }
.history-tools { justify-content: space-between; flex-wrap: wrap; margin: 16px 0; }
.history-tools .button { flex-shrink: 0; white-space: nowrap; }
.history-tools form { flex: 1; min-width: 0; }
input { width: 100%; min-width: 40px; max-width: 320px; border: 1px solid #dcebe7; border-radius: 6px; padding: 9px; font: inherit; font-size: 13px; }
.history-list { display: grid; gap: 6px; }
.history-row { text-align: left; border: 1px solid transparent; background: #fcfbf8; color: #0b5f5a; padding: 12px; border-radius: 7px; cursor: pointer; font: inherit; min-width: 0; }
.history-row:hover, .history-row.selected { background: #e3efec; border-color: #dcebe7; }
.history-row strong { display: block; font-weight: 400; font-size: 13px; overflow-wrap: anywhere; }
.history-row span { display: block; margin-top: 6px; font-size: 11px; color: var(--muted); }
.history-pagination { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 15px; }
.history-pagination .button:last-child { margin-left: auto; }
.history-error { color: #b16642; font-size: 13px; line-height: 1.8; }
@media (max-width: 720px) { .history-panel { padding: 18px; } .history-tools form { flex-basis: 100%; } }
</style>
