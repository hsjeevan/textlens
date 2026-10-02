import type { Run, UploadResponse } from "./types";

// Same-origin prefix; Vite (dev) and nginx (container) proxy it to the API.
export const API_BASE = "/api";

export class ApiError extends Error {}

async function request<T>(path: string, init: RequestInit, timeoutMs: number, ok = 200): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch {
    throw new ApiError("Couldn't reach the API.");
  }
  if (resp.status !== ok) {
    let detail: unknown;
    try {
      detail = (await resp.json()).detail;
    } catch {
      detail = undefined;
    }
    // The proxy answers 502/504 itself when the API is down.
    if (resp.status === 502 || resp.status === 504) throw new ApiError("Couldn't reach the API.");
    throw new ApiError(typeof detail === "string" ? detail : `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export function uploadFile(file: File, force = false): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", new File([file], file.name, { type: "text/plain" }));
  return request(`/upload${force ? "?force=true" : ""}`, { method: "POST", body }, 30_000, 202);
}

export function fetchInsights(runId: string): Promise<Run> {
  return request(`/insights/${encodeURIComponent(runId)}`, {}, 10_000);
}

export async function clearCache(): Promise<number> {
  const { deleted } = await request<{ deleted: number }>("/cache", { method: "DELETE" }, 30_000);
  return deleted;
}

export async function apiOnline(): Promise<boolean> {
  try {
    return (await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2_000) })).ok;
  } catch {
    return false;
  }
}
