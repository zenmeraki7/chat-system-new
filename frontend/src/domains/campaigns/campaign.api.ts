import { api } from "../../api";

export type Campaign = {
  campaign_id: string;
  name: string;
  status: string;
  type: string;
  phone_number_id: string;
  template_id?: string | null;
  total_recipients?: number;
  eligible_recipients?: number;
  delivered_count?: number;
  failed_count?: number;
  read_count?: number;
  replied_count?: number;
  actual_cost?: number | null;
};

export function getCampaigns(query: string) {
  return api<unknown>(`/campaigns?${query}`);
}
