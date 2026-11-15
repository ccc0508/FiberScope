<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowUpRight, BookA, ChevronRight, Search, X } from "lucide-vue-next";
import PageHeader from "../components/PageHeader.vue";
import { fiberTerms, matchesFiberTerm, termCategories, termLinks, type FiberTerm } from "../glossary";

const route = useRoute();
const router = useRouter();
const query = computed(() => typeof route.query.q === "string" ? route.query.q.slice(0, 150) : "");
const search = ref(query.value);
const category = computed(() => termCategories.some((item) => item.key === route.query.category) ? String(route.query.category) : "");
const terms = computed(() => fiberTerms.filter((term) => (!category.value || term.category === category.value) && matchesFiberTerm(term, query.value)));
const selected = computed(() => terms.value.find((term) => term.id === route.query.term) ?? terms.value[0]);
const selectedCategory = computed(() => termCategories.find((item) => item.key === selected.value?.category));
const related = computed(() => (selected.value?.related ?? []).map((id) => fiberTerms.find((term) => term.id === id)).filter((term): term is FiberTerm => !!term));
const links = computed(() => selected.value ? termLinks(selected.value) : []);
const detailHeading = ref<HTMLElement>();
const list = ref<HTMLElement>();
const copied = ref(false);
const manualLink = ref("");
const manualLinkInput = ref<HTMLInputElement>();
let copyAttempt = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let copiedTimer: ReturnType<typeof setTimeout> | undefined;

watch(search, (value) => {
  clearTimeout(searchTimer);
  if (value === query.value) return;
  searchTimer = setTimeout(() => {
    void router.replace({ query: { ...route.query, q: value.slice(0, 150) || undefined, term: undefined } });
  }, 180);
});
watch(query, (value) => {
  clearTimeout(searchTimer);
  search.value = value;
});
watch(() => selected.value?.id, async () => {
  copyAttempt++;
  clearTimeout(copiedTimer);
  copied.value = false;
  manualLink.value = "";
  await nextTick();
  const active = list.value?.querySelector<HTMLElement>(".glossary-index-item.active");
  if (!active || !list.value) return;
  const row = active.getBoundingClientRect(), container = list.value.getBoundingClientRect();
  if (row.top < container.top || row.bottom > container.bottom) {
    list.value.scrollTop += row.top - container.top - list.value.clientHeight / 2 + row.height / 2;
  }
}, { immediate: true });

function setCategory(value: string) {
  clearTimeout(searchTimer);
  void router.replace({ query: { q: search.value || undefined, category: value || undefined } });
  list.value?.scrollTo({ top: 0 });
}
function reset() {
  clearTimeout(searchTimer);
  search.value = "";
  void router.replace({ query: {} });
}
async function choose(term: FiberTerm, fromRelated = false) {
  clearTimeout(searchTimer);
  await router.push({ query: {
    q: fromRelated ? undefined : search.value || undefined,
    category: fromRelated ? term.category : category.value || undefined,
    term: term.id,
  } });
  if (window.matchMedia("(max-width: 760px)").matches || fromRelated) {
    await nextTick();
    detailHeading.value?.focus({ preventScroll: true });
    detailHeading.value?.scrollIntoView({ block: "start", behavior: "instant" });
  }
}
async function copyLink() {
  if (!selected.value) return;
  const attempt = ++copyAttempt;
  clearTimeout(copiedTimer);
  copied.value = false;
  const href = router.resolve({ path: "/glossary", query: { term: selected.value.id } }).href;
  const url = new URL(href, window.location.href).href;
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    if (attempt !== copyAttempt) return;
    manualLink.value = url;
    await nextTick();
    if (attempt === copyAttempt) {
      manualLinkInput.value?.focus();
      manualLinkInput.value?.select();
    }
    return;
  }
  if (attempt !== copyAttempt) return;
  manualLink.value = "";
  copied.value = true;
  copiedTimer = setTimeout(() => { copied.value = false; }, 2200);
}
onBeforeUnmount(() => {
  copyAttempt++;
  clearTimeout(searchTimer);
  clearTimeout(copiedTimer);
});
</script>

