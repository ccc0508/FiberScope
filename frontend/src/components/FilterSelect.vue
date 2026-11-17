<script lang="ts">
/** One choice in a FilterSelect. Everything but `value` and `label` is optional. */
export interface FilterOption {
  value: string;
  label: string;
  /** a count shown in mono on the right (e.g. samples per type) */
  count?: number;
  /** dot colour, for options that encode a series (use materialColors[key]) */
  color?: string;
  /** secondary text shown in mono on the right, e.g. the unit */
  hint?: string;
  /** group heading; keep the options of one group adjacent (they render in first-seen order) */
  group?: string;
  /** material stain marker: circle / rounded square / triangle in the material colour */
  marker?: "softwood" | "hardwood" | "blend";
}
</script>

<script setup lang="ts">
/*
 * FilterSelect — a select-only combobox (button[role=combobox] + listbox) styled per mode.
 *
 * - The popover is a `popover="manual"` element, so it renders in the top layer: above the
 *   garden dock and the polarized phone pill, never clipped or dimmed by its card, yet it
 *   stays inside the component in the DOM (focus order, `contains`, scoped CSS all work).
 * - Long lists (> 7 options, or `searchable`) get an inline search field that filters the
 *   listbox as you type (role=combobox on the input, aria-activedescendant on the options).
 * - On phones (≤ 720px) the list opens as a bottom sheet with a scrim; focus is trapped in
 *   the sheet and returns to the trigger when it closes.
 * Keyboard: Enter / Space / Alt+↓ / ↑ / ↓ open; ↑ ↓ Home End PageUp PageDown move; Enter or
 * Space (Alt+↑) choose; Escape closes and refocuses the trigger; Tab closes; typing jumps to
 * a matching option (or starts a search in a searchable list).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Check, ChevronDown, Search, X } from "lucide-vue-next";
import { reducedMotion } from "../mode";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: FilterOption[];
    /** id of the trigger; the listbox is `${id}-options`, options `${id}-${index}` */
    id: string;
    /** accessible name of the field, the sheet title on phones */
    label: string;
    /** short visible label inside the trigger, before the value (for toolbars without a label) */
    eyebrow?: string;
    /** show a search field: "auto" = more than 7 options */
    searchable?: boolean | "auto";
    size?: "default" | "compact";
    /** fill the width of the container */
    block?: boolean;
    /** shown when no option matches modelValue (otherwise the first option is shown) */
    placeholder?: string;
    /** the "everything" value; any other value marks the field as filtered */
    resetValue?: string;
    disabled?: boolean;
  }>(),
  {
    eyebrow: undefined,
    searchable: "auto",
    size: "default",
    block: false,
    placeholder: undefined,
    resetValue: "",
    disabled: false,
  },
);
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const root = ref<HTMLElement>(),
  trigger = ref<HTMLButtonElement>(),
  layer = ref<HTMLElement>(),
  scroller = ref<HTMLElement>(),
  listbox = ref<HTMLElement>(),
  searchInput = ref<HTMLInputElement>();
const open = ref(false),
  sheet = ref(false),
  up = ref(false),
  query = ref(""),
  active = ref(-1),
  fadeTop = ref(false),
  fadeBottom = ref(false),
  dragY = ref(0),
  dragging = ref(false);

/* ---------------------------------------------------------------- options */
const searchable = computed(() =>
  props.searchable === "auto" ? props.options.length > 7 : props.searchable,
);
const selectedIndex = computed(() =>
  props.options.findIndex((o) => o.value === props.modelValue),
);
const selected = computed<FilterOption | undefined>(() =>
  selectedIndex.value >= 0
    ? props.options[selectedIndex.value]
    : props.placeholder != null
      ? undefined
      : props.options[0],
);
const filtered = computed(
  () =>
    props.modelValue !== props.resetValue &&
    props.options.some((o) => o.value === props.resetValue),
);
const fold = (text: string) => text.toLowerCase();
/** search form of a text: lower case without spaces and punctuation, plus the index of each
 *  kept character in the original (so "G03 第 2" finds "G03，第 2 次循环" and can mark it) */
const SKIP = /[\s,，、.。·・:：;；()（）[\]【】\-–—_/]/;
function normalize(text: string) {
  let out = "";
  const at: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (SKIP.test(ch)) continue;
    out += ch.toLowerCase();
    at.push(i);
  }
  return { text: out, at };
}
interface Row {
  option: FilterOption;
  index: number;
  parts: [string, string, string] | null;
}
const rows = computed<Row[]>(() => {
  const needle = normalize(query.value).text;
  const out: Row[] = [];
  props.options.forEach((option, index) => {
    if (!needle) {
      out.push({ option, index, parts: null });
      return;
    }
    const label = normalize(option.label);
    const hit = label.text.indexOf(needle);
    if (hit >= 0) {
      const from = label.at[hit]!,
        to = label.at[hit + needle.length - 1]! + 1;
      out.push({
        option,
        index,
        parts: [option.label.slice(0, from), option.label.slice(from, to), option.label.slice(to)],
      });
    } else if (
      normalize(option.hint ?? "").text.includes(needle) ||
      normalize(option.group ?? "").text.includes(needle)
    )
      out.push({ option, index, parts: null });
  });
  return out;
});
const sections = computed(() => {
  const out: { label: string | null; rows: Row[] }[] = [];
  for (const row of rows.value) {
    const label = row.option.group ?? null;
    let section = out.find((s) => s.label === label);
    if (!section) out.push((section = { label, rows: [] }));
    section.rows.push(row);
  }
  return out;
});
/** navigation order = render order (grouped) */
const flat = computed(() => sections.value.flatMap((s) => s.rows));
const total = computed(() =>
  query.value.trim()
    ? `${flat.value.length} / ${props.options.length}`
    : `${props.options.length} 项`,
);
/** reserve the width of the longest choice so the field does not jump when the value changes */
const reserve = computed(() => {
  if (props.block || props.size === "compact") return undefined;
  const width = (text: string, cjk: number, latin: number) =>
    [...text].reduce((w, ch) => w + (/[\u2e80-\uffef]/.test(ch) ? cjk : latin), 0);
  let widest = 0;
  for (const o of props.options) {
    const side = o.hint
      ? width(o.hint, 11.5, 7.2) + 8
      : o.count != null
        ? String(o.count).length * 7.4 + 8
        : 0;
    widest = Math.max(widest, width(o.label, 14, 7.8) + side + (o.marker || o.color ? 17 : 0));
  }
  const eyebrow = props.eyebrow ? width(props.eyebrow, 12, 7.4) + 22 : 0;
  return `${Math.round(Math.min(208, widest + eyebrow + 60))}px`;
});

