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

export type EmbeddedSignupConfigResponse = {
  app_id: string;
  config_id: string;
  oauth_dialog_url: string;
  required_scopes: string[];
  expected_origin: string;
};

export type WhatsAppOperationalReadiness = {
  embedded_signup_completed: boolean;
  code_exchanged: boolean;
  token_valid: boolean;
  required_scopes_granted: boolean;
  business_fetch_ok: boolean;
  waba_fetch_ok: boolean;
  phone_fetch_ok: boolean;
  phone_belongs_to_waba: boolean;
  waba_subscribed_to_app: boolean;
  messages_webhook_enabled: boolean;
  webhook_last_received_at?: string | null;
  phone_registered: boolean;
  can_send_test_message: boolean;
  can_receive_webhook: boolean;
  templates_fetch_ok: boolean;
  final_status: 'not_started' | 'pending' | 'action_required' | 'operational';
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

export async function getEmbeddedSignupConfig(): Promise<EmbeddedSignupConfigResponse> {
  const { data } = await apiClient.get<EmbeddedSignupConfigResponse>('/whatsapp/embedded-signup/config');
  return data;
}

export async function getWhatsAppOperationalReadiness(): Promise<WhatsAppOperationalReadiness> {
  const { data } = await apiClient.get<WhatsAppOperationalReadiness>('/whatsapp/operational-readiness');
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
