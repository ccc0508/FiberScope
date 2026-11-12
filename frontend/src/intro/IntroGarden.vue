<script setup lang="ts">
import ModeSwitch from "../components/ModeSwitch.vue";
import { platformName } from "../nav";
// Placeholder prologue for the garden mode; the full intro is built separately.
</script>

<template>
  <main id="main" class="intro intro--garden" tabindex="-1">
    <div class="intro-top">
      <span class="intro-brand">FiberScope</span>
      <ModeSwitch compact />
    </div>
    <section class="intro-body" aria-labelledby="intro-title">
      <p class="intro-eyebrow">Prologue · {{ platformName }}</p>
      <h1 id="intro-title">序章</h1>
      <RouterLink class="intro-enter" to="/">进入工作台 <span aria-hidden="true">→</span></RouterLink>
    </section>
  </main>
</template>

<style scoped>
.intro {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  padding: 18px 24px 40px;
  color: var(--text);
  background:
    radial-gradient(55% 45% at 8% 0%, #ffe6da 0%, transparent 62%),
    radial-gradient(45% 55% at 100% 18%, #e8e2fb 0%, transparent 62%),
    radial-gradient(60% 55% at 28% 100%, #e1f0e5 0%, transparent 62%),
    linear-gradient(155deg, #fff4ee 0%, #f1f0fa 52%, #eef6ef 100%);
}
.intro-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.intro-brand {
  font-family: var(--font-display);
  font-variation-settings: "SOFT" 100, "WONK" 1, "opsz" 72;
  font-weight: 560;
  font-size: 21px;
}
.intro-body {
  margin: auto 0;
  padding: 0 clamp(0px, 6vw, 96px);
}
.intro-eyebrow {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 16px;
  color: var(--text-2);
}
h1 {
  margin: 14px 0 30px;
  font-family: var(--font-display-cn);
  font-weight: 400;
  font-size: clamp(56px, 9vw, 120px);
  letter-spacing: 0.12em;
  line-height: 1.05;
}
.intro-enter {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-radius: 999px;
  background: var(--text);
  color: #fff7f2;
  font-size: 15px;
  font-weight: 500;
  text-decoration: none;
  box-shadow: 0 12px 26px -14px rgba(42, 34, 56, 0.8);
}
</style>
