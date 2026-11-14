// Live numbers for the garden prologue (序章 · 纤维花园). Everything the story shows comes from
// the read-only API, never from the prototype snapshot:
//   metadata     → sample / display-point / recycled counts, indicator groups, data blocks, notes
//   beating      → °SR curves, beating range, unbeaten (0 r) fibre length
//   fiber-paper  → composition by sample type, fibre length × tensile index pairs
// The three requests load in parallel and fail independently: whatever arrived is shown, a
// missing number reads "—", and reload() only repeats the requests that failed.
import { computed, onBeforeUnmount, ref, type Ref } from "vue";
import {
  get,
  typeKeys,
  typeNames,
  type ListResult,
  type Metadata,
  type SampleType,
} from "../../api";
import { pearson } from "../../analysis";
import { firstReach, type CurvePoint } from "../../beating";

export type LoadStatus = "loading" | "ready" | "error";

const GROUP_LABEL: Record<string, string> = {
  fiber: "纤维",
  paper: "纸张",
  distribution: "长度分布",
  strength: "强度",
};

interface BeatingRow {
  material_code: "SW" | "HW";
  beating_revolutions: number | null;
  beating_degree_sr: number | null;
  fiber_length_weighted_mm: number | null;
}
interface FiberPaperRow {
  sample_type: SampleType;
  fiber_length_weighted_mm: number | null;
  tensile_index: number | null;
}

/** The beating page opens on this target too (Beating.vue default); it is a reading aid, not data. */
export const TARGET_SR = 45;

