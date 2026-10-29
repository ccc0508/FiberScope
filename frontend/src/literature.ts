import { apiPath } from "./urls";

export interface Citation {
  ref: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  chunk_id: string;
  excerpt: string;
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
}
export interface Feedback {
  rating: "helpful" | "inaccurate";
  tags: string[];
  note: string;
  updated_at?: string;
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
  can_feedback?: boolean;
  result: Answer | null;
  feedback: Feedback | null;
}
export const stateNames: Record<HistoryItem["status"], string> = {
  processing: "处理中", answered: "已回答", refused: "未能可靠回答", failed: "处理失败", interrupted: "处理中断",
};
export const feedbackTags = [
  { key: "numeric_error", label: "数值错误" },
  { key: "unsupported_citation", label: "引用不支持" },
  { key: "irrelevant", label: "答非所问" },
  { key: "incomplete", label: "遗漏内容" },
  { key: "wrong_refusal", label: "不该拒答" },
];
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
