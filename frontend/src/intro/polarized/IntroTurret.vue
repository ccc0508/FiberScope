<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { objectives, routeNote, turretTicks } from "./content";

/*
 * Objective turret (final section of the prologue): the eight workspace pages sit on a
 * revolving nosepiece. Hovering or focusing a lens swings the needle and fills the eyepiece
 * with that page's analyzer colour; every lens is a plain link to its page.
 */
const props = defineProps<{ recycledBlocks: number | null }>();

const active = ref(0);
const current = computed(() => objectives[active.value]!);
const note = (path: string) => routeNote(path, props.recycledBlocks);
function pick(i: number) {
  active.value = i;
}

// the eyepiece drift only runs while the turret is on screen
const root = ref<HTMLElement>();
const live = ref(false);
let io: IntersectionObserver | undefined;
onMounted(() => {
  if (!root.value || typeof IntersectionObserver !== "function") return;
  io = new IntersectionObserver((entries) => {
    live.value = entries[0]?.isIntersecting ?? false;
  });
  io.observe(root.value);
});
onBeforeUnmount(() => io?.disconnect());
</script>

<template>
  <div
    ref="root"
    class="lt"
    :class="{ live }"
    :style="{
      '--pzi-tone': current.tone,
      '--pzi-tone-ink': current.toneInk,
      '--pzi-needle': `${(active * 360) / objectives.length}deg`,
    }"
  >
    <div class="lt-dial">
      <svg class="lt-ring" viewBox="0 0 600 600" aria-hidden="true" focusable="false">
        <circle cx="300" cy="300" r="296" class="lt-r0" />
        <circle cx="300" cy="300" r="262" class="lt-r1" />
        <circle cx="300" cy="300" r="214" class="lt-r2" />
        <path :d="turretTicks.short" class="lt-tick" />
        <path :d="turretTicks.long" class="lt-tick lt-tick-l" />
      </svg>
      <div class="lt-needle" aria-hidden="true"><i></i></div>
      <div class="lt-eye" aria-hidden="true">
        <div class="lt-eye-field"></div>
        <div class="lt-eye-cross"></div>
        <div class="lt-eye-txt">
          <span class="lt-eye-mag">{{ current.item.magnification }}</span>
          <span class="mono lt-eye-k"
            ><span class="lt-tm">TOTAL MAG · </span>Γ <b>{{ current.item.retardation }}</b> nm</span
          >
        </div>
      </div>
      <ol class="lt-lenses" aria-label="物镜：工作台的 8 个页面">
        <li
          v-for="(o, i) in objectives"
          :key="o.item.path"
          class="lt-pos"
          :style="{ '--a': `${o.angle.toFixed(1)}deg` }"
        >
          <RouterLink
            :to="o.item.path"
            class="lt-lens"
            :class="{ on: i === active }"
            :style="{ '--pzi-tone': o.tone }"
            @pointerenter="pick(i)"
            @focus="pick(i)"
          >
            <span class="lens" aria-hidden="true"
              ><span class="lens-mag mono">{{ o.item.magnification }}</span></span
            >
            <span class="lt-lbl"
              ><span class="mono lt-idx" aria-hidden="true">{{ o.item.index }}</span
              >{{ o.item.label }}</span
            >
            <span class="sr-only">：物镜 {{ o.item.magnification }}，{{ note(o.item.path) }}</span>
          </RouterLink>
        </li>
      </ol>
    </div>

    <div class="lt-panel">
      <span class="mono lt-n">OBJ {{ current.item.index }} · {{ current.item.group }}</span>
      <p class="lt-t">{{ current.item.label }}</p>
      <p class="lt-d">{{ note(current.item.path) }}</p>
      <RouterLink class="button primary lt-go" :to="current.item.path"
        >进入{{ current.item.label }} <span aria-hidden="true">→</span></RouterLink
      >
      <p class="mono lt-hint">悬停或用 Tab 聚焦物镜，目镜中预览该页的检偏器色</p>
    </div>
  </div>
</template>