/* ---------------------------------------------------------------- open / close */
const phone = () => window.matchMedia("(max-width: 720px)").matches;
function show(seed = "") {
  if (props.disabled || !props.options.length) return;
  query.value = seed;
  sheet.value = phone();
  // a keyboard user can open a trigger that has scrolled out of view: bring it back first
  // (html scroll-padding keeps it clear of the fixed chrome)
  const t = trigger.value?.getBoundingClientRect();
  if (
    !sheet.value &&
    t &&
    (t.top < chromeInset("--chrome-top") ||
      t.bottom > window.innerHeight - chromeInset("--chrome-bottom"))
  )
    trigger.value?.scrollIntoView({ block: "nearest", behavior: "instant" });
  const list = flat.value;
  active.value = list.some((r) => r.index === selectedIndex.value)
    ? selectedIndex.value
    : (list[0]?.index ?? -1);
  open.value = true;
}
function close(refocus = true) {
  if (!open.value) return;
  open.value = false;
  if (refocus) trigger.value?.focus({ preventScroll: true });
}
function choose(index: number) {
  const option = props.options[index];
  if (!option) return;
  emit("update:modelValue", option.value);
  close();
}
function toggle() {
  if (open.value) close();
  else show();
}

/* ---------------------------------------------------------------- active option */
let scrollToActive = false;
function setActive(index: number, reveal = true) {
  scrollToActive = reveal;
  active.value = index;
}
function move(step: number | "first" | "last") {
  const list = flat.value;
  if (!list.length) return;
  const at = list.findIndex((r) => r.index === active.value);
  const next =
    step === "first"
      ? 0
      : step === "last"
        ? list.length - 1
        : at < 0
          ? 0
          : Math.abs(step) > 1
            ? Math.max(0, Math.min(list.length - 1, at + step))
            : (at + step + list.length) % list.length;
  setActive(list[next]!.index);
}
watch(query, () => {
  const list = flat.value;
  const keep = !query.value.trim() && list.some((r) => r.index === selectedIndex.value);
  setActive(keep ? selectedIndex.value : (list[0]?.index ?? -1));
  void nextTick(updateFades);
});
watch(
  () => props.options,
  () => {
    if (open.value && !flat.value.some((r) => r.index === active.value))
      setActive(flat.value[0]?.index ?? -1, false);
  },
);
watch(active, async () => {
  if (!scrollToActive || !open.value) return;
  scrollToActive = false;
  await nextTick();
  const box = scroller.value,
    option = box?.querySelector<HTMLElement>(`[id="${props.id}-${active.value}"]`);
  if (!box || !option) return;
  const item = option.getBoundingClientRect(),
    view = box.getBoundingClientRect(),
    pad = 18; // clear the fade masks
  if (item.top < view.top + pad) box.scrollTop -= view.top + pad - item.top;
  else if (item.bottom > view.bottom - pad) box.scrollTop += item.bottom - (view.bottom - pad);
});
const activeId = computed(() =>
  open.value && active.value >= 0 && flat.value.some((r) => r.index === active.value)
    ? `${props.id}-${active.value}`
    : undefined,
);

/* ---------------------------------------------------------------- keyboard */
let typed = "",
  typedAt = 0;
function typeahead(char: string) {
  const now = Date.now();
  typed = now - typedAt > 700 ? char : typed + char;
  typedAt = now;
  const list = flat.value;
  if (!list.length) return;
  const at = Math.max(0, list.findIndex((r) => r.index === active.value));
  const from = typed.length === 1 ? at + 1 : at;
  const ordered = [...list.slice(from), ...list.slice(0, from)];
  const hit = ordered.find((r) => fold(r.option.label).startsWith(fold(typed)));
  if (hit) setActive(hit.index);
}
const printable = (e: KeyboardEvent) =>
  e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
function onKeydown(event: KeyboardEvent, from: "trigger" | "search" | "list") {
  if (event.isComposing || event.keyCode === 229) return; // IME (中文输入) owns these keys
  const key = event.key;
  if (key === "Tab") {
    if (!open.value) return;
    if (sheet.value) {
      trapTab(event);
      return;
    }
    // close and let the browser continue the tab order from the trigger
    if (from !== "trigger") trigger.value?.focus({ preventScroll: true });
    close(false);
    return;
  }
  if (key === "Escape") {
    if (!open.value) return;
    event.preventDefault();
    event.stopPropagation();
    close();
    return;
  }
  if (!open.value) {
    if (from !== "trigger") return;
    if (["ArrowDown", "ArrowUp", "Enter", " ", "Home", "End"].includes(key)) {
      event.preventDefault();
      show();
      if (key === "Home") move("first");
      else if (key === "End") move("last");
    } else if (printable(event)) {
      event.preventDefault();
      if (searchable.value) show(key);
      else {
        show();
        typeahead(key);
      }
    }
    return;
  }
  switch (key) {
    case "Enter":
      event.preventDefault();
      if (active.value >= 0) choose(active.value);
      return;
    case " ":
      if (from === "search" || (typed && Date.now() - typedAt < 700)) {
        if (from !== "search") {
          event.preventDefault();
          typeahead(" ");
        }
        return;
      }
      event.preventDefault();
      if (active.value >= 0) choose(active.value);
      return;
    case "ArrowUp":
      event.preventDefault();
      if (event.altKey) {
        if (active.value >= 0) choose(active.value);
        else close();
      } else move(-1);
      return;
    case "ArrowDown":
      event.preventDefault();
      if (!event.altKey) move(1);
      return;
    case "Home":
      event.preventDefault();
      move("first");
      return;
    case "End":
      event.preventDefault();
      move("last");
      return;
    case "PageUp":
      event.preventDefault();
      move(-10);
      return;
    case "PageDown":
      event.preventDefault();
      move(10);
      return;
  }
  if (from !== "search" && printable(event)) {
    event.preventDefault();
    if (searchable.value) {
      query.value += key;
      searchInput.value?.focus({ preventScroll: true });
    } else typeahead(key);
  }
}
/** phone sheet: Tab cycles inside the sheet */
function trapTab(event: KeyboardEvent) {
  const nodes = [
    ...(layer.value?.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input, [role=listbox]",
    ) ?? []),
  ];
  if (!nodes.length) return;
  event.preventDefault();
  const at = nodes.indexOf(document.activeElement as HTMLElement);
  const next = (at + (event.shiftKey ? -1 : 1) + nodes.length) % nodes.length;
  nodes[at < 0 ? 0 : next]!.focus({ preventScroll: true });
}

