import {
  computed,
  onBeforeUnmount,
  ref,
  watch,
  type ComputedRef,
  type Directive,
  type Ref,
  type WatchStopHandle,
} from "vue";
import { mode, reducedMotion } from "./mode";

/*
 * Shared interaction motion for ported pages (garden character, v4 util.js).
 * Each helper is opt-in, does nothing visible in polarized, and is inert under
 * prefers-reduced-motion. Import them in <script setup>; a `vSeg` / `vTilt` binding is
 * usable as `v-seg` / `v-tilt` in that component's template.
 *
 *   <div v-seg class="seg" role="group" aria-label="原料">
 *     <button :aria-pressed="type === ''" @click="type = ''">全部</button> …
 *   </div>
 *   <section v-tilt class="card">…</section>
 *   const shown = useCountUp(() => total.value);   // {{ shown ?? "—" }}
 */

/* ---------------------------------------------------------------- v-seg: sliding selection blob */
interface SegState {
  blob: HTMLSpanElement;
  current: HTMLElement | null;
  mutations: MutationObserver;
  resize: ResizeObserver;
  stopMode: WatchStopHandle;
  raf: number;
}
const segStates = new WeakMap<HTMLElement, SegState>();
const SELECTED = ':scope > button[aria-pressed="true"], :scope > button[aria-checked="true"], :scope > button.on';

function placeSeg(el: HTMLElement, animate: boolean) {
  const state = segStates.get(el);
  if (!state) return;
  const { blob } = state;
  const target = el.querySelector<HTMLElement>(SELECTED);
  const moved = target !== state.current;
  state.current = target;
  // garden only: in polarized the blob is display: none and the buttons keep their fill
  if (!target || mode.value !== "garden") {
    el.classList.remove("blob-ready");
    blob.style.opacity = "0";
    return;
  }
  const slide = animate && moved && !reducedMotion.value;
  if (!slide) blob.style.transition = "none";
  blob.style.opacity = "1";
  blob.style.width = `${target.offsetWidth}px`;
  blob.style.height = `${target.offsetHeight}px`;
  blob.style.transform = `translate(${target.offsetLeft}px, ${target.offsetTop}px)`;
  el.classList.add("blob-ready");
  if (!slide) {
    void blob.offsetWidth; // commit the jump before transitions come back
    blob.style.transition = "";
  } else {
    el.classList.remove("morph");
    void el.offsetWidth;
    el.classList.add("morph");
  }
}

/**
 * `v-seg` on a `.seg` container: a blob slides (spring) to the pressed button and squashes
 * on the way. Selection is read from the buttons' aria-pressed / aria-checked / .on, so the
 * page keeps its own state and keyboard handling.
 */
export const vSeg: Directive<HTMLElement> = {
  mounted(el) {
    const blob = document.createElement("span");
    blob.className = "seg-blob";
    blob.setAttribute("aria-hidden", "true");
    el.prepend(blob);
    el.classList.add("has-blob");
    const schedule = (animate: boolean) => {
      const state = segStates.get(el);
      if (!state) return;
      cancelAnimationFrame(state.raf);
      state.raf = requestAnimationFrame(() => placeSeg(el, animate));
    };
    const mutations = new MutationObserver((records) => {
      // ignore our own writes: the blob, and the container's blob-ready / morph classes
      if (records.every((r) => r.target === blob || (r.type === "attributes" && r.target === el)))
        return;
      placeSeg(el, true);
      // new or removed buttons need watching for size changes too
      if (records.some((r) => r.type === "childList")) observeButtons();
    });
    mutations.observe(el, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-pressed", "aria-checked", "class"],
    });
    // font swaps and wrapping move the buttons without any attribute change
    const resize = new ResizeObserver(() => schedule(false));
    const observeButtons = () => {
      resize.disconnect();
      resize.observe(el);
      el.querySelectorAll<HTMLElement>(":scope > button").forEach((b) => resize.observe(b));
    };
    // the two modes lay the control out differently: re-place after a switch, no slide
    const stopMode = watch(mode, () => schedule(false), { flush: "post" });
    segStates.set(el, { blob, current: null, mutations, resize, stopMode, raf: 0 });
    observeButtons();
    placeSeg(el, false);
  },
  unmounted(el) {
    const state = segStates.get(el);
    if (!state) return;
    state.mutations.disconnect();
    state.resize.disconnect();
    state.stopMode();
    cancelAnimationFrame(state.raf);
    segStates.delete(el);
  },
};

