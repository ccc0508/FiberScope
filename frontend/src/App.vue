<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute } from "vue-router";
import { appPath } from "./urls";
import {
  LayoutDashboard,
  ChartNoAxesCombined,
  Combine,
  ScatterChart,
  Repeat2,
  ScanSearch,
  Database,
  PanelLeftClose,
  PanelLeftOpen,
  BookOpen,
  FileSpreadsheet,
  X,
} from "lucide-vue-next";
const navOpen = ref(false);
const sidebar = ref<HTMLElement>();
const navToggle = ref<HTMLButtonElement>();
let mobileViewport: MediaQueryList | undefined;
function syncViewport() {
  if (!mobileViewport?.matches) navOpen.value = false;
}
function navigationKey(event: KeyboardEvent) {
  if (!navOpen.value || info.value?.open) return;
  if (event.key === "Escape") {
    event.preventDefault();
    navOpen.value = false;
  } else if (event.key === "Tab") {
    const items = sidebar.value?.querySelectorAll<HTMLElement>(
      "a[href], button:not(:disabled)",
    );
    if (!items?.length) return;
    const first = items[0]!,
      last = items[items.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
}
watch(navOpen, async (open) => {
  await nextTick();
  if (open) sidebar.value?.querySelector<HTMLElement>("nav .active")?.focus();
  else navToggle.value?.focus({ preventScroll: true });
});
const route = useRoute();
const pageTitle = computed(() =>
  route.path === "/literature-data"
    ? "文献数据"
    : route.path === "/literature"
      ? "文献问答"
      : route.path === "/sources"
        ? "数据来源"
        : route.path === "/recycled"
          ? "再生纸浆循环"
          : route.path === "/association"
            ? "纤维—纸张关联"
            : route.path === "/blends"
              ? "复配分析"
              : route.path === "/beating"
                ? "打浆分析"
                : "数据总览",
);
watch(pageTitle, async (title) => {
  document.title = `${title} · 植物纤维可视化分析平台`;
  await nextTick();
  hoveredItem.value = undefined;
  moveHighlight();
});
const info = ref<HTMLDialogElement>();
const navigation = ref<HTMLElement>();
const highlight = ref({ y: 0, height: 43 });
const hoveredItem = ref<HTMLElement>();
let navObserver: ResizeObserver | undefined;
function moveHighlight(item?: HTMLElement) {
  const target =
    item ?? navigation.value?.querySelector<HTMLElement>(".active");
  if (!target || !navigation.value) return;
  const bounds = target.getBoundingClientRect();
  highlight.value = {
    y: bounds.top - navigation.value.getBoundingClientRect().top,
    height: bounds.height,
  };
}
function hoverNavigation(event: PointerEvent) {
  if (event.pointerType === "touch") return;
  const item = (event.target as HTMLElement).closest<HTMLElement>(".nav-item");
  if (item) {
    hoveredItem.value = item;
    moveHighlight(item);
  }
}
function resetHighlight() {
  hoveredItem.value = undefined;
  const focused = document.activeElement as HTMLElement | null;
  moveHighlight(
    focused?.matches(".nav-item") && navigation.value?.contains(focused)
      ? focused
      : undefined,
  );
}
onMounted(() => {
  mobileViewport = window.matchMedia("(max-width: 720px)");
  mobileViewport.addEventListener("change", syncViewport);
  document.addEventListener("keydown", navigationKey);
  document.title = `${pageTitle.value} · 植物纤维可视化分析平台`;
  moveHighlight();
  navObserver = new ResizeObserver(() => moveHighlight(hoveredItem.value));
  if (navigation.value) navObserver.observe(navigation.value);
});
onBeforeUnmount(() => {
  navObserver?.disconnect();
  mobileViewport?.removeEventListener("change", syncViewport);
  document.removeEventListener("keydown", navigationKey);
});
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <button
    v-if="navOpen"
    class="nav-scrim"
    aria-label="关闭导航"
    @click="navOpen = false"
  ></button>
  <aside
    ref="sidebar"
    class="sidebar"
    :class="{ open: navOpen }"
    aria-label="主导航"
  >
    <div class="brand">
      <RouterLink class="brand-link" to="/" @click="navOpen = false">
        <img :src="appPath('favicon.svg')" width="34" height="34" alt="" />
        <strong class="platform-name"
          ><span>植物纤维</span><span>可视化分析平台</span></strong
        > </RouterLink
      ><button
        class="icon-button mobile-close"
        type="button"
        aria-label="关闭导航"
        @click="navOpen = false"
      >
        <PanelLeftClose :size="18" />
      </button>
    </div>
    <div class="workspace">
      <span class="workspace-mark"><Database :size="17" /></span
      ><span>植物纤维研究<small>实验数据工作台</small></span>
    </div>
    <div class="nav-label">工作空间</div>
    <nav
      ref="navigation"
      class="sliding-navigation"
      @pointermove="hoverNavigation"
      @pointerleave="resetHighlight"
      @focusin="moveHighlight($event.target as HTMLElement)"
      @focusout="moveHighlight()"
    >
      <div
        class="nav-highlight"
        aria-hidden="true"
        :style="{
          transform: `translateY(${highlight.y}px)`,
          height: `${highlight.height}px`,
        }"
      ></div>
      <RouterLink
        to="/"
        class="nav-item"
        :class="{ active: route.path === '/' }"
        @click="navOpen = false"
        ><LayoutDashboard :size="18" /><span>数据总览</span></RouterLink
      >
      <div class="nav-label second">分析与探索</div>
      <RouterLink
        to="/beating"
        class="nav-item"
        :class="{ active: route.path === '/beating' }"
        @click="navOpen = false"
      >
        <ChartNoAxesCombined :size="18" /><span>打浆分析</span>
      </RouterLink>
      <RouterLink
        to="/blends"
        class="nav-item"
        :class="{ active: route.path === '/blends' }"
        @click="navOpen = false"
      >
        <Combine :size="18" /><span>复配分析</span>
      </RouterLink>
      <RouterLink
        to="/association"
        class="nav-item"
        :class="{ active: route.path === '/association' }"
        @click="navOpen = false"
      >
        <ScatterChart :size="18" /><span>纤维—纸张关联</span>
      </RouterLink>
      <RouterLink
        to="/recycled"
        class="nav-item"
        :class="{ active: route.path === '/recycled' }"
        @click="navOpen = false"
      >
        <Repeat2 :size="18" /><span>再生纸浆循环</span>
      </RouterLink>
      <RouterLink
        to="/sources"
        class="nav-item"
        :class="{ active: route.path === '/sources' }"
        @click="navOpen = false"
      >
        <ScanSearch :size="18" /><span>数据来源</span>
      </RouterLink>
      <div class="nav-label second">科研助手</div>
      <RouterLink
        to="/literature"
        class="nav-item"
        :class="{ active: route.path === '/literature' }"
        @click="navOpen = false"
      >
        <BookOpen :size="18" /><span>文献问答</span>
      </RouterLink>
      <RouterLink
        to="/literature-data"
        class="nav-item"
        :class="{ active: route.path === '/literature-data' }"
        @click="navOpen = false"
      >
        <FileSpreadsheet :size="18" /><span>文献数据</span>
      </RouterLink>
    </nav>
    <div class="sidebar-bottom">
      <button class="nav-item" @click="info?.showModal()">
        <BookOpen :size="18" /><span>数据说明</span>
      </button>
      <div class="project-foot">
        <span class="readonly-dot"></span>
        <div>科研数据 · 只读访问<small>保留原始记录与实验口径</small></div>
      </div>
    </div>
  </aside>
  <div class="shell" :inert="navOpen">
    <button
      ref="navToggle"
      class="icon-button mobile-toggle"
      type="button"
      aria-label="展开导航"
      :aria-expanded="navOpen"
      @click="navOpen = true"
    >
      <PanelLeftOpen :size="20" />
    </button>
    <main id="main" tabindex="-1"><RouterView /></main>
  </div>
  <dialog
    ref="info"
    aria-label="关于这些实验数据"
    class="info-dialog"
    @click="$event.target === info && info?.close()"
  >
    <div class="dialog-heading">
      <div>
        <span class="eyebrow">FIBERSCOPE</span>
        <h2>关于这些实验数据</h2>
      </div>
      <button
        class="icon-button"
        aria-label="关闭数据说明"
        @click="info?.close()"
      >
        <X :size="20" />
      </button>
    </div>
    <p>
      核心样本保存12项纤维特性和9项纸张性能。再生纸浆以逐行观测独立保存，循环均值由数据库汇总。
    </p>
    <ul>
      <li>复配两端复用纯浆样本，物理样本数与实验展示点数不同。</li>
      <li>空值显示为“—”，不替换为0；比例保持0—100%口径。</li>
      <li>透气度与耐折度单位待复核，14个再生纸浆数据块的正式处理条件未知。</li>
      <li>图表展示对应关系，不代表因果关系。</li>
    </ul>
    <button class="button primary" @click="info?.close()">知道了</button>
  </dialog>
</template>
