<script setup lang="ts">
/*
 * One live number in the garden prologue: a soft placeholder while the API answers,
 * then the formatted value ("—" when the API has no value; 0 stays 0).
 */
defineProps<{ value: string; busy?: boolean; width?: string }>();
</script>

<template>
  <span v-if="busy" class="lv-busy"
    ><span class="lv-skel" aria-hidden="true" :style="{ width: width ?? '2.6em' }"></span
    ><span class="sr-only">读取中</span></span
  >
  <template v-else>{{ value }}</template>
</template>

<style scoped>
.lv-busy {
  display: inline-flex;
  vertical-align: middle;
}
.lv-skel {
  display: inline-block;
  height: 0.9em;
  border-radius: 999px;
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--text) 8%, transparent),
    color-mix(in srgb, var(--text) 16%, transparent),
    color-mix(in srgb, var(--text) 8%, transparent)
  );
  background-size: 200% 100%;
  animation: lv-shimmer 1.4s linear infinite;
}
@keyframes lv-shimmer {
  to {
    background-position: -200% 0;
  }
}
</style>
