<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
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
  ChevronRight,
  BookOpen,
  X,
} from "lucide-vue-next";
const navOpen = ref(false);
const info = ref<HTMLDialogElement>();
const navigation = ref<HTMLElement>();
const highlight = ref({ y: 0, height: 43 });
const hoveredItem = ref<HTMLElement>();
let navObserver: ResizeObserver | undefined;
function moveHighlight(item?: HTMLElement) {
  const target = item ?? navigation.value?.querySelector<HTMLElement>(".active");
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
  moveHighlight(focused?.matches(".nav-item") && navigation.value?.contains(focused) ? focused : undefined);
}
onMounted(() => {
  moveHighlight();
  navObserver = new ResizeObserver(() => moveHighlight(hoveredItem.value));
  if (navigation.value) navObserver.observe(navigation.value);
});
onBeforeUnmount(() => navObserver?.disconnect());
const upcoming = [
  { name: "打浆分析", icon: ChartNoAxesCombined },
  { name: "复配分析", icon: Combine },
  { name: "纤维—纸张关联", icon: ScatterChart },
  { name: "再生纸浆循环", icon: Repeat2 },
  { name: "质量与追溯", icon: ScanSearch },
];
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <button
    v-if="navOpen"
    class="nav-scrim"
    aria-label="关闭导航"
    @click="navOpen = false"
  ></button>
  <aside class="sidebar" :class="{ open: navOpen }" aria-label="主导航">
    <div class="brand">
      <RouterLink class="brand-link" to="/" @click="navOpen = false">
        <img src="/favicon.svg" width="34" height="34" alt="" />
        <span
          ><strong>FiberScope</strong><small>纤维视界</small></span
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
        :style="{ transform: `translateY(${highlight.y}px)`, height: `${highlight.height}px` }"
      ></div>
      <RouterLink
        to="/"
        class="nav-item active"
        aria-current="page"
        @click="navOpen = false"
        ><LayoutDashboard :size="18" /><span>数据总览</span></RouterLink
      >
      <div class="nav-label second">分析与探索 <span>后续开放</span></div>
      <button
        v-for="item in upcoming"
        :key="item.name"
        class="nav-item"
        disabled
        :title="`${item.name}将在后续版本开放`"
      >
        <component :is="item.icon" :size="18" /><span>{{ item.name }}</span>
      </button>
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
  <div class="shell">
    <header class="topbar">
      <div class="breadcrumbs">
        <button
          class="icon-button mobile-toggle"
          aria-label="展开导航"
          :aria-expanded="navOpen"
          @click="navOpen = true"
        >
          <PanelLeftOpen :size="20" /></button
        ><span>植物纤维研究</span><ChevronRight :size="14" /><strong
          >数据总览</strong
        >
      </div>
      <span class="topbar-note">实验数据分析平台</span>
    </header>
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