/* ---------------------------------------------------------------- placement (desktop) */
const GAP = 8,
  EDGE = 16,
  MARGIN = 12;
let naturalWidth = 0,
  naturalHeight = 0,
  lastRect = "",
  frame = 0;
function chromeInset(name: string) {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
}
function measure() {
  const el = layer.value;
  if (!el) return;
  const vw = document.documentElement.clientWidth;
  el.style.width = "max-content";
  el.style.maxWidth = `${Math.min(searchable.value ? 420 : 380, vw - EDGE * 2)}px`;
  el.style.setProperty("--filter-max-h", "none");
  naturalWidth = el.offsetWidth + 2; // offsetWidth rounds; a fraction short wraps the widest row
  naturalHeight = el.offsetHeight;
  el.style.maxWidth = "";
}
function place() {
  const el = layer.value,
    t = trigger.value?.getBoundingClientRect();
  if (!el || !t || sheet.value) return;
  const vw = document.documentElement.clientWidth,
    vh = window.innerHeight;
  const maxW = Math.min(searchable.value ? 420 : 380, vw - EDGE * 2);
  const minW = Math.min(maxW, Math.max(t.width, props.size === "compact" ? 120 : 232));
  const width = Math.round(Math.min(maxW, Math.max(minW, naturalWidth)));
  const left = Math.round(Math.max(EDGE, Math.min(t.left, vw - EDGE - width)));
  const cap = searchable.value ? 440 : 380;
  // keep clear of the fixed chrome: the garden dock / polarized pill below, the header above
  const below = vh - chromeInset("--chrome-bottom") - t.bottom - GAP - MARGIN,
    above = t.top - chromeInset("--chrome-top") - GAP - MARGIN;
  const natural = Math.min(cap, naturalHeight);
  up.value = natural > below && above > below;
  const room = Math.floor(up.value ? above : below);
  el.style.width = `${width}px`;
  el.style.left = `${left}px`;
  el.style.top = up.value ? "auto" : `${Math.round(t.bottom + GAP)}px`;
  el.style.bottom = up.value ? `${Math.round(vh - t.top + GAP)}px` : "auto";
  el.style.setProperty("--filter-max-h", `${Math.max(140, Math.min(cap, room))}px`);
  el.style.setProperty("--filter-origin-x", `${Math.round(t.left + Math.min(t.width / 2, 48) - left)}px`);
}
/** keep the popover on its trigger while the page scrolls or the tile tilts; close it once
 *  the trigger slides under the fixed chrome */
function follow() {
  frame = requestAnimationFrame(follow);
  if (!open.value || sheet.value || !trigger.value) return;
  const t = trigger.value.getBoundingClientRect();
  const key = `${t.left}|${t.top}|${t.width}|${window.innerWidth}|${window.innerHeight}`;
  if (key === lastRect) return;
  lastRect = key;
  if (
    t.bottom < chromeInset("--chrome-top") ||
    t.top > window.innerHeight - chromeInset("--chrome-bottom")
  ) {
    close(false);
    return;
  }
  place();
}
function updateFades() {
  const box = scroller.value;
  if (!box) return;
  fadeTop.value = box.scrollTop > 2;
  fadeBottom.value = box.scrollTop + box.clientHeight < box.scrollHeight - 2;
}

/* ---------------------------------------------------------------- transition hooks */
function onEnter(node: Element) {
  const el = node as HTMLElement;
  el.setAttribute("popover", "manual");
  try {
    el.showPopover?.();
  } catch {
    /* no popover API: the layer still renders as a fixed element */
  }
  if (sheet.value) {
    fitViewport();
    watchViewport(true);
  } else {
    measure();
    lastRect = "";
    place();
  }
  updateFades();
  // focus: the search field on desktop; the list in a phone sheet (no surprise keyboard)
  if (sheet.value && !query.value) listbox.value?.focus({ preventScroll: true });
  else if (searchable.value) {
    searchInput.value?.focus({ preventScroll: true });
    const end = query.value.length;
    searchInput.value?.setSelectionRange(end, end);
  }
  if (!sheet.value) frame = requestAnimationFrame(follow);
  // reveal the selected option without animating the scroll
  const box = scroller.value,
    option = box?.querySelector<HTMLElement>(`[id="${props.id}-${active.value}"]`);
  if (box && option) {
    box.scrollTop = Math.max(0, option.offsetTop - box.clientHeight / 2 + option.offsetHeight / 2);
    updateFades();
  }
}
/** explicit timings: the garden spring and the polarized edge sweep outlast the layer's own
 *  transition, so Vue must not end the enter early. Under reduced motion the transition
 *  classes are skipped altogether (`:css="false"`): the list appears and leaves at once. */
const durations = computed(() =>
  sheet.value ? { enter: 300, leave: 220 } : { enter: 440, leave: 120 },
);
function onBeforeLeave(node: Element) {
  // keep a closing popover out of the tab order and away from the pointer
  (node as HTMLElement).inert = true;
}
/* phone sheet: sit inside the visual viewport, so the on-screen keyboard never covers it */
function fitViewport() {
  const vv = window.visualViewport,
    el = layer.value;
  if (!vv || !el || !sheet.value) return;
  el.style.top = `${Math.round(vv.offsetTop)}px`;
  el.style.height = `${Math.round(vv.height)}px`;
}
function watchViewport(on: boolean) {
  const vv = window.visualViewport;
  if (!vv) return;
  const method = on ? "addEventListener" : "removeEventListener";
  vv[method]("resize", fitViewport);
  vv[method]("scroll", fitViewport);
}
watch(open, (isOpen) => {
  if (!isOpen) {
    cancelAnimationFrame(frame);
    watchViewport(false);
    dragY.value = 0;
    dragging.value = false;
  }
});

