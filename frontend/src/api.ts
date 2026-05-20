const API_BASE = "http://localhost:8000/api/v1";

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

export async function api<T>(path: string, method: HttpMethod = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  return (await res.json()) as T;
}

