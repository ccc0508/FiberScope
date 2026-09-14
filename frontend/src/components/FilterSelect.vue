<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
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
const trigger = ref<HTMLButtonElement>();
const open = ref(false);
const active = ref(0);
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
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => document.removeEventListener("pointerdown", outside));
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
      <div v-if="open" class="filter-popover">
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
              :style="{ background: option.color ?? '#99a8b9' }"
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
  height: 35px;
  padding: 0 11px;
  border: 1px solid #dfe5ec;
  border-radius: 6px;
  background: white;
  color: #617085;
  font-size: 13px;
  transition:
    border-color 0.15s,
    background 0.15s,
    box-shadow 0.15s;
}
.filter-trigger:hover {
  border-color: #a9c4dc;
  background: #f8fbfe;
}
.filter-trigger.expanded {
  border-color: #6ca1ce;
  box-shadow: 0 0 0 3px #4386bf14;
}
.filter-trigger.filtered {
  color: #3476ad;
  background: #f1f7fc;
  border-color: #bbd4e9;
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
  top: calc(100% + 7px);
  width: 252px;
  max-width: calc(100vw - 48px);
  background: white;
  border: 1px solid #e0e7ef;
  border-radius: 9px;
  padding: 7px;
  box-shadow:
    0 8px 28px #253d571a,
    0 2px 6px #253d5709;
  z-index: 20;
  transform-origin: top left;
}
.filter-popover-title {
  padding: 7px 9px 9px;
  color: #8996a6;
  font-size: 11px;
  font-weight: 500;
}
.filter-option {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 38px;
  padding: 8px 9px;
  border-radius: 5px;
  cursor: pointer;
  color: #596c81;
  font-size: 13px;
  transition:
    background 0.1s,
    color 0.1s;
}
.filter-option.highlighted {
  background: #f1f5fa;
}
.filter-option.selected {
  color: #3476ad;
  background: #edf5fc;
}
.filter-option.selected.highlighted {
  background: #e5f0fb;
}
.filter-option-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  flex-shrink: 0;
}
.filter-option-label {
  flex: 1;
}
.filter-option-count {
  font-size: 11px;
  color: #899caf;
  font-variant-numeric: tabular-nums;
}
.filter-check {
  visibility: hidden;
  color: #4386bf;
}
.filter-check.visible {
  visibility: visible;
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
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
  }
}
</style>
