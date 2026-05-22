export type WhatsAppReadinessState =
  | "DETECTED"
  | "REGISTER_NUMBER"
  | "VERIFY_DISPLAY_NAME"
  | "SUBSCRIBE_WEBHOOKS"
  | "SEND_TEST_MESSAGE"
  | "WAIT_DELIVERY_WEBHOOK"
  | "READY";

export function computeOnboardingState(input: {
  hasPhone: boolean;
  cloudApiRegistered: boolean;
  displayNameStatus?: string | null;
  webhookSubscribed: boolean;
  messageTestPassed: boolean;
  webhookHealthy: boolean;
}): WhatsAppReadinessState {
  if (!input.hasPhone) return "DETECTED";
  if (!input.cloudApiRegistered) return "REGISTER_NUMBER";
  if (String(input.displayNameStatus || "").toUpperCase() !== "APPROVED") return "VERIFY_DISPLAY_NAME";
  if (!input.webhookSubscribed) return "SUBSCRIBE_WEBHOOKS";
  if (!input.messageTestPassed) return "SEND_TEST_MESSAGE";
  if (!input.webhookHealthy) return "WAIT_DELIVERY_WEBHOOK";
  return "READY";
}