<template>
  <div class="overview glossary-page">
    <PageHeader description="查阅常用名词，读懂指标、单位与实验含义。" />

    <section class="glossary-tools" aria-label="查找术语">
      <div class="glossary-search">
        <Search :size="19" aria-hidden="true" />
        <label class="sr-only" for="glossary-search">搜索术语、英文名或单位</label>
        <input id="glossary-search" v-model="search" type="search" maxlength="150" autocomplete="off" placeholder="搜索术语、英文名或单位，如 打浆度、coarseness" />
        <button v-if="search" class="icon-button" type="button" aria-label="清除搜索" @click="search = ''"><X :size="17" /></button>
      </div>
      <div class="glossary-categories" role="group" aria-label="术语分类">
        <button type="button" :aria-pressed="!category" :class="{ selected: !category }" @click="setCategory('')">
          全部术语 <span>{{ fiberTerms.length }}</span>
        </button>
        <button v-for="item in termCategories" :key="item.key" type="button" :aria-pressed="category === item.key" :class="{ selected: category === item.key }" @click="setCategory(item.key)">
          {{ item.label }} <span>{{ fiberTerms.filter((term) => term.category === item.key).length }}</span>
        </button>
      </div>
    </section>

    <div class="glossary-result-bar">
      <p role="status" aria-live="polite">{{ query ? `“${query}” · ` : '' }}共 {{ terms.length }} 个术语</p>
      <button v-if="query || category" class="text-button" type="button" @click="reset">重置筛选</button>
      <span v-else class="glossary-list-hint">选择一个术语查看释义</span>
    </div>

    <div v-if="selected" class="glossary-workbench">
      <nav ref="list" class="card glossary-index" aria-label="术语目录">
        <ul>
          <li v-for="term in terms" :key="term.id">
            <button type="button" class="glossary-index-item" :class="{ active: selected.id === term.id }" :aria-current="selected.id === term.id ? 'true' : undefined" @click="choose(term)">
              <span><strong>{{ term.name }}</strong><small>{{ term.english }}</small></span>
              <ChevronRight :size="16" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </nav>

      <article class="card glossary-detail" aria-labelledby="glossary-term-title">
        <header class="glossary-term-header">
          <div class="glossary-term-meta"><span>{{ selectedCategory?.label }}</span><span>{{ selected.metricKeys?.length ? '平台指标' : '基础与延伸概念' }}</span></div>
          <h2 id="glossary-term-title" ref="detailHeading" tabindex="-1">{{ selected.name }}</h2>
          <p class="glossary-english">{{ selected.english }}</p>
          <p v-if="selected.aliases.length" class="glossary-aliases"><span>也可搜索</span>{{ selected.aliases.slice(0, 4).join('、') }}</p>
        </header>

        <p class="glossary-definition">{{ selected.definition }}</p>

        <dl v-if="selected.unit || selected.unitStatus" class="glossary-unit-row">
          <dt>{{ selected.metricKeys?.length ? '平台单位' : '常用表达' }}</dt>
          <dd><span class="glossary-unit">{{ selected.unit || '尚未确认' }}</span><span v-if="selected.unitStatus === 'tentative'" class="glossary-unit-state">单位暂定</span><span v-else-if="selected.unitStatus === 'unconfirmed'" class="glossary-unit-state">待核对报告形式</span></dd>
        </dl>

        <section v-if="selected.formula" class="glossary-formula" aria-label="计算关系">
          <h3>计算关系</h3><p>{{ selected.formula }}</p>
          <p v-if="selected.example" class="glossary-example">{{ selected.example }}</p>
        </section>
        <section v-else-if="selected.example" class="glossary-formula" aria-label="单位换算示例"><h3>单位换算示例</h3><p>{{ selected.example }}</p></section>

        <section class="glossary-explanation"><h3>如何理解</h3><p>{{ selected.reading }}</p></section>
        <section class="glossary-caution"><h3>读数时留意</h3><p>{{ selected.caution }}</p></section>

        <section v-if="related.length" class="glossary-related" aria-label="相关术语">
          <h3>一起了解</h3>
          <div><button v-for="term in related" :key="term.id" type="button" @click="choose(term, true)">{{ term.name }}<ChevronRight :size="13" aria-hidden="true" /></button></div>
        </section>

        <div v-if="links.length" class="glossary-page-links">
          <RouterLink v-for="link in links" :key="link.to" :to="link.to">{{ link.label }}<ArrowUpRight :size="15" aria-hidden="true" /></RouterLink>
        </div>

        <footer class="glossary-detail-footer">
          <button class="text-button glossary-copy" type="button" @click="copyLink">{{ copied ? '已复制链接' : '复制本条链接' }}</button>
          <div class="glossary-manual-link" :class="{ 'sr-only': !manualLink }">
            <p role="status">{{ manualLink ? '无法自动复制，请手动复制下方链接。' : copied ? '术语链接已复制' : '' }}</p>
            <input v-if="manualLink" ref="manualLinkInput" type="text" :value="manualLink" aria-label="术语链接" readonly />
          </div>
        </footer>
      </article>
    </div>

    <section v-else class="card glossary-empty" aria-label="没有匹配的术语">
      <BookA :size="34" aria-hidden="true" /><h2>没有找到匹配的术语</h2><p>试试更短的关键词、英文名，或清除分类筛选。</p><button class="button" type="button" @click="reset">查看全部术语</button>
    </section>

  </div>
