/** Keep requests, downloads and assets on the configured application mount path. */
export function appPath(path: string, base = import.meta.env?.BASE_URL ?? "/"): string {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

export function apiPath(path: string, base?: string): string {
  return appPath(`api/v1/${path.replace(/^\/+/, "")}`, base);
}
