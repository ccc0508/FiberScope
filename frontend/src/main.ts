import { createApp, watch } from "vue";
import { createRouter, createWebHistory, type LocationQuery } from "vue-router";
import App from "./App.vue";
import { isMode, mode, setMode } from "./mode";
// Fonts are bundled (@fontsource, no CDN) and split by unicode-range: a face is only
// downloaded when text is rendered in it. The shared body faces load with the app; each
// mode's display / mono faces load on demand (src/fonts/*.ts), which keeps the CJK
// @font-face tables of the other mode out of the render-blocking stylesheet.
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";
import "./style.css";
import "./styles/polarized.css";
import "./styles/garden.css";

// Pages are code-split: a page is only downloaded when visited, and one failing chunk
// cannot take the others down.
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", component: () => import("./pages/Overview.vue") },
    { path: "/beating", component: () => import("./pages/Beating.vue") },
    { path: "/blends", component: () => import("./pages/Blends.vue") },
    { path: "/association", component: () => import("./pages/Association.vue") },
    { path: "/recycled", component: () => import("./pages/Recycled.vue") },
    { path: "/sources", component: () => import("./pages/Sources.vue") },
    { path: "/literature", component: () => import("./pages/Literature.vue") },
    { path: "/literature-data", component: () => import("./pages/LiteratureData.vue") },
    { path: "/intro", component: () => import("./pages/Intro.vue"), meta: { bare: true } },
    // dev-only showcase of the shared building blocks in both modes (dropped from builds)
    ...(import.meta.env.DEV
      ? [{ path: "/__foundation", component: () => import("./dev/FoundationPreview.vue") }]
      : []),
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// ?mode=polarized|garden switches (and remembers) the mode, then leaves the URL so the
// page's own query state stays clean.
router.beforeEach((to) => {
  const requested = to.query.mode;
  if (typeof requested !== "string" || !isMode(requested)) return;
  setMode(requested, { animate: false });
  const query: LocationQuery = { ...to.query };
  delete query.mode;
  return { path: to.path, query, hash: to.hash, replace: true };
});

const modeFonts = {
  polarized: () => import("./fonts/polarized"),
  garden: () => import("./fonts/garden"),
};
watch(
  mode,
  (value) => {
    // fonts are decorative here: a failed chunk only means the fallback face is used
    modeFonts[value]().catch(() => undefined);
  },
  { immediate: true },
);

const app = createApp(App).use(router);
void router.isReady().finally(() => app.mount("#app"));