/* ---------------------------------------------------------------- pointer */
function outside(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) close(false);
}
function panelMousedown(event: MouseEvent) {
  // keep focus where it is (trigger, search or list) unless the search field is clicked
  if (!(event.target as HTMLElement).closest("input")) event.preventDefault();
}
/** buttons inside the layer (close, clear search): Escape closes, Tab stays in a phone sheet;
 *  the search field and the list handle their own keys */
function onLayerKeydown(event: KeyboardEvent) {
  if (!(event.target instanceof HTMLButtonElement)) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    close();
  } else if (event.key === "Tab" && sheet.value) trapTab(event);
}
function onFocusout(event: FocusEvent) {
  if (open.value && !root.value?.contains(event.relatedTarget as Node)) close(false);
}
/* phone sheet: drag the handle down to dismiss */
let dragStart = 0,
  dragAt = 0;
function dragDown(event: PointerEvent) {
  if (!sheet.value || event.button !== 0) return;
  dragStart = event.clientY;
  dragAt = performance.now();
  dragging.value = true;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
}
function dragMove(event: PointerEvent) {
  if (dragging.value) dragY.value = Math.max(0, event.clientY - dragStart);
}
function dragEnd() {
  if (!dragging.value) return;
  const fast = dragY.value / Math.max(1, performance.now() - dragAt) > 0.6;
  dragging.value = false;
  if (dragY.value > 96 || (fast && dragY.value > 24)) close();
  else dragY.value = 0;
}

let media: MediaQueryList | undefined;
const onMedia = () => {
  if (open.value && phone() !== sheet.value) close(false);
};
onMounted(() => {
  document.addEventListener("pointerdown", outside, true);
  media = window.matchMedia("(max-width: 720px)");
  media.addEventListener("change", onMedia);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", outside, true);
  media?.removeEventListener("change", onMedia);
  cancelAnimationFrame(frame);
  watchViewport(false);
});
</script>

<template>
  <div
    ref="root"
    class="filter-select"
    :class="[`size-${size}`, { block, open, disabled }]"
    :style="reserve ? { '--filter-reserve': reserve } : undefined"
    @focusout="onFocusout"
  >
    <button
      :id="id"
      ref="trigger"
      type="button"
      class="filter-trigger"
      :class="{ expanded: open, filtered, 'has-eyebrow': !!eyebrow }"
      role="combobox"
      :aria-label="label"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-controls="`${id}-options`"
      :aria-activedescendant="open && !sheet ? activeId : undefined"
      :disabled="disabled"
      @click="toggle"
      @keydown="onKeydown($event, 'trigger')"
    >
      <span v-if="eyebrow" class="filter-eyebrow" aria-hidden="true">{{ eyebrow }}</span>
      <i
        v-if="selected?.marker"
        class="filter-mk"
        :class="`mk-${selected.marker}`"
        aria-hidden="true"
      ></i>
      <i
        v-else-if="selected?.color"
        class="filter-dot"
        :style="{ background: selected.color }"
        aria-hidden="true"
      ></i>
      <span class="filter-value" :class="{ placeholder: !selected }">{{
        selected?.label ?? placeholder
      }}</span>
      <span v-if="selected?.hint" class="filter-aside">{{ selected.hint }}</span>
      <span v-else-if="selected?.count != null" class="filter-aside">{{ selected.count }}</span>
      <span class="filter-chevron" aria-hidden="true"><ChevronDown :size="15" /></span>
    </button>

    <Transition
      :name="sheet ? 'filter-sheet' : 'filter-pop'"
      :duration="durations"
      :css="!reducedMotion"
      @enter="onEnter"
      @before-leave="onBeforeLeave"
    >
      <div
        v-if="open"
        ref="layer"
        class="filter-popover"
        :class="{ sheet, up, searchable }"
        :role="sheet ? 'dialog' : undefined"
        :aria-modal="sheet ? 'true' : undefined"
        :aria-labelledby="sheet ? `${id}-title` : undefined"
        @mousedown="panelMousedown"
        @keydown="onLayerKeydown"
        @click.self="sheet && close()"
      >
        <div
          class="filter-panel"
          :class="{ dragging }"
          :style="dragY ? { transform: `translateY(${dragY}px)` } : undefined"
        >
          <div
            v-if="sheet"
            class="filter-sheet-head"
            @pointerdown="dragDown"
            @pointermove="dragMove"
            @pointerup="dragEnd"
            @pointercancel="dragEnd"
          >
            <span class="filter-grab" aria-hidden="true"></span>
            <div class="filter-sheet-title">
              <span :id="`${id}-title`">{{ label }}</span>
              <span class="filter-total" aria-hidden="true">{{ total }}</span>
              <button
                type="button"
                class="filter-close"
                aria-label="关闭"
                @pointerdown.stop
                @click="close()"
              >
                <X :size="18" />
              </button>
            </div>
          </div>
          <div v-if="searchable" class="filter-search">
            <Search :size="15" aria-hidden="true" />
            <input
              ref="searchInput"
              v-model="query"
              type="search"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded="true"
              :aria-controls="`${id}-options`"
              :aria-activedescendant="activeId"
              :aria-label="`搜索${label}`"
              placeholder="输入关键词筛选"
              autocomplete="off"
              spellcheck="false"
              enterkeyhint="done"
              @keydown="onKeydown($event, 'search')"
            />
            <button
              v-if="query"
              type="button"
              class="filter-clear"
              aria-label="清除搜索"
              @click="
                query = '';
                searchInput?.focus({ preventScroll: true });
              "
            >
              <X :size="14" />
            </button>
            <span v-else-if="!sheet" class="filter-total" aria-hidden="true">{{ total }}</span>
          </div>
          <div
            ref="scroller"
            class="filter-scroll"
            :class="{ 'fade-top': fadeTop, 'fade-bottom': fadeBottom }"
            @scroll.passive="updateFades"
          >
            <div
              :id="`${id}-options`"
              ref="listbox"
              role="listbox"
              :aria-label="label"
              :tabindex="sheet ? -1 : undefined"
              :aria-activedescendant="sheet ? activeId : undefined"
              class="filter-list"
              @keydown="onKeydown($event, 'list')"
            >
              <template v-for="(section, s) in sections" :key="section.label ?? `s${s}`">
                <div
                  :role="section.label ? 'group' : 'presentation'"
                  :aria-labelledby="section.label ? `${id}-group-${s}` : undefined"
                  class="filter-section"
                >
                  <div
                    v-if="section.label"
                    :id="`${id}-group-${s}`"
                    class="filter-group"
                    role="presentation"
                  >
                    <span>{{ section.label }}</span
                    ><span class="filter-group-n" aria-hidden="true">{{ section.rows.length }}</span>
                  </div>
                  <div
                    v-for="row in section.rows"
                    :id="`${id}-${row.index}`"
                    :key="row.option.value"
                    role="option"
                    :aria-selected="row.option.value === modelValue"
                    class="filter-option"
                    :class="{
                      selected: row.option.value === modelValue,
                      highlighted: row.index === active,
                    }"
                    @pointermove="active !== row.index && setActive(row.index, false)"
                    @click="choose(row.index)"
                  >
                    <i
                      v-if="row.option.marker"
                      class="filter-mk"
                      :class="`mk-${row.option.marker}`"
                      aria-hidden="true"
                    ></i>
                    <i
                      v-else-if="row.option.color"
                      class="filter-dot"
                      :style="{ background: row.option.color }"
                      aria-hidden="true"
                    ></i>
                    <span class="filter-label"
                      ><template v-if="row.parts"
                        >{{ row.parts[0] }}<mark>{{ row.parts[1] }}</mark>{{ row.parts[2] }}</template
                      ><template v-else>{{ row.option.label }}</template></span
                    >
                    <span v-if="row.option.hint" class="filter-hint">{{ row.option.hint }}</span>
                    <span v-if="row.option.count != null" class="filter-count">{{
                      row.option.count
                    }}</span>
                    <span class="filter-check" aria-hidden="true"><Check :size="13" /></span>
                  </div>
                </div>
              </template>
            </div>
            <div v-if="!flat.length" class="filter-empty">
              <p>没有匹配“{{ query.trim() }}”的选项</p>
              <button
                type="button"
                class="filter-empty-clear"
                @click="
                  query = '';
                  searchInput?.focus({ preventScroll: true });
                "
              >
                清除搜索
              </button>
            </div>
          </div>
          <div v-if="searchable && !sheet" class="filter-foot" aria-hidden="true">
            <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>↵</kbd> 确认</span
            ><span><kbd>Esc</kbd> 关闭</span>
          </div>
          <p class="sr-only" role="status" aria-live="polite">
            {{ query.trim() ? `找到 ${flat.length} 项` : "" }}
          </p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* =====================================================================
   FilterSelect · shared anatomy (tokens: --sel-* in style.css)
   ===================================================================== */
