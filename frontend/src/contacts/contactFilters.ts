export type ContactFilterInput = {
  opt_in_status?: string;
  suppression_status?: string;
  tag?: string;
  last_inbound_after?: string;
};

export function buildContactFilters(input: ContactFilterInput) {
  return {
    opt_in_status: input.opt_in_status || undefined,
    suppression_status: input.suppression_status || undefined,
    tag: input.tag || undefined,
    last_inbound_after: input.last_inbound_after || undefined,
  };
}
