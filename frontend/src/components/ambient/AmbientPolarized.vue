<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { createField, type FieldController } from "../../ambient/field";
import { reducedMotion } from "../../mode";
import heroTexture from "../../assets/modes/polarized/hero-polarized.jpg";

/*
 * Decorative interference band behind the top of the workspace (v1 「偏光」 field).
 * Driven by the shell: analyzer angle and compensator follow scroll, the stage follows
 * the pointer, a route change sweeps the analyzer. Falls back to a CSS gradient.
 */
const props = defineProps<{
  /** 0..1 scroll progress */
  phase: number;
  /** 1 → 0 after a route change */
  sweep: number;
  /** pointer, -1..1 */
  stageX: number;
  stageY: number;
  /** per-route compensator offset (nm) */
  retardation: number;
  scrollY: number;
}>();

const canvas = ref<HTMLCanvasElement>();
const glOn = ref(false);
let field: FieldController | null = null;

/*
 * Under prefers-reduced-motion the field is one still frame that never follows scroll,
 * pointer or route sweeps (only the per-route compensator, which changes with the page).
 */
let last = "";
function update() {
  if (!field) return;
  const still = reducedMotion.value;
  const phase = still ? 0 : props.phase,
    sweep = still ? 0 : props.sweep;
  const theta = 90 - 32 * phase + sweep * 90;
  const values = {
    analyzer: (theta * Math.PI) / 180,
    retard: props.retardation + phase * 520 + sweep * 480,
    scroll: still ? 0 : props.scrollY / Math.max(1, window.innerHeight),
    stageX: still ? 0 : props.stageX * 0.3,
    stageY: still ? 0 : -props.stageY * 0.3,
  };
  const key = JSON.stringify(values);
  if (key === last) return; // nothing changed: no redraw
  last = key;
  field.set(values);
}
const bandShift = computed(() =>
  reducedMotion.value ? 0 : -props.scrollY * 0.45,
);

onMounted(() => {
  if (!canvas.value) return;
  try {
    field = createField(canvas.value, {
      scale: 0.42,
      texture: heroTexture,
      still: reducedMotion.value,
      params: {
        intensity: 0.72,
        texAmt: 0.42,
        vig: 0,
        density: 0.5,
        grain: 0.012,
        zoom: 0.9,
        left: 0.55,
      },
      onFail: () => {
        field?.dispose();
        field = null;
        glOn.value = false;
      },
      // the CSS gradient stands in while the GPU context is lost
      onLost: () => {
        glOn.value = false;
      },
      onRestored: () => {
        glOn.value = true;
        last = "";
        update();
      },
    });
  } catch {
    field = null;
  }
  glOn.value = !!field;
  update();
});
watch(
  () => [props.phase, props.sweep, props.stageX, props.stageY, props.retardation, props.scrollY],
  update,
);
watch(reducedMotion, (value) => {
  field?.setStill(value);
  update();
});
onBeforeUnmount(() => {
  field?.dispose();
  field = null;
});
</script>

<template>
  <div class="pz-ambient" aria-hidden="true">
    <div
      class="pz-band"
      :class="{ 'gl-off': !glOn }"
      :style="{ transform: `translate3d(0, ${bandShift.toFixed(1)}px, 0)` }"
    >
      <canvas ref="canvas" class="pz-band-canvas"></canvas>
      <div class="pz-band-fallback"></div>
      <div class="pz-band-grid"></div>
    </div>
    <div class="pz-floor"></div>
  </div>
</template>

<style scoped>
.pz-ambient {
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  overflow: hidden;
  background: #06070a;
}
.pz-band {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 520px;
  overflow: hidden;
  will-change: transform;
  -webkit-mask-image: linear-gradient(180deg, #000 0%, rgba(0, 0, 0, 0.75) 50%, transparent 100%);
  mask-image: linear-gradient(180deg, #000 0%, rgba(0, 0, 0, 0.75) 50%, transparent 100%);
}
.pz-band-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  opacity: 0.5;
}
.pz-band-fallback {
  position: absolute;
  inset: 0;
  display: none;
  background:
    radial-gradient(50% 80% at 78% 20%, rgba(224, 71, 158, 0.25), transparent 70%),
    radial-gradient(40% 70% at 95% 60%, rgba(46, 196, 214, 0.2), transparent 70%),
    radial-gradient(40% 60% at 60% 0%, rgba(242, 193, 78, 0.16), transparent 70%);
}
.gl-off .pz-band-canvas {
  display: none;
}
.gl-off .pz-band-fallback {
  display: block;
}
.pz-band-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 30%);
  mask-image: linear-gradient(90deg, transparent, #000 30%);
}
/* a faint field-of-view glow that stays when the band has scrolled away */
.pz-floor {
  position: absolute;
  inset: auto 0 0 0;
  height: 60vh;
  background: radial-gradient(60% 70% at 85% 120%, rgba(91, 91, 214, 0.08), transparent 70%);
}
@media (max-width: 720px) {
  .pz-band {
    height: 380px;
  }
}
</style>