/* block-level: fills a column or block container (full width on phones), sizes to its
   content as an item of a row toolbar */
.filter-select {
  position: relative;
  display: flex;
  flex-shrink: 0;
  max-width: 100%;
}
.filter-select.block {
  width: 100%;
}
/* reserve the longest choice on wider screens (phones stack the controls full width) */
@media (min-width: 721px) {
  .filter-select {
    min-width: var(--filter-reserve, 0px);
  }
}

/* ---------------------------------------------------------------- trigger */
.filter-trigger {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 100%;
  height: 44px;
  padding: 0 7px 0 13px;
  border: 1px solid var(--sel-line);
  border-radius: var(--radius-sm);
  background: var(--sel-sheen), var(--sel-bg);
  box-shadow: var(--sel-shadow);
  color: var(--text);
  font-size: 14px;
  line-height: 1.2;
  text-align: left;
  white-space: nowrap;
  transition:
    border-color 0.18s var(--ease),
    background-color 0.18s var(--ease),
    box-shadow 0.22s var(--ease),
    transform 0.22s var(--ease);
}
.size-compact .filter-trigger {
  height: 34px;
  gap: 6px;
  padding: 0 5px 0 11px;
  font-size: 13px;
  border-radius: var(--radius-xs);
}
.filter-trigger:hover {
  border-color: var(--sel-line-hover);
  background: var(--sel-sheen), var(--sel-bg-hover);
}
.filter-trigger:focus-visible {
  outline: none;
}
.filter-trigger:disabled {
  opacity: 0.5;
}
.filter-eyebrow {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-3);
  font-size: 12px;
}
.filter-eyebrow::after {
  content: "";
  width: 1px;
  height: 16px;
  background: var(--sel-line-hover);
}
.filter-value {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
  letter-spacing: 0.01em;
}
.filter-value.placeholder {
  color: var(--text-3);
  font-weight: 400;
}
.filter-trigger.filtered .filter-value {
  color: var(--accent-ink);
}
.filter-aside {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.filter-chevron {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-xs);
  color: var(--text-2);
  transition:
    background-color 0.18s,
    color 0.18s;
}
.filter-chevron svg {
  transition: transform 0.28s var(--ease);
}
.size-compact .filter-chevron {
  width: 22px;
  height: 22px;
}
.expanded .filter-chevron {
  color: var(--text);
}
.expanded .filter-chevron svg {
  transform: rotate(180deg);
}

/* markers: dot (series colour) or the material stain shape */
.filter-dot,
.filter-mk {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.filter-mk.mk-softwood {
  background: var(--sw);
}
.filter-mk.mk-hardwood {
  background: var(--hw);
  border-radius: 2px;
}
.filter-mk.mk-blend {
  width: 9px;
  height: 9px;
  border-radius: 0;
  background: var(--bl);
  clip-path: polygon(50% 0, 100% 100%, 0 100%);
}

/* ---------------------------------------------------------------- popover layer (top layer) */
.filter-popover {
  position: fixed;
  inset: auto;
  z-index: 90; /* only matters without the popover API */
  margin: 0;
  padding: 0;
  border: 0;
  width: auto;
  height: auto;
  max-width: none;
  max-height: none;
  overflow: visible;
  background: transparent;
  color: var(--text);
  transform-origin: var(--filter-origin-x, 24px) top;
}
.filter-popover.up {
  transform-origin: var(--filter-origin-x, 24px) bottom;
}
.filter-popover .filter-panel {
  transform-origin: inherit; /* the open animation runs on the panel */
}
.filter-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  max-height: var(--filter-max-h, 380px);
  padding: 6px;
  border-radius: calc(var(--radius-sm) + 2px);
  border: 1px solid var(--sel-pop-line);
  background: var(--sel-pop-bg);
  box-shadow: var(--sel-pop-shadow);
  -webkit-backdrop-filter: blur(22px) saturate(1.4);
  backdrop-filter: blur(22px) saturate(1.4);
  overflow: hidden;
}

