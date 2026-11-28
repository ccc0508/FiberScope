<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { BookOpen, RefreshCw, Send } from "lucide-vue-next";
import { get } from "../api";
import { isGarden } from "../mode";
import PageHeader from "../components/PageHeader.vue";
import LiteratureHistory from "../components/LiteratureHistory.vue";
import LiteratureCitations from "../components/literature/LiteratureCitations.vue";
import LiteratureLibrary, { type LibraryDocument } from "../components/literature/LiteratureLibrary.vue";
import { useAbortablePolling } from "../composables/useAbortablePolling";
import {
  answerBlocks,
  literatureRequest,
  secondsLabel,
  timeLabel,
  type Answer,
  type HistoryItem,
  type HistoryRecord,
} from "../literature";

const documents = ref<LibraryDocument[]>([]);
const enabled = ref(false);
const generalQuestions = ref(false);
const loading = ref(true);
const loadError = ref("");
const question = ref("");
const submitted = ref("");
const asking = ref(false);
const error = ref("");
const answer = ref<Answer | null>(null);
const historyPanel = ref<InstanceType<typeof LiteratureHistory>>();
const citationsPanel = ref<InstanceType<typeof LiteratureCitations>>();
const historyReady = ref(false);
const selected = ref<HistoryRecord | null>(null);

let pendingSubmission: { question: string; request_id: string } | undefined;
let libraryController: AbortController | undefined;
let answerController: AbortController | undefined;
const polling = useAbortablePolling();

