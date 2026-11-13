<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch, type ComponentPublicInstance } from "vue";
import {
  BookOpen,
  ChevronDown,
  ExternalLink,
  RefreshCw,
  Send,
} from "lucide-vue-next";
import { get } from "../api";
import { apiPath } from "../urls";
import { isGarden, reducedMotion } from "../mode";
import { vTilt } from "../motion";
import PageHeader from "../components/PageHeader.vue";
import LiteratureHistory from "../components/LiteratureHistory.vue";
import EvidenceExcerpt from "../components/EvidenceExcerpt.vue";
import {
  answerBlocks,
  citationKind,
  citationKinds,
  citationTitle,
  literatureRequest,
  pageRange,
  secondsLabel,
  timeLabel,
  type Answer,
  type Citation,
  type HistoryRecord,
  type HistoryItem,
} from "../literature";

interface Document {
  id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
}
const documents = ref<Document[]>([]),
  enabled = ref(false),
  loading = ref(true),
  loadError = ref("");
const question = ref(""),
  submitted = ref(""),
  asking = ref(false),
  error = ref(""),
  answer = ref<Answer | null>(null);
const historyPanel = ref<InstanceType<typeof LiteratureHistory>>();
const historyReady = ref(false), selected = ref<HistoryRecord | null>(null);
let pendingSubmission: { question: string; request_id: string } | undefined;
let pollTimer: number | undefined, disposed = false, selectionVersion = 0;
const canAsk = computed(
  () =>
    enabled.value &&
    documents.value.length > 0 &&
    !loading.value &&
    !asking.value &&
    historyReady.value &&
    question.value.trim().length >= 2,
);
const blocks = computed(() => (answer.value ? answerBlocks(answer.value.answer) : []));
const examples = [
  "PFI 打浆如何影响纤维素的聚集结构？",
  "这篇文献采用了哪些方法研究纤维素结构？",
];
const pdf = (id: string, page = 1) =>
  apiPath(`literature/documents/${encodeURIComponent(id)}/pdf#page=${page}`);
const imageUrl = (checksum: string) => apiPath(`literature/images/${encodeURIComponent(checksum)}`);
const citation = (token: string) =>
  answer.value?.citations.find((c) => c.ref === token);
let libraryController: AbortController | undefined,
  answerController: AbortController | undefined;
