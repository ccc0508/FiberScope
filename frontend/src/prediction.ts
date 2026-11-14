import { ApiError } from "./api";
import { apiPath } from "./urls";

export type Species = "softwood" | "hardwood";
export type Mode = "fiber" | "degree";
export interface Feature {
  key: string;
  name: string;
  unit: string;
  range: [number, number];
  required: boolean;
}
export interface ModelSpecies {
  key: Species;
  name: string;
  sample_count: number;
  degree_range: [number, number];
  features: Feature[];
  example: { degree: number; features: Record<string, number> };
}
export interface PredictionMetadata {
  model_version: string;
  species: ModelSpecies[];
  notes: string[];
}
export interface PaperResult {
  key: string;
  name: string;
  value: number;
  unit: string | null;
  unit_status: string;
  nested_r2: number;
  model_reliable: boolean;
  in_range: boolean;
  reference_only: boolean;
  unreliable_inputs: string[];
  notes: string[];
  status: string;
}
export interface FiberResult {
  key: string;
  name: string;
  unit: string;
  value: number;
  cv_r2: number;
  model_reliable: boolean;
  in_range: boolean;
}
export interface PredictionResult {
  model_version: string;
  mode: Mode;
  species: Species;
  species_name: string;
  sample_count: number;
  input: { degree?: number; features?: Record<string, number> };
  paper: PaperResult[];
  fiber: FiberResult[];
  warnings: string[];
}

export type InputValue = number | string | undefined;

/** Shared page validation, including all missing fields rather than only the first. */
export function validatePredictionInput(mode: Mode, fields: Feature[], degree: InputValue, values: Record<string, InputValue>): Record<string, string> {
  const errors: Record<string, string> = {};
  const finite = (value: InputValue): value is number => typeof value === "number" && Number.isFinite(value);
  if (mode === "degree") {
    if (!finite(degree) || degree <= 0 || degree > 100)
      errors.degree = "请填写大于0、不超过100的打浆度（°SR）。";
    return errors;
  }
  for (const field of fields) {
    const value = values[field.key];
    const empty = value === undefined || value === "";
    if (empty && !field.required) continue;
    if (!finite(value)) errors[field.key] = `请填写有效的${field.name}。`;
    else if (value < 0) errors[field.key] = `${field.name}不能小于0。`;
    else if (field.unit === "%" && value > 100) errors[field.key] = `${field.name}需在0–100%之间。`;
    else if (field.unit === "°" && value > 180) errors[field.key] = `${field.name}需在0–180°之间。`;
  }
  return errors;
}

/** A display threshold, not a claimed physical limit. Export retains the raw value. */
export function predictionNumber(value: number, digits = 3): string {
  if (!Number.isFinite(value)) return "数值不可用";
  const magnitude = Math.abs(value);
  if (magnitude >= 1e9 || (magnitude > 0 && magnitude < 10 ** -digits))
    return value.toExponential(3);
  return value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export async function predict(
  mode: Mode,
  input: { species: Species; degree: number } | { species: Species; features: Record<string, number> },
  signal: AbortSignal,
): Promise<PredictionResult> {
  const timeout = new AbortController();
  const timer = window.setTimeout(() => timeout.abort(), 15000);
  const abort = () => timeout.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) timeout.abort();
  try {
    const response = await fetch(apiPath(`prediction/${mode}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal: timeout.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok)
      throw new ApiError(body?.error?.message ?? "预测失败，请检查输入后重试。", body?.error?.request_id);
    if (!body) throw new ApiError("预测结果无法读取，请重试。");
    return body as PredictionResult;
  } catch (error) {
    if (signal.aborted || error instanceof ApiError) throw error;
    throw new ApiError("暂时无法连接预测服务，请稍后重试。");
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

/** Keep inputs and caveats with the exported values so references cannot look like measurements. */
export function predictionCsv(result: PredictionResult): string {
  const rows: (string | number)[][] = [[
    "树种", "方式", "模型版本", "输入参数", "类别", "指标", "预测值", "单位", "状态", "单步R²", "说明",
  ]];
  const prefix = [result.species_name, result.mode === "degree" ? "打浆度整链预测" : "实测纤维预测",
    result.model_version, JSON.stringify(result.input)];
  for (const row of result.paper) {
    rows.push([...prefix, "纸张性能", row.name, row.value, row.unit ?? "单位未确认", row.status,
      row.nested_r2, [...result.warnings, ...row.notes,
        ...(row.unit_status === "tentative" ? ["单位暂定"] : [])].join(" ")]);
  }
  for (const row of result.fiber) {
    rows.push([...prefix, "纤维指标", row.name, row.value, row.unit,
      !row.in_range ? "外推参考" : row.model_reliable ? "单步可参考" : "仅供参考",
      row.cv_r2, result.warnings.join(" ")]);
  }
  return "\uFEFF" + rows.map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(",")).join("\r\n");
}
