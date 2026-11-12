<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { Check, ChevronDown, Filter } from "lucide-vue-next";

interface Option {
  value: string;
  label: string;
  count?: number;
  color?: string;
}
const props = defineProps<{
  modelValue: string;
  options: Option[];
  id: string;
  label: string;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const root = ref<HTMLElement>();
const popover = ref<HTMLElement>();
const popoverLeft = ref(0);
/*
 * Vertical placement: the shells have fixed bars at the top and bottom (garden dock, phone
 * tab bar, polarized phone pill), measured by --chrome-top / --chrome-bottom. The popover
 * opens downward when it fits above the bottom bar, otherwise upward when there is more
 * room above; its height is capped to the room it has. With little room either way the
 * page scrolls it into view (html scroll-padding keeps it clear of the bars).
 */
const placement = ref<"down" | "up">("down");
const maxHeight = ref<number | null>(null);
const POPOVER_GAP = 8,
  VIEWPORT_MARGIN = 8,
  POPOVER_MAX = 360,
  POPOVER_MIN = 150;
function chromeInset(name: string) {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
}
function positionPopover() {
  if (!open.value || !root.value || !popover.value) return;
  const bounds = root.value.getBoundingClientRect();
  const width = popover.value.getBoundingClientRect().width;
  popoverLeft.value = Math.max(
    16 - bounds.left,
    Math.min(
      0,
      document.documentElement.clientWidth - 16 - bounds.left - width,
    ),
  );
}
function placePopover() {
  if (!open.value || !root.value || !popover.value) return;
  const bounds = root.value.getBoundingClientRect();
  const below =
    window.innerHeight - chromeInset("--chrome-bottom") - bounds.bottom - POPOVER_GAP - VIEWPORT_MARGIN;
  const above = bounds.top - chromeInset("--chrome-top") - POPOVER_GAP - VIEWPORT_MARGIN;
  const natural = Math.min(POPOVER_MAX, popover.value.scrollHeight);
  const up = natural > below && above > below;
  const room = up ? above : below;
  placement.value = up ? "up" : "down";
  if (room >= Math.min(natural, POPOVER_MIN)) {
    maxHeight.value = Math.min(POPOVER_MAX, Math.floor(room));
    return;
  }
  // no usable room on either side: open downward at a readable height and scroll to it
  placement.value = "down";
  maxHeight.value = Math.min(POPOVER_MAX, Math.max(POPOVER_MIN, Math.floor(window.innerHeight * 0.5)));
  void nextTick(() => popover.value?.scrollIntoView({ block: "nearest" }));
}
const trigger = ref<HTMLButtonElement>();
const open = ref(false);
const active = ref(0);
watch(open, async (isOpen) => {
  if (!isOpen) return;
  placement.value = "down";
  maxHeight.value = null;
  await nextTick();
  placePopover();
  positionPopover();
});
watch([active, open], async () => {
  await nextTick();
  if (open.value && popover.value) {
    positionPopover();
    const option = root.value?.querySelector<HTMLElement>(
      `[id="${props.id}-${active.value}"]`,
    );
    if (!option) return;
    const item = option.getBoundingClientRect(),
      box = popover.value.getBoundingClientRect();
    if (item.top < box.top) popover.value.scrollTop -= box.top - item.top;
    else if (item.bottom > box.bottom)
      popover.value.scrollTop += item.bottom - box.bottom;
  }
});
function onResize() {
  placePopover();
  positionPopover();
}
const selected = computed(
  () =>
    props.options.find((o) => o.value === props.modelValue) ?? props.options[0],
);
function show() {
  active.value = Math.max(
    0,
    props.options.findIndex((o) => o.value === props.modelValue),
  );
  open.value = true;
}
function choose(index: number) {
  const option = props.options[index];
  if (!option) return;
  emit("update:modelValue", option.value);
  open.value = false;
  trigger.value?.focus({ preventScroll: true });
}
function keydown(event: KeyboardEvent) {
  if (event.key === "Tab") {
    open.value = false;
    return;
  }
  if (event.key === "Escape") {
    if (open.value) {
      event.preventDefault();
      event.stopPropagation();
      open.value = false;
    }
    return;
  }
  if (
    !["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)
  )
    return;
  event.preventDefault();
  if (!open.value) {
    show();
    return;
  }
  if (event.key === "Enter" || event.key === " ") {
    choose(active.value);
    return;
  }
  if (event.key === "Home") active.value = 0;
  else if (event.key === "End") active.value = props.options.length - 1;
  else
    active.value =
      (active.value +
        (event.key === "ArrowDown" ? 1 : -1) +
        props.options.length) %
      props.options.length;
}
function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", outside);
  window.addEventListener("resize", onResize);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", outside);
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <div
    ref="root"
    class="filter-select"
    @focusout="!root?.contains($event.relatedTarget as Node) && (open = false)"
  >
    <button
      ref="trigger"
      type="button"
      class="filter-trigger"
      :class="{ expanded: open, filtered: !!modelValue }"
      role="combobox"
      :aria-label="label"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-controls="`${id}-options`"
      :aria-activedescendant="open ? `${id}-${active}` : undefined"
      @click="open ? (open = false) : show()"
      @keydown="keydown"
    >
      <Filter :size="15" /><span>{{ selected?.label }}</span
      ><ChevronDown :size="14" class="filter-chevron" />
    </button>
    <Transition name="filter-pop">
      <div
        v-if="open"
        ref="popover"
        class="filter-popover"
        :class="{ up: placement === 'up' }"
        :style="{
          left: `${popoverLeft}px`,
          maxHeight: maxHeight != null ? `${maxHeight}px` : undefined,
        }"
      >
        <div class="filter-popover-title">{{ label }}</div>
        <div :id="`${id}-options`" role="listbox" :aria-label="label">
          <div
            v-for="(option, index) in options"
            :id="`${id}-${index}`"
            :key="option.value"
            role="option"
            :aria-selected="option.value === modelValue"
            class="filter-option"
            :class="{
              selected: option.value === modelValue,
              highlighted: index === active,
            }"
            @pointermove="active = index"
            @mousedown.prevent
            @click="choose(index)"
          >
            <span
              class="filter-option-dot"
              :style="option.color ? { background: option.color } : undefined"
            ></span>
            <span class="filter-option-label">{{ option.label }}</span>
            <span v-if="option.count != null" class="filter-option-count">{{
              option.count
            }}</span>
            <Check
              :size="15"
              class="filter-check"
              :class="{ visible: option.value === modelValue }"
            />
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.filter-select {
  position: relative;
  flex-shrink: 0;
}
.filter-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 13px;
  white-space: nowrap;
  transition:
    border-color 0.15s,
    background 0.15s,
    box-shadow 0.15s,
    color 0.15s;
}
.filter-trigger:hover {
  color: var(--text);
  background: var(--surface-hover);
}
.filter-trigger.expanded {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px var(--accent-tint);
}
.filter-trigger.filtered {
  color: var(--accent-ink);
  border-color: var(--accent);
  background: var(--accent-tint);
}
.filter-chevron {
  margin-left: 3px;
  transition: transform 0.16s;
}
.expanded .filter-chevron {
  transform: rotate(180deg);
}
.filter-popover {
  position: absolute;
  left: 0;
  top: calc(100% + 8px);
  width: 252px;
  max-width: calc(100vw - 48px);
  max-height: min(360px, 50vh);
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 7px;
  box-shadow: var(--shadow-pop);
  z-index: 20;
  transform-origin: top left;
}
.filter-popover.up {
  top: auto;
  bottom: calc(100% + 8px);
  transform-origin: bottom left;
}
.filter-popover-title {
  padding: 7px 9px 9px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
}
.filter-option {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 38px;
  padding: 8px 10px;
  border-radius: var(--radius-xs);
  cursor: pointer;
  color: var(--text-2);
  font-size: 13px;
  transition:
    background 0.1s,
    color 0.1s;
}
.filter-option.highlighted {
  background: var(--surface-hover);
  color: var(--text);
}
.filter-option.selected {
  color: var(--accent-ink);
  background: var(--accent-tint);
}
.filter-option-dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex-shrink: 0;
  background: var(--text-3);
}
.filter-option-label {
  flex: 1;
}
.filter-option-count {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.filter-check {
  visibility: hidden;
  color: var(--accent-ink);
}
.filter-check.visible {
  visibility: visible;
}

/* polarized: dark field, hairlines, interference edge when open */
:root[data-mode="polarized"] .filter-trigger {
  border-radius: var(--radius-sm);
  border-color: var(--line);
}
:root[data-mode="polarized"] .filter-trigger.expanded {
  border-color: transparent;
  background:
    linear-gradient(var(--surface-2), var(--surface-2)) padding-box,
    var(--ifl) border-box;
  box-shadow: none;
}
:root[data-mode="polarized"] .filter-popover {
  background: linear-gradient(180deg, #151923, #0d1016);
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .filter-option.selected {
  color: var(--text);
  background: rgba(255, 255, 255, 0.08);
  box-shadow: inset 2px 0 0 var(--accent);
}

/* garden: white pill, glass popover */
:root[data-mode="garden"] .filter-trigger {
  border: 0;
  color: var(--text);
  background: rgba(255, 255, 255, 0.72);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.95),
    0 6px 16px -12px rgba(74, 52, 110, 0.45);
}
:root[data-mode="garden"] .filter-trigger:hover {
  background: #fff;
}
:root[data-mode="garden"] .filter-trigger.expanded {
  box-shadow:
    inset 0 0 0 1px #fff,
    0 0 0 3px rgba(106, 76, 192, 0.22);
}
:root[data-mode="garden"] .filter-trigger.filtered {
  color: var(--bl-ink);
  background: var(--bl-tint);
}
:root[data-mode="garden"] .filter-popover {
  border: 0;
  border-radius: 22px;
  padding: 8px;
  /* opaque: chart text behind the popover must not show through next to the options */
  background: linear-gradient(160deg, #ffffff, #fff8f5);
  box-shadow:
    inset 0 0 0 1px #fff,
    0 30px 60px -28px rgba(74, 52, 110, 0.5);
}
:root[data-mode="garden"] .filter-option {
  border-radius: 14px;
}
:root[data-mode="garden"] .filter-option.selected {
  color: var(--text);
  background: var(--bl-tint);
}

.filter-pop-enter-active {
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
}
.filter-pop-leave-active {
  transition:
    opacity 0.1s ease,
    transform 0.1s ease;
}
.filter-pop-enter-from,
.filter-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
.filter-popover.up.filter-pop-enter-from,
.filter-popover.up.filter-pop-leave-to {
  transform: translateY(4px) scale(0.98);
}
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
  }
}
</style>
