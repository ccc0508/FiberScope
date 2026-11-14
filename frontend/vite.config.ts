import { defineConfig, type ProxyOptions } from "vite";
import vue from "@vitejs/plugin-vue";

const apiProxy: ProxyOptions = {
  target: "http://127.0.0.1:8000",
  configure(proxy) {
    proxy.on("proxyReq", (proxyReq, request) => {
      // Overwrite the forwarded host with the browser-facing host for origin checks.
      proxyReq.setHeader("X-Forwarded-Host", request.headers.host ?? "");
    });
  },
};

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        // three.js is only reached through dynamic imports in the /intro prologues
        // (src/intro/*/fibril3d.ts, fibers3d.ts); give it one named, cacheable chunk
        manualChunks(id) {
          if (id.includes("/node_modules/three/")) return "three";
        },
      },
    },
    // That chunk is ~530 kB minified (~130 kB gzip) and cannot be split further, but it
    // never loads outside /intro and never blocks the first paint; every other chunk stays
    // well under the default 500 kB, so the limit sits just above three.js.
    chunkSizeWarningLimit: 560,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": apiProxy },
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: { "/api": apiProxy },
  },
});
