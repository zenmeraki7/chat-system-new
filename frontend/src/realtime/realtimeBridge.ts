import { API_BASE } from "../api";
import { appStore } from "../state/appStore";

function authToken(): string | null {
  for (const key of ["access_token", "token", "auth_token", "jwt", "bearer_token"]) {
    const value = localStorage.getItem(key) || sessionStorage.getItem(key);
    if (value?.trim()) return value.trim();
  }
  return null;
}

function ingestEvent(eventName: string, raw: string) {
  if (!eventName || !raw) return;
  const payload = JSON.parse(raw || "{}");
  if (eventName === "connected") appStore.setNetwork({ realtimeConnected: true, backpressureWarning: null });
  if (eventName === "heartbeat") {
    const lagMs = payload.ts ? Math.max(0, Date.now() - new Date(payload.ts).getTime()) : 0;
    appStore.setNetwork({ realtimeConnected: true, lastEventAt: new Date().toISOString(), lagMs, backpressureWarning: lagMs > 120000 ? `Delivery updates delayed by ${Math.round(lagMs / 60000)}m` : null });
  }
  if (eventName === "message_status") appStore.patchEntity("messages", String(payload.message_id || payload.id), { status: payload.status, provider_message_id: payload.provider_message_id });
  if (eventName === "conversation_update") appStore.patchEntity("conversations", String(payload.conversation_id), { status: payload.new_status, updated_at: payload.created_at });
  if (eventName === "campaign_progress") appStore.patchEntity("campaigns", String(payload.campaign_id), payload);
  if (eventName === "webhook_health_alert") appStore.setNetwork({ backpressureWarning: "Webhook processing failures detected." });
}

export function startRealtimeBridge() {
  const token = authToken();
  if (!token || typeof ReadableStream === "undefined") return () => undefined;
  const controller = new AbortController();
  let retryTimer: number | undefined;
  let closed = false;

  const connect = async () => {
    try {
      const response = await fetch(`${API_BASE}/realtime/events?interval_ms=3000`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error(`Realtime stream failed: ${response.status}`);
      appStore.setNetwork({ realtimeConnected: true, backpressureWarning: null });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          const eventLine = chunk.split("\n").find((line) => line.startsWith("event:"));
          const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
          ingestEvent(eventLine?.slice(6).trim() || "message", dataLine?.slice(5).trim() || "{}");
        }
      }
    } catch (error) {
      if (closed || controller.signal.aborted) return;
      appStore.setNetwork({ realtimeConnected: false, backpressureWarning: "Realtime stream disconnected. Reconnecting..." });
      retryTimer = window.setTimeout(connect, 3000);
    }
  };

  connect();
  return () => {
    closed = true;
    if (retryTimer) window.clearTimeout(retryTimer);
    controller.abort();
  };
}
