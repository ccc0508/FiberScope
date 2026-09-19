export type SampleType = "softwood" | "hardwood" | "blend";
export interface Sample {
  sample_id: number;
  canonical_code: string;
  sample_type: SampleType;
  display_name: string;
  notes: string | null;
  component_count: number;
  sw_proportion_pct: number;
  hw_proportion_pct: number;
  sw_beating_revolutions: number | null;
  hw_beating_revolutions: number | null;
  sw_beating_degree_sr: number | null;
  hw_beating_degree_sr: number | null;
}
export interface ListResult<T> {
  data: T[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  meta: { view: string; notes: string[] };
}
export interface Metadata {
  indicators: {
    key: string;
    name: string;
    unit: string | null;
    group: string;
    scope: string[];
    unit_status: string;
  }[];
  counts: Record<string, number>;
  blocks: { block_code: string }[];
  notes: string[];
  sample_types: Record<SampleType, string>;
}
export type Lineage = {
  source_id: number;
  file_name: string;
  sheet_name: string;
  source_row: number;
  usage_type: string;
  canonical_code: string | null;
};
export type Query = Record<string, string | number | undefined>;

export class ApiError extends Error {
  constructor(
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function get<T>(
  path: string,
  query: Query = {},
  signal?: AbortSignal,
): Promise<T> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const timeout = new AbortController();
  const timer = window.setTimeout(() => timeout.abort(), 15000);
  const abort = () => timeout.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) timeout.abort();
  try {
    const response = await fetch(`/api/v1/${path}?${params}`, {
      signal: timeout.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok)
      throw new ApiError(
        body?.error?.message ?? "数据服务暂时不可用，请稍后重试。",
        body?.error?.request_id,
      );
    if (!body) throw new ApiError("数据响应无法读取，请重试。");
    return body as T;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof ApiError) throw error;
    throw new ApiError("暂时无法连接数据服务，请检查连接后重试。");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export const typeNames: Record<SampleType, string> = {
  softwood: "针叶木浆",
  hardwood: "阔叶木浆",
  blend: "针阔复配",
};
export const typeKeys: SampleType[] = ["softwood", "hardwood", "blend"];
export function number(value: number | null | undefined, digits = 0) {
  return value == null
    ? "—"
    : value.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
}
