export const ONBOARDING_SEQUENCE = [
  "EMBEDDED_SIGNUP_STARTED",
  "CODE_RECEIVED",
  "CODE_EXCHANGED",
  "WABA_LINKED",
  "PHONE_NUMBER_DETECTED",
  "PHONE_NUMBER_PENDING_VERIFICATION",
  "PHONE_NUMBER_VERIFIED",
  "CLOUD_API_REGISTERED",
  "WEBHOOK_SUBSCRIBED",
  "MESSAGE_TEST_PASSED",
  "ONBOARDING_COMPLETE",
] as const;

export const ONBOARDING_FAILURE_STATES = [
  "DISPLAY_NAME_REJECTED",
  "BUSINESS_VERIFICATION_PENDING",
  "TWO_STEP_PIN_REQUIRED",
  "PHONE_NUMBER_CONFLICT",
  "TOKEN_EXPIRED",
  "PERMISSION_REVOKED",
  "WEBHOOK_FAILED",
  "REAUTH_REQUIRED",
  "ONBOARDING_FAILED",
  "MESSAGE_TEST_REQUIRED",
] as const;

export type OnboardingStage = (typeof ONBOARDING_SEQUENCE)[number];
export type OnboardingFailureStage = (typeof ONBOARDING_FAILURE_STATES)[number];
export type OnboardingState = OnboardingStage | OnboardingFailureStage;

export function isOnboardingComplete(state?: string | null): boolean {
  return String(state || "").toUpperCase() === "ONBOARDING_COMPLETE";
}