<style scoped>
@property --pzi-tone {
  syntax: "<color>";
  inherits: true;
  initial-value: transparent;
}
.lt {
  --pzi-needle: 0deg;
  display: grid;
  grid-template-columns: minmax(0, 620px) minmax(0, 1fr);
  gap: clamp(28px, 5vw, 90px);
  align-items: center;
  margin-top: 26px;
  transition: --pzi-tone 0.6s;
}
.lt-dial {
  position: relative;
  width: min(100%, 620px);
  aspect-ratio: 1;
  container-type: inline-size;
}
.lt-ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.lt-r0 {
  fill: color-mix(in srgb, var(--surface) 60%, transparent);
  stroke: color-mix(in srgb, var(--text) 22%, transparent);
  stroke-width: 1;
}
.lt-r1 {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 6%, transparent);
  stroke-width: 40;
}
.lt-r2 {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 12%, transparent);
  stroke-width: 1;
  stroke-dasharray: 2 6;
}
.lt-tick {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 18%, transparent);
  stroke-width: 1;
}
.lt-tick-l {
  stroke: color-mix(in srgb, var(--text) 42%, transparent);
}
.lt-needle {
  position: absolute;
  inset: 0;
  transform: rotate(var(--pzi-needle));
  transition: transform 0.7s cubic-bezier(0.3, 0.7, 0.2, 1);
  pointer-events: none;
}
.lt-needle i {
  position: absolute;
  left: 50%;
  top: 6.5%;
  width: 2px;
  height: 22%;
  margin-left: -1px;
  border-radius: 1px;
  background: linear-gradient(180deg, var(--pzi-tone), transparent);
  box-shadow: 0 0 18px var(--pzi-tone);
}

/* eyepiece: the chosen page's analyzer colour as a drifting interference field */
.lt-eye {
  position: absolute;
  inset: 30%;
  border-radius: 50%;
  overflow: hidden;
  isolation: isolate;
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--text) 18%, transparent),
    0 0 0 8px color-mix(in srgb, var(--bg) 90%, transparent),
    0 0 0 9px color-mix(in srgb, var(--text) 8%, transparent),
    0 0 90px -10px var(--pzi-tone);
}
.lt-eye-field {
  position: absolute;
  inset: -20%;
  background:
    radial-gradient(circle at 50% 50%, transparent 30%, color-mix(in srgb, var(--bg) 75%, transparent) 72%),
    repeating-linear-gradient(
      118deg,
      color-mix(in srgb, var(--pzi-tone) 70%, transparent) 0 6px,
      transparent 6px 15px,
      color-mix(in srgb, var(--pzi-tone) 45%, var(--text)) 15px 17px,
      transparent 17px 29px
    ),
    conic-gradient(from 210deg, var(--pzi-tone), var(--bg) 30%, var(--pzi-tone) 52%, var(--bg) 78%, var(--pzi-tone));
  filter: blur(1.5px) saturate(1.2);
  animation: pzi-drift 18s linear infinite paused;
  will-change: transform;
}
.live .lt-eye-field {
  animation-play-state: running;
}
@keyframes pzi-drift {
  to {
    transform: rotate(360deg);
  }
}
.lt-eye-cross {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(color-mix(in srgb, var(--text) 22%, transparent), color-mix(in srgb, var(--text) 22%, transparent)) center / 1px 100% no-repeat,
    linear-gradient(color-mix(in srgb, var(--text) 22%, transparent), color-mix(in srgb, var(--text) 22%, transparent)) center / 100% 1px no-repeat;
}
/* a dark lens disc behind the readout keeps it legible over any tone */
.lt-eye-txt {
  position: absolute;
  inset: 22%;
  border-radius: 50%;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 6px;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--bg) 84%, transparent), color-mix(in srgb, var(--bg) 55%, transparent) 70%, transparent);
  text-shadow:
    0 2px 18px var(--bg),
    0 0 4px var(--bg);
}
.lt-eye-mag {
  font-family: var(--font-display);
  font-weight: 200;
  font-size: clamp(30px, 4.4vw, 62px);
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--text);
}
/* an opaque pill: the readout must stay legible on the brightest tone */
.lt-eye-k {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--text);
  white-space: nowrap;
  background: color-mix(in srgb, var(--bg) 84%, transparent);
  text-shadow: none;
}
.lt-eye-k b {
  font-weight: 500;
}

