export interface Measurement {
  record_id: string;
  raw_material: string;
  metric: string;
  measurement_state: string;
  raw_value: string;
  value: number;
  raw_unit: string;
  source_bbox_pt: number[];
  source_pdf_page: number;
  source_table: string;
  label_word_ids: string[];
  header_word_ids: string[];
  unit_word_ids: string[];
  state_word_ids: string[];
  context_word_ids?: string[];
  source_quote?: string;
  source_kind?: "table" | "text";
  source_value_text?: string;
  value_qualifier?: string;
}
export interface ReviewData {
  raw_material: string;
  metric: string;
  measurement_state: string;
  raw_value: string;
  raw_unit: string;
  experiment_condition: string;
  condition_source: string;
}
export interface Review {
  revision: number;
  status: "pending" | "confirmed" | "rejected";
  suitability: "unassessed" | "suitable" | "unsuitable";
  note: string;
  current: ReviewData;
  updated_at: string | null;
  approved_for_training: boolean;
}
export interface ExtractionTask {
  id: string;
  status: "processing" | "completed" | "failed" | "interrupted";
  created_at: string;
  message: string | null;
  has_reviewable_result?: boolean;
  can_review?: boolean;
  source: { filename: string; page: number | null; table: string; mode?: "document" | "table" };
  progress?: { page: number; page_count: number; stage: string; measurement_count: number };
  reviews?: Record<string, Review>;
  review_summary?: {
    total: number;
    confirmed: number;
    rejected: number;
    pending: number;
    suitable: number;
  };
  snapshot?: {
    evidence?: {
      page_count?: number;
      width_pt?: number;
      height_pt?: number;
      words?: { id: string; text: string; bbox: number[] }[];
      pages?: Record<string, {width_pt: number; height_pt: number; words: {id: string; text: string; bbox: number[]}[]}>;
    };
    result?: {
      measurements: Measurement[]; warnings: string[]; coverage_complete?: boolean;
      discovered_tables?: {page: number; table: string; reason: string; status: string; measurement_count?: number}[];
      coverage?: {page: number; status: string; reason?: string; notes: string[]}[];
    };
  } | null;
}
export const metricNames: Record<string, string> = {
  fiber_length: "纤维长度",
  fiber_width: "纤维宽度",
  wall_thickness: "细胞壁厚度",
  slender_ratio: "长宽比",
  runkel_ratio: "Runkel 比",
  flexibility_coefficient: "柔性系数",
  tensile_index: "抗张指数",
  burst_index: "耐破指数",
  tear_index: "撕裂指数",
  fines: "细小纤维",
  curl_index: "卷曲指数",
  kink_index: "扭结指数",
  coarseness: "粗度",
  fibrillation: "纤维化",
  cooking_temperature: "蒸煮温度",
  cooking_time: "蒸煮时间",
  active_alkali: "有效碱用量",
  pulp_yield: "纸浆得率",
  beating_degree: "打浆度",
  refining_time: "打浆时间",
  refining_revolutions: "打浆转数",
  basis_weight: "定量",
  brightness: "白度",
  kappa_number: "卡伯值",
  klason_lignin: "Klason 木质素",
  acid_soluble_lignin: "酸溶木质素",
  holocellulose: "综纤维素",
  alpha_cellulose: "α-纤维素",
};
export const measurementStates: Record<string, string> = {
  raw_material: "原料形态",
  unrefined: "未打浆",
  refined: "打浆后",
  unspecified: "未说明",
};
export const taskStates = {
  processing: "提取中",
  completed: "提取完成",
  failed: "提取失败",
  interrupted: "处理中断",
};
export const reviewStates = {
  pending: "待核对",
  confirmed: "已确认",
  rejected: "已驳回",
};
export const scanReasonNames: Record<string,string> = {
  provider_error: "模型调用失败",
  model_balance_exhausted: "模型服务余额不足",
  model_rate_limited: "模型服务限流",
  model_auth_failed: "模型服务认证失败",
  validation_failed: "结果未通过原文证据校验",
  text_unavailable: "页面没有可提取文字",
  page_too_complex: "页面文字超过处理上限",
  budget_exhausted: "处理时间预算已用完",
  discovery_limit: "候选数量达到单页上限",
};
export function currentReview(task: ExtractionTask, r: Measurement): Review {
  return (
    task.reviews?.[r.record_id] ?? {
      revision: 0,
      status: "pending",
      suitability: "unassessed",
      note: "",
      updated_at: null,
      approved_for_training: false,
      current: {
        raw_material: r.raw_material,
        metric: r.metric,
        measurement_state: r.measurement_state,
        raw_value: r.raw_value,
        raw_unit: r.raw_unit,
        experiment_condition: "",
        condition_source: "",
      },
    }
  );
}
export function groups(records: Measurement[]) {
  const result = new Map<string, Measurement[]>();
  for (const r of records) {
    const group = result.get(r.raw_material) ?? [];
    group.push(r);
    result.set(r.raw_material, group);
  }
  return [...result].map(([name, records]) => ({ name, records }));
}
export async function extractionRequest<T>(
  path = "",
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1/literature/extractions${path}`, {
    credentials: "same-origin",
    ...options,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      body?.error?.message ?? body?.detail ?? "文献数据服务暂时不可用。",
    );
  if (!body) throw new Error("无法读取服务响应，请刷新任务列表重试。");
  return body as T;
}
