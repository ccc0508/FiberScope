<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import ShellPolarized from "./components/shell/ShellPolarized.vue";
import ShellGarden from "./components/shell/ShellGarden.vue";
import DataNotes from "./components/DataNotes.vue";
import { mode, reducedMotion } from "./mode";
import { pageLabelFor, platformName } from "./nav";

/*
 * App frame. The mode decides which chrome (ShellPolarized / ShellGarden) is drawn;
 * <main> with the <RouterView> stays in the same place in the tree, so switching modes
 * keeps the page instance, its loaded data, URL state and scroll position.
 * Routes with meta.bare (the /intro prologue) render without any chrome.
 */
const route = useRoute();
const bare = computed(() => route.meta.bare === true);

const pageTitle = computed(() => pageLabelFor(route.path));
watch(pageTitle, (title) => {
  document.title = `${title} · ${platformName}`;
});

/* ---------------------------------------------------------------- polarized: change objective = refocus */
// After a route change the page's blocks pull into focus one after another (CSS in
// styles/polarized.css). The class is removed again once the stagger has finished, so it
// never touches content that appears later (data loading) or a page's own animations.
const mainEl = ref<HTMLElement>();
let focusTimer = 0;
function focusPull() {
  const el = mainEl.value;
  window.clearTimeout(focusTimer);
  if (!el) return;
  el.classList.remove("pz-focus-in");
  if (mode.value !== "polarized" || reducedMotion.value) return;
  void el.offsetWidth; // restart the animation
  el.classList.add("pz-focus-in");
  focusTimer = window.setTimeout(() => el.classList.remove("pz-focus-in"), 1000);
}
watch(() => route.path, focusPull, { flush: "post" });

/* ---------------------------------------------------------------- data notes dialog */
const info = ref<InstanceType<typeof DataNotes> | null>(null);
function openInfo() {
  info.value?.open();
}

/* ---------------------------------------------------------------- mobile navigation drawer (polarized) */
const navOpen = ref(false);
const polarShell = ref<InstanceType<typeof ShellPolarized> | null>(null);
let mobileViewport: MediaQueryList | undefined;
function syncViewport() {
  if (!mobileViewport?.matches) navOpen.value = false;
}
function navigationKey(event: KeyboardEvent) {
  if (!navOpen.value || document.querySelector("dialog[open]")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    navOpen.value = false;
  } else if (event.key === "Tab") {
    const items = polarShell.value?.drawer?.querySelectorAll<HTMLElement>(
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
    } else if (!polarShell.value?.drawer?.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    }
  }
}
watch(navOpen, async (open) => {
  await nextTick();
  const drawer = polarShell.value?.drawer;
  if (open)
    (
      drawer?.querySelector<HTMLElement>('[aria-current="page"]') ??
      drawer?.querySelector<HTMLElement>("a[href]")
    )?.focus();
  else polarShell.value?.toggle?.focus({ preventScroll: true });
});
watch([mode, bare], () => {
  navOpen.value = false;
});

onMounted(() => {
  mobileViewport = window.matchMedia("(max-width: 720px)");
  mobileViewport.addEventListener("change", syncViewport);
  document.addEventListener("keydown", navigationKey);
  document.title = `${pageTitle.value} · ${platformName}`;
  focusPull();
});
onBeforeUnmount(() => {
  window.clearTimeout(focusTimer);
  mobileViewport?.removeEventListener("change", syncViewport);
  document.removeEventListener("keydown", navigationKey);
});
</script>

<template>
  <RouterView v-if="bare" />
  <template v-else>
    <a class="skip-link" href="#main">跳到主要内容</a>
    <ShellPolarized
      v-if="mode === 'polarized'"
      ref="polarShell"
      v-model:nav-open="navOpen"
      @about="openInfo"
    />
    <ShellGarden v-else @about="openInfo" />
    <div class="app-frame" :inert="navOpen">
      <main id="main" ref="mainEl" tabindex="-1"><RouterView /></main>
      <footer class="app-foot">
        <span class="app-foot-brand">FiberScope · {{ platformName }}</span>
        <span>植物纤维研究 · 实验数据工作台</span>
        <span class="app-foot-ro"
          ><i aria-hidden="true"></i>科研数据 · 只读访问 · 保留原始记录与实验口径</span
        >
      </footer>
    </div>
    <DataNotes ref="info" />
  </template>
</template>
