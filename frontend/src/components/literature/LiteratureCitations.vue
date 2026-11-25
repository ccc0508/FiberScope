<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch, type ComponentPublicInstance } from "vue";
import { ChevronDown, ExternalLink } from "lucide-vue-next";
import EvidenceExcerpt from "../EvidenceExcerpt.vue";
import { reducedMotion } from "../../mode";
import { apiPath, appPath } from "../../urls";
import {
  citationKind,
  citationKinds,
  citationTitle,
  pageRange,
  type Citation,
  type HistoryRecord,
} from "../../literature";

const props = defineProps<{
  citations: Citation[];
  selected: HistoryRecord | null;
}>();

const PREVIEW_HEIGHT = 190;
const openCites = reactive(new Set<string>());
const tallCites = reactive(new Set<string>());
const highlighted = ref<string | null>(null);
const citeEls = new Map<string, HTMLElement>();

const citeObserver =
  typeof ResizeObserver === "undefined"
    ? undefined
    : new ResizeObserver((entries) => {
        for (const entry of entries) {
          const el = entry.target as HTMLElement;
          const key = el.dataset.cite;
          if (!key) continue;
          if (el.offsetHeight > PREVIEW_HEIGHT + 12) tallCites.add(key);
          else tallCites.delete(key);
        }
      });

function trackExcerpt(key: string, el: Element | ComponentPublicInstance | null) {
  const previous = citeEls.get(key);
  if (previous && previous !== el) {
    citeObserver?.unobserve(previous);
    citeEls.delete(key);
  }
  if (el instanceof HTMLElement && previous !== el) {
    citeEls.set(key, el);
    citeObserver?.observe(el);
  }
}

watch(
  () => props.citations,
  () => {
    openCites.clear();
    highlighted.value = null;
  },
);

const collapsed = (c: Citation) => tallCites.has(c.ref) && !openCites.has(c.ref);
function toggleCite(key: string) {
  if (openCites.has(key)) openCites.delete(key);
  else openCites.add(key);
}
function revealCite(key: string) {
  if (tallCites.has(key)) openCites.add(key);
}
function focusCitation(token: string) {
  openCites.add(token);
  highlighted.value = token;
  const el = document.getElementById(`literature-citation-${token.slice(1, -1)}`);
  if (!el) return;
  el.scrollIntoView({ block: "start", behavior: reducedMotion.value ? "auto" : "smooth" });
  el.focus({ preventScroll: true });
}
const toggleLabel = (c: Citation) => {
  const open = openCites.has(c.ref);
  if (citationKind(c) === "db") return open ? "收起查询详情" : "展开查询详情";
  return open ? "收起原文片段" : "展开原文片段";
};
const pdf = (id: string, page = 1) =>
  apiPath(`literature/documents/${encodeURIComponent(id)}/pdf#page=${page}`);
const citationReader = (record: HistoryRecord | null, c: Citation) =>
  record && /^\[\d+\]$/.test(c.ref)
    ? appPath(`literature/read/${encodeURIComponent(record.id)}/${c.ref.slice(1, -1)}`)
    : pdf(c.document_id, c.page_start);
const imageUrl = (checksum: string) => apiPath(`literature/images/${encodeURIComponent(checksum)}`);

onBeforeUnmount(() => {
  citeObserver?.disconnect();
});

defineExpose({ focusCitation });
</script>

