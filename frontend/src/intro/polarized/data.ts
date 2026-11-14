// Live numbers for the polarized prologue. Everything shown comes from the read-only API:
//   metadata          → counts, indicators, recycled data blocks
//   samples           → composition (softwood / hardwood / blend), beating and blend ranges
//   lineage + recycled/details → source files and source rows (as the 数据来源 page counts them)
// The two groups load in parallel and fail independently; a missing number shows "—".
import { computed, onBeforeUnmount, ref } from "vue";
import {
  get,
  number,
  typeKeys,
  typeNames,
  type ListResult,
  type Metadata,
  type Sample,
  type SampleType,
} from "../../api";
import { groupSources, type SourceObservation, type SourceUsage } from "../../sources";

export type LoadStatus = "loading" | "ready" | "error";

export interface CompositionItem {
  type: SampleType;
  label: string;
  n: number;
  /** share of all physical samples, 0–100 */
  share: number;
  /** "打浆 0–34,000 r" / "针叶木 10%–90%", null when the samples carry no values */
  range: string | null;
}

async function all<T>(path: string, signal: AbortSignal): Promise<T[]> {
  const first = await get<ListResult<T>>(path, { page_size: 500 }, signal);
  const data = [...first.data];
  for (let page = 2; page <= first.pagination.total_pages; page++)
    data.push(...(await get<ListResult<T>>(path, { page_size: 500, page }, signal)).data);
  return data;
}

function span(values: (number | null | undefined)[]) {
  const list = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  return list.length ? { min: Math.min(...list), max: Math.max(...list) } : null;
}

export function useIntroStats() {
  const metadata = ref<Metadata | null>(null);
  const samples = ref<Sample[] | null>(null);
  const sources = ref<{ files: number; rows: number } | null>(null);
  const coreStatus = ref<LoadStatus>("loading");
  const sourceStatus = ref<LoadStatus>("loading");
  const message = ref("");
  let controller: AbortController | undefined;

  const failed = (error: unknown) =>
    error instanceof Error && error.message ? error.message : "数据读取失败。";

  async function load() {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    const { signal } = current;
    message.value = "";
    const jobs: Promise<void>[] = [];
    if (coreStatus.value !== "ready") {
      coreStatus.value = "loading";
      jobs.push(
        Promise.all([get<Metadata>("metadata", {}, signal), all<Sample>("samples", signal)]).then(
          ([meta, list]) => {
            if (signal.aborted) return;
            metadata.value = meta;
            samples.value = list;
            coreStatus.value = "ready";
          },
          (error) => {
            if (signal.aborted) return;
            coreStatus.value = "error";
            message.value ||= failed(error);
          },
        ),
      );
    }
    if (sourceStatus.value !== "ready") {
      sourceStatus.value = "loading";
      jobs.push(
        Promise.all([
          all<SourceUsage>("lineage", signal),
          all<SourceObservation>("recycled/details", signal),
        ]).then(
          ([usages, observations]) => {
            if (signal.aborted) return;
            // one source row = one (file, sheet, version, row): the 数据来源 page's own grouping
            const rows = groupSources(usages, observations);
            sources.value = { files: new Set(rows.map((r) => r.file_name)).size, rows: rows.length };
            sourceStatus.value = "ready";
          },
          (error) => {
            if (signal.aborted) return;
            sourceStatus.value = "error";
            message.value ||= failed(error);
          },
        ),
      );
    }
    await Promise.all(jobs);
  }

  const stats = computed(() => {
    const meta = metadata.value;
    const count = (key: string) => {
      const v = meta?.counts?.[key];
      return typeof v === "number" ? v : null;
    };
    const group = (key: string) => (meta ? meta.indicators.filter((i) => i.group === key).length : null);
    const beating = count("beating"),
      blends = count("blends");
    return {
      samples: count("samples"),
      indicators: meta ? meta.indicators.length : null,
      fiberProps: group("fiber"),
      paperProps: group("paper"),
      /** 核心实验展示点 = beating + blend display points (blend ends reuse pure samples) */
      displayPoints: beating != null && blends != null ? beating + blends : null,
      recycledObs: count("recycled/details"),
      recycledCycles: count("recycled/cycles"),
      recycledBlocks: meta ? meta.blocks.length : null,
      coreSources: count("sources"),
      sourceRows: sources.value?.rows ?? null,
      sourceFiles: sources.value?.files ?? null,
    };
  });

  const composition = computed<CompositionItem[] | null>(() => {
    const list = samples.value;
    if (!list) return null;
    const total = list.length;
    return typeKeys.map((type) => {
      const own = list.filter((s) => s.sample_type === type);
      let range: string | null = null;
      if (type === "blend") {
        const r = span(own.map((s) => s.sw_proportion_pct));
        if (r) range = `针叶木 ${number(r.min)}%–${number(r.max)}%`;
      } else {
        const r = span(
          own.map((s) => (type === "softwood" ? s.sw_beating_revolutions : s.hw_beating_revolutions)),
        );
        if (r) range = `打浆 ${number(r.min)}–${number(r.max)} r`;
      }
      return {
        type,
        label: typeNames[type],
        n: own.length,
        share: total ? (own.length / total) * 100 : 0,
        range,
      };
    });
  });

  onBeforeUnmount(() => controller?.abort());
  void load();

  return { stats, composition, coreStatus, sourceStatus, message, reload: load };
}