async function all<T>(path: string, signal: AbortSignal): Promise<T[]> {
  const first = await get<ListResult<T>>(path, { page_size: 500 }, signal);
  const rows = [...first.data];
  for (let page = 2; page <= first.pagination.total_pages; page++)
    rows.push(...(await get<ListResult<T>>(path, { page_size: 500, page }, signal)).data);
  return rows;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export interface Correlation {
  key: "all" | SampleType;
  label: string;
  /** pairs with both values present */
  n: number;
  r: number | null;
}

export function useGardenIntroData() {
  const metadata = ref<Metadata | null>(null);
  const beating = ref<BeatingRow[] | null>(null);
  const fiberPaper = ref<FiberPaperRow[] | null>(null);
  const parts = {
    metadata: ref<LoadStatus>("loading"),
    beating: ref<LoadStatus>("loading"),
    fiberPaper: ref<LoadStatus>("loading"),
  };
  const message = ref("");
  let controller: AbortController | undefined;

  function job<T>(state: Ref<LoadStatus>, target: Ref<T | null>, task: Promise<T>, signal: AbortSignal) {
    return task.then(
      (value) => {
        if (signal.aborted) return;
        target.value = value;
        state.value = "ready";
      },
      (error: unknown) => {
        if (signal.aborted) return;
        state.value = "error";
        message.value ||= error instanceof Error && error.message ? error.message : "数据读取失败。";
      },
    );
  }

  async function load() {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    const { signal } = current;
    message.value = "";
    const jobs: Promise<void>[] = [];
    if (parts.metadata.value !== "ready") {
      parts.metadata.value = "loading";
      jobs.push(job(parts.metadata, metadata, get<Metadata>("metadata", {}, signal), signal));
    }
    if (parts.beating.value !== "ready") {
      parts.beating.value = "loading";
      jobs.push(job(parts.beating, beating, all<BeatingRow>("beating", signal), signal));
    }
    if (parts.fiberPaper.value !== "ready") {
      parts.fiberPaper.value = "loading";
      jobs.push(job(parts.fiberPaper, fiberPaper, all<FiberPaperRow>("fiber-paper", signal), signal));
    }
    await Promise.all(jobs);
  }

  const status = computed<LoadStatus>(() => {
    const list = Object.values(parts).map((p) => p.value);
    if (list.includes("loading")) return "loading";
    return list.includes("error") ? "error" : "ready";
  });
  /** every request failed (nothing to show), as opposed to a partial failure */
  const allFailed = computed(() => Object.values(parts).every((p) => p.value === "error"));
  const loading = {
    metadata: computed(() => parts.metadata.value === "loading"),
    beating: computed(() => parts.beating.value === "loading"),
    fiberPaper: computed(() => parts.fiberPaper.value === "loading"),
  };

  /* ---------------------------------------------------------------- metadata */
  const stats = computed(() => {
    const meta = metadata.value;
    const count = (key: string) => {
      const v = meta?.counts?.[key];
      return finite(v) ? v : null;
    };
    const group = (key: string) => (meta ? meta.indicators.filter((i) => i.group === key).length : null);
    const beatingPoints = count("beating"),
      blendPoints = count("blends");
    return {
      samples: count("samples"),
      indicators: meta ? meta.indicators.length : null,
      fiberProps: group("fiber"),
      paperProps: group("paper"),
      beatingPoints,
      blendPoints,
      /** 核心实验展示点 = beating + blend display points (blend ends reuse pure samples) */
      displayPoints: beatingPoints != null && blendPoints != null ? beatingPoints + blendPoints : null,
      recycledObs: count("recycled/details"),
      recycledCycles: count("recycled/cycles"),
      recycledBlocks: meta ? meta.blocks.length : null,
      /** blocks whose formal treatment condition is not recorded */
      unknownBlocks: meta ? meta.blocks.filter((b) => !b.condition_label).length : null,
    };
  });
  const notes = computed(() => metadata.value?.notes ?? []);
  /** indicator counts per group, in the API's order (labels as on the overview page) */
  const indicatorGroups = computed(() => {
    const list = metadata.value?.indicators;
    if (!list) return null;
    const byGroup = new Map<string, number>();
    for (const item of list) byGroup.set(item.group, (byGroup.get(item.group) ?? 0) + 1);
    return [...byGroup].map(([key, n]) => ({ key, n, label: GROUP_LABEL[key] ?? key }));
  });

  /* ---------------------------------------------------------------- fiber-paper: composition + r */
  const composition = computed(() => {
    const rows = fiberPaper.value;
    if (!rows) return null;
    return typeKeys.map((type) => ({
      type,
      label: typeNames[type],
      n: rows.filter((r) => r.sample_type === type).length,
    }));
  });
  const correlations = computed<Correlation[] | null>(() => {
    const rows = fiberPaper.value;
    if (!rows) return null;
    const of = (key: Correlation["key"]): Correlation => {
      const pairs = rows
        .filter((r) => key === "all" || r.sample_type === key)
        .filter((r) => finite(r.fiber_length_weighted_mm) && finite(r.tensile_index))
        .map((r) => [r.fiber_length_weighted_mm, r.tensile_index] as [number, number]);
      return { key, label: key === "all" ? "全部类型（合并）" : typeNames[key], n: pairs.length, r: pearson(pairs) };
    };
    return [of("all"), ...typeKeys.map(of)];
  });

  /* ---------------------------------------------------------------- beating: curves and reach */
  const curves = computed(() => {
    const rows = beating.value;
    if (!rows) return null;
    const curve = (code: "SW" | "HW"): CurvePoint[] =>
      rows
        .filter((r) => r.material_code === code && finite(r.beating_revolutions) && finite(r.beating_degree_sr))
        .map((r) => ({ x: r.beating_revolutions as number, y: r.beating_degree_sr as number }))
        .sort((a, b) => a.x - b.x);
    return { softwood: curve("SW"), hardwood: curve("HW") };
  });
  const beatingFacts = computed(() => {
    const rows = beating.value;
    const c = curves.value;
    if (!rows || !c) return null;
    const revs = rows.map((r) => r.beating_revolutions).filter(finite);
    // "≈ 9,600 r": linear interpolation between neighbouring observations, rounded to 100 r
    const reach = (points: CurvePoint[]) => {
      const x = firstReach(points, TARGET_SR);
      return x == null ? null : Math.round(x / 100) * 100;
    };
    const sw = reach(c.softwood),
      hw = reach(c.hardwood);
    const unbeaten = (code: "SW" | "HW") => {
      const row = rows.find((r) => r.material_code === code && r.beating_revolutions === 0);
      return row && finite(row.fiber_length_weighted_mm) ? row.fiber_length_weighted_mm : null;
    };
    return {
      maxRev: revs.length ? Math.max(...revs) : null,
      reach: { softwood: sw, hardwood: hw },
      diff: sw != null && hw != null ? sw - hw : null,
      unbeatenLength: { softwood: unbeaten("SW"), hardwood: unbeaten("HW") },
    };
  });

  void load();
  onBeforeUnmount(() => controller?.abort());

  return {
    status,
    allFailed,
    loading,
    message,
    reload: load,
    stats,
    notes,
    indicatorGroups,
    composition,
    correlations,
    curves,
    beatingFacts,
  };
}
