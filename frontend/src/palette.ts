import { reactive, watch } from "vue";
import type { SampleType } from "./api";
import { mode, type Mode } from "./mode";

/*
 * Real colour strings for SVG / canvas attributes, following the active mode.
 * CSS var() is unreliable inside SVG presentation attributes (fill="", stroke="") and
 * unavailable to canvas, so charts bind these reactive objects instead; they update in
 * place when the mode changes. Values mirror the tokens in style.css — keep them in sync.
 *
 *  - materialColors      marks, lines, fills (≥3:1 against the chart paper)
 *  - materialInkColors   text in a material colour (≥4.5:1 on --surface)
 *  - materialTintColors  soft backgrounds behind material-coloured content
 */
type MaterialSet = Record<SampleType, string>;

const MATERIAL: Record<Mode, MaterialSet> = {
  // polarized: interference colours on a black field
  polarized: { softwood: "#F2C14E", hardwood: "#2EC4D6", blend: "#E0479E" },
  // garden: stain colours peach / sage / lilac
  garden: { softwood: "#DA6B3C", hardwood: "#4E9A6A", blend: "#8B6CD9" },
};
const MATERIAL_INK: Record<Mode, MaterialSet> = {
  polarized: { softwood: "#F2C14E", hardwood: "#2EC4D6", blend: "#F06BB6" },
  garden: { softwood: "#A9481F", hardwood: "#2C6F45", blend: "#5E40B3" },
};
const MATERIAL_TINT: Record<Mode, MaterialSet> = {
  polarized: { softwood: "#2A2414", hardwood: "#0F2A2F", blend: "#2C1424" },
  garden: { softwood: "#FFE6D8", hardwood: "#DDF0E1", blend: "#ECE5FB" },
};

export interface ChartColors {
  /** chart background ("paper"); also the halo ring drawn around points */
  paper: string;
  grid: string;
  axis: string;
  /** tick labels and axis titles */
  text: string;
  /** emphasised labels / values inside the chart */
  textStrong: string;
  /** target / reference lines (e.g. 目标打浆度) */
  target: string;
  /** hover crosshair / guide */
  guide: string;
  /** keyboard / selection ring */
  focus: string;
  /** recycled pulp series */
  recycled: string;
  /** 待复核 / flagged observations */
  review: string;
  accent: string;
}

const CHART: Record<Mode, ChartColors> = {
  polarized: {
    paper: "#0E1117",
    grid: "rgba(255, 255, 255, 0.07)",
    axis: "rgba(255, 255, 255, 0.28)",
    text: "#9AA3B2",
    textStrong: "#ECEFF4",
    target: "rgba(236, 239, 244, 0.6)",
    guide: "rgba(236, 239, 244, 0.4)",
    focus: "#FFFFFF",
    recycled: "#9A9AF5",
    review: "#FF9466",
    accent: "#2EC4D6",
  },
  garden: {
    paper: "#FFFCFD",
    grid: "rgba(42, 34, 56, 0.075)",
    axis: "rgba(42, 34, 56, 0.28)",
    text: "#5E5670",
    textStrong: "#2A2238",
    target: "#4A3B63",
    guide: "rgba(42, 34, 56, 0.35)",
    focus: "#2A2238",
    recycled: "#776C8C",
    review: "#A94B24",
    accent: "#4A3B63",
  },
};

export const materialColors = reactive<MaterialSet>({ ...MATERIAL[mode.value] });
export const materialInkColors = reactive<MaterialSet>({ ...MATERIAL_INK[mode.value] });
export const materialTintColors = reactive<MaterialSet>({ ...MATERIAL_TINT[mode.value] });
/** Same colours keyed by the beating-page material codes. */
export const materialCodeColors = reactive({
  SW: MATERIAL[mode.value].softwood,
  HW: MATERIAL[mode.value].hardwood,
});
export const chartColors = reactive<ChartColors>({ ...CHART[mode.value] });

/** Non-reactive lookup, e.g. for a canvas that redraws itself in a watch(mode, …). */
export function paletteFor(value: Mode) {
  return {
    material: MATERIAL[value],
    materialInk: MATERIAL_INK[value],
    materialTint: MATERIAL_TINT[value],
    chart: CHART[value],
  };
}

watch(
  mode,
  (value) => {
    Object.assign(materialColors, MATERIAL[value]);
    Object.assign(materialInkColors, MATERIAL_INK[value]);
    Object.assign(materialTintColors, MATERIAL_TINT[value]);
    materialCodeColors.SW = MATERIAL[value].softwood;
    materialCodeColors.HW = MATERIAL[value].hardwood;
    Object.assign(chartColors, CHART[value]);
  },
  { flush: "sync" },
);
