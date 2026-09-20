<script setup lang="ts">
import { nextTick, ref, watch, onBeforeUnmount } from "vue";
import { X, FileSpreadsheet } from "lucide-vue-next";
import {
  get,
  number,
  typeNames,
  type Sample,
  type Lineage,
  type ListResult,
} from "../api";
const props = defineProps<{ sample: Sample | null }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
const lineage = ref<Lineage[]>([]),
  loading = ref(false),
  error = ref("");
let controller: AbortController | undefined;
const usageNames: Record<string, string> = {
  experiment_sample: "实验展示",
  sample_component: "原料组分",
  fiber_measurement: "纤维测量",
  paper_measurement: "纸张测量",
  source_only: "端点核对",
};
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  lineage.value = [];
  try {
    const data = await get<ListResult<Lineage>>(
      "lineage",
      { canonical_code: props.sample?.canonical_code, page_size: 500 },
      current.signal,
    );
    if (!current.signal.aborted) lineage.value = data.data;
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "来源读取失败。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
watch(
  () => props.sample,
  async (sample) => {
    if (sample) {
      await nextTick();
      dialog.value?.showModal();
      void load();
    } else {
      controller?.abort();
      dialog.value?.close();
    }
  },
);
function close() {
  dialog.value?.close();
  emit("close");
}
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <dialog
    ref="dialog"
    aria-label="样本详情与来源追溯"
    class="detail-drawer"
    @close="emit('close')"
    @click="$event.target === dialog && close()"
  >
    <div v-if="sample" class="drawer-content">
      <div class="dialog-heading">
        <div>
          <span class="eyebrow">样本详情</span>
          <h2>{{ sample.canonical_code }}</h2>
        </div>
        <button class="icon-button" aria-label="关闭样本详情" @click="close">
          <X :size="21" />
        </button>
      </div>
      <p class="detail-name">{{ sample.display_name }}</p>
      <span class="type-tag" :class="sample.sample_type"
        ><i></i>{{ typeNames[sample.sample_type] }}</span
      >
      <section class="detail-section">
        <h3>原料与打浆条件</h3>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>原料</th>
                <th>比例 / %</th>
                <th>转数 / r</th>
                <th>打浆度 / °SR</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>针叶木浆</td>
                <td>{{ number(sample.sw_proportion_pct) }}</td>
                <td>{{ number(sample.sw_beating_revolutions) }}</td>
                <td>{{ number(sample.sw_beating_degree_sr, 1) }}</td>
              </tr>
              <tr>
                <td>阔叶木浆</td>
                <td>{{ number(sample.hw_proportion_pct) }}</td>
                <td>{{ number(sample.hw_beating_revolutions) }}</td>
                <td>{{ number(sample.hw_beating_degree_sr, 1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="sample.notes" class="detail-note">{{ sample.notes }}</p>
      </section>
      <section class="detail-section">
        <h3>
          <FileSpreadsheet :size="17" />来源追溯
          <span class="count-badge">{{ loading ? "…" : lineage.length }}</span>
        </h3>
        <p class="muted">同一来源行可以承担多个用途。</p>
        <RouterLink
          class="button"
          :to="{ path: '/sources', query: { q: sample.canonical_code } }"
          @click="close"
        >
          查看合并后的来源行
        </RouterLink>
        <div v-if="loading" class="inline-empty" role="status">
          正在读取来源…
        </div>
        <div v-else-if="error" role="alert">
          <p>{{ error }}</p>
          <button class="button" @click="load">重新读取</button>
        </div>
        <p v-else-if="!lineage.length">暂无关联来源记录。</p>
        <ol v-else class="lineage-list">
          <li
            v-for="(item, index) in lineage"
            :key="`${item.source_id}-${index}`"
          >
            <div class="source-icon"><FileSpreadsheet :size="18" /></div>
            <div>
              <strong>{{ item.file_name }}</strong>
              <p>
                {{ item.sheet_name }} · 第 {{ item.source_row }} 行
                <span>{{
                  usageNames[item.usage_type] ?? item.usage_type
                }}</span>
              </p>
            </div>
          </li>
        </ol>
      </section>
      <div class="drawer-foot">只读记录 · 数值保留数据库口径</div>
    </div>
  </dialog>
</template>
