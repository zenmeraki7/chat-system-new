export const frontendBackendContracts = {
  auth: ["GET /auth/me"],
  tenant: ["GET /tenant/context"],
  whatsapp: [
    "GET /whatsapp/onboarding/status",
    "POST /whatsapp/embedded-signup/session",
    "POST /whatsapp/connect",
    "POST /whatsapp/phone-numbers/:id/register",
    "POST /whatsapp/phone-numbers/:id/test-message",
    "GET /whatsapp/phone-numbers/:id/readiness",
  ],
  campaigns: [
    "GET /campaigns?cursor=&limit=",
    "POST /campaigns",
    "POST /campaigns/:id/freeze-recipients",
    "POST /campaigns/:id/preview",
    "POST /campaigns/:id/confirm-launch",
    "POST /campaigns/:id/launch",
    "POST /campaigns/:id/pause",
    "POST /campaigns/:id/cancel",
  ],
  contacts: [
    "GET /contacts/crm/records?cursor=&limit=&filters...",
    "POST /contacts/imports",
    "GET /contacts/imports/:id",
  ],
  inbox: [
    "POST /conversations/:id/messages",
    "POST /conversations/:id/internal-notes",
    "PATCH /conversations/:id/assignment",
  ],
  billing: ["GET /billing/wallet", "GET /billing/ledger"],
  dashboard: ["GET /dashboard/command-center"],
} as const;
