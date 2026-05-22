import { API_ORIGIN } from "../../api";
import { isApiError } from "../../api/errors";

type SafeLogOptions = {
  exposeToConsole?: boolean;
  context?: Record<string, unknown>;
};

const REDACT_KEYS = ["phone_e164", "wa_id", "access_token", "authorization", "email", "download_url", "waba_id", "phone_number_id", "business_id"];

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== "object") return value;
  const out: Record<string, unknown> = {};
  for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
    out[key] = REDACT_KEYS.includes(key.toLowerCase()) ? "[REDACTED]" : redact(inner);
  }
  return out;
}

export function safeLogClientError(event: string, error: unknown, options?: SafeLogOptions) {
  if (!options?.exposeToConsole) return;
  const payload = {
    event,
    message: error instanceof Error ? error.message : String(error),
    context: redact(options?.context || {}),
  };
  // eslint-disable-next-line no-console
  console.error(payload);
}

export function toUserErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.userMessage && error.requestId) return `${error.userMessage} (Request ID: ${error.requestId})`;
    if (error.userMessage) return error.userMessage;
  }
  return "Something went wrong. Contact support if this continues.";
}

export function safeDownloadUrl(path?: string | null): string | null {
  if (!path) return null;
  if (!path.startsWith("/exports/")) return null;
  if (path.includes("..")) return null;
  return `${API_ORIGIN}${path}`;
}