</template>

<style scoped>
.glossary-tools { padding: 20px 0 0; border-top: 1px solid var(--border-strong); }
.glossary-search { display: flex; align-items: center; gap: 12px; background: var(--paper); border: 1px solid var(--border-strong); padding: 0 14px; min-height: 49px; color: var(--muted); }
.glossary-search:focus-within { border-color: var(--signal); box-shadow: 0 0 0 2px var(--signal-tint); }
.glossary-search input { min-width: 0; width: 100%; padding: 13px 0; border: 0; outline: none; background: transparent; color: var(--ink); font-size: 14px; }
.glossary-search input::placeholder { color: var(--muted); }
.glossary-search input::-webkit-search-cancel-button { display: none; }
.glossary-categories { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 17px; }
.glossary-categories button { min-height: 38px; display: inline-flex; align-items: center; gap: 10px; padding: 8px 13px; border: 1px solid transparent; border-radius: 3px; font-size: 13px; color: var(--ink-2); }
.glossary-categories button:hover { background: var(--panel); }
.glossary-categories button.selected { color: var(--signal-ink); border-color: var(--border-strong); background: var(--signal-tint); font-weight: 600; }
.glossary-categories span { font-family: var(--font-mono); font-size: 11px; font-weight: 400; }
.glossary-result-bar { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 49px; color: var(--muted); font-size: 12px; }
.glossary-result-bar p { overflow-wrap: anywhere; }
.glossary-list-hint { white-space: nowrap; }
.glossary-workbench { display: grid; grid-template-columns: minmax(230px, 30%) minmax(0, 1fr); align-items: start; gap: 21px; }
.glossary-index { max-height: calc(100vh - 280px); min-height: 340px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; overscroll-behavior: contain; }
.glossary-index ul { padding: 7px; margin: 0; list-style: none; }
.glossary-index li + li { border-top: 1px solid var(--border); }
.glossary-index-item { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 10px; text-align: left; padding: 15px 13px; border-left: 3px solid transparent; }
.glossary-index-item span { min-width: 0; }
.glossary-index-item strong { display: block; font-size: 14px; font-weight: 500; }
.glossary-index-item small { display: block; font-size: 11px; color: var(--muted); margin-top: 5px; line-height: 1.5; overflow-wrap: anywhere; }
.glossary-index-item > svg { color: var(--muted); }
.glossary-index-item:hover { background: var(--surface-hover); }
.glossary-index-item.active { background: var(--signal-tint); border-left-color: var(--signal); color: var(--signal-ink); }
.glossary-index-item.active strong { font-weight: 700; }
.glossary-index-item:focus-visible { outline-offset: -3px; }
.glossary-detail { min-width: 0; padding: 29px 32px 22px; }
.glossary-term-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 17px; font-size: 11px; color: var(--muted); }
.glossary-term-meta span + span { border-left: 1px solid var(--border-strong); padding-left: 10px; }
.glossary-term-header h2 { font-size: 28px; line-height: 1.5; scroll-margin-top: 22px; outline: none; }
.glossary-term-header h2:focus-visible { outline: 2px solid var(--focus); outline-offset: 5px; }
.glossary-english { font-size: 13px; line-height: 1.6; color: var(--signal-ink); margin-top: 4px; overflow-wrap: anywhere; }
.glossary-aliases { color: var(--muted); font-size: 12px; line-height: 1.8; margin-top: 12px; overflow-wrap: anywhere; }
.glossary-aliases span { display: inline-block; margin-right: 10px; color: var(--ink-2); }
.glossary-definition { margin-top: 24px; font-size: 16px; line-height: 1.95; color: var(--ink); }
.glossary-unit-row { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; padding: 15px 0; margin: 19px 0 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.glossary-unit-row dt { color: var(--muted); font-size: 12px; }
.glossary-unit-row dd { display: flex; flex-wrap: wrap; gap: 11px; align-items: center; margin: 0; }
.glossary-unit { font-family: var(--font-mono); font-size: 15px; }
.glossary-unit-state { border: 1px solid var(--border-strong); padding: 2px 7px; color: var(--warn); background: var(--warn-tint); font-size: 11px; border-radius: 3px; }
.glossary-formula { padding: 16px 18px; margin-top: 23px; border: 1px solid var(--border); background: var(--surface-2); border-radius: var(--radius-xs); }
.glossary-formula h3 { font-size: 12px; color: var(--signal-ink); margin-bottom: 9px; font-weight: 500; }
.glossary-formula p { line-height: 1.9; font-size: 14px; overflow-wrap: anywhere; }
.glossary-formula .glossary-example { margin-top: 10px; font-size: 12px; color: var(--ink-2); }
.glossary-explanation, .glossary-caution { margin-top: 24px; }
.glossary-explanation h3, .glossary-caution h3 { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.glossary-explanation p, .glossary-caution p { font-size: 14px; line-height: 1.95; color: var(--ink-2); }
.glossary-caution { padding-left: 14px; border-left: 2px solid var(--warn); }
.glossary-caution h3 { color: var(--warn); }
.glossary-related { margin-top: 27px; padding-top: 22px; border-top: 1px solid var(--border); }
.glossary-related h3 { font-weight: 500; color: var(--muted); font-size: 12px; margin-bottom: 10px; }
.glossary-related > div { display: flex; flex-wrap: wrap; gap: 7px; }
.glossary-related button { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); padding: 6px 9px; min-height: 34px; font-size: 12px; text-align: left; }
.glossary-related button:hover { color: var(--signal-ink); border-color: var(--signal); background: var(--signal-tint); }
.glossary-page-links { display: flex; flex-wrap: wrap; gap: 11px 22px; margin-top: 22px; }
.glossary-page-links a { display: inline-flex; gap: 5px; align-items: center; font-size: 12px; min-height: 28px; }
.glossary-page-links a:hover { text-decoration: underline; }
.glossary-detail-footer { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: flex-end; gap: 15px; padding-top: 20px; margin-top: 20px; border-top: 1px solid var(--border); color: var(--muted); }
.glossary-copy { white-space: nowrap; font-size: 11px; flex-shrink: 0; min-height: 32px; }
.glossary-manual-link { flex-basis: 100%; min-width: 0; font-size: 12px; }
.glossary-manual-link input { display: block; width: 100%; margin-top: 8px; padding: 8px 10px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; }
.glossary-empty { min-height: 330px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 35px 20px; gap: 15px; text-align: center; }
.glossary-empty > svg { color: var(--signal); }
.glossary-empty h2 { font-size: 20px; }
.glossary-empty p { color: var(--muted); line-height: 1.8; }
@media (max-width: 1050px) {
  .glossary-workbench { grid-template-columns: 225px minmax(0, 1fr); gap: 15px; }
  .glossary-detail { padding: 24px 22px 20px; }
  .glossary-index-item { padding: 13px 9px; }
}
@media (max-width: 760px) {
  .glossary-tools { padding-top: 16px; }
  .glossary-search { min-height: 46px; padding: 0 11px; gap: 8px; }
  .glossary-search input { font-size: 13px; }
  .glossary-categories { gap: 3px; margin-top: 12px; }
  .glossary-categories button { padding: 7px 9px; gap: 7px; font-size: 12px; min-height: 36px; }
  .glossary-list-hint { display: none; }
  .glossary-workbench { grid-template-columns: minmax(0, 1fr); gap: 17px; }
  .glossary-index { min-height: 0; max-height: 235px; }
  .glossary-index ul { padding: 4px; }
  .glossary-index-item { padding: 10px 12px; }
  .glossary-index-item small { margin-top: 2px; }
  .glossary-detail { padding: 23px 20px 19px; }
  .glossary-term-header h2 { font-size: 24px; }
  .glossary-term-meta { margin-bottom: 12px; }
  .glossary-definition { font-size: 15px; margin-top: 21px; }
  .glossary-explanation p, .glossary-caution p { font-size: 13px; }
  .glossary-formula { padding: 14px; }
  .glossary-formula p { font-size: 13px; }
  .glossary-detail-footer { gap: 9px; }
  .glossary-copy { font-size: 10px; }
}
@media (max-width: 380px) {
  .glossary-detail { padding: 21px 16px 18px; }
}
</style>