/* search */
.filter-search {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  height: 40px;
  margin: 2px 2px 6px;
  padding: 0 8px 0 12px;
  border-radius: var(--radius-xs);
  background: var(--sel-search-bg);
  box-shadow: inset 0 0 0 1px var(--sel-line);
  color: var(--text-3);
  transition: box-shadow 0.18s;
}
.filter-search:focus-within {
  box-shadow: inset 0 0 0 1px var(--sel-halo-edge);
}
.filter-search input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--text);
  font-size: 13.5px;
  outline: none;
  -webkit-appearance: none;
  appearance: none;
}
.filter-search input::-webkit-search-cancel-button {
  display: none;
}
.filter-search input::placeholder {
  color: var(--text-3);
}
.filter-search input:focus-visible {
  outline: none;
}
.filter-clear {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  color: var(--text-2);
}
.filter-clear:hover {
  background: var(--sel-row-active);
  color: var(--text);
}
.filter-total {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* scroll area with fade masks */
.filter-scroll {
  --fade-t: 0px;
  --fade-b: 0px;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--sel-line-hover) transparent;
  -webkit-mask-image: linear-gradient(
    to bottom,
    transparent 0,
    black var(--fade-t),
    black calc(100% - var(--fade-b)),
    transparent 100%
  );
  mask-image: linear-gradient(
    to bottom,
    transparent 0,
    black var(--fade-t),
    black calc(100% - var(--fade-b)),
    transparent 100%
  );
}
.filter-scroll.fade-top {
  --fade-t: 22px;
}
.filter-scroll.fade-bottom {
  --fade-b: 28px;
}
.filter-list:focus,
.filter-list:focus-visible {
  outline: none;
}
.filter-section + .filter-section {
  margin-top: 4px;
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 5px;
  color: var(--text-3);
  font-size: 11.5px;
  white-space: nowrap;
}
.filter-group-n {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

/* options */
.filter-option {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 8px 10px 8px 12px;
  border-radius: var(--radius-xs);
  color: var(--text-2);
  font-size: 13.5px;
  line-height: 1.4;
  cursor: pointer;
  transition:
    background-color 0.12s,
    color 0.12s,
    box-shadow 0.16s;
}
.filter-option.highlighted {
  color: var(--text);
  background: var(--sel-row-active);
}
.filter-option.selected {
  color: var(--text);
  font-weight: 500;
}
.filter-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow-wrap: anywhere;
}
.filter-label mark {
  background: var(--sel-mark);
  color: inherit;
  border-radius: 3px;
  padding: 0 1px;
}
.filter-hint,
.filter-count {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.filter-check {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--accent-ink);
  opacity: 0;
  transform: scale(0.6);
  transition:
    opacity 0.14s,
    transform 0.22s var(--spring);
}
.selected .filter-check {
  opacity: 1;
  transform: none;
}

/* empty search result */
.filter-empty {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 22px 16px 24px;
  text-align: center;
  color: var(--text-2);
  font-size: 13px;
}
.filter-empty-clear {
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--sel-line-hover);
  color: var(--text);
  font-size: 12.5px;
}
.filter-empty-clear:hover {
  background: var(--sel-row-active);
}

/* keyboard legend */
.filter-foot {
  flex-shrink: 0;
  display: flex;
  gap: 14px;
  margin: 4px 2px 0;
  padding: 8px 8px 3px;
  border-top: 1px solid var(--sel-line);
  color: var(--text-3);
  font-size: 11px;
}
.filter-foot kbd {
  display: inline-grid;
  place-items: center;
  min-width: 17px;
  height: 17px;
  margin-right: 2px;
  padding: 0 4px;
  border-radius: 4px;
  border: 1px solid var(--sel-line-hover);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
}
@media (hover: none) {
  .filter-foot {
    display: none;
  }
}

/* ---------------------------------------------------------------- phone: bottom sheet */
.filter-popover.sheet {
  inset: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  /* no backdrop-filter here: it would become the panel's backdrop root and stop its blur */
  background: var(--scrim);
  touch-action: none;
}
.sheet .filter-panel {
  background: var(--sel-sheet-bg);
  /* the layer follows the visual viewport (keyboard), so cap by its height too */
  max-height: min(calc(100% - 24px), 84dvh, 680px);
  padding: 0 10px max(12px, env(safe-area-inset-bottom));
  border-width: 1px 0 0;
  border-radius: 24px 24px 0 0;
  touch-action: pan-y;
  transition: transform 0.26s var(--ease);
}
.sheet .filter-panel.dragging {
  transition: none;
}
.filter-sheet-head {
  flex-shrink: 0;
  padding: 8px 4px 6px;
  touch-action: none;
  cursor: grab;
}
.filter-grab {
  display: block;
  width: 40px;
  height: 4px;
  margin: 2px auto 10px;
  border-radius: 999px;
  background: var(--sel-line-hover);
}
.filter-sheet-title {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}
.filter-sheet-title > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.filter-sheet-title .filter-total {
  margin-right: auto;
  font-weight: 400;
}
.filter-close {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  color: var(--text-2);
  background: var(--sel-row-active);
}
.sheet .filter-search {
  height: 44px;
  margin: 6px 0 8px;
}
.sheet .filter-search input {
  font-size: 16px; /* no iOS zoom on focus */
}
.sheet .filter-option {
  min-height: 48px;
  font-size: 15px;
  padding: 10px 12px 10px 14px;
}
.sheet .filter-check {
  width: 22px;
  height: 22px;
}

/* ---------------------------------------------------------------- open / close motion */
/* The open/close motion runs on the panel, not on the popover root: an opacity below 1 on
   the root would make it the panel's backdrop root and switch the frosted blur off while it
   animates. Keyframes rather than transitions: the panel enters the top layer in the same
   frame, so a transition would have no starting style to run from. <Transition> gets its
   durations explicitly (see `durations`). Each mode sets --pop-from / --pop-dur / --pop-ease. */
