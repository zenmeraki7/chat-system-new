import { ApiError } from "./errors";

export const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
export const API_BASE = `${API_ORIGIN}/api/v1`;

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

type RequestOptions = {
  headers?: Record<string, string>;
};

function resolveAuthToken(): string | null {
  const keys = ["access_token", "token", "auth_token", "jwt", "bearer_token"];
  for (const key of keys) {
    const session = sessionStorage.getItem(key);
    if (session && session.trim()) return session.trim();
    if (import.meta.env.DEV) {
      const local = localStorage.getItem(key);
      if (local && local.trim()) return local.trim();
    }
  }
  return null;
}

function buildMutationSafetyHeaders(method: HttpMethod): Record<string, string> {
  if (method === "GET") return {};
  const headers: Record<string, string> = {};
  const csrfToken = sessionStorage.getItem("csrf_token");
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  headers["Idempotency-Key"] = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return headers;
}

export async function apiClient<T>(path: string, method: HttpMethod = "GET", body?: unknown, options?: RequestOptions): Promise<T> {
  const token = resolveAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...buildMutationSafetyHeaders(method),
    ...(options?.headers || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const raw = await res.text();
    let code: string | undefined;
    let userMessage: string | undefined;
    let requestId: string | undefined;
    try {
      const parsed = JSON.parse(raw);
      code = typeof parsed?.code === "string" ? parsed.code : undefined;
      userMessage = typeof parsed?.user_message === "string" ? parsed.user_message : undefined;
      requestId = typeof parsed?.request_id === "string" ? parsed.request_id : undefined;
    } catch {
      // Ignore JSON parse failures for plain-text error payloads.
    }
    throw new ApiError(res.status, raw, { code, userMessage, requestId });
  }
  return (await res.json()) as T;
}
