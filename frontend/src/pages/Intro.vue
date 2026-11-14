<script lang="ts">
import { shallowReactive, type Component } from "vue";
import type { Mode } from "../mode";

/*
 * Resolved prologue modules, kept for the lifetime of the app (module scope): a mode switch,
 * or a later visit to /intro, renders the prologue synchronously. The page never collapses
 * to an empty frame, which would clamp the scroll position to 0 and drop keyboard focus.
 */
const loaders: Record<Mode, () => Promise<{ default: Component }>> = {
  polarized: () => import("../intro/IntroPolarized.vue"),
  garden: () => import("../intro/IntroGarden.vue"),
};
const resolved = shallowReactive<Partial<Record<Mode, Component>>>({});
const pending: Partial<Record<Mode, Promise<void>>> = {};
function load(value: Mode): Promise<void> {
  if (resolved[value]) return Promise.resolve();
  return (pending[value] ??= loaders[value]().then(
    (module) => {
      resolved[value] = module.default;
    },
    (error: unknown) => {
      delete pending[value]; // a failed chunk is requested again on the next try
      throw error;
    },
  ));
}
</script>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, watchEffect } from "vue";
import { mode } from "../mode";

/*
 * /intro (序章) — rendered without any workspace shell (route meta.bare).
 * Each mode has its own prologue. The active one loads first; the other is fetched once the
 * page is idle. Should a switch arrive before that chunk, the current prologue stays on
 * screen (keeping the page height, so the scroll position survives) until the new one can
 * replace it in a single render. Each prologue draws its own ModeSwitch, and focus moves to
 * the new switch's checked option.
 */
const shown = ref<Mode | null>(null);
const failed = ref(false);
watchEffect(() => {
  if (resolved[mode.value]) shown.value = mode.value;
});
watch(
  mode,
  (value) => {
    failed.value = false;
    load(value).catch(() => {
      if (mode.value === value) failed.value = true;
    });
  },
  { immediate: true },
);
const current = computed(() =>
  failed.value || !shown.value ? undefined : resolved[shown.value],
);

// A swap that waited for its chunk happens after ModeSwitch has finished; keep focus on the
// switch (runs before the DOM update, so the old prologue still holds the focus here).
watch(shown, async (next, previous) => {
  if (!previous) return;
  const hadFocus = !!document.activeElement?.closest(".mode-switch");
  await nextTick();
  if (hadFocus && (!document.activeElement || document.activeElement === document.body))
    document
      .querySelector<HTMLElement>('.mode-switch [role="radio"][aria-checked="true"]')
      ?.focus({ preventScroll: true });
});

onMounted(() => {
  const other: Mode = mode.value === "polarized" ? "garden" : "polarized";
  const prefetch = () => void load(other).catch(() => undefined);
  if (typeof window.requestIdleCallback === "function")
    window.requestIdleCallback(prefetch, { timeout: 3000 });
  else setTimeout(prefetch, 1500);
});
</script>

<template>
  <component :is="current" v-if="current" />
  <main v-else-if="failed" id="main" class="intro-failed" tabindex="-1">
    <h1>序章</h1>
    <p role="alert">序章暂时无法加载，请检查网络后刷新页面。</p>
    <RouterLink class="button primary" to="/">进入工作台</RouterLink>
  </main>
</template>

<style scoped>
.intro-failed {
  display: grid;
  place-content: center;
  justify-items: start;
  gap: 14px;
  min-height: 100vh;
  padding: 24px 16px;
  color: var(--text);
}
.intro-failed h1 {
  margin: 0;
  font-size: 28px;
}
.intro-failed p {
  margin: 0;
  color: var(--text-2);
}
</style>
