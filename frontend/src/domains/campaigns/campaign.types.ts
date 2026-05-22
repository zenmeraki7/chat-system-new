export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export const ACTIVE_CAMPAIGN_STATUSES: CampaignStatus[] = ["queued", "running"];
