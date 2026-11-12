<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Info } from "lucide-vue-next";
import ModeSwitch from "../ModeSwitch.vue";
import AmbientGarden from "../ambient/AmbientGarden.vue";
import { introItem, navItemFor, navItems, platformName } from "../../nav";
import { reducedMotion } from "../../mode";

/*
 * 「纤维花园」 workspace chrome (v4): glass top header and a floating bottom dock.
 * The dock comes before <main> in the DOM so keyboard users reach navigation first;
 * on phones it turns into a horizontally scrollable tab bar.
 */
defineProps<{ navOpen?: boolean }>();
const emit = defineEmits<{ about: [] }>();

const route = useRoute();
const current = computed(() => navItemFor(route.path) ?? navItems[0]!);

// separators between navigation groups
const dockEntries = computed(() =>
  navItems.map((item, i) => ({
    item,
    separated: i === 0 || item.group !== navItems[i - 1]!.group,
  })),
);

const dock = ref<HTMLElement>();
const inner = ref<HTMLElement>();
const blobEl = ref<HTMLElement>();
const blob = ref({ x: 0, w: 0, ready: false });
const more = ref({ left: false, right: false });
let observer: ResizeObserver | undefined;

function edgeFade() {
  const el = inner.value;
  if (!el) return;
  const over = el.scrollWidth - el.clientWidth;
  more.value = { right: over > 2 && el.scrollLeft < over - 2, left: over > 2 && el.scrollLeft > 2 };
}
function placeBlob(animate: boolean) {
  const el = inner.value;
  const active = el?.querySelector<HTMLElement>('.gd-dock-item[aria-current="page"]');
  if (!el || !active) return;
  if (!animate && blobEl.value) {
    // jump (first layout, resize, font swap): no slide
    const el = blobEl.value;
    el.style.transition = "none";
    requestAnimationFrame(() => requestAnimationFrame(() => (el.style.transition = "")));
  }
  blob.value = { x: active.offsetLeft, w: active.offsetWidth, ready: true };
  // restart the soft "morph" squash while the blob slides to the new item
  if (animate && blobEl.value && !reducedMotion.value) {
    blobEl.value.classList.remove("morph");
    void blobEl.value.offsetWidth;
    blobEl.value.classList.add("morph");
  }
  // keep the active item visible in the phone tab bar
  if (el.scrollWidth > el.clientWidth) {
    el.scrollTo({
      left: active.offsetLeft - el.clientWidth / 2 + active.offsetWidth / 2,
      behavior: animate && !reducedMotion.value ? "smooth" : "auto",
    });
  }
  edgeFade();
}
watch(
  () => route.path,
  async () => {
    await nextTick();
    placeBlob(true);
  },
);
onMounted(() => {
  placeBlob(false);
  if (inner.value) {
    observer = new ResizeObserver(() => placeBlob(false));
    observer.observe(inner.value);
  }
  // web fonts change the item widths after first layout
  document.fonts?.ready.then(() => placeBlob(false)).catch(() => undefined);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <AmbientGarden />
  <a class="skip-link gd-skip-dock" href="#dock">跳到导航</a>
  <header class="gd-top">
    <RouterLink class="gd-brand" to="/" aria-label="FiberScope 纤维花园 · 数据总览">
      <span class="gd-brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" fill="none" stroke-linecap="round">
          <path d="M5 21c5-9 10 3 22-8" stroke="#DA6B3C" stroke-width="2.4" />
          <path d="M5 14c6 6 12-7 22 1" stroke="#4E9A6A" stroke-width="2.4" />
          <path d="M7 26c6-3 11-14 19-16" stroke="#8B6CD9" stroke-width="2.4" />
        </svg>
      </span>
      <span class="gd-brand-text">
        <span class="gd-brand-name">FiberScope</span>
        <span class="gd-brand-sub">{{ platformName }} · 纤维花园</span>
      </span>
    </RouterLink>
    <div class="gd-top-r">
      <span class="gd-where" aria-hidden="true"
        ><span class="gd-where-n">{{ current.index }}</span>{{ current.label }}</span
      >
      <button class="gd-btn" type="button" @click="emit('about')">
        <Info :size="17" /><span class="gd-btn-label">数据说明</span>
      </button>
      <ModeSwitch compact />
    </div>
  </header>

  <nav
    id="dock"
    ref="dock"
    class="gd-dock"
    :class="{ 'more-l': more.left, 'more-r': more.right }"
    aria-label="主导航"
    tabindex="-1"
  >
    <div ref="inner" class="gd-dock-inner" @scroll.passive="edgeFade">
      <span
        ref="blobEl"
        class="gd-dock-blob"
        :class="{ ready: blob.ready }"
        aria-hidden="true"
        :style="{ width: `${blob.w}px`, transform: `translateX(${blob.x}px)` }"
      ></span>
      <RouterLink
        class="gd-dock-item"
        :to="introItem.path"
        title="首页 · 序章"
        :aria-label="`${introItem.short} · ${introItem.label}`"
      >
        <span class="gd-dock-ico"><component :is="introItem.icon" :size="22" /></span>
        <span class="gd-dock-lbl">{{ introItem.short }}</span>
      </RouterLink>
      <template v-for="entry in dockEntries" :key="entry.item.path">
        <span v-if="entry.separated" class="gd-dock-sep" aria-hidden="true"></span>
        <RouterLink
          class="gd-dock-item"
          :to="entry.item.path"
          :title="`${entry.item.group} · ${entry.item.label}`"
          :aria-label="entry.item.label"
          :aria-current="entry.item === current ? 'page' : undefined"
        >
          <span class="gd-dock-ico"><component :is="entry.item.icon" :size="22" /></span>
          <span class="gd-dock-lbl"
            ><span class="full">{{ entry.item.label }}</span
            ><span class="short" aria-hidden="true">{{ entry.item.short }}</span></span
          >
        </RouterLink>
      </template>
    </div>
  </nav>
</template>

<style scoped>
.gd-skip-dock:focus,
.gd-skip-dock:focus-visible {
  left: 180px;
}

/* ---------------------------------------------------------------- glass header */
.gd-top {
  position: fixed;
  left: 0;
  right: 0;
  top: 0;
  z-index: 40;
  /* the token is what pages use for sticky offsets: the header is exactly that tall */
  height: var(--chrome-top);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 32px;
  isolation: isolate;
}
.gd-top::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background: rgba(255, 248, 250, 0.78);
  -webkit-backdrop-filter: blur(18px) saturate(1.3);
  backdrop-filter: blur(18px) saturate(1.3);
  box-shadow:
    0 1px 0 rgba(42, 34, 56, 0.08),
    0 14px 30px -26px rgba(74, 52, 110, 0.4);
}
.gd-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  color: var(--text);
  text-decoration: none;
  border-radius: 14px;
}
.gd-brand-mark {
  width: 40px;
  height: 40px;
  flex: none;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.7);
  box-shadow:
    inset 0 0 0 1px #fff,
    var(--shadow-sm);
}
.gd-brand-mark svg {
  width: 28px;
  height: 28px;
}
.gd-brand-text {
  min-width: 0;
}
.gd-brand-name {
  display: block;
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 1, "opsz" 72;
  font-weight: 560;
  font-size: 21px;
  letter-spacing: -0.02em;
  line-height: 1;
}
.gd-brand-sub {
  display: block;
  font-size: 12px;
  color: var(--text-2);
  margin-top: 4px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.gd-top-r {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.gd-where {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  padding: 0 6px;
  font-size: 13px;
  color: var(--text-2);
}
.gd-where-n {
  font-family: var(--font-display);
  font-style: italic;
  font-variation-settings: "SOFT" 100, "WONK" 1;
  font-size: 15px;
  color: var(--text-3);
}
.gd-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: rgba(255, 255, 255, 0.8);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.95),
    0 6px 16px -10px rgba(74, 52, 110, 0.35);
  transition:
    transform 0.35s cubic-bezier(0.34, 1.45, 0.5, 1),
    background 0.25s;
  white-space: nowrap;
}
.gd-btn:hover {
  background: #fff;
}
.gd-btn:active {
  transform: scale(0.96);
}

