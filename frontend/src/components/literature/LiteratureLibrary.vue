<script setup lang="ts">
import { computed } from "vue";
import { ChevronDown, ExternalLink } from "lucide-vue-next";
import { vTilt } from "../../motion";
import { apiPath } from "../../urls";

export interface LibraryDocument {
  id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
}

const props = defineProps<{
  documents: LibraryDocument[];
  enabled: boolean;
}>();

const maxPages = computed(() => Math.max(1, ...props.documents.map((d) => d.page_count)));
const pageShare = (d: LibraryDocument) => Math.max(0.08, d.page_count / maxPages.value);
const pdf = (id: string) => apiPath(`literature/documents/${encodeURIComponent(id)}/pdf#page=1`);
</script>

<template>
  <details class="card lit-library" open>
    <summary>
      <span class="lit-title">当前文献库</span>
      <span class="lit-badge">{{ documents.length }} 篇文献</span>
      <ChevronDown class="lit-chevron" :size="17" aria-hidden="true" />
    </summary>
    <p class="lit-sub">
      {{
        enabled
          ? "可查询以下文献及平台实验数据；不检索互联网。回答分别标注文献与实验数据来源。"
          : "文献问答尚未启用，请先配置文献库和模型服务。"
      }}
    </p>
    <ol v-if="documents.length" class="lit-docs">
      <li
        v-for="(doc, i) in documents"
        :key="doc.id"
        v-tilt
        class="lit-doc"
        :class="`n${(i % 3) + 1}`"
        :style="{ '--p': pageShare(doc).toFixed(3) }"
      >
        <span class="lit-spine" aria-hidden="true"></span>
        <span class="lit-doc-no" aria-hidden="true">No. {{ String(i + 1).padStart(2, "0") }}</span>
        <strong class="lit-doc-name">{{ doc.filename }}</strong>
        <span class="lit-doc-foot">
          <span class="lit-doc-meta"
            ><span class="nw">{{ doc.page_count }} 页 ·</span> <span class="nw">{{ doc.chunk_count }} 个文本片段</span></span
          >
          <a
            class="lit-doc-link"
            :href="pdf(doc.id)"
            target="_blank"
            rel="noopener"
            :aria-label="`阅读原文 ${doc.filename}`"
            >阅读原文<ExternalLink :size="13" aria-hidden="true"
          /></a>
        </span>
      </li>
    </ol>
    <p v-if="enabled && !documents.length" class="lit-sub">
      暂无已完成导入的文献，请先补充文献。
    </p>
  </details>
</template>

<style scoped>
.lit-library {
  padding: 22px;
  container-type: inline-size;
}
:root[data-mode="garden"] .lit-library {
  padding: 22px 24px;
}
.lit-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
:root[data-mode="garden"] .lit-title {
  font-size: 19px;
  font-weight: 500;
  letter-spacing: 0.03em;
}
.lit-sub {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.lit-badge {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
:root[data-mode="polarized"] .lit-badge {
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
}
:root[data-mode="garden"] .lit-badge {
  font-size: 14px;
}
.nw {
  white-space: nowrap;
}
.lit-library summary {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 12px;
  padding-right: 30px;
  cursor: pointer;
  list-style: none;
  border-radius: var(--radius-xs);
}
.lit-library summary::-webkit-details-marker {
  display: none;
}
.lit-chevron {
  position: absolute;
  right: 0;
  top: 2px;
  color: var(--text-2);
  transition: transform 0.25s var(--ease);
}
.lit-library:not([open]) .lit-chevron {
  transform: rotate(-90deg);
}
.lit-library > .lit-sub {
  margin-top: 8px;
}
.lit-docs {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.lit-doc {
  min-width: 0;
}
.lit-doc-no {
  display: none;
}
.lit-doc-name {
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1.45;
  color: var(--text);
  overflow-wrap: anywhere;
}
.lit-doc-meta {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
.lit-doc-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  font-size: 12.5px;
}
:root[data-mode="polarized"] .lit-doc {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  grid-template-areas:
    "spine name link"
    "spine meta link";
  align-items: center;
  gap: 2px 12px;
  padding: 10px 10px 10px 8px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--text) 2.5%, transparent);
}
:root[data-mode="polarized"] .lit-doc-foot {
  display: contents;
}
:root[data-mode="polarized"] .lit-spine {
  grid-area: spine;
  position: relative;
  width: 6px;
  height: 40px;
  border-radius: 3px;
  overflow: hidden;
  background: color-mix(in srgb, var(--text) 7%, transparent);
}
:root[data-mode="polarized"] .lit-spine::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: calc(var(--p) * 100%);
  background: var(--ifl);
}
:root[data-mode="polarized"] .lit-doc-name {
  grid-area: name;
  align-self: end;
}
:root[data-mode="polarized"] .lit-doc-meta {
  grid-area: meta;
  align-self: start;
}
:root[data-mode="polarized"] .lit-doc-link {
  grid-area: link;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 3%, transparent);
  color: var(--text);
  transition:
    background 0.2s,
    border-color 0.2s;
}
:root[data-mode="polarized"] .lit-doc-link:hover {
  background: color-mix(in srgb, var(--text) 8%, transparent);
  border-color: color-mix(in srgb, var(--text) 32%, transparent);
}
@container (min-width: 640px) {
  :root[data-mode="polarized"] .lit-docs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
:root[data-mode="garden"] .lit-docs {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
:root[data-mode="garden"] .lit-doc {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 160px;
  padding: 16px;
  border-radius: 22px;
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--surface) 94%, transparent),
    color-mix(in srgb, var(--surface-2) 80%, transparent)
  );
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
.lit-doc.n1 {
  --n: var(--accent);
}
.lit-doc.n2 {
  --n: color-mix(in oklab, var(--accent) 78%, var(--surface));
}
.lit-doc.n3 {
  --n: color-mix(in oklab, var(--accent) 62%, var(--surface));
}
:root[data-mode="garden"] .lit-spine {
  display: block;
  width: calc(var(--p) * 100%);
  height: 6px;
  border-radius: 9px;
  background: var(--n);
}
:root[data-mode="garden"] .lit-doc-no {
  display: block;
  font-family: var(--font-display), var(--font-body);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 12.5px;
  color: var(--text-2);
}
:root[data-mode="garden"] .lit-doc-name {
  flex: 1;
  font-size: 13px;
  line-height: 1.5;
}
:root[data-mode="garden"] .lit-doc-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 8px;
}
:root[data-mode="garden"] .lit-doc-meta {
  font-size: 12px;
  color: var(--text-2);
}
:root[data-mode="garden"] .lit-doc-link {
  padding: 2px 0;
  font-weight: 500;
  color: var(--bl-ink);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--bl-ink) 30%, transparent);
  text-underline-offset: 3px;
}
:root[data-mode="garden"] .lit-doc-link:hover {
  text-decoration-color: currentColor;
}
@container (max-width: 900px) {
  :root[data-mode="garden"] .lit-docs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@container (max-width: 460px) {
  :root[data-mode="garden"] .lit-docs {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .lit-doc {
    min-height: 0;
  }
}
@media (max-width: 720px) {
  .lit-library,
  :root[data-mode="garden"] .lit-library {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .lit-library {
    border-radius: 24px;
  }
}
</style>
