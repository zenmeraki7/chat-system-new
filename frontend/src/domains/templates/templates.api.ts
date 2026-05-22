import { api } from "../../api";

export function getTemplates(query: string) {
  return api<unknown>(`/templates?${query}`);
}