/* ---------------------------------------------------------------- floating dock */
.gd-dock {
  position: fixed;
  left: 50%;
  bottom: 18px;
  z-index: 60;
  translate: -50% 0;
  max-width: calc(100vw - 24px);
  border-radius: 30px;
}
.gd-dock:focus-visible {
  outline-offset: 4px;
}
.gd-dock-inner {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 30px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.8), rgba(255, 255, 255, 0.62));
  -webkit-backdrop-filter: blur(22px) saturate(1.5);
  backdrop-filter: blur(22px) saturate(1.5);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.95),
    inset 0 1px 0 #fff,
    0 26px 50px -24px rgba(74, 52, 110, 0.55),
    0 4px 12px -6px rgba(74, 52, 110, 0.2);
}
.gd-dock-blob {
  position: absolute;
  left: 0;
  top: 8px;
  height: calc(100% - 16px);
  border-radius: 22px;
  pointer-events: none;
  opacity: 0;
  background: linear-gradient(135deg, #ffe3d3 0%, #f3e8ff 55%, #e2f2e6 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.95),
    0 8px 18px -10px rgba(74, 52, 110, 0.45);
  transition:
    transform 0.55s cubic-bezier(0.34, 1.45, 0.5, 1),
    width 0.55s cubic-bezier(0.34, 1.45, 0.5, 1);
}
.gd-dock-blob.ready {
  opacity: 1;
}
.gd-dock-blob.morph {
  animation: gd-morph 0.6s cubic-bezier(0.22, 0.9, 0.25, 1);
}
@keyframes gd-morph {
  35% {
    border-radius: 40% 60% 55% 45% / 60% 45% 55% 40%;
    scale: 1.06 0.9;
  }
}
.gd-dock-item {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 70px;
  padding: 6px 9px 5px;
  border-radius: 22px;
  color: var(--text-2);
  text-decoration: none;
  font-size: 12px;
  line-height: 1.3;
  white-space: nowrap;
  transition: color 0.25s;
}
.gd-dock-ico {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  transition: transform 0.35s cubic-bezier(0.34, 1.45, 0.5, 1);
}
.gd-dock-item:hover {
  color: var(--text);
}
.gd-dock-item:hover .gd-dock-ico {
  transform: translateY(-5px) scale(1.16);
}
.gd-dock-item[aria-current="page"] {
  color: var(--text);
  font-weight: 500;
}
.gd-dock-item .short {
  display: none;
}
.gd-dock-sep {
  width: 1px;
  align-self: center;
  height: 34px;
  margin: 0 5px;
  flex: none;
  background: linear-gradient(transparent, var(--line-strong), transparent);
}
.gd-dock::before,
.gd-dock::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 2;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
}
.gd-dock::after {
  right: 0;
  width: 60px;
  border-radius: 0 24px 0 0;
  background:
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='16' viewBox='0 0 10 16'><path d='M2 2l6 6-6 6' fill='none' stroke='%232A2238' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>")
      no-repeat right 9px center / 8px 13px,
    linear-gradient(90deg, rgba(255, 250, 252, 0), rgba(255, 250, 252, 0.97) 70%);
}
.gd-dock::before {
  left: 0;
  width: 40px;
  border-radius: 24px 0 0 0;
  background: linear-gradient(270deg, rgba(255, 250, 252, 0), rgba(255, 250, 252, 0.95) 70%);
}
.gd-dock.more-r::after,
.gd-dock.more-l::before {
  opacity: 1;
}

