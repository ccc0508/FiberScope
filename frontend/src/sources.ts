import type { Lineage } from "./api";

export interface SourceUsage extends Lineage {
  source_version: string;
  display_name: string | null;
  experiment_code: string | null;
  display_code: string | null;
  material_code: string | null;
}
export interface SourceObservation {
  file_name: string;
  sheet_name: string;
  source_row: number;
  source_version: string;
  block_code: string;
  cycle_no: number;
  replicate_no: number;
  [key: string]: string | number | null;
}
export interface SourceRow {
  key: string;
  file_name: string;
  sheet_name: string;
  source_row: number;
  source_version: string;
  usages: SourceUsage[];
  observations: SourceObservation[];
}
export const usageNames: Record<string, string> = {
  experiment_sample: "实验展示",
  sample_component: "原料组分",
  fiber_measurement: "纤维测量",
  paper_measurement: "纸张测量",
  source_only: "仅保留来源",
};
export function usageLabel(row: SourceUsage) {
  const material =
    row.material_code === "SW"
      ? "针叶木浆"
      : row.material_code === "HW"
        ? "阔叶木浆"
        : row.material_code;
  return `${usageNames[row.usage_type] ?? row.usage_type}${material ? ` · ${material}` : ""}`;
}
export function groupSources(
  usages: SourceUsage[],
  observations: SourceObservation[],
): SourceRow[] {
  const grouped = new Map<string, SourceRow>();
  function source(row: SourceUsage | SourceObservation) {
    const key = JSON.stringify([
      row.file_name,
      row.sheet_name,
      row.source_version,
      row.source_row,
    ]);
    let result = grouped.get(key);
    if (!result) {
      result = {
        key,
        file_name: row.file_name,
        sheet_name: row.sheet_name,
        source_row: row.source_row,
        source_version: row.source_version,
        usages: [],
        observations: [],
      };
      grouped.set(key, result);
    }
    return result;
  }
  for (const row of usages) source(row).usages.push(row);
  for (const row of observations) source(row).observations.push(row);
  return [...grouped.values()].sort(
    (a, b) =>
      a.file_name.localeCompare(b.file_name, "zh-CN") ||
      a.sheet_name.localeCompare(b.sheet_name) ||
      a.source_version.localeCompare(b.source_version) ||
      a.source_row - b.source_row,
  );
}
export function matchesSource(row: SourceRow, query: string) {
  const text = [
    row.file_name,
    row.sheet_name,
    String(row.source_row),
    row.source_version,
    ...row.usages.flatMap((u) => [
      u.canonical_code,
      u.display_name,
      u.display_code,
    ]),
    ...row.observations.map((o) => o.block_code),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .every((word) => text.includes(word));
}
