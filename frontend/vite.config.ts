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
