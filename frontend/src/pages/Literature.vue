<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import {
  BookOpen,
  FileText,
  Send,
  RefreshCw,
  ExternalLink,
} from "lucide-vue-next";
import { get } from "../api";
import { apiPath } from "../urls";
import LiteratureHistory from "../components/LiteratureHistory.vue";
import { literatureRequest, feedbackTags, timeLabel, type Answer, type HistoryRecord, type HistoryItem, type Feedback } from "../literature";

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
const rating = ref<Feedback["rating"] | "">(""), tags = ref<string[]>([]), note = ref("");
const feedbackSaving = ref(false), feedbackError = ref(""), feedbackSaved = ref(false);
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
const lines = computed(
  () =>
    answer.value?.answer
      .split("\n")
      .filter(Boolean)
      .map((line) => line.split(/(\[\d+\])/g)) ?? [],
);
const examples = [
  "PFI 打浆如何影响纤维素的聚集结构？",
  "这篇文献采用了哪些方法研究纤维素结构？",
];
const pdf = (id: string, page = 1) =>
  apiPath(`literature/documents/${encodeURIComponent(id)}/pdf#page=${page}`);
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
  rating.value = record.feedback?.rating ?? "";
  tags.value = [...(record.feedback?.tags ?? [])];
  note.value = record.feedback?.note ?? "";
  feedbackSaved.value = !!record.feedback;
  feedbackError.value = "";
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
async function saveFeedback(value?: Feedback["rating"]) {
  if (!selected.value || !selected.value.can_feedback || feedbackSaving.value) return;
  if (value) { rating.value = value; tags.value = []; }
  if (!rating.value) return;
  const id = selected.value.id;
  feedbackSaving.value = true; feedbackError.value = ""; feedbackSaved.value = false;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const feedback = await literatureRequest<Feedback>(`history/${id}/feedback`, { rating: rating.value, tags: rating.value === "helpful" ? [] : tags.value, note: note.value }, controller.signal);
    if (disposed || selected.value?.id !== id) return;
    selected.value.feedback = feedback;
    feedbackSaved.value = true;
  } catch (e) {
    if (!disposed && selected.value?.id === id) feedbackError.value = e instanceof Error ? e.message : "评价保存失败，请重试。";
  } finally { clearTimeout(timer); feedbackSaving.value = false; }
}
function focusCitation(ref: string) {
  document.getElementById(`literature-citation-${ref.slice(1, -1)}`)?.focus();
}
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(pollTimer);
  libraryController?.abort();
  answerController?.abort();
});
load();
</script>

