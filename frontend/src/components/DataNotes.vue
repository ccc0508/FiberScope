<script lang="ts">
import { get, type Metadata } from "../api";

// one metadata request per visit, shared by the shells and the prologue; a failure is retried
// the next time the dialog opens
let request: Promise<Metadata> | null = null;
function loadMetadata(): Promise<Metadata> {
  return (request ??= get<Metadata>("metadata").catch((error: unknown) => {
    request = null;
    throw error;
  }));
}
</script>

<script setup lang="ts">
import { computed, ref, shallowRef } from "vue";
import { X } from "lucide-vue-next";
import { number } from "../api";

/*
 * 数据说明 — the "about these data" dialog, opened from the 数据说明 button of both shells
 * and of the garden prologue. Every count comes from /api/v1/metadata (read when the dialog
 * first opens); until it arrives, or when it cannot be read, numbers show as "—".
 */
const dialog = ref<HTMLDialogElement>();
const metadata = shallowRef<Metadata | null>(null);
const state = ref<"idle" | "loading" | "ready" | "error">("idle");
let opener: HTMLElement | null = null;

const core = (group: string) =>
  metadata.value
    ? metadata.value.indicators.filter((i) => i.group === group && i.scope.includes("core")).length
    : null;
const fiberCount = computed(() => core("fiber"));
const paperCount = computed(() => core("paper"));
/** indicators whose unit is not confirmed, e.g. 透气度与耐折度 */
const unitFlagged = computed(() =>
  metadata.value
    ? metadata.value.indicators.filter((i) => i.unit_status !== "confirmed").map((i) => i.name)
    : null,
);
/** recycled data blocks without a recorded treatment condition */
const unknownBlocks = computed(() =>
  metadata.value ? metadata.value.blocks.filter((b) => !b.condition_label).length : null,
);
const caveat = computed(() => {
  const units = unitFlagged.value,
    blocks = unknownBlocks.value;
  const parts: string[] = [];
  if (units === null) parts.push("部分指标单位待复核");
  else if (units.length) parts.push(`${units.join("与")}单位待复核`);
  if (blocks === null || blocks > 0)
    parts.push(`${number(blocks)}个再生纸浆数据块的正式处理条件未知`);
  return parts.length ? `${parts.join("，")}。` : "";
});

async function read() {
  if (state.value === "ready" || state.value === "loading") return;
  state.value = "loading";
  try {
    metadata.value = await loadMetadata();
    state.value = "ready";
  } catch {
    state.value = "error";
  }
}

function open() {
  if (!dialog.value || dialog.value.open) return;
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  dialog.value.showModal();
  void read();
}
function close() {
  dialog.value?.close();
}
function onClose() {
  // the browser normally returns focus to the opener; keep it if the opener went away
  if (!document.activeElement || document.activeElement === document.body)
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  opener = null;
}
defineExpose({ open, close });
</script>

<template>
  <dialog
    ref="dialog"
    class="info-dialog data-notes"
    aria-labelledby="data-notes-title"
    @close="onClose"
    @click="$event.target === dialog && close()"
  >
    <div class="dialog-heading">
      <div>
        <span class="eyebrow">FiberScope · 数据说明</span>
        <h2 id="data-notes-title">关于这些实验数据</h2>
      </div>
      <button class="icon-button" type="button" aria-label="关闭数据说明" @click="close">
        <X :size="20" aria-hidden="true" />
      </button>
    </div>
    <p>
      核心样本保存{{ number(fiberCount) }}项纤维特性和{{ number(paperCount) }}项纸张性能。再生纸浆以逐行观测独立保存，循环均值由数据库汇总。
    </p>
    <ul>
      <li>复配两端复用纯浆样本，物理样本数与实验展示点数不同。</li>
      <li>空值显示为“—”，不替换为0；比例保持0—100%口径。</li>
      <li v-if="caveat">{{ caveat }}</li>
      <li>图表展示对应关系，不代表因果关系。</li>
    </ul>
    <p v-if="state === 'loading' || state === 'error'" class="data-notes-state" role="status">
      {{ state === "loading" ? "正在读取数据说明…" : "数据说明暂时无法读取，数字显示为“—”。" }}
    </p>
    <button class="button primary" type="button" @click="close">知道了</button>
  </dialog>
</template>

<style scoped>
.data-notes-state {
  margin-bottom: 18px;
}
</style>
