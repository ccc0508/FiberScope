import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Overview from "./pages/Overview.vue";
import "./style.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Overview },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(router).mount("#app");