async function load() {
  libraryController?.abort();
  const current = new AbortController();
  libraryController = current;
  loading.value = true;
  loadError.value = "";
  try {
    const result = await get<{ enabled: boolean; documents: Document[] }>(
      "literature/documents",
      {},
      current.signal,
    );
    if (!current.signal.aborted) {
      documents.value = result.documents;
      enabled.value = result.enabled;
    }
  } catch (e) {
    if (!current.signal.aborted) {
      loadError.value = e instanceof Error ? e.message : "文献库读取失败。";
      enabled.value = false;
    }
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
function showRecord(record: HistoryRecord) {
  selected.value = record;
  submitted.value = record.question;
  answer.value = record.status === "answered" || record.status === "refused" ? record.result : null;
  asking.value = record.status === "processing";
  const failures: Record<string, string> = {
    timeout: "本次问答超时，记录已保存，可以重新提问。",
    provider_error: "模型服务暂不可用，本次失败记录已保存。",
    retrieval_error: "文献检索失败，本次失败记录已保存。",
    worker_error: "文献问答处理失败，本次失败记录已保存。",
    service_restarted: "服务在处理期间中断，本次记录已保存，可以重新提问。",
  };
  error.value = record.status === "failed" || record.status === "interrupted"
    ? failures[record.reason_code ?? ""] ?? "本次处理失败，可以重新提问。" : "";
}
async function openRecord(id: string, keepQuestion = false) {
  clearTimeout(pollTimer);
  answerController?.abort();
  const version = ++selectionVersion;
  const current = new AbortController();
  answerController = current;
  const timer = window.setTimeout(() => current.abort(), 15000);
  try {
    const record = await literatureRequest<HistoryRecord>(`history/${encodeURIComponent(id)}`, undefined, current.signal);
    if (disposed || version !== selectionVersion) return;
    showRecord(record);
    if (!keepQuestion) question.value = record.question;
    if (record.status === "processing") {
      pollTimer = window.setTimeout(() => openRecord(id, true), 1500);
    } else {
      pendingSubmission = undefined;
      historyPanel.value?.refresh();
    }
  } catch (e) {
    if (disposed || version !== selectionVersion) return;
    asking.value = false;
    error.value = "暂时无法读取回答，请点击历史记录重试。已接收的问题会继续在后台处理。";
  } finally { clearTimeout(timer); }
}
function historyLoaded(latest?: HistoryItem) {
  historyReady.value = true;
  if (!selected.value && !pendingSubmission && latest) openRecord(latest.id);
}
async function ask(fresh = false) {
  if (!canAsk.value) return;
  clearTimeout(pollTimer);
  answerController?.abort();
  const version = ++selectionVersion;
  const current = new AbortController();
  answerController = current;
  asking.value = true;
  error.value = "";
  answer.value = null;
  selected.value = null;
  submitted.value = question.value.trim();
  if (fresh || !pendingSubmission || pendingSubmission.question !== submitted.value) {
    pendingSubmission = { question: submitted.value, request_id: crypto.randomUUID() };
  }
  const timeout = window.setTimeout(() => current.abort(), 15000);
  try {
    const record = await literatureRequest<HistoryRecord>("ask", pendingSubmission, current.signal);
    if (disposed || version !== selectionVersion) return;
    showRecord(record);
    historyPanel.value?.refresh();
    if (record.status === "processing") pollTimer = window.setTimeout(() => openRecord(record.id, true), 1000);
    else pendingSubmission = undefined;
  } catch (e) {
    if (disposed || version !== selectionVersion) return;
    asking.value = false;
    error.value = current.signal.aborted
      ? "提交响应超时，请先刷新历史确认是否已接收，重试会沿用本次提交编号。"
      : e instanceof TypeError || e instanceof SyntaxError
        ? "暂时无法连接文献问答服务，请检查连接后重试。"
        : e instanceof Error
          ? e.message
          : "文献问答暂不可用，请稍后重试。";
  } finally {
    clearTimeout(timeout);
  }
}
function reask() {
  if (!selected.value || asking.value) return;
  question.value = selected.value.question;
  ask(true);
}

/* ---------------------------------------------------------------- citations */
/*
 * A long excerpt starts as a clipped preview (v1 cite-card / v4 .ex) and opens in place.
 * Only excerpts taller than the preview get a toggle: a ResizeObserver measures the
 * unclipped content (KaTeX and tables change the height after mount).
 */
const PREVIEW_HEIGHT = 190; // keep in sync with --lit-preview below
const openCites = reactive(new Set<string>());
const tallCites = reactive(new Set<string>());
const highlighted = ref<string | null>(null);
const citeEls = new Map<string, HTMLElement>();
const citeObserver =
  typeof ResizeObserver === "undefined"
    ? undefined
    : new ResizeObserver((entries) => {
        for (const entry of entries) {
          const el = entry.target as HTMLElement,
            key = el.dataset.cite;
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
watch(answer, () => {
  openCites.clear();
  highlighted.value = null;
});
const collapsed = (c: Citation) => tallCites.has(c.ref) && !openCites.has(c.ref);
function toggleCite(key: string) {
  if (openCites.has(key)) openCites.delete(key);
  else openCites.add(key);
}
/** A keyboard user tabbing into a clipped preview (a table region, a link) opens it. */
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
const reviewTone = computed(() => {
  const status = answer.value?.review_summary?.status;
  return status === "completed" ? "ok" : status === "unresolved" || status === "incomplete" ? "warn" : "plain";
});

/* ---------------------------------------------------------------- library + garden signature */
const maxPages = computed(() => Math.max(1, ...documents.value.map((d) => d.page_count)));
/** share of the longest document, never thinner than a visible sliver */
const pageShare = (d: Document) => Math.max(0.08, d.page_count / maxPages.value);
const grouped = (n: number) => n.toLocaleString("zh-CN");
/* v4 literatureSig: one spine per document, height = PDF pages (real library data) */
const sig = computed(() => {
  const docs = documents.value;
  if (!docs.length) return null;
  const slot = 300 / docs.length,
    bw = Math.min(30, slot * 0.78);
  return {
    spines: docs.map((d, i) => {
      const h = 18 + (d.page_count / maxPages.value) * 92;
      return { id: d.id, x: i * slot, y: 116 - h, w: bw, h, pages: d.page_count, tone: `n${(i % 3) + 1}` };
    }),
    labels: slot >= 18,
    count: docs.length,
    pages: docs.reduce((sum, d) => sum + d.page_count, 0),
    chunks: docs.reduce((sum, d) => sum + d.chunk_count, 0),
  };
});

onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(pollTimer);
  libraryController?.abort();
  answerController?.abort();
  citeObserver?.disconnect();
});
load();
</script>

<template>
  <div class="overview literature-page">
    <PageHeader description="带着问题阅读文献，让每一条回答都有可查看的依据。">
      <template #actions>
        <span class="connection" :class="{ offline: !!loadError || (!loading && !enabled) }"
          ><span></span
          >{{ loading ? "正在读取" : loadError ? "连接待检查" : enabled ? "文献库已连接" : "问答未启用" }}</span
        ><button class="button" :disabled="loading || asking" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新文献库
        </button>
      </template>
      <template v-if="isGarden && (loading || sig)" #visual>
        <figure class="lit-sig">
          <svg
            v-if="sig"
            viewBox="0 0 420 134"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <g v-for="s in sig.spines" :key="s.id" class="sig-spine" :class="s.tone">
              <rect :x="s.x.toFixed(1)" :y="s.y.toFixed(1)" :width="s.w.toFixed(1)" :height="s.h.toFixed(1)" rx="7" />
              <line
                :x1="(s.x + 7).toFixed(1)"
                :x2="(s.x + s.w - 7).toFixed(1)"
                :y1="(s.y + 10).toFixed(1)"
                :y2="(s.y + 10).toFixed(1)"
              />
              <text v-if="sig.labels" class="sig-m" :x="(s.x + s.w / 2).toFixed(1)" y="130" text-anchor="middle">{{ s.pages }}</text>
            </g>
            <text class="sig-n" x="420" y="62" text-anchor="end">{{ sig.count }}</text>
            <text class="sig-t" x="420" y="84" text-anchor="end">篇文献</text>
            <text class="sig-m" x="420" y="104" text-anchor="end">{{ grouped(sig.chunks) }} 个片段</text>
          </svg>
          <div v-else class="lit-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            柱高 = PDF 页数 ·
            <span class="nw">共 <b>{{ sig ? grouped(sig.pages) : "—" }}</b> 页</span><template v-if="enabled"> · <span class="nw">不检索互联网</span></template>
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <div class="lit-main">
      <p v-if="loading" class="card lit-state lit-ask" role="status">
        <RefreshCw :size="18" class="spinning" aria-hidden="true" />正在读取文献库…
      </p>
      <div v-else-if="loadError" class="card lit-state lit-ask" role="alert">
        <p>{{ loadError }}</p>
        <button class="button" @click="load">重新加载</button>
      </div>
      <form v-else class="card lit-ask" aria-labelledby="literature-ask-title" @submit.prevent="ask()">
        <div class="lit-head">
          <h2 id="literature-ask-title"><label for="literature-question">你想了解什么？</label></h2>
        </div>
        <p id="literature-question-help" class="lit-sub">
          每次提问独立处理，问题和回答长期保存，所有访问者可查看。
        </p>
        <div class="lit-askbox">
          <textarea
            id="literature-question"
            v-model="question"
            maxlength="2000"
            rows="4"
            :disabled="asking"
            placeholder="例如：PFI 打浆如何影响纤维素的聚集结构？"
            aria-describedby="literature-question-help literature-question-count"
          />
          <div class="lit-askrow">
            <span id="literature-question-count" class="lit-count">{{ question.length }} / 2000</span>
            <button class="button primary lit-submit" type="submit" :disabled="!canAsk">
              <Send :size="15" />{{ asking ? "正在查阅…" : "开始提问" }}
            </button>
          </div>
        </div>
        <div class="lit-try">
          <span class="field-label">试着问</span
          ><button
            v-for="example in examples"
            :key="example"
            type="button"
            :disabled="asking"
            @click="question = example"
          >
            {{ example }}
          </button>
        </div>
      </form>

      <section
        v-if="asking"
        class="card lit-state lit-progress"
        role="status"
        aria-live="polite"
      >
        <div class="lit-progress-bar" aria-hidden="true"><i></i></div>
        <div class="lit-thinking" aria-hidden="true"><i></i><i></i><i></i></div>
        <BookOpen :size="26" aria-hidden="true" />
        <h2>正在查阅与分析</h2>
        <p>系统会按问题需要检索、阅读文献并复核答案，可能需要数分钟。已接收的问题会在后台继续处理，刷新后可从历史记录查看。</p>
      </section>
      <section v-if="error" class="card lit-state lit-error" role="alert">
        <p>{{ error }}</p>
        <button class="button" :disabled="!canAsk" @click="ask(!!selected)">{{ selected ? "重新提问" : "重试提交" }}</button>
      </section>

      <section
        v-if="answer"
        class="card lit-answer"
        aria-labelledby="answer-title"
      >
        <!-- the live region covers the answer itself, not the long excerpts below it -->
        <div class="lit-answer-live" aria-live="polite">
          <div class="lit-head">
            <h2 id="answer-title">
              {{ answer.status === "answered" ? "回答" : "暂时无法可靠回答" }}
            </h2>
            <span class="lit-badge" :class="{ warn: answer.status !== 'answered' }">{{
              answer.status === "answered"
                ? `${answer.citations.length} 条引用`
                : "证据不足或未通过引用校验"
            }}</span>
          </div>
          <p class="lit-q">{{ submitted }}</p>
          <div v-if="answer.review_summary" class="lit-review" :class="`tone-${reviewTone}`" role="status">
            <p><i aria-hidden="true"></i>{{ answer.review_summary.notice }}</p>
            <details v-if="answer.review_summary.unresolved.length">
              <summary>查看尚未解决的问题（{{ answer.review_summary.unresolved.length }}）</summary>
              <ul>
                <li v-for="item in answer.review_summary.unresolved" :key="item.id">
                  <strong>{{ item.requirement }}</strong>：{{ item.reason }}
                </li>
              </ul>
            </details>
          </div>
          <div class="lit-body">
            <p v-for="(block, index) in blocks" :key="index" :class="{ 'lit-lead': block.lead }">
              <template v-for="(part, j) in block.parts" :key="j"
                ><span v-if="part.cite && citation(part.text)" class="nw"
                  ><button
                    type="button"
                    class="lit-ref"
                    :aria-label="`查看引用 ${part.text}`"
                    @click="focusCitation(part.text)"
                  ><span class="lit-ref-br">[</span>{{ part.text.slice(1, -1) }}<span class="lit-ref-br">]</span></button
                  ><component :is="part.strong ? 'strong' : 'span'" v-if="part.after">{{ part.after }}</component></span
                ><code v-else-if="part.code">{{ part.text }}</code
                ><strong v-else-if="part.strong">{{ part.text }}{{ part.after }}</strong
                ><template v-else>{{ part.text }}{{ part.after }}</template></template
              >
            </p>
          </div>
          <p class="caveat lit-note">
            回答依据本次取得的文献或实验数据；引用用于追溯来源，不替代对研究结论和适用条件的判断。
          </p>
        </div>
        <div v-if="selected" class="lit-record">
          <span>已保存 · {{ timeLabel(selected.created_at) }}<template v-if="selected.latency_ms != null"> · 用时 {{ secondsLabel(selected.latency_ms) }}</template></span>
          <button class="button" :disabled="asking" @click="reask">重新提问</button>
        </div>

        <section
          v-if="answer.citations.length"
          class="lit-cites"
          aria-labelledby="literature-cites-title"
        >
          <h3 id="literature-cites-title">引用与原文片段 <span class="lit-cites-n">{{ answer.citations.length }}</span></h3>
          <ol>
            <li
              v-for="c in answer.citations"
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
                  :href="pdf(c.document_id, c.page_start)"
                  target="_blank"
                  rel="noopener"
                  :aria-label="`查看原文 ${c.filename} 第 ${c.page_start} 页`"
                  >查看原文<ExternalLink :size="13" aria-hidden="true"
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
      </section>
    </div>

    <LiteratureHistory
      ref="historyPanel"
      class="lit-history"
      :selected="selected?.id"
      @ready="historyLoaded"
      @select="openRecord"
    />

    <details v-if="!loading && !loadError" class="card lit-library" open>
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
  </div>
</template>

<style scoped>
/* =================================================================== page grid
   polarized (v1 .lit-grid): main column + 360px side (history over library)
   garden (v4 bento): ask + answer (2/3) beside history (1/3), library full width below
   The side blocks never share rows with the main column: .lit-main spans both side rows,
   and the last row is 1fr, so the history keeps its own height. */
.literature-page {
  --lit-preview: 190px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.literature-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.literature-page > .page-header {
  margin-bottom: 4px;
}
.lit-main {
  display: grid;
  gap: 18px;
  min-width: 0;
  align-content: start;
}
:root[data-mode="polarized"] .literature-page {
  grid-template-columns: minmax(0, 1fr) 360px;
  grid-template-rows: auto auto 1fr;
}
:root[data-mode="polarized"] .lit-main {
  grid-column: 1;
  grid-row: 2 / span 2;
}
:root[data-mode="polarized"] .lit-history {
  grid-column: 2;
  grid-row: 2;
}
:root[data-mode="polarized"] .lit-library {
  grid-column: 2;
  grid-row: 3;
}
:root[data-mode="garden"] .literature-page {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}
:root[data-mode="garden"] .lit-main {
  grid-column: 1;
  grid-row: 2;
}
:root[data-mode="garden"] .lit-history {
  grid-column: 2;
  grid-row: 2;
}
:root[data-mode="garden"] .lit-library {
  grid-column: 1 / -1;
  grid-row: 3;
}

/* =================================================================== shared card parts */
.lit-ask,
.lit-answer,
.lit-library {
  padding: 22px;
}
:root[data-mode="garden"] .lit-ask,
:root[data-mode="garden"] .lit-answer,
:root[data-mode="garden"] .lit-library {
  padding: 22px 24px;
}
.lit-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 12px;
}
.lit-head h2,
.lit-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
.lit-head h2 label {
  cursor: text;
}
:root[data-mode="garden"] .lit-head h2,
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
.lit-badge.warn {
  color: var(--warn);
}
:root[data-mode="polarized"] .lit-badge.warn {
  border-color: color-mix(in srgb, var(--warn) 45%, transparent);
}
.nw {
  white-space: nowrap;
}

/* =================================================================== states */
.lit-state {
  padding: 26px 22px;
  text-align: center;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.8;
}
p.lit-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.lit-state > svg {
  color: var(--accent-ink);
}
.lit-state h2 {
  margin: 8px 0 4px;
  font-size: 16px;
  color: var(--text);
}
.lit-state .button {
  margin-top: 10px;
}
.lit-error {
  text-align: left;
}
:root[data-mode="polarized"] .lit-error {
  box-shadow: inset 2px 0 0 var(--bad);
}
:root[data-mode="garden"] .lit-error {
  background: linear-gradient(160deg, var(--surface), var(--bad-tint));
}
.lit-error p {
  color: var(--text);
}
/* asking: an indeterminate interference bar (polarized) or three pulsing stain dots (garden).
   Nothing here pretends to know how far along the answer is. */
.lit-progress {
  position: relative;
  overflow: hidden;
}
.lit-progress-bar {
  display: none;
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 3px;
  background: var(--line-soft);
  overflow: hidden;
}
.lit-progress-bar i {
  display: block;
  width: 38%;
  height: 100%;
  background: var(--ifl, var(--accent));
  animation: lit-scan 1.6s var(--ease) infinite;
}
@keyframes lit-scan {
  from {
    translate: -100% 0;
  }
  to {
    translate: 270% 0;
  }
}
:root[data-mode="polarized"] .lit-progress-bar {
  display: block;
}
.lit-thinking {
  display: none;
  justify-content: center;
  gap: 8px;
  margin-bottom: 10px;
}
.lit-thinking i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--sw);
  animation: lit-pulse 1s ease-in-out infinite alternate;
}
.lit-thinking i:nth-child(2) {
  background: var(--hw);
  border-radius: 2px;
  animation-delay: 0.2s;
}
.lit-thinking i:nth-child(3) {
  background: var(--bl);
  border-radius: 0;
  clip-path: polygon(50% 0, 100% 100%, 0 100%);
  animation-delay: 0.4s;
}
@keyframes lit-pulse {
  to {
    opacity: 0.35;
    scale: 0.8;
  }
}
:root[data-mode="garden"] .lit-thinking {
  display: flex;
}
:root[data-mode="garden"] .lit-progress > svg {
  display: none;
}

/* =================================================================== ask */
.lit-askbox {
  margin-top: 14px;
}
.lit-askbox textarea {
  display: block;
  width: 100%;
  min-height: 120px;
  max-height: 360px;
  resize: vertical;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text);
}
.lit-askbox textarea::placeholder {
  color: var(--text-3);
}
.lit-askbox textarea:disabled {
  opacity: 0.6;
  cursor: progress;
}
.lit-askrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.lit-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.lit-submit {
  flex-shrink: 0;
}
/* v1 .ask-box: one dark well holding the textarea and its counter row */
:root[data-mode="polarized"] .lit-askbox {
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: color-mix(in srgb, var(--bg) 62%, transparent);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
:root[data-mode="polarized"] .lit-askbox:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .lit-askbox:has(textarea:focus-visible) {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 28%, transparent);
}
:root[data-mode="polarized"] .lit-askbox textarea {
  padding: 12px;
  border: 0;
  background: transparent;
}
:root[data-mode="polarized"] .lit-askbox textarea:focus-visible {
  outline: none;
}
:root[data-mode="polarized"] .lit-askrow {
  padding: 6px 6px 6px 12px;
}
/* v4 .textarea: a soft glass well; the counter and button sit under it */
:root[data-mode="garden"] .lit-askbox textarea {
  padding: 16px 18px;
  border: 0;
  border-radius: 22px;
  background: var(--surface-2);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    inset 0 2px 10px color-mix(in srgb, var(--accent) 7%, transparent);
}
:root[data-mode="garden"] .lit-askrow {
  margin-top: 12px;
  padding-left: 4px;
}
.lit-try {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}
.lit-try .field-label {
  margin: 0 4px 0 0;
}
:root[data-mode="polarized"] .lit-try .field-label {
  flex-basis: 100%;
  margin-bottom: 2px;
}
.lit-try button {
  min-height: 34px;
  padding: 6px 13px;
  border-radius: 999px;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  color: var(--text-2);
  transition:
    color 0.18s,
    border-color 0.18s,
    background 0.2s,
    transform 0.3s var(--spring);
}
:root[data-mode="polarized"] .lit-try button {
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--text) 2.5%, transparent);
}
:root[data-mode="polarized"] .lit-try button:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--line-strong);
}
:root[data-mode="garden"] .lit-try button {
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface), var(--shadow-sm);
}
:root[data-mode="garden"] .lit-try button:hover:not(:disabled) {
  background: var(--surface);
  transform: translateY(-2px);
}

