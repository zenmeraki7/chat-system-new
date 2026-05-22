import { api } from "../../api";

export function getContacts(query: string) {
  return api<unknown>(`/contacts/crm/records?${query}`);
}