/* ---------------------------------------------------------------- responsive */
@media (max-width: 1180px) {
  .gd-where {
    display: none;
  }
  .gd-dock-item {
    min-width: 62px;
    padding: 6px 6px 5px;
    font-size: 11.5px;
  }
}
@media (max-width: 980px) {
  .gd-dock-item .full {
    display: none;
  }
  .gd-dock-item .short {
    display: inline;
  }
  .gd-dock-item {
    min-width: 54px;
  }
}
@media (max-width: 720px) {
  .gd-top {
    padding: 0 12px 0 14px;
    gap: 8px;
  }
  .gd-brand {
    gap: 9px;
  }
  .gd-brand-sub {
    display: none;
  }
  .gd-brand-name {
    font-size: 18px;
  }
  .gd-brand-mark {
    width: 36px;
    height: 36px;
    border-radius: 12px;
  }
  .gd-brand-mark svg {
    width: 24px;
    height: 24px;
  }
  .gd-top-r {
    gap: 6px;
  }
  .gd-btn {
    padding: 7px 10px;
  }
  .gd-btn-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  /* dock → bottom tab bar */
  .gd-dock {
    left: 0;
    right: 0;
    bottom: 0;
    translate: none;
    max-width: none;
    border-radius: 24px 24px 0 0;
  }
  .gd-dock-inner {
    border-radius: 24px 24px 0 0;
    padding: 6px 8px calc(6px + env(safe-area-inset-bottom));
    overflow-x: auto;
    scrollbar-width: none;
    justify-content: flex-start;
    scroll-snap-type: x proximity;
  }
  .gd-dock-inner::-webkit-scrollbar {
    display: none;
  }
  .gd-dock-item {
    min-width: 56px;
    flex: 1 0 auto;
    scroll-snap-align: center;
    font-size: 11px;
    padding: 4px 4px 3px;
  }
  .gd-dock-ico {
    width: 30px;
    height: 30px;
  }
  .gd-dock-item:hover .gd-dock-ico {
    transform: none;
  }
  .gd-dock-sep {
    height: 28px;
    margin: 0 2px;
  }
  .gd-dock-blob {
    top: 6px;
    height: calc(100% - 12px - env(safe-area-inset-bottom));
  }
}
@media (max-width: 380px) {
  .gd-brand-name {
    display: none;
  }
}
</style>
