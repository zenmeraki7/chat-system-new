export function loadTablePrefs(key: string) {
  try {
    return JSON.parse(localStorage.getItem(`table_prefs:${key}`) || "{}") as { sortBy?: string; sortDir?: "asc" | "desc"; pageSize?: number };
  } catch {
    return {};
  }
}

export function saveTablePrefs(key: string, prefs: { sortBy?: string; sortDir?: "asc" | "desc"; pageSize?: number }) {
  localStorage.setItem(`table_prefs:${key}`, JSON.stringify(prefs));
}
