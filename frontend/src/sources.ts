import type { Lineage, SampleType } from "./api";

export interface SourceUsage extends Lineage {
  source_version: string;
  display_name: string | null;
  experiment_code: string | null;
  display_code: string | null;
  material_code: string | null;
  /** material of the linked sample (null for source-only rows) */
  sample_type?: SampleType | null;
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

/** Material of a source file or target: the three pulps, recycled pulp, or unknown. */
export type SourceKind = SampleType | "recycled" | "other";
export interface SourceTarget {
  label: string;
  kind: SourceKind;
}
/** Linked samples (with their material) and recycled block · cycle labels of one source row, without repeats. */
export function sourceTargets(row: SourceRow): SourceTarget[] {
  const seen = new Map<string, SourceTarget>();
  for (const u of row.usages)
    if (u.canonical_code && !seen.has(u.canonical_code))
      seen.set(u.canonical_code, {
        label: u.canonical_code,
        kind: u.sample_type ?? "other",
      });
  for (const o of row.observations) {
    const label = `${o.block_code} · 第 ${o.cycle_no} 次循环`;
    if (!seen.has(label)) seen.set(label, { label, kind: "recycled" });
  }
  return [...seen.values()];
}
/**
 * Material of a whole source file from its rows: one material when every linked sample
 * shares it, "blend" for blend files (they also list the reused pure-pulp end points),
 * "recycled" for recycled observations, otherwise "other".
 */
export function sourceKind(rows: SourceRow[]): SourceKind {
  const kinds = new Set<SourceKind>();
  for (const r of rows) {
    if (r.observations.length) kinds.add("recycled");
    for (const u of r.usages) if (u.sample_type) kinds.add(u.sample_type);
  }
  if (kinds.size === 1) return [...kinds][0]!;
  return kinds.has("blend") && !kinds.has("recycled") ? "blend" : "other";
}
export type MaterialCounts = Record<SampleType, number>;
export interface Provenance {
  /** unique linked samples per material */
  samples: MaterialCounts;
  /** experiment display points per experiment group and material */
  beating: MaterialCounts;
  blend: MaterialCounts;
}
/** How linked samples become experiment display points, from the source usages alone. */
export function provenance(rows: SourceRow[]): Provenance {
  const empty = (): MaterialCounts => ({ softwood: 0, hardwood: 0, blend: 0 });
  const result: Provenance = { samples: empty(), beating: empty(), blend: empty() };
  const samples = new Map<string, SampleType>();
  const points = new Set<string>();
  for (const r of rows)
    for (const u of r.usages) {
      if (!u.sample_type) continue;
      if (u.canonical_code) samples.set(u.canonical_code, u.sample_type);
      if (u.usage_type !== "experiment_sample" || !u.experiment_code) continue;
      const group = /blend/i.test(u.experiment_code)
        ? "blend"
        : /beating/i.test(u.experiment_code)
          ? "beating"
          : null;
      const id = JSON.stringify([u.experiment_code, u.canonical_code, u.display_code]);
      if (!group || points.has(id)) continue;
      points.add(id);
      result[group][u.sample_type]++;
    }
  for (const type of samples.values()) result.samples[type]++;
  return result;
}
