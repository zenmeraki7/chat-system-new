import { api } from "../../api";
import type { WhatsAppOnboardingStatus, WhatsAppSetupDiagnostics } from "./onboarding.types";

export function getOnboardingStatus() {
  return api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status");
}

export function getSetupDiagnostics() {
  return api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics");
}