/* =================================================================== answer */
.lit-q {
  margin: 14px 0 12px;
  font-size: 14.5px;
  line-height: 1.7;
  color: var(--text);
  overflow-wrap: anywhere;
}
/* v1 .ans-q: quoted question with a cyan rule */
:root[data-mode="polarized"] .lit-q {
  padding: 14px 16px;
  border-radius: 12px;
  border-left: 2px solid var(--accent);
  background: color-mix(in srgb, var(--text) 3.5%, transparent);
}
/* v4 .qbubble: a speech bubble */
:root[data-mode="garden"] .lit-q {
  padding: 14px 18px;
  border-radius: 22px 22px 22px 6px;
  background: var(--surface-2);
  box-shadow: inset 0 0 0 1px var(--surface);
}
.lit-review {
  --st: var(--text-3);
  --st-tint: var(--surface-2);
  --st-ink: var(--text-2);
  margin-bottom: 14px;
  font-size: 12.5px;
  line-height: 1.7;
}
.lit-review.tone-ok {
  --st: var(--ok);
  --st-tint: var(--ok-tint);
  --st-ink: var(--ok);
}
.lit-review.tone-warn {
  --st: var(--warn);
  --st-tint: var(--warn-tint);
  --st-ink: var(--warn);
}
.lit-review > p {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--text-2);
}
.lit-review > p > i {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--st);
  translate: 0 -1px;
}
:root[data-mode="garden"] .lit-review > p {
  display: inline-flex;
  padding: 4px 12px;
  border-radius: 14px;
  background: var(--st-tint);
  color: var(--st-ink);
  font-weight: 500;
}
:root[data-mode="garden"] .lit-review.tone-plain > p {
  font-weight: 400;
}
.lit-review details {
  margin-top: 8px;
  color: var(--text-2);
}
.lit-review summary {
  cursor: pointer;
  width: fit-content;
  border-radius: var(--radius-xs);
}
.lit-review ul {
  margin: 6px 0 0;
  padding-left: 20px;
}
.lit-review li strong {
  color: var(--text);
  font-weight: 500;
}
.lit-body {
  font-size: 15px;
  line-height: 1.95;
  color: var(--text);
  overflow-wrap: anywhere;
}
:root[data-mode="polarized"] .lit-body {
  color: color-mix(in oklab, var(--text) 86%, var(--text-2));
}
.lit-body p {
  margin: 0 0 12px;
}
.lit-body .lit-lead {
  margin: 18px 0 6px;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.6;
  color: var(--text);
}
:root[data-mode="garden"] .lit-body .lit-lead {
  font-weight: 500;
  font-size: 16.5px;
}
.lit-body .lit-lead:first-child {
  margin-top: 2px;
}
.lit-body strong {
  font-weight: 700;
  color: var(--text);
}
.lit-body code {
  font-family: var(--font-mono);
  font-size: 0.84em;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  overflow-wrap: anywhere;
}
:root[data-mode="polarized"] .lit-body code {
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
:root[data-mode="garden"] .lit-body code {
  background: var(--bl-tint);
}
.lit-ref {
  display: inline-grid;
  grid-auto-flow: column;
  place-items: center;
  min-width: 22px;
  height: 20px;
  margin: 0 2px;
  padding: 0 5px;
  vertical-align: 2px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1;
  transition:
    background 0.2s,
    color 0.2s,
    transform 0.3s var(--spring);
}
:root[data-mode="polarized"] .lit-ref {
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  background: var(--accent-tint);
  color: var(--accent-ink);
}
:root[data-mode="polarized"] .lit-ref:hover {
  background: color-mix(in srgb, var(--accent) 26%, transparent);
  color: var(--text);
}
:root[data-mode="polarized"] .lit-ref-br {
  display: none;
}
:root[data-mode="garden"] .lit-ref {
  padding: 0 6px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--bl-tint);
  color: var(--bl-ink);
}
:root[data-mode="garden"] .lit-ref:hover {
  background: color-mix(in oklab, var(--bl) 30%, var(--surface));
  color: var(--text);
  transform: translateY(-1px);
}
.lit-note {
  margin-top: 4px;
}
.lit-record {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
.lit-record .button {
  font-family: var(--font-body);
}
:root[data-mode="polarized"] .lit-record .button {
  min-height: 32px;
  padding: 0 12px;
  font-size: 13px;
}

/* =================================================================== citations */
.lit-cites {
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
/* kind identity: database (v1 gold edge / v4 green badge), paper text and figures (v1
   magenta edge / v4 neutral badge), arithmetic */
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

/* =================================================================== library */
.lit-library {
  container-type: inline-size;
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
/* v1 .doc: a page-count spine filled with the interference gradient, name, mono meta, pill */
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
/* v4 .docs: glass document tiles, a stain bar as long as the page count, "No. 01" */
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

/* =================================================================== garden hero signature (v4 literatureSig) */
.lit-sig {
  position: relative;
  margin: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lit-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 146px;
  overflow: visible;
}
.lit-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 134;
}
.lit-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.lit-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.sig-spine.n1 {
  --n: var(--accent);
}
.sig-spine.n2 {
  --n: color-mix(in oklab, var(--accent) 78%, var(--surface));
}
.sig-spine.n3 {
  --n: color-mix(in oklab, var(--accent) 62%, var(--surface));
}
.sig-spine rect {
  fill: var(--n);
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: lit-grow 0.9s var(--spring) backwards;
}
.sig-spine:nth-child(2) rect {
  animation-delay: 0.05s;
}
.sig-spine:nth-child(3) rect {
  animation-delay: 0.1s;
}
.sig-spine:nth-child(4) rect {
  animation-delay: 0.15s;
}
.sig-spine:nth-child(n + 5) rect {
  animation-delay: 0.2s;
}
@keyframes lit-grow {
  from {
    scale: 1 0.2;
    opacity: 0;
  }
}
.sig-spine line {
  stroke: var(--surface);
  stroke-opacity: 0.7;
  stroke-width: 1.4;
}
.sig-n {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 0, "opsz" 144;
  font-size: 46px;
  font-weight: 340;
  letter-spacing: -0.02em;
  fill: var(--text);
}
.sig-t {
  font-family: var(--font-body);
  font-size: 11.5px;
  fill: var(--text-2);
}
.sig-m {
  font-family: var(--font-mono);
  font-size: 10.5px;
  fill: var(--text-2);
}

/* =================================================================== responsive
   One column: the main column's blocks join the page grid (display: contents), so the
   history can sit between the question and the answer (v4 bento order). */
@media (max-width: 1100px) {
  :root[data-mode="polarized"] .literature-page {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: none;
  }
  :root[data-mode="polarized"] .lit-main {
    display: contents;
  }
  :root[data-mode="polarized"] .lit-main > *,
  :root[data-mode="polarized"] .lit-history,
  :root[data-mode="polarized"] .lit-library {
    grid-column: 1;
    grid-row: auto;
  }
  :root[data-mode="polarized"] .lit-ask {
    order: 1;
  }
  :root[data-mode="polarized"] .lit-history {
    order: 2;
  }
  :root[data-mode="polarized"] .lit-progress,
  :root[data-mode="polarized"] .lit-error,
  :root[data-mode="polarized"] .lit-answer {
    order: 3;
  }
  :root[data-mode="polarized"] .lit-library {
    order: 4;
  }
}
@media (max-width: 980px) {
  :root[data-mode="garden"] .literature-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .lit-main {
    display: contents;
  }
  :root[data-mode="garden"] .lit-main > *,
  :root[data-mode="garden"] .lit-history,
  :root[data-mode="garden"] .lit-library {
    grid-column: 1;
    grid-row: auto;
  }
  :root[data-mode="garden"] .lit-ask {
    order: 1;
  }
  :root[data-mode="garden"] .lit-history {
    order: 2;
  }
  :root[data-mode="garden"] .lit-progress,
  :root[data-mode="garden"] .lit-error,
  :root[data-mode="garden"] .lit-answer {
    order: 3;
  }
  :root[data-mode="garden"] .lit-library {
    order: 4;
  }
}
@media (max-width: 720px) {
  .literature-page {
    gap: 14px;
  }
  .lit-ask,
  .lit-answer,
  .lit-library,
  :root[data-mode="garden"] .lit-ask,
  :root[data-mode="garden"] .lit-answer,
  :root[data-mode="garden"] .lit-library {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .lit-ask,
  :root[data-mode="garden"] .lit-answer,
  :root[data-mode="garden"] .lit-library,
  :root[data-mode="garden"] .lit-state {
    border-radius: 24px;
  }
  .lit-askbox textarea {
    font-size: 14.5px;
  }
  .lit-body {
    font-size: 14.5px;
    line-height: 1.9;
  }
  .lit-cite,
  :root[data-mode="garden"] .lit-cite {
    padding: 12px;
  }
  .lit-fields > div {
    grid-template-columns: minmax(0, 1fr);
  }
  .lit-sig {
    width: 100%;
  }
}
</style>
