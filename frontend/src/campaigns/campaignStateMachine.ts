export type CampaignState = "DRAFT" | "FROZEN" | "PREVIEWED" | "CONFIRMED" | "LAUNCHED" | "PAUSED" | "CANCELLED";

export function canLaunch(state: CampaignState) {
  return state === "CONFIRMED";
}
