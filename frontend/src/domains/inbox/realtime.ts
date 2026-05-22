export function buildInboxRealtimeChannel(businessId: string) {
  return `business:${businessId}:inbox`;
}
