import type { CampaignStatus } from "./campaign.types";

export function isCampaignActive(status: string | null | undefined): boolean {
  const normalized = String(status || "").toLowerCase() as CampaignStatus;
  return normalized === "queued" || normalized === "running" || normalized === "scheduled";
}
