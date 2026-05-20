import { apiClient } from './client';

export type EmbeddedSignupSessionResponse = {
  onboarding_session_id: string;
  state: string;
  expected_origin: string;
  expires_at: string;
};

export type WhatsAppConnectResponse = {
  status: string;
  phone_number_id?: string | null;
  verify_token?: string;
};

export async function createEmbeddedSignupSession(expectedOrigin: string, ttlMinutes = 15): Promise<EmbeddedSignupSessionResponse> {
  const { data } = await apiClient.post<EmbeddedSignupSessionResponse>('/whatsapp/embedded-signup/session', {
    expected_origin: expectedOrigin,
    ttl_minutes: ttlMinutes
  });
  return data;
}

export async function connectWhatsAppWithCodeAndState(code: string, state: string): Promise<WhatsAppConnectResponse> {
  const { data } = await apiClient.post<WhatsAppConnectResponse>('/whatsapp/connect', {
    code,
    state
  });
  return data;
}

export async function runWhatsAppEmbeddedSignupFlow(params: {
  expectedOrigin: string;
  openEmbeddedSignup: (state: string) => Promise<{ code: string; state: string }>;
  ttlMinutes?: number;
}): Promise<WhatsAppConnectResponse> {
  const session = await createEmbeddedSignupSession(params.expectedOrigin, params.ttlMinutes ?? 15);
  const result = await params.openEmbeddedSignup(session.state);
  return connectWhatsAppWithCodeAndState(result.code, result.state);
}

