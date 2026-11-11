import { apiPath } from "./urls";

export interface CitationImage {
  id: string;
  label: string;
  page: number;
  sha256: string;
  width: number;
  height: number;
}

export interface Citation {
  kind?: "source_text" | "source_image" | "calculation" | "experiment_query";
  ref: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  chunk_id: string;
  excerpt: string;
  visual_assets?: CitationImage[];
  source_chunks?: {
    chunk_id: string;
    chunk_index: number;
    page_start: number;
    page_end: number;
    text: string;
    kind?: string;
  }[];
}
export interface Answer {
  status: "answered" | "refused";
  answer: string;
  citations: Citation[];
  latency_ms: number;
  review_summary?: {
    status: "completed" | "unresolved" | "incomplete" | "not_required";
    notice: string;
    unresolved: { id: string; requirement: string; reason: string }[];
    supplement_rounds: number;
    review_rounds: number;
  };
}
export interface HistoryItem {
  id: string;
  question: string;
  status: "processing" | "answered" | "refused" | "failed" | "interrupted";
  created_at: string;
  completed_at: string | null;
  latency_ms: number | null;
  reason_code: string | null;
}
export interface HistoryRecord extends HistoryItem {
  result: Answer | null;
}
export const stateNames: Record<HistoryItem["status"], string> = {
  processing: "处理中", answered: "已回答", refused: "未能可靠回答", failed: "处理失败", interrupted: "处理中断",
};
export const timeLabel = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });

export async function literatureRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiPath(`literature/${path}`), {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.error?.message ?? result?.detail ?? "问答记录服务暂不可用，请稍后重试。");
  if (!result) throw new Error("问答记录响应无法读取，请重试。");
  return result as T;
}