<template>
  <div class="overview literature-page">
    <section class="page-heading">
      <div>
        <span class="eyebrow"><BookOpen :size="14" /> 科研助手</span>
        <h1>文献问答</h1>
        <p>带着问题阅读文献，让每一条回答都有可查看的依据。</p>
      </div>
      <button class="button" :disabled="loading || asking" @click="load">
        <RefreshCw :size="15" />刷新文献库
      </button>
    </section>
    <LiteratureHistory ref="historyPanel" :selected="selected?.id" @ready="historyLoaded" @select="openRecord" />
    <p v-if="loading" class="card literature-state" role="status">
      正在读取文献库…
    </p>
    <div v-else-if="loadError" class="card literature-state" role="alert">
      <p>{{ loadError }}</p>
      <button class="button" @click="load">重新加载</button>
    </div>
    <template v-else>
      <details class="card library" open>
        <summary>
          <span>当前文献库</span
          ><span class="library-count">{{ documents.length }} 篇文献</span>
        </summary>
        <p class="muted">
          {{
            enabled
              ? "仅依据以下已导入文献回答，不检索互联网，也不查询实验数据库。"
              : "文献问答尚未启用，请先配置文献库和模型服务。"
          }}
        </p>
        <div v-for="doc in documents" :key="doc.id" class="library-document">
          <FileText :size="22" />
          <div>
            <strong>{{ doc.filename }}</strong
            ><small
              >{{ doc.page_count }} 页 · {{ doc.chunk_count }} 个文本片段</small
            >
          </div>
          <a
            class="text-link"
            :href="pdf(doc.id)"
            target="_blank"
            rel="noopener"
            >阅读原文<ExternalLink :size="13"
          /></a>
        </div>
        <p v-if="enabled && !documents.length" class="muted">
          暂无已完成导入的文献，请先补充文献。
        </p>
      </details>
      <form class="card question-card" @submit.prevent="ask()">
        <label for="literature-question">你想了解什么？</label
        ><textarea
          id="literature-question"
          v-model="question"
          maxlength="2000"
          rows="4"
          :disabled="asking"
          placeholder="例如：PFI 打浆如何影响纤维素的聚集结构？"
          aria-describedby="literature-question-help"
        />
        <div class="question-foot">
          <p id="literature-question-help">
            每次提问独立处理，问题和回答长期保存，所有访问者可查看。<span
              >{{ question.length }} / 2000</span
            >
          </p>
          <button class="button primary" type="submit" :disabled="!canAsk">
            <Send :size="15" />{{ asking ? "正在查阅…" : "开始提问" }}
          </button>
        </div>
        <div class="example-questions">
          <span>试着问</span
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
    </template>
    <section
      v-if="asking"
      class="card literature-state"
      role="status"
      aria-live="polite"
    >
      <BookOpen :size="26" />
      <h2>正在检索文献并核对引用</h2>
      <p>回答可能需要几十秒。已接收的问题会在后台继续处理，刷新后可从历史记录查看。</p>
    </section>
    <section v-if="error" class="card literature-state" role="alert">
      <p>{{ error }}</p>
      <button class="button" :disabled="!canAsk" @click="ask(!!selected)">{{ selected ? "重新提问" : "重试提交" }}</button>
    </section>
    <section
      v-if="answer"
      class="card answer-card"
      aria-live="polite"
      aria-labelledby="answer-title"
    >
      <div class="answer-heading">
        <h2 id="answer-title">
          {{
            answer.status === "answered" ? "文献中的回答" : "暂时无法可靠回答"
          }}
        </h2>
        <span>{{
          answer.status === "answered"
            ? `${answer.citations.length} 条引用`
            : "证据不足或未通过引用校验"
        }}</span>
      </div>
      <p class="submitted-question">{{ submitted }}</p>
      <div class="answer-content">
        <p v-for="(line, index) in lines" :key="index">
          <template v-for="(part, j) in line" :key="j"
            ><button
              v-if="citation(part)"
              class="citation-ref"
              :aria-label="`查看引用 ${part}`"
              @click="focusCitation(part)"
            >
              {{ part }}</button
            ><template v-else>{{ part }}</template></template
          >
        </p>
      </div>
      <p class="answer-note">
        回答仅反映当前文献中的证据。引用校验确保来源可追溯，不替代对研究结论和适用条件的判断。
      </p>
      <div v-if="selected" class="record-info">
        <span>已保存 · {{ timeLabel(selected.created_at) }}<template v-if="selected.latency_ms != null"> · 用时 {{ (selected.latency_ms / 1000).toFixed(1) }} 秒</template></span>
        <button class="button" :disabled="asking || feedbackSaving" @click="reask">重新提问</button>
      </div>
      <section v-if="selected?.can_feedback" class="feedback-section" aria-label="用户反馈">
        <h3>这个回答对你有帮助吗？</h3>
        <div class="feedback-actions">
          <button :class="['button', { chosen: rating === 'helpful' }]" :disabled="feedbackSaving" @click="saveFeedback('helpful')">有帮助</button>
          <button :class="['button', { chosen: rating === 'inaccurate' }]" :disabled="feedbackSaving" @click="rating = 'inaccurate'; feedbackSaved = false">不准确</button>
          <span v-if="feedbackSaving" role="status">正在保存…</span><span v-else-if="feedbackSaved" role="status">评价已保存，可修改</span>
        </div>
        <form v-if="rating === 'inaccurate'" @submit.prevent="saveFeedback()">
          <fieldset :disabled="feedbackSaving"><legend>哪些地方需要改进？（可多选）</legend>
            <label v-for="tag in feedbackTags" :key="tag.key"><input v-model="tags" type="checkbox" :value="tag.key" @change="feedbackSaved = false" />{{ tag.label }}</label>
          </fieldset>
          <label class="feedback-note" for="feedback-note">补充说明（选填）</label>
          <textarea id="feedback-note" v-model="note" maxlength="2000" rows="3" :disabled="feedbackSaving" placeholder="例如：这项数值与原文表格不一致。" @input="feedbackSaved = false" />
          <button class="button" :disabled="feedbackSaving" type="submit">保存评价</button>
        </form>
        <p v-if="feedbackError" class="feedback-error" role="alert">{{ feedbackError }}</p>
        <p class="answer-note">评价用于改进问答，不代表专家审核或标准答案。</p>
      </section>
      <section v-else-if="selected" class="feedback-section" aria-label="已保存的用户反馈">
        <h3>用户反馈</h3>
        <p v-if="selected.feedback" class="answer-note">
          {{ selected.feedback.rating === 'helpful' ? '有帮助' : '不准确' }}
          <template v-if="selected.feedback.tags.length"> · {{ selected.feedback.tags.map(t => feedbackTags.find(tag => tag.key === t)?.label ?? t).join('、') }}</template>
          <template v-if="selected.feedback.note"> · {{ selected.feedback.note }}</template>
        </p>
        <p v-else class="answer-note">尚无用户反馈。</p>
        <p class="answer-note">所有访问者可查看，评价仅限原提交浏览器修改。</p>
      </section>
    </section>
    <section
      v-if="answer?.citations.length"
      class="evidence-section"
      aria-label="回答引用与原文片段"
    >
      <h2>引用与原文片段</h2>
      <article
        v-for="c in answer.citations"
        :id="`literature-citation-${c.ref.slice(1, -1)}`"
        :key="c.ref"
        class="card evidence-card"
        tabindex="-1"
      >
        <div class="evidence-heading">
          <span class="evidence-number">{{ c.ref }}</span>
          <div>
            <h3>{{ c.filename }}</h3>
            <small
              >PDF 第 {{ c.page_start
              }}{{
                c.page_end !== c.page_start ? `–${c.page_end}` : ""
              }}
              页</small
            >
          </div>
          <a
            class="text-link"
            :href="pdf(c.document_id, c.page_start)"
            target="_blank"
            rel="noopener"
            >查看原文<ExternalLink :size="13"
          /></a>
        </div>
        <blockquote>{{ c.excerpt }}</blockquote>
        <details v-if="(c.source_chunks?.length ?? 0) > 1" class="source-parts">
          <summary>查看引用的原文组成（{{ c.source_chunks?.length }} 段）</summary>
          <div v-for="part in c.source_chunks" :key="part.chunk_id">
            <small>PDF 第 {{ part.page_start }}{{ part.page_end !== part.page_start ? `–${part.page_end}` : "" }} 页</small>
            <blockquote>{{ part.text }}</blockquote>
          </div>
        </details>
      </article>
    </section>
  </div>
