import type { ApiError } from "./types";

/** POST JSON to the API. Rejects with the server's `{error}` body on a non-2xx response. */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body ?? {}),
  });
  const data = (await r.json().catch(() => ({}))) as T & ApiError;
  if (!r.ok) throw data;
  return data;
}

export function errorMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null && "error" in err) {
    const m = (err as ApiError).error;
    if (typeof m === "string" && m) return m;
  }
  return fallback;
}
