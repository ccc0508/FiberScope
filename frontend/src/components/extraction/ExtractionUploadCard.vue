<script setup lang="ts">
import { ref } from "vue";
import { ChevronDown, Upload } from "lucide-vue-next";

const props = defineProps<{
  open: boolean;
  extractionMode: "document" | "table";
  pdfPage: number;
  tableNo: string;
  file?: File;
  sessionReady: boolean;
  uploading: boolean;
  saving: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  "update:extractionMode": [value: "document" | "table"];
  "update:pdfPage": [value: number];
  "update:tableNo": [value: string];
  selectFile: [file: File | undefined];
  invalidFile: [message: string];
  submit: [];
}>();

const dragOver = ref(false);

function takeFile(selected: File | undefined) {
  if (!selected) return;
  if (!/\.pdf$/i.test(selected.name) && selected.type !== "application/pdf") {
    emit("invalidFile", "请选择 PDF 文件。");
    return;
  }
  emit("selectFile", selected);
}

function dropFile(event: DragEvent) {
  dragOver.value = false;
  if (props.uploading) return;
  takeFile(event.dataTransfer?.files?.[0]);
}

function fileChanged(event: Event) {
  emit("selectFile", (event.target as HTMLInputElement).files?.[0]);
}

function fileSize(f: File) {
  return `${(f.size / 1024 / 1024).toFixed(2)} MB`;
}
</script>

<template>
  <details
    class="card ld-upload"
    :open="open"
    @toggle="emit('update:open', ($event.target as HTMLDetailsElement).open)"
  >
    <summary class="ld-head">
      <Upload class="ld-head-ic" :size="17" aria-hidden="true" />
      <span class="ld-title">新增提取</span>
      <span class="ld-sub">可复制文字的 PDF · 最大 12MB</span>
      <ChevronDown class="ld-chevron" :size="17" aria-hidden="true" />
    </summary>
    <form class="upload-form" @submit.prevent="emit('submit')">
      <fieldset class="extraction-mode">
        <legend class="ld-label">提取方式</legend>
        <div class="ld-opts">
          <label :class="['ld-opt', { on: extractionMode === 'document' }]"
            ><input
              class="ld-radio"
              type="radio"
              value="document"
              :checked="extractionMode === 'document'"
              @change="emit('update:extractionMode', 'document')"
            />整篇自动识别</label
          ><label :class="['ld-opt', { on: extractionMode === 'table' }]"
            ><input
              class="ld-radio"
              type="radio"
              value="table"
              :checked="extractionMode === 'table'"
              @change="emit('update:extractionMode', 'table')"
            />指定表格</label
          >
        </div>
      </fieldset>
      <label
        class="ld-drop"
        :class="{ over: dragOver, ready: !!file }"
        @dragenter.prevent="dragOver = true"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="dropFile"
      >
        <span class="ld-drop-lens" aria-hidden="true"></span>
        <span class="ld-drop-ic" aria-hidden="true"><Upload :size="20" /></span>
        <span class="ld-drop-t">选择论文 PDF</span>
        <small v-if="file" class="ld-drop-file">{{ file.name }} · {{ fileSize(file) }}</small>
        <span v-else class="ld-drop-hint">点击选择，或将文件拖到此处</span>
        <input
          class="sr-only"
          type="file"
          accept=".pdf,application/pdf"
          aria-label="选择论文PDF"
          @change="fileChanged"
        />
      </label>
      <div v-if="extractionMode === 'table'" class="ld-table-fields">
        <label class="ld-field"
          ><span class="ld-label">PDF 页码</span
          ><input
            class="ld-input"
            type="number"
            min="1"
            max="200"
            aria-label="PDF页码"
            required
            :value="pdfPage"
            @input="emit('update:pdfPage', Number(($event.target as HTMLInputElement).value))"
        /></label>
        <label class="ld-field"
          ><span class="ld-label">表格编号</span>
          <span class="table-input">
            <span>Table</span
            ><input
              aria-label="表格编号"
              maxlength="8"
              placeholder="3"
              required
              :value="tableNo"
              @input="emit('update:tableNo', ($event.target as HTMLInputElement).value)"
            /></span
        ></label>
      </div>
      <button
        class="button primary ld-run"
        :disabled="!file || !sessionReady || uploading || saving"
      >
        <Upload :size="15" aria-hidden="true" />{{ uploading ? "正在提交…" : "开始提取" }}
      </button>
    </form>
    <p class="ld-note upload-note">
      {{ extractionMode === 'document' ? '无需填写页码或表格编号。模型逐页寻找相关表格和正文数值，结果保留原文出处；图中读数和扫描件暂不支持。' : '页码按 PDF 文件中的实际页序填写。' }}提取在后台继续，刷新页面后可从任务列表恢复。上传的论文、提取结果和审核记录长期保存，所有访问者可查看和审核。
    </p>
  </details>
