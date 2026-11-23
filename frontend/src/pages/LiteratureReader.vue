<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Minus, Plus } from "lucide-vue-next";
import { getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { literatureRequest } from "../literature";
import { apiPath } from "../urls";

interface CitationRegion {
  page: number;
  bbox: [number, number, number, number];
}
interface CitationLocation {
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  regions: CitationRegion[];
}

GlobalWorkerOptions.workerSrc = workerUrl;
const route = useRoute();
const location = shallowRef<CitationLocation>();
const pdfDocument = shallowRef<PDFDocumentProxy>();
const page = ref(1);
const zoom = ref(1);
const surfaceWidth = ref(0);
const sheetSize = shallowRef<{ width: number; height: number; scale: number; userUnit: number }>();
const surface = ref<HTMLElement>();
const canvas = ref<HTMLCanvasElement>();
const textLayer = ref<HTMLElement>();
const sheet = ref<HTMLElement>();
const loading = ref(true);
const rendering = ref(false);
const error = ref("");
const renderError = ref("");

const pdfUrl = computed(() => location.value
  ? apiPath(`literature/documents/${encodeURIComponent(location.value.document_id)}/pdf`)
  : "");
const reference = computed(() => String(route.params.reference));
const marks = computed(() => location.value?.regions.filter((region) => region.page === page.value) ?? []);
const citedPages = computed(() => {
  const cite = location.value;
  if (!cite) return [];
  return [...new Set([cite.page_start, ...cite.regions.map((region) => region.page), cite.page_end])]
    .filter((number) => number <= (pdfDocument.value?.numPages ?? Number.POSITIVE_INFINITY))
    .sort((a, b) => a - b);
});
const sheetStyle = computed(() => sheetSize.value && {
  width: `${sheetSize.value.width}px`,
  height: `${sheetSize.value.height}px`,
  "--scale-factor": sheetSize.value.scale,
  "--user-unit": sheetSize.value.userUnit,
});

function regionStyle([x0, y0, x1, y1]: CitationRegion["bbox"]) {
  return { left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` };
}

function scrollToCitation() {
  const first = marks.value[0];
  const top = first && sheet.value
    ? sheet.value.offsetTop + sheet.value.offsetHeight * first.bbox[1] / 1000 - 25
    : 0;
  surface.value?.scrollTo({ top: Math.max(0, top), left: 0 });
}

function openCitedPage(number: number) {
  if (number === page.value && !rendering.value) scrollToCitation();
  else page.value = number;
}

watch(() => [String(route.params.recordId), reference.value] as const, async ([recordId, refNumber], _, onCleanup) => {
  const request = new AbortController();
  let pdfLoad: ReturnType<typeof getDocument> | undefined;
  onCleanup(() => {
    request.abort();
    void pdfLoad?.destroy().catch(() => undefined);
  });
  loading.value = true;
  location.value = undefined;
  pdfDocument.value = undefined;
  error.value = "";
  zoom.value = 1;
  sheetSize.value = undefined;
  try {
    const cite = await literatureRequest<CitationLocation>(
      `history/${encodeURIComponent(recordId)}/citations/${encodeURIComponent(refNumber)}/location`,
      undefined, request.signal,
    );
    if (request.signal.aborted) return;
    location.value = cite;
    pdfLoad = getDocument({ url: pdfUrl.value, isEvalSupported: false });
    const pdf = await pdfLoad.promise;
    if (request.signal.aborted) return;
    page.value = Math.min(cite.page_start, pdf.numPages);
    pdfDocument.value = pdf;
  } catch (failure) {
    if (!request.signal.aborted) {
      error.value = location.value ? "无法加载这份 PDF，请尝试直接打开原文件。"
        : failure instanceof Error ? failure.message : "无法读取引用位置。";
    }
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}, { immediate: true });

watch([pdfDocument, page, zoom, surfaceWidth], async ([pdf, number, magnification, available], previous, onCleanup) => {
  if (!pdf || !available) return;
  let cancelled = false;
  let render: RenderTask | undefined;
  let layer: TextLayer | undefined;
  onCleanup(() => {
    cancelled = true;
    render?.cancel();
    layer?.cancel();
  });
  rendering.value = true;
  renderError.value = "";
  try {
    const pdfPage = await pdf.getPage(number);
    if (cancelled) return;
    const unscaled = pdfPage.getViewport({ scale: 1 });
    const scale = Math.min(1.45, Math.max(200, available - 32) / unscaled.width) * magnification;
    const viewport = pdfPage.getViewport({ scale });
    sheetSize.value = { width: viewport.width, height: viewport.height, scale, userUnit: pdfPage.userUnit };
    await nextTick();
    if (cancelled || !canvas.value || !textLayer.value) return;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.value.width = Math.ceil(viewport.width * pixelRatio);
    canvas.value.height = Math.ceil(viewport.height * pixelRatio);
    textLayer.value.replaceChildren();
    render = pdfPage.render({
      canvas: canvas.value, viewport, transform: [pixelRatio, 0, 0, pixelRatio, 0, 0],
    });
    layer = new TextLayer({
      textContentSource: pdfPage.streamTextContent(), container: textLayer.value, viewport,
    });
    await Promise.all([render.promise, layer.render().catch(() => undefined)]);
    if (cancelled) return;
    if (pdf !== previous[0] || number !== previous[1]) scrollToCitation();
  } catch {
    if (!cancelled) renderError.value = "无法显示这一页，请尝试打开原文件。";
  } finally {
    if (!cancelled) rendering.value = false;
  }
}, { flush: "post" });

let resize: ResizeObserver | undefined;
onMounted(() => {
  if (!surface.value) return;
  resize = new ResizeObserver(([entry]) => { if (entry) surfaceWidth.value = entry.contentRect.width; });
  resize.observe(surface.value);
});
onBeforeUnmount(() => resize?.disconnect());
</script>

<template>
  <main class="paper-reader">
    <header class="reader-heading">
      <RouterLink class="reader-back" to="/literature"><ArrowLeft :size="16" aria-hidden="true" />文献问答</RouterLink>
      <h1>{{ location?.filename ?? "阅读论文原文" }}</h1>
      <a v-if="pdfUrl" class="reader-original" :href="`${pdfUrl}#page=${page}`" target="_blank" rel="noopener">
        打开原始 PDF <ExternalLink :size="14" aria-hidden="true" />
      </a>
    </header>

    <div v-if="pdfDocument" class="reader-tools">
      <nav class="reader-controls" aria-label="PDF 翻页与缩放">
        <button type="button" aria-label="上一页" :disabled="page === 1" @click="page--"><ChevronLeft :size="18" /></button>
        <span class="page-count" aria-live="polite">{{ page }} / {{ pdfDocument.numPages }} 页</span>
        <button type="button" aria-label="下一页" :disabled="page === pdfDocument.numPages" @click="page++"><ChevronRight :size="18" /></button>
        <button type="button" aria-label="缩小" :disabled="zoom <= 0.75" @click="zoom -= 0.25"><Minus :size="16" /></button>
        <button type="button" aria-label="放大" :disabled="zoom >= 2" @click="zoom += 0.25"><Plus :size="16" /></button>
      </nav>
      <nav class="reader-cited-pages" aria-label="引用所在页">
        <span>引用 [{{ reference }}]</span>
        <button v-for="number in citedPages" :key="number" type="button"
          :aria-current="number === page ? 'page' : undefined" @click="openCitedPage(number)">第 {{ number }} 页</button>
      </nav>
      <p v-if="!location?.regions.length" class="reader-notice">这条引用没有可用的原文坐标，已跳到对应页。</p>
      <p v-else-if="!marks.length && citedPages.includes(page)" class="reader-notice">本页没有保存可用的标注位置。</p>
    </div>

    <div ref="surface" class="reader-surface" aria-label="PDF 原文" :aria-busy="loading || rendering" tabindex="0">
      <p v-if="loading" class="reader-status" role="status">正在打开原文…</p>
      <p v-else-if="error || renderError" class="reader-status" role="alert">{{ error || renderError }}</p>
      <div v-if="pdfDocument" v-show="!renderError" class="reader-sheet-wrap">
        <div ref="sheet" class="reader-sheet" :style="sheetStyle" v-show="sheetSize">
          <canvas ref="canvas" role="img" :aria-label="`PDF 第 ${page} 页`"></canvas>
          <div ref="textLayer" class="textLayer"></div>
          <div v-if="!rendering" class="reader-marks" aria-hidden="true">
            <div v-for="region in marks" :key="region.bbox.join(',')" class="reader-mark" :style="regionStyle(region.bbox)"></div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.paper-reader {
  --reader-ink: #182a34;
  --reader-line: #d4dddc;
  --reader-accent: #225c57;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  height: 100dvh;
  background: #f9faf8;
  color: var(--reader-ink);
  font: 400 .88rem/1.5 "Noto Sans SC", sans-serif;
}
.reader-heading, .reader-tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .65rem 1.15rem;
  padding: .75rem clamp(.85rem, 3vw, 2.2rem);
  border-bottom: 1px solid var(--reader-line);
}
.reader-heading h1 {
  flex: 1;
  min-width: min(100%, 12rem);
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 1rem;
  font-weight: 700;
}
.reader-back, .reader-original {
  color: var(--reader-accent);
  display: inline-flex;
  align-items: center;
  gap: .35rem;
}
.reader-controls, .reader-cited-pages {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .35rem;
}
.reader-controls button, .reader-cited-pages button {
  min-width: 2.1rem;
  min-height: 2.1rem;
  display: grid;
  place-items: center;
  padding: .22rem .5rem;
  border: 1px solid var(--reader-line);
  border-radius: .25rem;
  background: #fff;
  color: var(--reader-ink);
}
.reader-controls button:disabled { opacity: .45; }
.reader-cited-pages button[aria-current="page"] { background: var(--reader-accent); color: white; }
.reader-cited-pages span, .page-count { padding-inline: .35rem; }
.reader-notice { margin: 0; font-size: .82rem; }
.reader-surface {
  grid-row: 3;
  position: relative;
  overflow: auto;
  background: #e5ebe9;
}
.reader-status { padding: 1rem; text-align: center; }
.reader-sheet-wrap { width: max-content; min-width: 100%; padding: 1rem; }
.reader-sheet {
  position: relative;
  --total-scale-factor: calc(var(--scale-factor) * var(--user-unit));
  --scale-round-x: 1px;
  --scale-round-y: 1px;
  margin-inline: auto;
  background: white;
  box-shadow: 0 1px 12px #182a3428;
}
.reader-sheet canvas { display: block; width: 100%; height: 100%; }
.reader-marks {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}
.reader-mark {
  position: absolute;
  background: #ffd34955;
  outline: 1px solid #a46615;
  mix-blend-mode: multiply;
}
</style>
