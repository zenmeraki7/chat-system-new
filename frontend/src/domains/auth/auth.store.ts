const TOKEN_KEYS = ["access_token", "token", "auth_token", "jwt", "bearer_token"] as const;

export function getStoredToken(): string | null {
  for (const key of TOKEN_KEYS) {
    const sessionValue = sessionStorage.getItem(key);
    if (sessionValue) return sessionValue;
    if (import.meta.env.DEV) {
      const localValue = localStorage.getItem(key);
      if (localValue) return localValue;
    }
  }
  return null;
}

export function clearAuthStorage() {
  ["access_token", "token", "auth_token", "jwt", "bearer_token", "current_user_id", "auth_user_id", "auth_business_name", "auth_business_id"].forEach((k) => {
    localStorage.removeItem(k);
    sessionStorage.removeItem(k);
  });
}