<template>
  <section
    v-if="citations.length"
    class="lit-cites"
    aria-labelledby="literature-cites-title"
  >
    <h3 id="literature-cites-title">引用与原文片段 <span class="lit-cites-n">{{ citations.length }}</span></h3>
    <ol>
      <li
        v-for="c in citations"
        :id="`literature-citation-${c.ref.slice(1, -1)}`"
        :key="c.ref"
        class="lit-cite"
        :class="[`k-${citationKind(c)}`, { hl: highlighted === c.ref }]"
        tabindex="-1"
      >
        <div class="lit-cite-head">
          <span class="lit-cite-n">{{ c.ref }}</span>
          <span class="lit-kind">{{ citationKinds[citationKind(c)] }}</span>
          <h4>{{ citationTitle(c) }}</h4>
          <span v-if="c.document_id" class="lit-cite-page">PDF 第 {{ pageRange(c.page_start, c.page_end) }} 页</span>
          <a
            v-if="c.document_id"
            class="lit-link"
            :href="citationReader(selected, c)"
            target="_blank"
            rel="noopener"
            :aria-label="`阅读引用 ${c.ref} 原文，${c.filename} 第 ${c.page_start} 页`"
            >阅读原文<ExternalLink :size="13" aria-hidden="true"
          /></a>
        </div>
        <div
          :id="`literature-excerpt-${c.ref.slice(1, -1)}`"
          class="lit-cite-body"
          :class="{ collapsed: collapsed(c) }"
          @focusin="revealCite(c.ref)"
        >
          <div :ref="(el) => trackExcerpt(c.ref, el)" class="lit-cite-inner" :data-cite="c.ref">
            <EvidenceExcerpt
              :text="c.excerpt"
              :query="c.kind === 'experiment_query'"
              :label="c.ref"
            />
            <div v-if="c.visual_assets?.length" class="lit-images">
              <figure v-for="image in c.visual_assets" :key="image.id">
                <a :href="imageUrl(image.sha256)" target="_blank" rel="noreferrer"
                  :aria-label="`查看 ${image.label} 原图，PDF 第 ${image.page} 页`">
                  <img :src="imageUrl(image.sha256)" :alt="`${image.label}，PDF 第 ${image.page} 页原图`" loading="lazy" />
                </a>
                <figcaption>{{ image.label }} · PDF 第 {{ image.page }} 页 · 点击查看原图</figcaption>
              </figure>
            </div>
            <details v-if="(c.source_chunks?.length ?? 0) > 1" class="lit-parts">
              <summary>查看引用的原文组成（{{ c.source_chunks?.length }} 段）</summary>
              <div v-for="part in c.source_chunks" :key="part.chunk_id">
                <small>PDF 第 {{ pageRange(part.page_start, part.page_end) }} 页</small>
                <EvidenceExcerpt :text="part.text" />
              </div>
            </details>
          </div>
        </div>
        <button
          v-if="tallCites.has(c.ref)"
          type="button"
          class="lit-cite-toggle"
          :aria-expanded="openCites.has(c.ref)"
          :aria-controls="`literature-excerpt-${c.ref.slice(1, -1)}`"
          @click="toggleCite(c.ref)"
        >
          <ChevronDown :size="14" aria-hidden="true" />{{ toggleLabel(c) }}
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.lit-cites {
  --lit-preview: 190px;
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--line-soft);
}
.lit-cites > h3 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 14px;
  color: var(--text);
}
:root[data-mode="garden"] .lit-cites > h3 {
  font-size: 17px;
}
.lit-cites-n {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 400;
  color: var(--text-3);
}
.lit-cites ol {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.lit-cite {
  --k: var(--line-strong);
  --k-tint: var(--surface-2);
  --k-ink: var(--text-2);
  min-width: 0;
  padding: 14px;
  border-radius: 12px;
  scroll-margin: calc(var(--chrome-top) + 16px) 0 calc(var(--chrome-bottom) + 16px);
  transition:
    border-color 0.3s,
    background 0.3s,
    box-shadow 0.4s;
}
.lit-cite:focus-visible {
  outline: 2.5px solid var(--focus);
  outline-offset: 3px;
}
:root[data-mode="polarized"] .lit-cite.k-db {
  --k: color-mix(in srgb, var(--warn) 55%, transparent);
  --k-ink: var(--warn);
}
:root[data-mode="polarized"] .lit-cite:is(.k-paper, .k-image) {
  --k: color-mix(in srgb, var(--bl) 55%, transparent);
  --k-ink: var(--bl-ink);
}
:root[data-mode="garden"] .lit-cite.k-db {
  --k-tint: var(--ok-tint);
  --k-ink: var(--ok);
}
:root[data-mode="garden"] .lit-cite:is(.k-paper, .k-image) {
  --k-tint: var(--accent-tint);
  --k-ink: var(--text-2);
}
:root[data-mode="garden"] .lit-cite.k-calc {
  --k-tint: var(--warn-tint);
  --k-ink: var(--warn);
}
:root[data-mode="polarized"] .lit-cite {
  border: 1px solid var(--line-soft);
  background: color-mix(in srgb, var(--text) 2%, transparent);
}
:root[data-mode="polarized"] .lit-cite.hl {
  border-color: color-mix(in srgb, var(--accent) 80%, transparent);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
:root[data-mode="garden"] .lit-cite {
  padding: 14px 16px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .lit-cite.hl {
  background: var(--surface);
  box-shadow:
    inset 0 0 0 2px var(--bl),
    0 16px 30px -18px color-mix(in srgb, var(--bl-ink) 60%, transparent);
}
.lit-cite-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  font-size: 13px;
}
.lit-cite-n {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--accent-ink);
}
:root[data-mode="garden"] .lit-cite-n {
  color: var(--bl-ink);
}
.lit-kind {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  white-space: nowrap;
  color: var(--text-2);
}
:root[data-mode="polarized"] .lit-kind {
  border: 1px solid var(--k);
}
:root[data-mode="garden"] .lit-kind {
  padding: 2px 10px;
  font-size: 12px;
  background: var(--k-tint);
  color: var(--k-ink);
}
:root[data-mode="garden"] .lit-kind::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.lit-cite-head h4 {
  flex: 1 1 180px;
  min-width: 0;
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--text);
  overflow-wrap: anywhere;
}
.lit-cite.k-db h4 {
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.lit-cite-page {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
}
.lit-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  white-space: nowrap;
  color: var(--accent-ink);
  border-radius: var(--radius-xs);
}
.lit-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
:root[data-mode="garden"] .lit-link {
  color: var(--bl-ink);
  font-weight: 500;
}
.lit-cite-body {
  position: relative;
  margin-top: 10px;
  min-width: 0;
}
.lit-cite-body.collapsed {
  max-height: var(--lit-preview);
  overflow: hidden;
  -webkit-mask-image: linear-gradient(180deg, currentColor 62%, transparent);
  mask-image: linear-gradient(180deg, currentColor 62%, transparent);
}
.lit-cite-inner {
  min-width: 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-2);
}
.lit-cite-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--text);
}
.lit-cite-toggle svg {
  transition: transform 0.25s var(--ease);
}
.lit-cite-toggle[aria-expanded="true"] svg {
  transform: rotate(180deg);
}
:root[data-mode="polarized"] .lit-cite-toggle {
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--text) 3%, transparent);
}
:root[data-mode="polarized"] .lit-cite-toggle:hover {
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
:root[data-mode="garden"] .lit-cite-toggle {
  background: color-mix(in srgb, var(--surface) 80%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
:root[data-mode="garden"] .lit-cite-toggle:hover {
  background: var(--surface);
}
.lit-images {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 16px;
  margin: 12px 0;
}
.lit-images figure {
  margin: 0;
  min-width: 0;
}
.lit-images a {
  display: block;
  border-radius: var(--radius-xs);
}
.lit-images img {
  display: block;
  width: 100%;
  max-height: 360px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: var(--radius-xs);
}
.lit-images figcaption {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.lit-parts {
  margin-top: 12px;
}
.lit-parts summary {
  width: fit-content;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--text-2);
  border-radius: var(--radius-xs);
}
.lit-parts summary:hover {
  color: var(--text);
}
.lit-parts > div {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--line-soft);
}
.lit-parts small {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-3);
}
@media (max-width: 720px) {
  .lit-cite,
  :root[data-mode="garden"] .lit-cite {
    padding: 12px;
  }
}
</style>