const canAsk = computed(
  () =>
    enabled.value &&
    (generalQuestions.value || documents.value.length > 0) &&
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
const citation = (token: string) => answer.value?.citations.find((c) => c.ref === token);

async function load() {
  libraryController?.abort();
  const current = new AbortController();
  libraryController = current;
  loading.value = true;
  loadError.value = "";
  try {
    const result = await get<{ enabled: boolean; documents: LibraryDocument[]; supports_general_questions?: boolean }>(
      "literature/documents",
      {},
      current.signal,
    );
    if (!current.signal.aborted) {
      documents.value = result.documents;
      enabled.value = result.enabled;
      generalQuestions.value = result.supports_general_questions ?? false;
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
    initial_decision_format_failed: "首轮任务计划无法读取，本次失败记录已保存。",
    worker_error: "文献问答处理失败，本次失败记录已保存。",
    service_restarted: "服务在处理期间中断，本次记录已保存，可以重新提问。",
  };
  error.value =
    record.status === "failed" || record.status === "interrupted"
      ? failures[record.reason_code ?? ""] ?? "本次处理失败，可以重新提问。"
      : "";
}

async function openRecord(id: string, keepQuestion = false) {
  polling.clearPoll();
  answerController?.abort();
  const version = polling.nextVersion();
  const req = polling.createAbortable(15000);
  answerController = req.controller;
  try {
    const record = await literatureRequest<HistoryRecord>(`history/${encodeURIComponent(id)}`, undefined, req.signal);
    if (!polling.isCurrent(version)) return;
    showRecord(record);
    if (!keepQuestion) question.value = record.question;
    if (record.status === "processing") {
      polling.schedulePoll(() => openRecord(id, true), 1500);
    } else {
      pendingSubmission = undefined;
      historyPanel.value?.refresh();
    }
  } catch {
    if (!polling.isCurrent(version)) return;
    asking.value = false;
    error.value = "暂时无法读取回答，请点击历史记录重试。已接收的问题会继续在后台处理。";
  } finally {
    req.cleanup();
  }
}

function historyLoaded(latest?: HistoryItem) {
  historyReady.value = true;
  if (!selected.value && !pendingSubmission && latest) openRecord(latest.id);
}

async function ask(fresh = false) {
  if (!canAsk.value) return;
  polling.clearPoll();
  answerController?.abort();
  const version = polling.nextVersion();
  const req = polling.createAbortable(15000);
  answerController = req.controller;
  asking.value = true;
  error.value = "";
  answer.value = null;
  selected.value = null;
  submitted.value = question.value.trim();
  if (fresh || !pendingSubmission || pendingSubmission.question !== submitted.value) {
    pendingSubmission = { question: submitted.value, request_id: crypto.randomUUID() };
  }
  try {
    const record = await literatureRequest<HistoryRecord>("ask", pendingSubmission, req.signal);
    if (!polling.isCurrent(version)) return;
    showRecord(record);
    historyPanel.value?.refresh();
    if (record.status === "processing") polling.schedulePoll(() => openRecord(record.id, true), 1000);
    else pendingSubmission = undefined;
  } catch (e) {
    if (!polling.isCurrent(version)) return;
    asking.value = false;
    error.value = req.signal.aborted
      ? "提交响应超时，请先刷新历史确认是否已接收，重试会沿用本次提交编号。"
      : e instanceof TypeError || e instanceof SyntaxError
        ? "暂时无法连接文献问答服务，请检查连接后重试。"
        : e instanceof Error
          ? e.message
          : "文献问答暂不可用，请稍后重试。";
  } finally {
    req.cleanup();
  }
}

function reask() {
  if (!selected.value || asking.value) return;
  question.value = selected.value.question;
  ask(true);
}

const reviewTone = computed(() => {
  const status = answer.value?.review_summary?.status;
  return status === "completed" ? "ok" : status === "unresolved" || status === "incomplete" ? "warn" : "plain";
});

const maxPages = computed(() => Math.max(1, ...documents.value.map((d) => d.page_count)));
const grouped = (n: number) => n.toLocaleString("zh-CN");
const sig = computed(() => {
  const docs = documents.value;
  if (!docs.length) return null;
  const slot = 300 / docs.length;
  const bw = Math.min(30, slot * 0.78);
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
  libraryController?.abort();
  answerController?.abort();
});

load();
</script>

<template>
  <div class="overview literature-page">
    <PageHeader description="带着问题阅读文献，让每一条回答都有可查看的依据。">
      <template #actions>
        <span class="connection" :class="{ offline: !!loadError || (!loading && !enabled) }"
          ><span></span
          >{{ loading ? "正在读取" : loadError ? "连接待检查" : enabled ? (documents.length ? "文献库已连接" : "问答已启用") : "问答未启用" }}</span
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
            <span class="nw">共 <b>{{ sig ? grouped(sig.pages) : "—" }}</b> 页</span><template v-if="enabled"> · <span class="nw">{{ generalQuestions ? "科研问答使用本地证据" : "不检索互联网" }}</span></template>
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
        <div class="lit-answer-live" aria-live="polite">
          <div class="lit-head">
            <h2 id="answer-title">
              {{ answer.status === "answered" ? "回答" : "暂时无法可靠回答" }}
            </h2>
            <span v-if="answer.status !== 'answered' || answer.citations.length" class="lit-badge" :class="{ warn: answer.status !== 'answered' }">{{
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
                    @click="citationsPanel?.focusCitation(part.text)"
                  ><span class="lit-ref-br">[</span>{{ part.text.slice(1, -1) }}<span class="lit-ref-br">]</span></button
                  ><component :is="part.strong ? 'strong' : 'span'" v-if="part.after">{{ part.after }}</component></span
                ><code v-else-if="part.code">{{ part.text }}</code
                ><strong v-else-if="part.strong">{{ part.text }}{{ part.after }}</strong
                ><template v-else>{{ part.text }}{{ part.after }}</template></template
              >
            </p>
          </div>
          <div v-if="answer.public_web_sources?.length" class="lit-note">
            <h3>网页来源</h3>
            <ol>
              <li v-for="source in answer.public_web_sources" :key="source.index" :value="source.index">
                <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
              </li>
            </ol>
          </div>
          <p v-if="answer.citations.length" class="caveat lit-note">
            回答依据本次取得的文献或实验数据；引用用于追溯来源，不替代对研究结论和适用条件的判断。
          </p>
        </div>
        <div v-if="selected" class="lit-record">
          <span>已保存 · {{ timeLabel(selected.created_at) }}<template v-if="selected.latency_ms != null"> · 用时 {{ secondsLabel(selected.latency_ms) }}</template></span>
          <button class="button" :disabled="asking" @click="reask">重新提问</button>
        </div>

        <LiteratureCitations ref="citationsPanel" :citations="answer.citations" :selected="selected" />
      </section>
    </div>

    <LiteratureHistory
      ref="historyPanel"
      class="lit-history"
      :selected="selected?.id"
      @ready="historyLoaded"
      @select="openRecord"
    />

    <LiteratureLibrary v-if="!loading && !loadError" :documents="documents" :enabled="enabled" />
  </div>
</template>

<style scoped>
.literature-page {
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

.lit-ask,
.lit-answer {
  padding: 22px;
}
:root[data-mode="garden"] .lit-ask,
:root[data-mode="garden"] .lit-answer {
  padding: 22px 24px;
}
.lit-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 12px;
}
.lit-head h2 {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
.lit-head h2 label {
  cursor: text;
}
:root[data-mode="garden"] .lit-head h2 {
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
  from { translate: -100% 0; }
  to { translate: 270% 0; }
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
  to { opacity: 0.35; scale: 0.8; }
}
:root[data-mode="garden"] .lit-thinking {
  display: flex;
}
:root[data-mode="garden"] .lit-progress > svg {
  display: none;
}

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
:root[data-mode="polarized"] .lit-askbox {
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: color-mix(in srgb, var(--bg) 62%, transparent);
  transition: border-color 0.2s, box-shadow 0.2s;
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
  transition: color 0.18s, border-color 0.18s, background 0.2s, transform 0.3s var(--spring);
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

.lit-q {
  margin: 14px 0 12px;
  font-size: 14.5px;
  line-height: 1.7;
  color: var(--text);
  overflow-wrap: anywhere;
}
:root[data-mode="polarized"] .lit-q {
  padding: 14px 16px;
  border-radius: 12px;
  border-left: 2px solid var(--accent);
  background: color-mix(in srgb, var(--text) 3.5%, transparent);
}
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
  transition: background 0.2s, color 0.2s, transform 0.3s var(--spring);
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
.sig-spine.n1 { --n: var(--accent); }
.sig-spine.n2 { --n: color-mix(in oklab, var(--accent) 78%, var(--surface)); }
.sig-spine.n3 { --n: color-mix(in oklab, var(--accent) 62%, var(--surface)); }
.sig-spine rect {
  fill: var(--n);
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: lit-grow 0.9s var(--spring) backwards;
}
.sig-spine:nth-child(2) rect { animation-delay: 0.05s; }
.sig-spine:nth-child(3) rect { animation-delay: 0.1s; }
.sig-spine:nth-child(4) rect { animation-delay: 0.15s; }
.sig-spine:nth-child(n + 5) rect { animation-delay: 0.2s; }
@keyframes lit-grow {
  from { scale: 1 0.2; opacity: 0; }
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
  :root[data-mode="polarized"] .lit-ask { order: 1; }
  :root[data-mode="polarized"] .lit-history { order: 2; }
  :root[data-mode="polarized"] .lit-progress,
  :root[data-mode="polarized"] .lit-error,
  :root[data-mode="polarized"] .lit-answer { order: 3; }
  :root[data-mode="polarized"] .lit-library { order: 4; }
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
  :root[data-mode="garden"] .lit-ask { order: 1; }
  :root[data-mode="garden"] .lit-history { order: 2; }
  :root[data-mode="garden"] .lit-progress,
  :root[data-mode="garden"] .lit-error,
  :root[data-mode="garden"] .lit-answer { order: 3; }
  :root[data-mode="garden"] .lit-library { order: 4; }
}
@media (max-width: 720px) {
  .literature-page {
    gap: 14px;
  }
  .lit-ask,
  .lit-answer,
  :root[data-mode="garden"] .lit-ask,
  :root[data-mode="garden"] .lit-answer {
    padding: 18px 16px;
  }
  :root[data-mode="garden"] .lit-ask,
  :root[data-mode="garden"] .lit-answer,
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
  .lit-sig {
    width: 100%;
  }
}
</style>