.filter-popover {
  --pop-from: translateY(-6px) scale(0.97);
  --pop-dur: 0.22s;
  --pop-ease: var(--ease);
}
.filter-popover.up {
  --pop-from: translateY(6px) scale(0.97);
}
.filter-pop-enter-active .filter-panel {
  animation: filter-pop-in var(--pop-dur) var(--pop-ease) both;
}
.filter-pop-leave-active .filter-panel {
  animation: filter-pop-out 0.12s ease both;
}
@keyframes filter-pop-in {
  from {
    opacity: 0;
    transform: var(--pop-from);
  }
}
@keyframes filter-pop-out {
  to {
    opacity: 0;
    transform: var(--pop-from);
  }
}
.filter-sheet-enter-active,
.filter-sheet-leave-active {
  transition: background-color 0.3s var(--ease);
}
.filter-sheet-enter-active .filter-panel {
  transition: transform 0.3s var(--ease);
}
.filter-sheet-leave-active .filter-panel {
  transition: transform 0.22s ease-in;
}
.filter-sheet-enter-from,
.filter-sheet-leave-to {
  background-color: transparent;
}
.filter-sheet-enter-from .filter-panel,
.filter-sheet-leave-to .filter-panel {
  transform: translateY(100%);
}

/* =====================================================================
   Polarized · dark instrument readout
   ===================================================================== */
