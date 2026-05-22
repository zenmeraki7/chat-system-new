import { api } from "../../api";

export type AuthLoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  memberships?: Array<{ business_id: string; business_name: string; role: string }>;
};

export type MeProfile = {
  id: string;
  business_name?: string;
  status?: string;
};

export function login(email: string, password: string) {
  return api<AuthLoginResponse>("/auth/login", "POST", { email: email.trim(), password });
}

export function getMe() {
  return api<MeProfile>("/auth/me");
}
