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

/* ---------------------------------------------------------------- answer text */
/** One inline run of an answer line: plain text, **bold**, `code` or a [n] citation token. */
export interface AnswerPart {
  text: string;
  strong?: boolean;
  code?: boolean;
  /** a "[n]" token; the page decides whether it matches a citation */
  cite?: boolean;
  /** closing punctuation right after a citation ("。", "；"), kept on the same line as it */
  after?: string;
}
export interface AnswerBlock {
  /** the whole line is bold, e.g. "**1. 数据库结果**": shown as a small section lead */
  lead: boolean;
  parts: AnswerPart[];
}

const CITE_TOKEN = /(\[\d+\])/;
const citeParts = (text: string, strong?: boolean): AnswerPart[] =>
  text
    .split(CITE_TOKEN)
    .filter(Boolean)
    .map((t) => ({ text: t, ...(strong ? { strong } : {}), ...(/^\[\d+\]$/.test(t) ? { cite: true } : {}) }));

/**
 * Split an answer into lines and inline runs, without ever producing HTML: **bold** and
 * `code` become flags on text runs, which the template renders through interpolation.
 * An unmatched ** or ` stays literal text.
 */
export function answerBlocks(answer: string): AnswerBlock[] {
  return answer
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const whole = /^\s*\*\*([^*\n]+?)\*\*\s*$/.exec(line);
      if (whole) return { lead: true, parts: citeParts(whole[1]!) };
      const parts = line
        .split(/(\*\*[^*\n]+?\*\*|`[^`\n]+`)/)
        .filter(Boolean)
        .flatMap((seg): AnswerPart[] => {
          if (/^\*\*[^*\n]+?\*\*$/.test(seg)) return citeParts(seg.slice(2, -2), true);
          if (/^`[^`\n]+`$/.test(seg)) return [{ text: seg.slice(1, -1), code: true }];
          return citeParts(seg);
        });
      return { lead: false, parts: glueClosers(parts) };
    });
}
/* A citation chip is an atomic inline, so a browser may break right after it and start the
   next line with "。". Move such closing punctuation into the citation part. */
const CLOSERS = /^[。，、；：！？）】」』”’》,.;:!?)\]]+/;
function glueClosers(parts: AnswerPart[]): AnswerPart[] {
  const out: AnswerPart[] = [];
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]!;
    const next = parts[i + 1];
    if (part.cite && next && !next.cite && !next.code) {
      const match = CLOSERS.exec(next.text);
      if (match) {
        out.push({ ...part, after: match[0] });
        const rest = next.text.slice(match[0].length);
        if (rest) out.push({ ...next, text: rest });
        i++;
        continue;
      }
    }
    out.push(part);
  }
  return out;
}

/* ---------------------------------------------------------------- citations */
export type CitationKind = "db" | "paper" | "image" | "calc" | "other";
export const citationKinds: Record<CitationKind, string> = {
  db: "实验数据库查询",
  paper: "文献原文",
  image: "原文图像",
  calc: "计算结果",
  other: "引用来源",
};
export function citationKind(c: Pick<Citation, "kind" | "document_id">): CitationKind {
  switch (c.kind) {
    case "experiment_query":
      return "db";
    case "source_text":
      return "paper";
    case "source_image":
      return "image";
    case "calculation":
      return "calc";
    default:
      return c.document_id ? "paper" : "other";
  }
}
/** The citation's title without a repeated kind prefix ("实验数据库查询 · fiber.v_x" → "fiber.v_x"). */
export function citationTitle(c: Pick<Citation, "kind" | "document_id" | "filename">): string {
  const prefix = `${citationKinds[citationKind(c)]} · `;
  return c.filename.startsWith(prefix) && c.filename.length > prefix.length
    ? c.filename.slice(prefix.length)
    : c.filename;
}
/** "4" or "3–4" */
export const pageRange = (start: number, end: number) => (end !== start ? `${start}–${end}` : `${start}`);

export interface QueryField {
  name: string;
  description: string;
  unit: string | null;
}
export interface QueryExcerpt {
  sql: string | null;
  views: string[];
  columns: string[];
  rows: unknown[][];
  fields: QueryField[];
  rowCount: number | null;
  truncated: boolean;
  queriedAt: string | null;
}
/**
 * Read an experiment-database citation (a JSON snapshot of one SQL query) into its parts.
 * Returns null for anything that is not a complete query snapshot: the page then shows the
 * raw excerpt as before.
 */
export function parseQueryExcerpt(text: string): QueryExcerpt | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const o = data as Record<string, unknown>;
  if (!Array.isArray(o.columns) || !Array.isArray(o.rows)) return null;
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  const columns = o.columns.map((c) => String(c));
  const rows = o.rows.filter(Array.isArray) as unknown[][];
  const fields = (Array.isArray(o.column_metadata) ? o.column_metadata : [])
    .filter((m): m is Record<string, unknown> => !!m && typeof m === "object")
    .map((m) => ({ name: str(m.name) ?? "", description: str(m.description) ?? "", unit: str(m.unit) }))
    .filter((f) => f.name || f.description);
  const views = Array.isArray(o.views) ? o.views.map(String) : str(o.view) ? [String(o.view)] : [];
  return {
    sql: str(o.sql),
    views,
    columns,
    rows,
    fields,
    rowCount: typeof o.row_count === "number" ? o.row_count : null,
    truncated: o.truncated === true,
    queriedAt: str(o.queried_at),
  };
}
/** A query result cell as text: NULL is "—", 0 stays 0. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
/** "6.4 秒" */
export const secondsLabel = (ms: number) => `${(ms / 1000).toFixed(1)} 秒`;
