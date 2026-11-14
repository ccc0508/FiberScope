import type { Component } from "vue";
import {
  BookOpen,
  ChartNoAxesCombined,
  Combine,
  FileSpreadsheet,
  LayoutDashboard,
  Repeat2,
  ScanSearch,
  ScatterChart,
  Sprout,
} from "lucide-vue-next";

export type NavGroup = "工作空间" | "分析与探索" | "科研助手";
export const navGroups: readonly NavGroup[] = ["工作空间", "分析与探索", "科研助手"];

/** Which generated image (src/assets/modes/garden) a garden hero lens shows, and how it is cropped. */
export interface GardenLens {
  image: "clay-fibers" | "paper-network" | "glass-leaves";
  /** CSS object-position, doubles as the zoom origin */
  position: string;
  scale: number;
}

export interface NavItem {
  path: string;
  /** Chinese page name; also used for document.title and breadcrumbs */
  label: string;
  /** short label for the garden mobile dock */
  short: string;
  group: NavGroup;
  icon: Component;
  /** "01" … "08" */
  index: string;
  /** Latin ghost word behind the polarized title (v1), e.g. "Beating" */
  english: string;
  /** English eyebrow of the garden hero (v4 voice), e.g. "Garden overview" */
  gardenEnglish: string;
  /** polarized objective: total magnification, e.g. "20×" */
  magnification: string;
  /** polarized title weight contrast: heavy part + light part (label = strong + light) */
  titleStrong: string;
  titleLight: string;
  /** polarized ambient field: compensator offset in nm (each page gets its own hue) */
  retardation: number;
  gardenLens: GardenLens;
}

const items: Omit<NavItem, "index">[] = [
  {
    path: "/",
    label: "数据总览",
    short: "总览",
    group: "工作空间",
    icon: LayoutDashboard,
    english: "Overview",
    gardenEnglish: "Garden overview",
    magnification: "10×",
    titleStrong: "数据",
    titleLight: "总览",
    retardation: 300,
    gardenLens: { image: "clay-fibers", position: "74% 58%", scale: 1.5 },
  },
  {
    path: "/beating",
    label: "打浆分析",
    short: "打浆",
    group: "分析与探索",
    icon: ChartNoAxesCombined,
    english: "Beating",
    gardenEnglish: "Beating",
    magnification: "20×",
    titleStrong: "打浆",
    titleLight: "分析",
    retardation: 360,
    gardenLens: { image: "clay-fibers", position: "64% 66%", scale: 3.1 },
  },
  {
    path: "/blends",
    label: "复配分析",
    short: "复配",
    group: "分析与探索",
    icon: Combine,
    english: "Blends",
    gardenEnglish: "Blending",
    magnification: "40×",
    titleStrong: "复配",
    titleLight: "分析",
    retardation: 425,
    gardenLens: { image: "glass-leaves", position: "50% 46%", scale: 1.62 },
  },
  {
    path: "/association",
    label: "纤维—纸张关联",
    short: "关联",
    group: "分析与探索",
    icon: ScatterChart,
    english: "Association",
    gardenEnglish: "Fibre × paper",
    magnification: "100×",
    titleStrong: "纤维—纸张",
    titleLight: "关联",
    retardation: 495,
    gardenLens: { image: "paper-network", position: "50% 52%", scale: 1.3 },
  },
  {
    path: "/recycled",
    label: "再生纸浆循环",
    short: "再生",
    group: "分析与探索",
    icon: Repeat2,
    english: "Recycled",
    gardenEnglish: "Recycling loops",
    magnification: "200×",
    titleStrong: "再生纸浆",
    titleLight: "循环",
    retardation: 560,
    gardenLens: { image: "paper-network", position: "74% 38%", scale: 2.5 },
  },
  {
    path: "/sources",
    label: "数据来源",
    short: "来源",
    group: "分析与探索",
    icon: ScanSearch,
    english: "Sources",
    gardenEnglish: "Provenance",
    magnification: "400×",
    titleStrong: "数据",
    titleLight: "来源",
    retardation: 620,
    gardenLens: { image: "glass-leaves", position: "62% 58%", scale: 2.7 },
  },
  {
    path: "/literature",
    label: "文献问答",
    short: "问答",
    group: "科研助手",
    icon: BookOpen,
    english: "Literature",
    gardenEnglish: "Ask the literature",
    magnification: "1000×",
    titleStrong: "文献",
    titleLight: "问答",
    retardation: 690,
    gardenLens: { image: "clay-fibers", position: "26% 88%", scale: 2.1 },
  },
  {
    path: "/literature-data",
    label: "文献数据",
    short: "文献数据",
    group: "科研助手",
    icon: FileSpreadsheet,
    english: "Extraction",
    gardenEnglish: "Literature data",
    magnification: "4000×",
    titleStrong: "文献",
    titleLight: "数据",
    retardation: 750,
    gardenLens: { image: "paper-network", position: "22% 76%", scale: 3.2 },
  },
];

/** The eight workspace routes, in navigation order. */
export const navItems: readonly NavItem[] = items.map((item, i) => ({
  ...item,
  index: String(i + 1).padStart(2, "0"),
}));
export const navTotal = String(navItems.length).padStart(2, "0");

/** The prologue (rendered without any shell). */
export const introItem = {
  path: "/intro",
  label: "序章",
  short: "首页",
  english: "Prologue",
  icon: Sprout,
} as const;

export const platformName = "植物纤维可视化分析平台";

export function navItemFor(path: string): NavItem | undefined {
  const clean = path.replace(/\/+$/, "") || "/";
  return navItems.find((item) => item.path === clean);
}

/** Page name for document.title; unknown paths redirect to the overview. */
export function pageLabelFor(path: string): string {
  if (path.replace(/\/+$/, "") === introItem.path) return introItem.label;
  return (navItemFor(path) ?? navItems[0]!).label;
}
