<script setup lang="ts">
import { ref } from "vue";
import { mode, setMode, type Mode } from "../mode";

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const options: { value: Mode; label: string; hint: string }[] = [
  { value: "polarized", label: "偏光", hint: "深色 · 正交偏光显微镜" },
  { value: "garden", label: "花园", hint: "浅色 · 纤维花园" },
];
const buttons = ref<HTMLButtonElement[]>([]);

/*
 * The other mode draws its own switch (another shell, or another prologue on /intro, which
 * may still be loading its chunk). Keep keyboard focus on the chosen option: focus it as
 * soon as it exists, unless the visitor has moved focus somewhere else in the meantime.
 */
const CHECKED = '.mode-switch [role="radio"][aria-checked="true"]';
function restoreFocus() {
  const focusLost = () =>
    !document.activeElement || document.activeElement === document.body;
  const tryFocus = () => {
    const target = document.querySelector<HTMLElement>(CHECKED);
    if (!target) return false;
    target.focus({ preventScroll: true });
    return true;
  };
  if (!focusLost() || tryFocus()) return;
  const observer = new MutationObserver(() => {
    if (!focusLost() || tryFocus()) stop();
  });
  const timer = window.setTimeout(() => stop(), 8000);
  function stop() {
    observer.disconnect();
    window.clearTimeout(timer);
  }
  observer.observe(document.body, { childList: true, subtree: true });
}
async function choose(value: Mode) {
  const hadFocus = !!buttons.value.some((b) => b === document.activeElement);
  await setMode(value);
  if (hadFocus && !document.activeElement?.closest(".mode-switch")) restoreFocus();
}
// radiogroup keyboard model: arrows move and select, focus follows
function keydown(event: KeyboardEvent, index: number) {
  const step =
    event.key === "ArrowRight" || event.key === "ArrowDown"
      ? 1
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? -1
        : 0;
  if (!step) return;
  event.preventDefault();
  const next = (index + step + options.length) % options.length;
  buttons.value[next]?.focus();
  void choose(options[next]!.value);
}
</script>

<template>
  <div
    class="mode-switch"
    :class="{ compact }"
    role="radiogroup"
    aria-label="界面风格"
  >
    <button
      v-for="(option, index) in options"
      :key="option.value"
      ref="buttons"
      type="button"
      role="radio"
      class="mode-option"
      :class="`mode-option--${option.value}`"
      :aria-checked="mode === option.value"
      :tabindex="mode === option.value ? 0 : -1"
      :title="option.hint"
      @click="choose(option.value)"
      @keydown="keydown($event, index)"
    >
      <svg
        v-if="option.value === 'polarized'"
        class="mode-glyph"
        viewBox="0 0 16 16"
        aria-hidden="true"
      >
        <circle cx="8" cy="8" r="5.4" fill="none" stroke="currentColor" stroke-width="1.3" />
        <line x1="3" y1="13" x2="13" y2="3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
      </svg>
      <svg v-else class="mode-glyph" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M2.5 11c3-5 5.5 1.6 11-4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        <path d="M2.5 7c3.4 3.3 6.4-3.8 11 .4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" opacity=".7" />
      </svg>
      <span class="mode-label">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.mode-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  flex-shrink: 0;
}
.mode-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 11px 0 9px;
  border-radius: 999px;
  font-size: 13px;
  line-height: 1;
  white-space: nowrap;
  transition:
    background 0.2s,
    color 0.2s,
    box-shadow 0.2s;
}
.mode-glyph {
  width: 15px;
  height: 15px;
}
.compact .mode-option {
  padding: 0 9px 0 8px;
  gap: 5px;
}
/* narrow phones: glyphs only (the label stays as the accessible name) */
@media (max-width: 440px) {
  .compact .mode-option {
    padding: 0 8px;
  }
  .compact .mode-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
}

/* polarized: hairline pill, the chosen objective lit by an interference ring */
:root[data-mode="polarized"] .mode-switch {
  border: 1px solid var(--line-strong);
  background: rgba(255, 255, 255, 0.02);
}
:root[data-mode="polarized"] .mode-option {
  color: var(--text-2);
  border: 1px solid transparent;
  min-height: 28px;
}
:root[data-mode="polarized"] .mode-option:hover {
  color: var(--text);
}
:root[data-mode="polarized"] .mode-option[aria-checked="true"] {
  color: var(--text);
  background:
    linear-gradient(#171b25, #171b25) padding-box,
    var(--ifl) border-box;
}
:root[data-mode="polarized"] .mode-option[aria-checked="true"] .mode-glyph circle {
  stroke: var(--bl);
}

/* garden: soft segmented control with a white blob */
:root[data-mode="garden"] .mode-switch {
  background: rgba(255, 255, 255, 0.5);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.9),
    inset 0 2px 6px rgba(74, 52, 110, 0.07);
}
:root[data-mode="garden"] .mode-option {
  color: var(--text-2);
}
:root[data-mode="garden"] .mode-option:hover {
  color: var(--text);
}
:root[data-mode="garden"] .mode-option[aria-checked="true"] {
  color: var(--text);
  font-weight: 500;
  background: linear-gradient(135deg, #fff 0%, #fff6f1 100%);
  box-shadow:
    0 6px 14px -8px rgba(74, 52, 110, 0.5),
    inset 0 0 0 1px #fff;
}
:root[data-mode="garden"] .mode-option--garden[aria-checked="true"] .mode-glyph path:first-child {
  stroke: var(--sw);
}
:root[data-mode="garden"] .mode-option--garden[aria-checked="true"] .mode-glyph path:last-child {
  stroke: var(--hw);
}
</style>
