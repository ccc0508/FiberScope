<script setup lang="ts">
import ModeSwitch from "../components/ModeSwitch.vue";
import { platformName } from "../nav";
// Placeholder prologue for the polarized mode; the full intro is built separately.
</script>

<template>
  <main id="main" class="intro intro--polarized" tabindex="-1">
    <div class="intro-top">
      <span class="intro-brand">FiberScope <span>偏光</span></span>
      <ModeSwitch compact />
    </div>
    <section class="intro-body" aria-labelledby="intro-title">
      <p class="intro-eyebrow">PROLOGUE · {{ platformName }}</p>
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
  padding: 18px 22px 40px;
  color: var(--text);
  background:
    radial-gradient(50% 60% at 78% 30%, rgba(224, 71, 158, 0.18), transparent 70%),
    radial-gradient(40% 60% at 95% 70%, rgba(46, 196, 214, 0.14), transparent 70%),
    radial-gradient(40% 50% at 60% 0%, rgba(242, 193, 78, 0.12), transparent 70%),
    var(--bg);
}
.intro-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.intro-brand {
  font-family: var(--font-display);
  font-size: 15px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.intro-brand span {
  font-family: var(--font-body);
  font-weight: 200;
  color: var(--text-2);
  margin-left: 8px;
}
.intro-body {
  margin: auto 0;
  padding: 0 clamp(0px, 6vw, 96px);
}
.intro-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--text-2);
}
h1 {
  margin: 18px 0 30px;
  font-family: var(--font-display-cn);
  font-weight: 900;
  font-size: clamp(56px, 10vw, 140px);
  line-height: 1;
}
.intro-enter {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 50px;
  padding: 0 26px;
  border-radius: 999px;
  border: 1px solid transparent;
  background:
    linear-gradient(#0b0d12, #0b0d12) padding-box,
    var(--ifl) border-box;
  color: var(--text);
  font-size: 16px;
  font-weight: 500;
  text-decoration: none;
}
</style>
