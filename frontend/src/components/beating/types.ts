import { materialCodeColors } from "../../palette";

export type Material = "SW" | "HW";

export interface BeatingRow {
  canonical_code: string;
  display_name: string;
  material_code: Material;
  beating_revolutions: number;
  [key: string]: string | number | null;
}

export const MATERIALS: Material[] = ["SW", "HW"];
export const SR_KEY = "beating_degree_sr";
export const TARGET_MIN = 20;
export const TARGET_MAX = 85;

export const materialName = (code: Material) =>
  code === "SW" ? "针叶木浆" : "阔叶木浆";

export const typeOfMaterial = (code: Material) =>
  code === "SW" ? "softwood" : "hardwood";

export const materialColor = (code: Material) => materialCodeColors[code];
