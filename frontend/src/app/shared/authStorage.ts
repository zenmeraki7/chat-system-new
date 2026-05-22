export function clearAuthStorage() {
  const keys = ["access_token", "token", "auth_token", "jwt", "bearer_token", "current_user_id", "auth_user_id", "auth_business_name", "auth_business_id", "auth_role", "auth_permissions"];
  keys.forEach((k) => {
    localStorage.removeItem(k);
    sessionStorage.removeItem(k);
  });
}
