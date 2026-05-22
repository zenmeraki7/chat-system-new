import { api } from "../../api";

export function getBillingOverview() {
  return api<unknown>("/analytics/overview");
}
