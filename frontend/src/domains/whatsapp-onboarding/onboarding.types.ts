export type WhatsAppOnboardingStatus = {
  onboarding_state: string;
  business_id?: string | null;
  waba_id?: string | null;
  phone_number_id?: string | null;
  display_phone_number?: string | null;
  verified_name?: string | null;
  display_name_status?: string | null;
  business_verification_status?: string | null;
  phone_number_quality_rating?: string | null;
  messaging_limit_tier?: string | null;
  cloud_api_registered?: boolean;
  two_step_verification_required?: boolean;
  webhook_subscribed?: boolean;
  test_message_passed?: boolean;
  blocking_reasons?: Array<{ code: string; title: string; recovery_action: string }>;
  permissions_granted?: string[];
  token_expires_at?: string | null;
  token_valid?: boolean;
};

export type WhatsAppSetupDiagnostics = {
  template_sync_status: string;
  template_total_count: number;
  template_approved_count: number;
  template_pending_count: number;
  template_last_synced_at?: string | null;
  webhook_subscription_status: string;
  webhook_last_received_at?: string | null;
  webhook_heartbeat_status: string;
  webhook_heartbeat_lag_seconds?: number | null;
};
