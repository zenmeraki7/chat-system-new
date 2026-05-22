import { api } from "../../api";

export function getConversations(query: string) {
  return api<unknown>(`/conversations?${query}`);
}