:root[data-mode="polarized"] .filter-trigger {
  border-radius: var(--radius-sm);
}
:root[data-mode="polarized"] .filter-trigger {
  height: 38px;
}
:root[data-mode="polarized"] .size-compact .filter-trigger {
  height: 34px;
}
/* HUD corner ticks (a reticle that locks on when the field is focused or open) */
:root[data-mode="polarized"] .filter-trigger::before {
  content: "";
  position: absolute;
  inset: -4px;
  pointer-events: none;
  --t: var(--sel-tick);
  background:
    linear-gradient(var(--t), var(--t)) top left / 7px 1px no-repeat,
    linear-gradient(var(--t), var(--t)) top left / 1px 7px no-repeat,
    linear-gradient(var(--t), var(--t)) top right / 7px 1px no-repeat,
    linear-gradient(var(--t), var(--t)) top right / 1px 7px no-repeat,
    linear-gradient(var(--t), var(--t)) bottom left / 7px 1px no-repeat,
    linear-gradient(var(--t), var(--t)) bottom left / 1px 7px no-repeat,
    linear-gradient(var(--t), var(--t)) bottom right / 7px 1px no-repeat,
    linear-gradient(var(--t), var(--t)) bottom right / 1px 7px no-repeat;
  opacity: 0;
  transform: scale(1.04);
  transition:
    opacity 0.2s var(--ease),
    transform 0.28s var(--ease);
}
/* interference edge: the hairline turns into the analyser gradient on hover / focus / open */
:root[data-mode="polarized"] .filter-trigger::after {
  content: "";
  position: absolute;
  inset: -1px;
  padding: 1px;
  border-radius: inherit;
  pointer-events: none;
  background: var(--ifl);
  -webkit-mask:
    linear-gradient(black 0 0) content-box,
    linear-gradient(black 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.24s var(--ease);
}
:root[data-mode="polarized"] .filter-trigger:hover::after {
  opacity: 0.5;
}
:root[data-mode="polarized"] .filter-trigger:hover::before {
  opacity: 0.55;
  transform: none;
}
:root[data-mode="polarized"] .filter-trigger:focus-visible,
:root[data-mode="polarized"] .filter-trigger.expanded {
  border-color: transparent;
  background: var(--sel-sheen), var(--sel-bg-hover);
}
:root[data-mode="polarized"] .filter-trigger:focus-visible::after,
:root[data-mode="polarized"] .filter-trigger.expanded::after {
  opacity: 1;
}
:root[data-mode="polarized"] .filter-trigger:focus-visible::before,
:root[data-mode="polarized"] .filter-trigger.expanded::before {
  --t: var(--focus);
  opacity: 1;
  transform: scale(0.985);
}
:root[data-mode="polarized"] .filter-eyebrow {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
:root[data-mode="polarized"] .filter-trigger.filtered .filter-value {
  color: var(--text);
}
:root[data-mode="polarized"] .filter-trigger.filtered::before {
  opacity: 0.55;
  transform: none;
}
:root[data-mode="polarized"] .filter-trigger.filtered .filter-chevron {
  color: var(--accent-ink);
}
:root[data-mode="polarized"] .filter-chevron {
  border-left: 1px solid var(--sel-line);
  border-radius: 0;
  width: 27px;
  margin-left: 1px;
}
:root[data-mode="polarized"] .size-compact .filter-chevron {
  width: 22px;
  border-left: 0;
}
:root[data-mode="polarized"] .filter-value {
  letter-spacing: 0.02em;
}

/* panel: near-opaque dark glass, hairline, interference top edge */
:root[data-mode="polarized"] .filter-panel {
  border-radius: var(--radius-sm);
}
:root[data-mode="polarized"] .filter-panel::before {
  content: "";
  position: absolute;
  left: 12px;
  right: 12px;
  top: 0;
  height: 1px;
  background: var(--ifl);
  opacity: 0.9;
  transform-origin: left;
  pointer-events: none;
}
:root[data-mode="polarized"] .filter-pop-enter-active .filter-panel::before {
  animation: filter-rail-in 0.36s var(--ease) 0.04s both;
}
@keyframes filter-rail-in {
  from {
    transform: scaleX(0);
  }
}
:root[data-mode="polarized"] .filter-popover {
  --pop-from: translateY(-3px) scaleY(0.96);
}
:root[data-mode="polarized"] .filter-popover.up {
  --pop-from: translateY(3px) scaleY(0.96);
}
:root[data-mode="polarized"] .filter-group {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
:root[data-mode="polarized"] .filter-group::after {
  content: "";
  order: 1;
  flex: 1;
  height: 1px;
  background: var(--sel-line);
}
:root[data-mode="polarized"] .filter-group-n {
  order: 2;
  letter-spacing: 0;
}
:root[data-mode="polarized"] .filter-option {
  border-radius: var(--radius-xs);
}
:root[data-mode="polarized"] .filter-option.highlighted {
  box-shadow:
    inset 0 0 0 1px var(--sel-row-glow),
    0 0 22px -10px var(--sel-row-glow);
}
:root[data-mode="polarized"] .filter-option.selected {
  background: var(--sel-row-selected);
}
:root[data-mode="polarized"] .filter-option.selected.highlighted {
  background: var(--sel-row-active);
}
/* the selected row carries a thin interference bar (a horizontal --ifl strip turned upright) */
:root[data-mode="polarized"] .filter-option.selected::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 9px;
  bottom: 9px;
  width: 2px;
  background: var(--ifv);
  border-radius: 2px;
}
:root[data-mode="polarized"] .filter-label mark {
  background: transparent;
  color: var(--accent-ink);
  box-shadow: inset 0 -1px 0 var(--accent);
  border-radius: 0;
  padding: 0;
}
:root[data-mode="polarized"] .filter-search {
  border-radius: var(--radius-xs);
}
:root[data-mode="polarized"] .filter-search input {
  font-family: var(--font-mono);
  font-size: 12.5px;
}
:root[data-mode="polarized"] .filter-search:focus-within {
  box-shadow: inset 0 0 0 1px var(--sel-halo-edge);
}
:root[data-mode="polarized"] .filter-foot {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
:root[data-mode="polarized"] .sheet .filter-panel {
  border-radius: 16px 16px 0 0;
}
:root[data-mode="polarized"] .sheet .filter-panel::before {
  left: 0;
  right: 0;
}
:root[data-mode="polarized"] .filter-sheet-title {
  font-size: 15px;
}

/* =====================================================================
   Garden · frosted glass field
   ===================================================================== */
:root[data-mode="garden"] .filter-trigger {
  border: 0;
  border-radius: var(--radius-sm);
  padding-left: 15px;
  box-shadow:
    0 0 0 1px var(--sel-line),
    inset 0 0 0 1px var(--sel-edge),
    inset 0 1px 0 var(--sel-edge),
    var(--sel-shadow);
  -webkit-backdrop-filter: blur(14px) saturate(1.3);
  backdrop-filter: blur(14px) saturate(1.3);
}
:root[data-mode="garden"] .size-compact .filter-trigger {
  border-radius: 12px;
  padding-left: 12px;
}
:root[data-mode="garden"] .filter-trigger:hover {
  transform: translateY(-1px);
  box-shadow:
    0 0 0 1px var(--sel-line),
    inset 0 0 0 1px var(--sel-edge),
    inset 0 1px 0 var(--sel-edge),
    var(--sel-shadow-hover);
}
:root[data-mode="garden"] .filter-trigger:focus-visible,
:root[data-mode="garden"] .filter-trigger.expanded {
  background: var(--sel-sheen), var(--sel-bg-hover);
  box-shadow:
    inset 0 0 0 1px var(--sel-halo-edge),
    var(--sel-shadow-hover);
}
/* keyboard focus on the closed field: one soft lilac halo (the open field needs none — the
   popover itself shows where focus is) */
:root[data-mode="garden"] .filter-trigger:focus-visible:not(.expanded) {
  box-shadow:
    inset 0 0 0 1px var(--sel-halo-edge),
    0 0 0 3px var(--sel-halo),
    var(--sel-shadow-hover);
}
:root[data-mode="garden"] .filter-trigger:active {
  transform: translateY(0) scale(0.99);
}
:root[data-mode="garden"] .filter-eyebrow {
  font-family: var(--font-body);
  font-style: normal;
  font-weight: 500;
  letter-spacing: 0.04em;
  font-size: 12.5px;
  font-variation-settings:
    "SOFT" 100,
    "WONK" 1,
    "opsz" 72;
}
:root[data-mode="garden"] .filter-chevron {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--sel-bead);
  color: var(--accent-ink);
  box-shadow: inset 0 0 0 1px var(--sel-edge);
}
:root[data-mode="garden"] .size-compact .filter-chevron {
  width: 24px;
  height: 24px;
}
:root[data-mode="garden"] .filter-trigger:hover .filter-chevron,
:root[data-mode="garden"] .expanded .filter-chevron {
  background: var(--accent-tint);
}
:root[data-mode="garden"] .expanded .filter-chevron svg {
  transition: transform 0.46s var(--spring);
}
:root[data-mode="garden"] .filter-trigger.filtered .filter-value {
  color: var(--accent-ink);
}
:root[data-mode="garden"] .filter-trigger.filtered .filter-chevron {
  background: var(--accent-tint);
}

/* panel: frosted card, soft plum shadow */
:root[data-mode="garden"] .filter-panel {
  border: 0;
  border-radius: 22px;
  padding: 7px;
  box-shadow:
    inset 0 0 0 1px var(--sel-edge),
    var(--sel-pop-shadow);
}
:root[data-mode="garden"] .filter-popover {
  --pop-from: translateY(-8px) scale(0.92);
  --pop-dur: 0.44s;
  --pop-ease: var(--spring);
}
:root[data-mode="garden"] .filter-popover.up {
  --pop-from: translateY(8px) scale(0.92);
}
:root[data-mode="garden"] .filter-group {
  font-family: var(--font-body);
  font-style: normal;
  font-weight: 500;
  letter-spacing: 0.04em;
  font-size: 12px;
  padding: 10px 12px 4px;
  font-variation-settings:
    "SOFT" 100,
    "WONK" 1,
    "opsz" 72;
}
:root[data-mode="garden"] .filter-group-n {
  font-style: normal;
}
:root[data-mode="garden"] .filter-option {
  border-radius: 14px;
  padding-left: 14px;
}
:root[data-mode="garden"] .filter-option.highlighted {
  background: var(--accent-tint);
  box-shadow:
    inset 0 0 0 1px var(--sel-halo-edge),
    var(--sel-row-shadow);
}
/* selected: a pastel stain blob with a filled check */
:root[data-mode="garden"] .filter-option.selected {
  background:
    radial-gradient(120% 160% at 0% 0%, var(--sel-sheen-soft), transparent 60%),
    var(--accent-tint);
}
:root[data-mode="garden"] .filter-check {
  background: var(--accent);
  color: var(--accent-contrast);
}
:root[data-mode="garden"] .filter-search {
  border-radius: 14px;
  box-shadow: inset 0 0 0 1px var(--sel-edge), inset 0 1px 3px var(--sel-line);
}
:root[data-mode="garden"] .filter-search:focus-within {
  box-shadow:
    inset 0 0 0 1px var(--sel-halo-edge),
    inset 0 1px 3px var(--sel-line);
}
:root[data-mode="garden"] .filter-foot {
  display: none;
}
:root[data-mode="garden"] .filter-empty p {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 14px;
}
:root[data-mode="garden"] .sheet .filter-panel {
  border-radius: 28px 28px 0 0;
  padding-left: 12px;
  padding-right: 12px;
}
:root[data-mode="garden"] .filter-sheet-title > span:first-child {
  font-weight: 500;
  font-size: 17px;
}
</style>
