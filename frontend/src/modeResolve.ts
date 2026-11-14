/**
 * Pure helpers for the two visual modes (no DOM access, so they can be unit-tested).
 * index.html repeats this resolution order in a tiny inline script so the first paint
 * already carries the right data-mode; keep both in sync.
 */
export type Mode = "polarized" | "garden";
export const MODES: readonly Mode[] = ["polarized", "garden"];
export const MODE_STORAGE_KEY = "fiberscope-mode";

export const MODE_THEME: Record<Mode, { themeColor: string; colorScheme: "dark" | "light" }> = {
  polarized: { themeColor: "#06070A", colorScheme: "dark" },
  garden: { themeColor: "#FBF4F6", colorScheme: "light" },
};

export function isMode(value: unknown): value is Mode {
  return value === "polarized" || value === "garden";
}

/** Resolution order: ?mode= query → stored choice → colour-scheme preference. */
export function resolveMode(
  queryValue: unknown,
  storedValue: unknown,
  prefersDark: boolean,
): { mode: Mode; source: "query" | "storage" | "system" } {
  if (isMode(queryValue)) return { mode: queryValue, source: "query" };
  if (isMode(storedValue)) return { mode: storedValue, source: "storage" };
  return { mode: prefersDark ? "polarized" : "garden", source: "system" };
}
