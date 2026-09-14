import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Overview from "./pages/Overview.vue";
import "@fontsource/lato/latin-400.css";
import "@fontsource/lato/latin-700.css";
import "@fontsource/lato/latin-900.css";
import "./style.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Overview },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(router).mount("#app");
