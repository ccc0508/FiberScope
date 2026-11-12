<script setup lang="ts">
import { defineAsyncComponent, onMounted } from "vue";
import { mode } from "../mode";

/*
 * /intro (序章) — rendered without any workspace shell (route meta.bare).
 * Each mode has its own prologue. The active one loads first; the other is fetched once the
 * page is idle, so a mode switch swaps prologues without an empty frame. Each prologue
 * draws its own ModeSwitch; ModeSwitch moves keyboard focus to the new one when it mounts.
 */
const loadPolarized = () => import("../intro/IntroPolarized.vue");
const loadGarden = () => import("../intro/IntroGarden.vue");
const IntroPolarized = defineAsyncComponent(loadPolarized);
const IntroGarden = defineAsyncComponent(loadGarden);

onMounted(() => {
  const other = mode.value === "polarized" ? loadGarden : loadPolarized;
  const prefetch = () => void other().catch(() => undefined);
  if (typeof window.requestIdleCallback === "function")
    window.requestIdleCallback(prefetch, { timeout: 3000 });
  else setTimeout(prefetch, 1500);
});
</script>

<template>
  <IntroPolarized v-if="mode === 'polarized'" />
  <IntroGarden v-else />
</template>