</template>

<style scoped>
.source-parts { margin-top: 12px; color: var(--ink-2); font-size: 13px; }
.source-parts summary { cursor: pointer; }
.source-parts > div { margin-top: 12px; }
.record-info, .feedback-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 18px; font-size: 12px; color: var(--muted); }
.record-info { justify-content: space-between; }
.feedback-section { margin-top: 20px; padding-top: 20px; border-top: 1px solid #f5f2ed; }
.feedback-section h3 { font-size: 14px; margin: 0; }
.chosen { background: #e3efec; border-color: #5fa8a2; color: #0b6e68; }
.feedback-section fieldset { display: flex; flex-wrap: wrap; gap: 12px; border: 0; padding: 12px 0; margin: 14px 0 0; font-size: 12px; }
.feedback-section legend, .feedback-note { color: var(--muted); font-size: 12px; }
.feedback-section fieldset label { display: inline-flex; align-items: center; gap: 5px; }
.feedback-section textarea { box-sizing: border-box; width: 100%; margin: 8px 0 12px; border: 1px solid #dcebe7; border-radius: 6px; padding: 10px; font: inherit; font-size: 13px; resize: vertical; }
.feedback-error { color: #b16642; font-size: 12px; }
.literature-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.library,
.question-card,
.answer-card,
.evidence-card {
  padding: 24px;
}
.library summary {
  cursor: pointer;
  font-size: 16px;
  font-weight: 700;
}
.library-count {
  margin-left: 16px;
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.muted {
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
}
.library-document {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-top: 15px;
  border-top: 1px solid #f5f2ed;
}
.library-document > svg {
  flex-shrink: 0;
  color: #127a3a;
}
.library-document > div {
  flex: 1;
  min-width: 0;
}
.library-document strong {
  font-size: 13px;
  font-weight: 400;
  overflow-wrap: anywhere;
}
.library-document small {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-top: 6px;
}
.text-link {
  color: #0b6e68;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  text-decoration: none;
  font-size: 12px;
}
.text-link:hover {
  text-decoration: underline;
}
.question-card > label {
  display: block;
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 16px;
}
.question-card textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 120px;
  max-height: 360px;
  border: 1px solid #dcebe7;
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  line-height: 1.8;
  padding: 14px;
  color: #0b5f5a;
  background: #fefdfb;
}
.question-card textarea:focus {
  outline: 2px solid #5fa8a2;
  outline-offset: 2px;
}
.question-card textarea::placeholder {
  color: #b8ae9a;
}
.question-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 12px;
}
.question-foot p {
  font-size: 12px;
  color: var(--muted);
  margin: 0;
  line-height: 1.8;
}
.question-foot p span {
  display: block;
}
.question-foot button {
  white-space: nowrap;
  flex-shrink: 0;
}
.example-questions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid #f5f2ed;
  font-size: 12px;
  color: var(--muted);
}
.example-questions button {
  border: 1px solid #dcebe7;
  background: #fcfaf7;
  color: var(--muted);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  cursor: pointer;
  text-align: left;
  line-height: 1.7;
}
.example-questions button:hover {
  background: #e3efec;
}
.literature-state {
  padding: 30px;
  text-align: center;
  color: var(--muted);
}
.literature-state > svg {
  color: #0b6e68;
}
.literature-state h2 {
  font-size: 16px;
}
.literature-state p {
  font-size: 13px;
  line-height: 1.8;
}
.answer-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.answer-heading h2,
.evidence-section > h2 {
  font-size: 16px;
  margin: 0;
}
.answer-heading span {
  font-size: 12px;
  color: var(--muted);
}
.submitted-question {
  font-size: 13px;
  color: var(--muted);
  padding-bottom: 18px;
  border-bottom: 1px solid #f5f2ed;
  overflow-wrap: anywhere;
}
.answer-content {
  font-size: 14px;
  line-height: 2;
  color: #0b5f5a;
  overflow-wrap: anywhere;
}
.citation-ref {
  font: inherit;
  font-size: 12px;
  color: #0b6e68;
  background: #e3efec;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
  margin: 0 3px;
  padding: 0 5px;
}
.answer-note {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
  margin-bottom: 0;
}
.evidence-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.evidence-card:focus {
  outline: 2px solid #5fa8a2;
  outline-offset: 3px;
}
.evidence-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.evidence-heading > div {
  flex: 1;
  min-width: 0;
}
.evidence-heading h3 {
  font-size: 13px;
  font-weight: 700;
  margin: 0 0 7px;
  overflow-wrap: anywhere;
}
.evidence-heading small {
  font-size: 12px;
  color: var(--muted);
}
.evidence-number {
  color: #0b6e68;
  font-size: 13px;
}
.evidence-card blockquote {
  margin: 18px 0 0;
  padding: 12px 16px;
  border-left: 3px solid #dcebe7;
  background: #fcfbf8;
  font-size: 13px;
  line-height: 1.9;
  color: var(--muted);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 320px;
  overflow-y: auto;
}
@media (max-width: 720px) {
  .library,
  .question-card,
  .answer-card,
  .evidence-card {
    padding: 18px;
  }
  .library-document {
    flex-wrap: wrap;
  }
  .library-document > .text-link {
    margin-left: 36px;
  }
  .evidence-heading {
    flex-wrap: wrap;
  }
  .evidence-heading > .text-link {
    margin-left: 30px;
  }
  .question-foot {
    align-items: flex-end;
  }
  .answer-heading {
    align-items: flex-start;
  }
  .answer-heading span {
    max-width: 45%;
    line-height: 1.7;
  }
}
</style>