/* lenses on the nosepiece */
.lt-lenses {
  list-style: none;
  margin: 0;
  padding: 0;
}
.lt-pos {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0;
  height: 0;
  transform: rotate(var(--a)) translateX(39.5cqw) rotate(calc(-1 * var(--a)));
}
.lt-lens {
  position: absolute;
  left: 0;
  top: 0;
  transform: translate(-50%, -28px);
  display: grid;
  justify-items: center;
  gap: 10px;
  width: 120px;
  padding: 4px;
  border-radius: 16px;
  color: var(--text-2);
  text-decoration: none;
}
.lens {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: radial-gradient(
    circle at 35% 30%,
    color-mix(in srgb, var(--surface-hover), var(--text) 9%),
    color-mix(in srgb, var(--bg), var(--surface) 45%) 70%
  );
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--text) 14%, transparent),
    inset 0 -6px 12px color-mix(in srgb, var(--bg) 60%, transparent);
  transition:
    box-shadow 0.3s,
    transform 0.3s;
}
.lens::before {
  content: "";
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  padding: 2px;
  background: var(--ifc);
  -webkit-mask:
    linear-gradient(black 0 0) content-box,
    linear-gradient(black 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.3s;
}
.lens-mag {
  font-size: 11px;
  color: var(--text-2);
  letter-spacing: -0.02em;
}
/* a faint dark chip: the needle and the active lens glow pass right behind the labels */
.lt-lbl {
  display: grid;
  justify-items: center;
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.3;
  text-align: center;
  white-space: nowrap;
  background: color-mix(in srgb, var(--bg) 74%, transparent);
  text-shadow: var(--pzi-halo, 0 1px 8px var(--bg));
}
.lt-idx {
  font-size: 10.5px;
  color: var(--text-2);
  letter-spacing: 0.1em;
}
.lt-lens:hover,
.lt-lens.on {
  color: var(--text);
}
.lt-lens:hover .lens {
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--text) 30%, transparent),
    inset 0 -6px 12px color-mix(in srgb, var(--bg) 60%, transparent);
}
/* the glow stays tight around the lens so the label under it keeps its contrast */
.lt-lens.on .lens {
  transform: scale(1.14);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--text) 40%, transparent),
    0 0 18px -4px var(--pzi-tone),
    0 0 34px -14px var(--pzi-tone);
}
.lt-lens.on .lens::before,
.lt-lens:focus-visible .lens::before {
  opacity: 1;
}
.lt-lens.on .lens-mag {
  color: var(--text);
}
.lt-lens.on .lt-lbl {
  font-weight: 700;
}
.lt-lens.on .lt-idx {
  color: var(--text);
}

/* panel */
.lt-panel {
  display: grid;
  gap: 12px;
  align-content: center;
  max-width: 460px;
}
.lt-n {
  font-size: 11.5px;
  letter-spacing: 0.12em;
  color: var(--pzi-tone-ink, var(--text-2));
}
.lt-t {
  margin: 0;
  font-size: clamp(30px, 3.4vw, 50px);
  font-weight: 900;
  line-height: 1.1;
  color: var(--text);
}
.lt-d {
  margin: 0;
  color: color-mix(in srgb, var(--text) 60%, var(--text-2));
  font-weight: 300;
  font-size: 16px;
  line-height: 1.85;
  min-height: 3.7em;
}
.lt-go {
  justify-self: start;
  margin-top: 8px;
  min-height: 50px;
  padding: 0 26px;
  font-size: 16px;
}
.lt-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-2);
}

@media (max-width: 1100px) {
  .lt {
    grid-template-columns: 1fr;
    justify-items: center;
  }
  .lt-panel {
    justify-items: center;
    text-align: center;
  }
  .lt-go {
    justify-self: center;
  }
}
@media (max-width: 560px) {
  .lt {
    margin-top: 10px;
    gap: 24px;
  }
  .lt-lens {
    width: max-content;
    min-width: 84px;
    /* clears the scaled active lens and its interference ring */
    gap: 8px;
    transform: translate(-50%, -21px);
  }
  .lens {
    width: 40px;
    height: 40px;
  }
  .lens-mag {
    font-size: 9px;
  }
  .lt-lbl {
    font-size: 11px;
  }
  .lt-idx {
    display: none;
  }
  .lt-eye {
    inset: 31%;
  }
  .lt-tm {
    display: none;
  }
  .lt-eye-k {
    font-size: 9.5px;
  }
  .lt-t {
    font-size: 30px;
  }
  .lt-d {
    font-size: 15px;
  }
}
@media (hover: none) {
  .lt-hint {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .lt-needle,
  .lt {
    transition: none;
  }
}
</style>