</template>

<style scoped>
.ld-upload {
  display: flex;
  flex-direction: column;
}
.upload-form {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}
.ld-drop {
  position: relative;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 6px;
  min-height: 150px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition:
    border-color 0.2s,
    background 0.2s;
}
.ld-drop:has(input:focus-visible) {
  outline: 2.5px solid var(--focus);
  outline-offset: 3px;
}
.ld-drop-t {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
.ld-drop-hint {
  font-size: 12.5px;
  color: var(--text-2);
}
.ld-drop-file {
  max-width: 100%;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.ld-drop-lens,
.ld-drop-ic {
  display: none;
}
:root[data-mode="polarized"] .ld-drop {
  border: 1px dashed var(--line-strong);
  border-radius: 16px;
  background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--rc) 13%, transparent), transparent 70%);
}
:root[data-mode="polarized"] .ld-drop:hover,
:root[data-mode="polarized"] .ld-drop.over {
  border-color: color-mix(in srgb, var(--accent) 80%, transparent);
  background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 70%);
}
:root[data-mode="polarized"] .ld-drop.ready {
  border-style: solid;
}
:root[data-mode="polarized"] .ld-drop-lens {
  display: block;
  width: 46px;
  height: 46px;
  margin-bottom: 4px;
  border-radius: 50%;
  background: var(--ifc);
  -webkit-mask: radial-gradient(circle, transparent 54%, currentColor 56%);
  mask: radial-gradient(circle, transparent 54%, currentColor 56%);
  opacity: 0.85;
}
:root[data-mode="garden"] .ld-drop {
  border: 1.5px dashed color-mix(in srgb, var(--accent) 26%, transparent);
  border-radius: 22px;
  background: color-mix(in srgb, var(--surface) 55%, transparent);
}
:root[data-mode="garden"] .ld-drop:hover,
:root[data-mode="garden"] .ld-drop.over {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: var(--accent-tint);
}
:root[data-mode="garden"] .ld-drop.ready {
  border-style: solid;
  background: var(--surface);
}
:root[data-mode="garden"] .ld-drop-ic {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 2px;
  border-radius: 50%;
  color: var(--text);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
:root[data-mode="garden"] .ld-drop-t {
  font-weight: 500;
}
.ld-table-fields {
  display: grid;
  grid-template-columns: minmax(96px, 0.6fr) minmax(0, 1fr);
  gap: 12px;
}
.table-input {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 0;
  padding-bottom: 0;
}
.table-input:focus-within {
  border-color: var(--focus) !important;
}
.table-input > span {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.table-input input {
  flex: 1;
  min-width: 0;
  padding: 9px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 13.5px;
}
.table-input input:focus-visible {
  outline: none;
}
.ld-run {
  min-height: 44px;
}
:root[data-mode="garden"] .ld-run {
  justify-self: start;
  padding: 0 22px;
}
.upload-note {
  margin-top: 14px;
}

@media (max-width: 720px) {
  .ld-table-fields {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  :root[data-mode="garden"] .ld-run {
    justify-self: stretch;
  }
}
</style>
