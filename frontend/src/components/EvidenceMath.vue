<script setup lang="ts">
import { ref, watchPostEffect } from 'vue';
import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/dist/katex.min.css';

const props = defineProps<{ text: string }>();
const host = ref<HTMLElement>();
watchPostEffect(() => {
  if (!host.value) return;
  // Reset on history changes; source HTML is always treated as plain text.
  host.value.textContent = props.text;
  renderMathInElement(host.value, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '$', right: '$', display: false },
      { left: '\\(', right: '\\)', display: false },
      { left: '\\[', right: '\\]', display: true },
    ],
    trust: false,
    throwOnError: true,
    strict: 'ignore',
    maxExpand: 500,
    maxSize: 20,
    // Auto-render leaves invalid formulas as their original text.
    errorCallback: () => {},
  });
});
</script>

<template><span ref="host" class="evidence-math" /></template>

<style scoped>
.evidence-math { white-space: pre-wrap; overflow-wrap: anywhere; }
.evidence-math :deep(.katex) { white-space: normal; }
.evidence-math :deep(.katex-display) { overflow-x: auto; overflow-y: hidden; padding: 6px 0; max-width: 100%; }
</style>