/* ---------------------------------------------------------------- v-tilt: pointer tilt + sheen */
interface TiltState {
  move: (event: PointerEvent) => void;
  leave: () => void;
  stopMode: WatchStopHandle;
}
const tiltStates = new WeakMap<HTMLElement, TiltState>();
function hoverCapable() {
  try {
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  } catch {
    return false;
  }
}

/**
 * `v-tilt` on a tile: in garden it leans toward the pointer (at most ~7–9°, less on big
 * tiles) with a soft sheen (v4 bindTilt). Off in polarized, under reduced motion, on touch
 * screens, and while the tile holds an open FilterSelect popover. Adds `.tilt`, which makes
 * the element position: relative and uses its ::after for the sheen.
 */
export const vTilt: Directive<HTMLElement> = {
  mounted(el) {
    el.classList.add("tilt");
    const reset = () => {
      el.classList.remove("tilting");
      el.style.removeProperty("--rx");
      el.style.removeProperty("--ry");
    };
    const move = (event: PointerEvent) => {
      if (
        mode.value !== "garden" ||
        reducedMotion.value ||
        event.pointerType !== "mouse" ||
        !hoverCapable() ||
        el.querySelector(".filter-popover")
      ) {
        reset();
        return;
      }
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const px = (event.clientX - r.left) / r.width - 0.5,
        py = (event.clientY - r.top) / r.height - 0.5;
      const k = Math.min(1, 360 / Math.max(r.width, r.height));
      el.classList.add("tilting");
      el.style.setProperty("--rx", `${(-py * 7 * k).toFixed(2)}deg`);
      el.style.setProperty("--ry", `${(px * 9 * k).toFixed(2)}deg`);
      el.style.setProperty("--mx", `${((px + 0.5) * 100).toFixed(1)}%`);
      el.style.setProperty("--my", `${((py + 0.5) * 100).toFixed(1)}%`);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", reset);
    const stopMode = watch([mode, reducedMotion], reset);
    tiltStates.set(el, { move, leave: reset, stopMode });
  },
  unmounted(el) {
    const state = tiltStates.get(el);
    if (!state) return;
    el.removeEventListener("pointermove", state.move);
    el.removeEventListener("pointerleave", state.leave);
    state.stopMode();
    tiltStates.delete(el);
  },
};

/* ---------------------------------------------------------------- useCountUp: KPI numerals */
/**
 * Counts a big number up to its real value when it first arrives from the API (v4 countUp),
 * in garden only and never under reduced motion. Returns the value to show:
 *  - `null` stays `null` (render "—"), and 0 shows as 0;
 *  - every animation ends exactly on the API value, and a later change jumps straight to
 *    the new value, so a refreshed number is never shown half-way.
 * Pass `el` (the element holding the number) to count only when it is on screen; if it is
 * off screen when the data arrives, the real value is shown at once (no fake 0 waiting).
 * Screen readers should get the final value: put `aria-hidden="true"` on the counting text
 * and the real value in an `.sr-only` sibling.
 */
export function useCountUp(
  source: () => number | null | undefined,
  options: { el?: Ref<HTMLElement | null | undefined>; duration?: number; decimals?: number } = {},
): ComputedRef<number | null> {
  const shown = ref<number | null>(source() ?? null);
  let raf = 0,
    counted = false;
  const finish = (value: number | null) => {
    cancelAnimationFrame(raf);
    shown.value = value;
  };
  const onScreen = () => {
    const node = options.el?.value;
    if (!node) return true;
    const r = node.getBoundingClientRect();
    return r.bottom > 0 && r.top < window.innerHeight;
  };
  const run = (target: number) => {
    const t0 = performance.now();
    const duration = options.duration ?? 1300 + Math.min(900, Math.abs(target) * 2);
    const decimals = options.decimals ?? (Number.isInteger(target) ? 0 : 2);
    const factor = 10 ** decimals;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - k, 4);
      if (k < 1) {
        shown.value = Math.round(target * eased * factor) / factor;
        raf = requestAnimationFrame(step);
      } else shown.value = target;
    };
    shown.value = 0;
    raf = requestAnimationFrame(step);
  };
  watch(
    source,
    (value) => {
      const target = value ?? null;
      if (target == null || counted || mode.value !== "garden" || reducedMotion.value || !onScreen()) {
        if (target != null) counted = true;
        finish(target);
        return;
      }
      counted = true;
      run(target);
    },
    { immediate: true, flush: "post" },
  );
  // switching to polarized or turning on reduced motion mid-count shows the real value
  watch([mode, reducedMotion], () => finish(source() ?? null));
  onBeforeUnmount(() => cancelAnimationFrame(raf));
  return computed(() => shown.value);
}
