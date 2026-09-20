import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Overview from "./pages/Overview.vue";
import Beating from "./pages/Beating.vue";
import Blends from "./pages/Blends.vue";
import Association from "./pages/Association.vue";
import Recycled from "./pages/Recycled.vue";
import Sources from "./pages/Sources.vue";
import Literature from "./pages/Literature.vue";
import "@fontsource/lato/latin-400.css";
import "@fontsource/lato/latin-700.css";
import "@fontsource/lato/latin-900.css";
import "./style.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Overview },
    { path: "/beating", component: Beating },
    { path: "/blends", component: Blends },
    { path: "/association", component: Association },
    { path: "/recycled", component: Recycled },
    { path: "/sources", component: Sources },
    { path: "/literature", component: Literature },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(router).mount("#app");
