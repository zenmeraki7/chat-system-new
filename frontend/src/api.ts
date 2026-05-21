const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const API_BASE = `${API_ORIGIN}/api/v1`;

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

function resolveAuthToken(): string | null {
  const keys = ["access_token", "token", "auth_token", "jwt", "bearer_token"];
  for (const key of keys) {
    const local = localStorage.getItem(key);
    if (local && local.trim()) return local.trim();
    const session = sessionStorage.getItem(key);
    if (session && session.trim()) return session.trim();
  }
  const envToken = import.meta.env.VITE_DEV_BEARER_TOKEN as string | undefined;
  if (envToken && envToken.trim()) return envToken.trim();
  return null;
}

export async function api<T>(path: string, method: HttpMethod = "GET", body?: unknown): Promise<T> {
  const token = resolveAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  return (await res.json()) as T;
}

export { API_ORIGIN, API_BASE };
