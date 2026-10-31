import type { SampleType } from "./api";

// 三种原料的标识色，与 style.css 的 --sw / --hw / --bl 保持一致。
// 在暖白纸面（#fbf8f1）上的对比度：针叶 5.8:1、阔叶 5.1:1、复配 6.6:1；
// 阔叶偏黄绿，避免与青色强调色（--signal）混淆。
export const materialColors: Record<SampleType, string> = {
  softwood: "#8a5604",
  hardwood: "#127a3a",
  blend: "#7a3f98",
};

export const materialCodeColors = {
  SW: materialColors.softwood,
  HW: materialColors.hardwood,
} as const;
