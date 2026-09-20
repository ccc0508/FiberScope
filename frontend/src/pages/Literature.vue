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

interface Document {
  id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
}
interface Citation {
  ref: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  chunk_id: string;
  excerpt: string;
}
interface Answer {
  status: "answered" | "refused";
  answer: string;
  citations: Citation[];
  latency_ms: number;
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
const canAsk = computed(
  () =>
    enabled.value &&
    documents.value.length > 0 &&
    !loading.value &&
    !asking.value &&
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
  `/api/v1/literature/documents/${encodeURIComponent(id)}/pdf#page=${page}`;
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
async function ask() {
  if (!canAsk.value) return;
  const current = new AbortController();
  answerController = current;
  asking.value = true;
  error.value = "";
  answer.value = null;
  submitted.value = question.value.trim();
  const timeout = window.setTimeout(() => current.abort(), 105000);
  try {
    const response = await fetch("/api/v1/literature/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: submitted.value }),
      signal: current.signal,
    });
    const body = await response.json();
    if (!response.ok)
      throw new Error(body?.error?.message ?? "文献问答暂不可用，请稍后重试。");
    answer.value = body;
  } catch (e) {
    error.value = current.signal.aborted
      ? "等待回答超时，请稍后重试。"
      : e instanceof TypeError || e instanceof SyntaxError
        ? "暂时无法连接文献问答服务，请检查连接后重试。"
        : e instanceof Error
          ? e.message
          : "文献问答暂不可用，请稍后重试。";
  } finally {
    clearTimeout(timeout);
    asking.value = false;
  }
}
function focusCitation(ref: string) {
  document.getElementById(`literature-citation-${ref.slice(1, -1)}`)?.focus();
}
onBeforeUnmount(() => {
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
      <form class="card question-card" @submit.prevent="ask">
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
            每次提问独立处理，不沿用上一次对话。<span
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
      <p>回答可能需要几十秒，完成引用校验后会一次展示。</p>
    </section>
    <section v-if="error" class="card literature-state" role="alert">
      <p>{{ error }}</p>
      <button class="button" :disabled="!canAsk" @click="ask">重新提问</button>
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
      </article>
    </section>
  </div>
</template>

<style scoped>
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
  color: #8191a4;
}
.muted {
  font-size: 12px;
  line-height: 1.8;
  color: #8191a4;
}
.library-document {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-top: 15px;
  border-top: 1px solid #edf1f5;
}
.library-document > svg {
  flex-shrink: 0;
  color: #58a397;
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
  color: #8191a4;
  font-size: 12px;
  margin-top: 6px;
}
.text-link {
  color: #4386bf;
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
  border: 1px solid #dce5ed;
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  line-height: 1.8;
  padding: 14px;
  color: #40566d;
  background: #fbfcfe;
}
.question-card textarea:focus {
  outline: 2px solid #8eb8dc;
  outline-offset: 2px;
}
.question-card textarea::placeholder {
  color: #9aa8b8;
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
  color: #8191a4;
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
  border-top: 1px solid #edf1f5;
  font-size: 12px;
  color: #8191a4;
}
.example-questions button {
  border: 1px solid #e1e9f0;
  background: #f7fafc;
  color: #617e99;
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  cursor: pointer;
  text-align: left;
  line-height: 1.7;
}
.example-questions button:hover {
  background: #edf5fc;
}
.literature-state {
  padding: 30px;
  text-align: center;
  color: #718399;
}
.literature-state > svg {
  color: #4386bf;
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
  color: #8191a4;
}
.submitted-question {
  font-size: 13px;
  color: #8191a4;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf1f5;
  overflow-wrap: anywhere;
}
.answer-content {
  font-size: 14px;
  line-height: 2;
  color: #40566d;
  overflow-wrap: anywhere;
}
.citation-ref {
  font: inherit;
  font-size: 12px;
  color: #4386bf;
  background: #edf5fc;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
  margin: 0 3px;
  padding: 0 5px;
}
.answer-note {
  font-size: 12px;
  color: #8191a4;
  line-height: 1.8;
  margin-bottom: 0;
}
.evidence-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.evidence-card:focus {
  outline: 2px solid #8eb8dc;
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
  color: #8191a4;
}
.evidence-number {
  color: #4386bf;
  font-size: 13px;
}
.evidence-card blockquote {
  margin: 18px 0 0;
  padding: 12px 16px;
  border-left: 3px solid #c8ddef;
  background: #f8fafc;
  font-size: 13px;
  line-height: 1.9;
  color: #657c91;
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
