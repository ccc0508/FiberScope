import { computed, nextTick, readonly, ref, type ComputedRef } from "vue";
import {
  MODE_STORAGE_KEY,
  MODE_THEME,
  isMode,
  resolveMode,
  type Mode,
} from "./modeResolve";

export type { Mode } from "./modeResolve";
export { MODES, isMode } from "./modeResolve";

/* ---------------------------------------------------------------- storage (never throws) */
function readStored(): string | null {
  try {
    return window.localStorage.getItem(MODE_STORAGE_KEY);
  } catch {
    return null;
  }
}
function writeStored(value: Mode) {
  try {
    window.localStorage.setItem(MODE_STORAGE_KEY, value);
  } catch {
    /* private window / blocked storage: the choice simply is not remembered */
  }
}
function media(query: string): MediaQueryList | undefined {
  try {
    return window.matchMedia?.(query);
  } catch {
    return undefined;
  }
}

/* ---------------------------------------------------------------- initial value */
const darkQuery = media("(prefers-color-scheme: dark)");
const motionQuery = media("(prefers-reduced-motion: reduce)");

function queryMode(): string | null {
  try {
    return new URLSearchParams(window.location.search).get("mode");
  } catch {
    return null;
  }
}
const initial = resolveMode(queryMode(), readStored(), !!darkQuery?.matches);
if (initial.source === "query") writeStored(initial.mode);
/** true once the visitor (or a ?mode= link) picked a mode; until then the OS scheme is followed. */
let explicit = initial.source !== "system";

const current = ref<Mode>(initial.mode);
/** The active visual mode. Read-only: change it with setMode / toggleMode. */
export const mode = readonly(current);
export const isPolarized = computed(() => current.value === "polarized");
export const isGarden = computed(() => current.value === "garden");

/** Live prefers-reduced-motion flag (ambient layers and page animations read it). */
export const reducedMotion = ref(!!motionQuery?.matches);
motionQuery?.addEventListener?.("change", (event) => {
  reducedMotion.value = event.matches;
});

/** Pick one value per mode, reactively: `const ink = byMode({ polarized: "#fff", garden: "#222" })`. */
export function byMode<T>(values: Record<Mode, T>): ComputedRef<T> {
  return computed(() => values[current.value]);
}

/* ---------------------------------------------------------------- apply to <html> */
function applyToDocument(value: Mode) {
  const root = document.documentElement;
  root.dataset.mode = value;
  root.style.colorScheme = MODE_THEME[value].colorScheme;
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
  }
  meta.content = MODE_THEME[value].themeColor;
}
applyToDocument(current.value);

type TransitionDocument = Document & {
  startViewTransition?: (update: () => Promise<void> | void) => unknown;
};

/**
 * Switch the visual mode in place: same route, same scroll position, no reload.
 * Uses a View Transition cross-fade when the browser supports it and motion is allowed.
 */
export function setMode(
  next: Mode,
  options: { persist?: boolean; animate?: boolean } = {},
): Promise<void> {
  if (!isMode(next)) return Promise.resolve();
  const { persist = true, animate = true } = options;
  if (persist) {
    explicit = true;
    writeStored(next);
  }
  if (next === current.value) return Promise.resolve();
  const scrollX = window.scrollX,
    scrollY = window.scrollY;
  const update = async () => {
    current.value = next;
    applyToDocument(next);
    await nextTick();
    // the two shells have different chrome heights; keep the reader where they were
    window.scrollTo(scrollX, scrollY);
  };
  const doc = document as TransitionDocument;
  if (
    animate &&
    !reducedMotion.value &&
    typeof doc.startViewTransition === "function" &&
    document.visibilityState === "visible"
  ) {
    try {
      let done!: () => void;
      const updated = new Promise<void>((resolve) => (done = resolve));
      doc.startViewTransition(async () => {
        try {
          await update();
        } finally {
          done();
        }
      });
      return updated;
    } catch {
      /* fall through to an instant switch */
    }
  }
  return update();
}

export function toggleMode(): Promise<void> {
  return setMode(current.value === "polarized" ? "garden" : "polarized");
}

/* ---------------------------------------------------------------- follow outside changes */
// another tab switched modes
window.addEventListener("storage", (event) => {
  if (event.key === MODE_STORAGE_KEY && isMode(event.newValue)) {
    explicit = true;
    void setMode(event.newValue, { persist: false, animate: false });
  }
});
// no explicit choice yet: follow the operating-system colour scheme live
darkQuery?.addEventListener?.("change", (event) => {
  if (!explicit) void setMode(event.matches ? "polarized" : "garden", { persist: false });
});
