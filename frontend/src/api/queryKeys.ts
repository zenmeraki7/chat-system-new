export const queryKeys = {
  authMe: ["auth", "me"] as const,
  tenantContext: ["tenant", "context"] as const,
  whatsappStatus: ["whatsapp", "onboarding", "status"] as const,
  campaigns: (filters?: Record<string, unknown>) => ["campaigns", filters || {}] as const,
  contacts: (filters?: Record<string, unknown>) => ["contacts", filters || {}] as const,
  billingLedger: (cursor?: string) => ["billing", "ledger", cursor || ""] as const,
};
