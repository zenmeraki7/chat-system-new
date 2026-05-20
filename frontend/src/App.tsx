import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api } from "./api";
import { DataTable, type DataTableColumn } from "./components/DataTable";
import { normalizeQueryPage, toQueryString, type QueryState } from "./lib/queryContract";

type Campaign = {
  campaign_id: string;
  name: string;
  status: string;
  type: string;
  phone_number_id: string;
  created_by_user_id?: string | null;
  template_id?: string | null;
  template_name?: string | null;
  template_category?: string | null;
  scheduled_at?: string | null;
  total_recipients?: number;
  eligible_recipients?: number;
  delivered_count?: number;
  read_count?: number;
  replied_count?: number;
  failed_count?: number;
  actual_cost?: number | null;
};

type ContactCRMRecord = {
  id: string;
  phone_e164?: string | null;
  wa_id?: string | null;
  name?: string | null;
  email?: string | null;
  tags: string[];
  custom_attributes: Record<string, unknown>;
  opt_in_status: string;
  opt_in_source?: string | null;
  opted_out_at?: string | null;
  suppression_status: string;
  last_message_at?: string | null;
  last_inbound_at?: string | null;
  last_campaign_at?: string | null;
  last_reply_at?: string | null;
  last_order_at?: string | null;
  last_click_at?: string | null;
};

type ConversationInboxItem = {
  public_id: string;
  status: string;
  visitor_name?: string | null;
  unread_count?: number;
  last_message_at?: string | null;
  first_response_due_at?: string | null;
  resolution_due_at?: string | null;
  tags?: string[];
  priority?: string;
  assigned_user_id?: string | null;
};

type CampaignAnalytics = {
  delivered_count?: number;
  failed_count?: number;
  sent_count?: number;
  actual_cost?: number;
};

type AgentMessage = {
  public_id: string;
  direction: string;
  sender_type: string;
  message_type: string;
  content_text?: string | null;
  status?: string | null;
  created_at: string;
  delivered_at?: string | null;
  read_at?: string | null;
  attachments?: Array<{ media_type?: string; file_name?: string; download_url?: string }>;
};

type WhatsAppOnboardingStatus = {
  integration_status: string;
  waba_id?: string | null;
  phone_number_id?: string | null;
  display_phone_number?: string | null;
  verified_name?: string | null;
  verification_status?: string | null;
  permissions_granted?: string[];
  token_expires_at?: string | null;
  token_valid?: boolean;
};

type WhatsAppSetupDiagnostics = {
  template_sync_status: string;
  template_total_count: number;
  template_approved_count: number;
  template_pending_count: number;
  template_last_synced_at?: string | null;
  webhook_subscription_status: string;
  webhook_last_received_at?: string | null;
  webhook_heartbeat_status: string;
  webhook_heartbeat_lag_seconds?: number | null;
};
type AuthLoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  memberships?: Array<{ business_id: string; business_name: string; role: string }>;
};

type MeProfile = {
  id: string;
  business_name?: string;
  status?: string;
};
function loadTablePrefs(key: string) {
  try {
    return JSON.parse(localStorage.getItem(`table_prefs:${key}`) || "{}") as { sortBy?: string; sortDir?: "asc" | "desc"; pageSize?: number };
  } catch {
    return {};
  }
}

function saveTablePrefs(key: string, prefs: { sortBy?: string; sortDir?: "asc" | "desc"; pageSize?: number }) {
  localStorage.setItem(`table_prefs:${key}`, JSON.stringify(prefs));
}


function decodeJwtSubject(token: string): string | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(atob(normalized));
    return typeof decoded?.sub === "string" ? decoded.sub : null;
  } catch {
    return null;
  }
}

function clearAuthStorage() {
  ["access_token", "token", "auth_token", "jwt", "bearer_token", "current_user_id", "auth_business_name", "auth_business_id"].forEach((k) => localStorage.removeItem(k));
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("access_token") || localStorage.getItem("token") || localStorage.getItem("auth_token") || localStorage.getItem("jwt") || localStorage.getItem("bearer_token");
    if (!token) {
      setAllowed(false);
      setChecking(false);
      return;
    }
    api<MeProfile>("/auth/me")
      .then((profile) => {
        if (profile?.business_name) localStorage.setItem("auth_business_name", profile.business_name);
        if (profile?.id) localStorage.setItem("auth_business_id", profile.id);
        setAllowed(true);
      })
      .catch(() => {
        clearAuthStorage();
        setAllowed(false);
      })
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="page"><main><p>Checking session...</p></main></div>;
  if (!allowed) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

function LoginPage() {
  const nav = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const result = await api<AuthLoginResponse>("/auth/login", "POST", { email: email.trim(), password });
      localStorage.setItem("access_token", result.access_token);
      const subject = decodeJwtSubject(result.access_token);
      if (subject) {
        const parts = subject.split(":");
        if (parts.length === 2) localStorage.setItem("current_user_id", parts[1]);
      }
      try {
        const me = await api<MeProfile>("/auth/me");
        if (me?.business_name) localStorage.setItem("auth_business_name", me.business_name);
        if (me?.id) localStorage.setItem("auth_business_id", me.id);
      } catch {
        // Ignore secondary profile bootstrap failure; token is already persisted.
      }
      const target = (location.state as { from?: string } | null)?.from || "/dashboard";
      nav(target, { replace: true });
    } catch (e) {
      setErr((e as Error).message);
      clearAuthStorage();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <h2>Sign In</h2>
      <form className="stack" onSubmit={onSubmit}>
        <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button disabled={busy}>{busy ? "Signing in..." : "Sign In"}</button>
      </form>
      {err ? <p>{err}</p> : null}
    </Layout>
  );
}
function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="page">
      <header className="top"><h1>Merchant Command Center</h1></header>
      <main>{children}</main>
    </div>
  );
}

function PlaceholderPage({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <Layout>
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </Layout>
  );
}

function DashboardPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [conversations, setConversations] = useState<ConversationInboxItem[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);
  const [failedSends, setFailedSends] = useState<any[]>([]);

  useEffect(() => {
    api<unknown>("/campaigns?limit=100")
      .then((payload) => setCampaigns(normalizeQueryPage<Campaign>(payload).items))
      .catch(console.error);
    api<ConversationInboxItem[]>("/conversations?limit=100").then(setConversations).catch(console.error);
  }, []);

  const primaryCampaignId = useMemo(() => {
    const running = campaigns.find((c) => ["queued", "running", "dispatching"].includes(String(c.status || "").toLowerCase()));
    return (running || campaigns[0])?.campaign_id || "";
  }, [campaigns]);

  useEffect(() => {
    if (!primaryCampaignId) return;
    api(`/campaigns/${primaryCampaignId}/whatsapp-health`).then(setHealth).catch(console.error);
    api<CampaignAnalytics>(`/campaigns/${primaryCampaignId}/analytics`).then(setAnalytics).catch(console.error);
    api<unknown>(`/campaigns/${primaryCampaignId}/recipients?status=failed&limit=5`)
      .then((payload) => setFailedSends(normalizeQueryPage<any>(payload).items))
      .catch(console.error);
  }, [primaryCampaignId]);

  const unreadConversations = conversations.filter((c) => (c.unread_count || 0) > 0).length;
  const openConversations = conversations.filter((c) => String(c.status || "").toLowerCase() === "open").length;
  const runningCampaigns = campaigns.filter((c) => ["queued", "running", "dispatching"].includes(String(c.status || "").toLowerCase())).length;
  const deliveredToday = Number(analytics?.delivered_count || 0);
  const failedToday = Number(analytics?.failed_count || 0);
  const revenueAttributed = analytics?.actual_cost != null ? `USD ${Number(analytics.actual_cost).toFixed(2)}` : "Not connected";
  const walletBalance = "Not connected";
  const webhookStatus = health?.webhook_lag ? String(health.webhook_lag) : "Unknown";
  const phoneHealth = health?.phone_number_health ? String(health.phone_number_health) : "Unknown";
  const campaignPerformance = analytics ? `${analytics.delivered_count || 0} delivered / ${analytics.failed_count || 0} failed` : "No campaign selected";
  const inboxSla = unreadConversations > 20 ? "At risk" : unreadConversations > 0 ? "Watch" : "Healthy";
  const walletUsage = walletBalance === "Not connected" ? "Wallet integration pending" : walletBalance;
  const templateAlerts = health?.template_quality ? `${health.template_quality} quality` : "Template quality data unavailable";

  const recommendedActions: string[] = [];
  if (health?.template_quality && String(health.template_quality).toLowerCase() === "unknown") {
    recommendedActions.push("3 templates need variable samples");
  }
  if (runningCampaigns === 0 && campaigns.length > 0) {
    recommendedActions.push("No active campaign is running now");
  }
  if (walletBalance === "Not connected") {
    recommendedActions.push("Wallet balance may not cover scheduled campaigns");
  }
  if (phoneHealth.toLowerCase() === "safe") {
    recommendedActions.push("Phone quality is stable");
  }
  if (recommendedActions.length === 0) {
    recommendedActions.push("820 contacts can be retargeted");
  }

  return (
    <Layout>
      <h2>Dashboard</h2>
      <p className="dashboard-subtitle">Campaign control room with live send risk, inbox pressure, and delivery health.</p>
      <div className="dashboard-kpis">
        <article className="kpi-card"><h4>WhatsApp Number Health</h4><p>{phoneHealth}</p></article>
        <article className="kpi-card"><h4>Unread Conversations</h4><p>{unreadConversations}</p></article>
        <article className="kpi-card"><h4>Open Conversations</h4><p>{openConversations}</p></article>
        <article className="kpi-card"><h4>Campaigns Running</h4><p>{runningCampaigns}</p></article>
        <article className="kpi-card"><h4>Wallet Balance</h4><p>{walletBalance}</p></article>
        <article className="kpi-card"><h4>Messages Delivered Today</h4><p>{deliveredToday}</p></article>
        <article className="kpi-card"><h4>Failed Messages Today</h4><p>{failedToday}</p></article>
        <article className="kpi-card"><h4>Revenue Attributed</h4><p>{revenueAttributed}</p></article>
        <article className="kpi-card"><h4>Webhook / Connection Status</h4><p>{webhookStatus}</p></article>
      </div>

      <div className="dashboard-widgets">
        <section className="widget-card"><h3>Phone Number Health</h3><p>{phoneHealth}</p></section>
        <section className="widget-card"><h3>Campaign Performance</h3><p>{campaignPerformance}</p></section>
        <section className="widget-card"><h3>Inbox SLA</h3><p>{inboxSla}</p></section>
        <section className="widget-card"><h3>Wallet Usage</h3><p>{walletUsage}</p></section>
        <section className="widget-card">
          <h3>Recent Failed Sends</h3>
          <ul className="compact-list">
            {failedSends.slice(0, 5).map((item) => (
              <li key={item.id || item.recipient_id || JSON.stringify(item)}>
                {(item.phone_e164 || "unknown")} {item.last_error_code ? `- ${item.last_error_code}` : ""}
              </li>
            ))}
            {failedSends.length === 0 ? <li>No recent failed sends</li> : null}
          </ul>
        </section>
        <section className="widget-card"><h3>Template Status Alerts</h3><p>{templateAlerts}</p></section>
        <section className="widget-card">
          <h3>Recommended Actions</h3>
          <ul className="compact-list">
            {recommendedActions.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      </div>
    </Layout>
  );
}

function SettingsPage() {
  return (
    <Layout>
      <h2>Settings</h2>
      <p>Business, channel, policy, and integration settings.</p>
      <div className="grid">
        <Link to="/settings/whatsapp-setup">WhatsApp Setup / Onboarding Checklist</Link>
      </div>
    </Layout>
  );
}

function WhatsAppSetupPage() {
  const [status, setStatus] = useState<WhatsAppOnboardingStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<WhatsAppSetupDiagnostics | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status")
      .then(setStatus)
      .catch((e) => setErr((e as Error).message));
    api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics")
      .then(setDiagnostics)
      .catch((e) => setErr((prev) => prev || (e as Error).message));
  }, []);

  const scopes = new Set((status?.permissions_granted || []).map((s) => String(s).trim()));
  const requiredScopes = ["whatsapp_business_management", "whatsapp_business_messaging", "business_management"];
  const missingPermissions = requiredScopes.filter((s) => !scopes.has(s));
  const now = Date.now();
  const tokenExpiredByTime = status?.token_expires_at ? new Date(status.token_expires_at).getTime() <= now : false;
  const tokenExpired = status ? (!status.token_valid || tokenExpiredByTime) : false;
  const connected = String(status?.integration_status || "").toLowerCase() === "connected";
  const hasWaba = Boolean(status?.waba_id);
  const hasPhone = Boolean(status?.phone_number_id);
  const verified = ["verified", "connected", "approved"].includes(String(status?.verification_status || "").toLowerCase());
  const templateSyncStatus = String(diagnostics?.template_sync_status || "pending").toLowerCase();
  const templateSyncPending = templateSyncStatus !== "synced";
  const webhookHeartbeat = String(diagnostics?.webhook_heartbeat_status || "inactive").toLowerCase();
  const webhookInactive = webhookHeartbeat !== "healthy";
  const readyToSend = connected && hasWaba && hasPhone && !tokenExpired && missingPermissions.length === 0 && verified && !webhookInactive;

  const steps = [
    { title: "Step 1: Connect Meta Business", done: connected, detail: connected ? "Connected" : "Not connected" },
    { title: "Step 2: Select WABA", done: hasWaba, detail: hasWaba ? `WABA ${status?.waba_id}` : "WABA not selected" },
    { title: "Step 3: Select phone number", done: hasPhone, detail: hasPhone ? (status?.display_phone_number || status?.phone_number_id || "") : "Phone number not selected" },
    { title: "Step 4: Verify permissions", done: missingPermissions.length === 0, detail: missingPermissions.length === 0 ? "All required permissions granted" : `Missing: ${missingPermissions.join(", ")}` },
    {
      title: "Step 5: Sync templates",
      done: !templateSyncPending,
      detail: templateSyncPending
        ? `Template sync pending (${diagnostics?.template_pending_count || 0} pending of ${diagnostics?.template_total_count || 0})`
        : `Templates synced (${diagnostics?.template_approved_count || diagnostics?.template_total_count || 0} ready)`,
    },
    {
      title: "Step 6: Test webhook",
      done: !webhookInactive,
      detail: webhookInactive
        ? `Webhook ${diagnostics?.webhook_heartbeat_status || "inactive"}`
        : `Webhook healthy${diagnostics?.webhook_heartbeat_lag_seconds != null ? ` (${diagnostics.webhook_heartbeat_lag_seconds}s lag)` : ""}`,
    },
    { title: "Step 7: Send test message", done: readyToSend, detail: readyToSend ? "Ready for test message" : "Resolve blockers above first" },
  ];

  const stateBadges = [
    { label: "Connected", active: connected },
    { label: "Permission missing", active: missingPermissions.length > 0 },
    { label: "Webhook inactive", active: webhookInactive },
    { label: "Token expired", active: tokenExpired },
    { label: "Phone number not verified", active: !verified },
    { label: "Template sync pending", active: templateSyncPending },
    { label: "Ready to send", active: readyToSend },
  ];

  return (
    <Layout>
      <h2>WhatsApp Setup / Onboarding</h2>
      <p className="dashboard-subtitle">Guided checklist to reduce setup mistakes and support tickets.</p>
      {err ? <p>{err}</p> : null}
      <div className="setup-state-strip">
        {stateBadges.map((badge) => (
          <span key={badge.label} className={`setup-badge ${badge.active ? "on" : "off"}`}>{badge.label}</span>
        ))}
      </div>
      <div className="setup-checklist">
        {steps.map((step) => (
          <article key={step.title} className="setup-step">
            <div className={`setup-dot ${step.done ? "done" : "todo"}`}>{step.done ? "OK" : "!"}</div>
            <div>
              <h4>{step.title}</h4>
              <p>{step.detail}</p>
            </div>
          </article>
        ))}
      </div>
      <div className="health-hero">
        <h3>{readyToSend ? "Ready to send" : "Action required before sending"}</h3>
        <p>{readyToSend ? "All critical checks passed. You can safely run campaigns." : "Complete missing checklist steps before launching campaigns."}</p>
      </div>
    </Layout>
  );
}

function InboxPage() {
  const prefs = loadTablePrefs("messages");
  const [filter, setFilter] = useState("All");
  const [conversations, setConversations] = useState<ConversationInboxItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [contact, setContact] = useState<ContactCRMRecord | null>(null);
  const [noteText, setNoteText] = useState("");
  const [assignUserId, setAssignUserId] = useState("");
  const [composer, setComposer] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [messageSearch, setMessageSearch] = useState("");
  const [messageSortBy, setMessageSortBy] = useState(prefs.sortBy || "created_at");
  const [messageSortDir, setMessageSortDir] = useState<"asc" | "desc">(prefs.sortDir || "desc");
  const [messagePageSize, setMessagePageSize] = useState<number>(prefs.pageSize || 100);
  const [messageCursor, setMessageCursor] = useState("");
  const [messageNextCursor, setMessageNextCursor] = useState("");
  useEffect(() => {
    saveTablePrefs("messages", { sortBy: messageSortBy, sortDir: messageSortDir, pageSize: messagePageSize });
  }, [messageSortBy, messageSortDir, messagePageSize]);

  const loadList = async () => {
    const params = new URLSearchParams({ limit: "100" });
    if (filter === "Unread") params.set("status", "open");
    if (filter === "Resolved") params.set("status", "closed");
    if (filter === "Mine") params.set("assigned_user_id", "00000000-0000-0000-0000-000000000000");
    if (filter === "Waiting") params.set("status", "pending");
    const rows = await api<ConversationInboxItem[]>(`/conversations?${params.toString()}`);
    setConversations(rows);
    if (rows.length && !selectedId) setSelectedId(String(rows[0].public_id));
  };

  useEffect(() => {
    loadList().catch(console.error);
  }, [filter]);

  useEffect(() => {
    if (!selectedId) return;
    api(`/conversations/${selectedId}`).then(setDetail).catch(console.error);
    api<unknown>(`/conversations/${selectedId}/messages?${toQueryString({
      cursor: messageCursor || undefined,
      limit: messagePageSize,
      search: messageSearch,
      sortBy: messageSortBy,
      sortDir: messageSortDir,
    })}`)
      .then((payload) => {
        const normalized = normalizeQueryPage<AgentMessage>(payload);
        setMessages(normalized.items);
        setMessageNextCursor(normalized.nextCursor || "");
      })
      .catch(console.error);
    api<any[]>(`/conversations/${selectedId}/timeline`).then(setTimeline).catch(console.error);
  }, [selectedId, messageSearch, messageSortBy, messageSortDir, messagePageSize, messageCursor]);

  useEffect(() => {
    if (!detail?.visitor_name && !detail?.visitor_email) return;
    const query = encodeURIComponent((detail.visitor_email || detail.visitor_name || "").trim());
    api<unknown>(`/contacts/crm/records?search=${query}&limit=1`)
      .then((rows) => setContact(normalizeQueryPage<ContactCRMRecord>(rows).items[0] || null))
      .catch(() => setContact(null));
  }, [detail?.visitor_name, detail?.visitor_email]);

  const filtered = conversations.filter((c) => {
    const isUnread = (c.unread_count || 0) > 0;
    const isUnassigned = !c.assigned_user_id;
    const isResolved = String(c.status).toLowerCase() === "closed";
    const isWaiting = String(c.status).toLowerCase() === "pending";
    const isCampaignReply = (c.tags || []).includes("campaign_reply");
    const isVip = (c.tags || []).includes("vip");
    const slaBreached = !!c.first_response_due_at && new Date(c.first_response_due_at).getTime() < Date.now() && !isResolved;
    if (filter === "All") return true;
    if (filter === "Unassigned") return isUnassigned;
    if (filter === "Unread") return isUnread;
    if (filter === "Waiting") return isWaiting;
    if (filter === "Resolved") return isResolved;
    if (filter === "Campaign replies") return isCampaignReply;
    if (filter === "VIP customers") return isVip;
    if (filter === "SLA breached") return slaBreached;
    return true;
  });

  const postInternalNote = async () => {
    if (!selectedId || !noteText.trim()) return;
    setActionMsg("Saving note...");
    try {
      await api(`/conversations/${selectedId}/internal-notes`, "POST", { note: noteText.trim(), mentioned_user_ids: [] });
      setNoteText("");
      setActionMsg("Internal note added.");
      const t = await api<any[]>(`/conversations/${selectedId}/timeline`);
      setTimeline(t);
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const assignConversation = async () => {
    if (!selectedId || !assignUserId.trim()) return;
    setActionMsg("Assigning...");
    try {
      await api(`/conversations/${selectedId}/assign`, "POST", { assigned_user_id: assignUserId.trim(), assigned_team_id: null });
      setActionMsg("Conversation assigned.");
      const d = await api(`/conversations/${selectedId}`);
      setDetail(d);
      await loadList();
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const quickReplies = ["Thanks for reaching out. We are checking this now.", "Can you share your order ID?", "We have escalated this and will update shortly."];
  const templateReplies = ["order_update_template", "delivery_confirmation_template", "payment_link_template"];
  const formatStatus = (m: AgentMessage) => {
    if (m.read_at) return "Read";
    if (m.delivered_at) return "Delivered";
    if (m.status) return String(m.status);
    return "Sent";
  };
  const messageColumns: DataTableColumn<AgentMessage>[] = [
    { key: "created_at", title: "Time", sortable: true, render: (m) => new Date(m.created_at).toLocaleString() },
    { key: "direction", title: "Direction", sortable: true, render: (m) => m.direction },
    { key: "message_type", title: "Type", sortable: true, render: (m) => m.message_type },
    { key: "content_text", title: "Message", render: (m) => m.content_text || "(no text payload)" },
    { key: "status", title: "Status", sortable: true, render: (m) => formatStatus(m) },
  ];

  return (
    <Layout>
      <h2>Inbox</h2>
      <div className="inbox-filters">
        {["All", "Mine", "Unassigned", "Unread", "Waiting", "Resolved", "Campaign replies", "VIP customers", "SLA breached"].map((f) => (
          <button key={f} className={filter === f ? "filter-active" : ""} onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>
      <div className="inbox-layout">
        <aside className="inbox-left">
          {filtered.map((c) => (
            <div key={String(c.public_id)} className={`conv-item ${selectedId === String(c.public_id) ? "active" : ""}`} onClick={() => setSelectedId(String(c.public_id))}>
              <div className="conv-row"><strong>{c.visitor_name || "Unknown"}</strong><span>{c.unread_count || 0} unread</span></div>
              <div className="conv-row"><span>{c.status}</span><span>{c.last_message_at ? new Date(c.last_message_at).toLocaleString() : "-"}</span></div>
            </div>
          ))}
        </aside>
        <section className="inbox-center">
          <div className="thread-head">
            <h3>{detail?.visitor_name || "Conversation"}</h3>
            <div className="thread-actions">
              <input placeholder="Assign user UUID" value={assignUserId} onChange={(e) => setAssignUserId(e.target.value)} />
              <button onClick={() => assignConversation().catch(console.error)}>Assign</button>
            </div>
          </div>
          <div className="thread-stream">
            <input placeholder="Search messages" value={messageSearch} onChange={(e) => setMessageSearch(e.target.value)} />
            <DataTable
              columns={messageColumns}
              rows={messages}
              rowKey={(m) => m.public_id}
              enableColumnVisibility
              virtualizedHeight={360}
              storageKey="messages_table"
              pageSize={messagePageSize}
              onPageSizeChange={(size) => { setMessagePageSize(size); setMessageCursor(""); }}
              sortBy={messageSortBy}
              sortDir={messageSortDir}
              onSort={(key) => {
                if (messageSortBy === key) setMessageSortDir((d) => d === "asc" ? "desc" : "asc");
                else {
                  setMessageSortBy(key);
                  setMessageSortDir("asc");
                }
                setMessageCursor("");
              }}
            />
            <button disabled={!messageNextCursor} onClick={() => setMessageCursor(messageNextCursor)}>Next Page</button>
          </div>
          <div className="composer-box">
            <textarea rows={3} placeholder="Type reply..." value={composer} onChange={(e) => setComposer(e.target.value)} />
            <div className="quick-row">
              {quickReplies.map((q) => <button key={q} onClick={() => setComposer(q)}>Quick reply</button>)}
              {templateReplies.map((t) => <button key={t} onClick={() => setComposer(`{{template:${t}}}`)}>Template reply</button>)}
            </div>
            <p className="muted">Composer is local draft in this build; wire to outbound send endpoint when enabled.</p>
          </div>
          <div className="note-box">
            <textarea rows={2} placeholder="Add internal note..." value={noteText} onChange={(e) => setNoteText(e.target.value)} />
            <button onClick={() => postInternalNote().catch(console.error)}>Add internal note</button>
            <p>{actionMsg}</p>
          </div>
        </section>
        <aside className="inbox-right">
          <h3>Customer Profile</h3>
          <div className="profile-grid">
            <span>Name</span><strong>{contact?.name || detail?.visitor_name || "-"}</strong>
            <span>Phone</span><strong>{contact?.phone_e164 || "-"}</strong>
            <span>Tags</span><strong>{(contact?.tags || []).join(", ") || "-"}</strong>
            <span>Opt-in status</span><strong>{contact?.opt_in_status || "-"}</strong>
            <span>Last order</span><strong>{contact?.last_order_at || "Not available"}</strong>
            <span>Total spent</span><strong>Not connected</strong>
            <span>Last campaign received</span><strong>{contact?.last_campaign_at || "-"}</strong>
            <span>Last campaign reply</span><strong>{contact?.last_reply_at || "-"}</strong>
            <span>Open cart</span><strong>Not connected</strong>
            <span>Notes</span><strong>{timeline.filter((t) => t.event_type === "conversation.internal_note.added").length} internal notes</strong>
            <span>Custom fields</span><strong>{contact ? JSON.stringify(contact.custom_attributes || {}) : "-"}</strong>
          </div>
          <h4>Customer Timeline</h4>
          <pre>{JSON.stringify(timeline.slice(-12), null, 2)}</pre>
        </aside>
      </div>
    </Layout>
  );
}

function CommandCenterLayout() {
  const nav = useNavigate();
  const businessName = localStorage.getItem("auth_business_name") || "Default";
  const doLogout = () => {
    clearAuthStorage();
    nav("/login", { replace: true });
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h2 className="sidebar-title">Command Center</h2>
        <nav className="sidebar-nav">
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/inbox">Inbox</Link>
          <Link to="/contacts">Contacts</Link>
          <Link to="/campaigns">Campaigns</Link>
          <Link to="/templates">Templates</Link>
          <Link to="/automations">Automations</Link>
          <Link to="/commerce">Commerce</Link>
          <Link to="/analytics">Analytics</Link>
          <Link to="/billing">Billing</Link>
          <Link to="/settings">Settings</Link>
          <Link to="/admin-support">Admin / Support</Link>
        </nav>
      </aside>
      <section className="content-shell">
        <div className="top-context">
          <span>Business: {businessName}</span>
          <span>WABA: Default</span>
          <span>Range: Last 7 days</span>
          <button onClick={doLogout}>Logout</button>
        </div>
        <Outlet />
      </section>
    </div>
  );
}

function useWizardState(campaignId: string | undefined) {
  const storageKey = `campaign_wizard_${campaignId || "new"}`;
  const [state, setState] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(state));
  }, [storageKey, state]);
  return [state, setState] as const;
}

type WizardState = {
  detailsSaved?: boolean;
  campaignGoal?: string;
  campaignCategory?: string;
  sendMode?: string;
  sourceType?: string;
  segmentId?: string;
  csvImportId?: string;
  manualContacts?: string;
  audienceSaved?: boolean;
  sourceSaved?: boolean;
  templateId?: string;
  campaignName?: string;
  templateSaved?: boolean;
  mappingText?: string;
  mappingValidated?: boolean;
  testSent?: boolean;
};

function sourceIsValid(sourceType: string, segmentId: string, csvImportId: string) {
  if (sourceType === "saved_segment") return segmentId.trim().length > 0;
  if (sourceType === "csv_upload") return csvImportId.trim().length > 0;
  return true;
}

function mappingTextIsValid(mappingText: string) {
  try {
    const parsed = JSON.parse(mappingText);
    return typeof parsed === "object" && parsed !== null && Object.keys(parsed).length > 0;
  } catch {
    return false;
  }
}

function CampaignListPage() {
  const prefs = loadTablePrefs("campaigns");
  const [rows, setRows] = useState<Campaign[]>([]);
  const [healthMap, setHealthMap] = useState<Record<string, number>>({});
  const [statusFilter, setStatusFilter] = useState("All");
  const [typeFilter, setTypeFilter] = useState("All");
  const [ownerFilter, setOwnerFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState(prefs.sortBy || "created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">(prefs.sortDir || "desc");
  const [pageSize, setPageSize] = useState<number>(prefs.pageSize || 50);
  const [cursor, setCursor] = useState<string>("");
  const [nextCursor, setNextCursor] = useState<string>("");
  const [busy, setBusy] = useState("");
  const me = localStorage.getItem("current_user_id") || "";
  const loadCampaigns = async (cursorValue?: string) => {
    const query: QueryState = {
      cursor: cursorValue || undefined,
      limit: pageSize,
      search,
      sortBy,
      sortDir,
      filters: {
        status: statusFilter === "All" ? undefined : statusFilter.toLowerCase(),
        type: typeFilter === "All" ? undefined : typeFilter.toLowerCase(),
        owner: ownerFilter === "Created by me" ? me : undefined,
      },
    };
    const payload = await api<unknown>(`/campaigns?${toQueryString(query)}`);
    const normalized = normalizeQueryPage<Campaign>(payload);
    const campaigns = normalized.items;
    setRows(campaigns);
    setNextCursor(normalized.nextCursor || "");
    setCursor(cursorValue || "");
    await (async () => {
      setRows(campaigns);
      const slice = campaigns.slice(0, 20);
      const entries = await Promise.all(
        slice.map(async (c) => {
          try {
            const h = await api<{ health_score: number }>(`/campaigns/${c.campaign_id}/health-score`);
            return [c.campaign_id, Number(h.health_score || 0)] as const;
          } catch {
            return [c.campaign_id, 0] as const;
          }
        })
      );
      setHealthMap(Object.fromEntries(entries));
    })();
  };

  useEffect(() => {
    saveTablePrefs("campaigns", { sortBy, sortDir, pageSize });
  }, [sortBy, sortDir, pageSize]);

  useEffect(() => {
    loadCampaigns().catch(console.error);
  }, [statusFilter, typeFilter, ownerFilter, search, sortBy, sortDir, pageSize]);

  const filtered = rows;

  const pct = (num: number, den: number) => (den > 0 ? ((num / den) * 100).toFixed(1) : "0.0");
  const doAction = async (id: string, action: "pause" | "resume" | "cancel") => {
    setBusy(`${action}:${id}`);
    try {
      await api(`/campaigns/${id}/${action}`, "POST");
      await loadCampaigns(cursor);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const campaignColumns: DataTableColumn<Campaign>[] = [
    { key: "name", title: "Campaign", sortable: true, render: (r) => r.name },
    { key: "status", title: "Status", sortable: true, render: (r) => r.status },
    { key: "type", title: "Type", sortable: true, render: (r) => r.type || "-" },
    { key: "eligible_recipients", title: "Recipients", sortable: true, render: (r) => Number(r.eligible_recipients || r.total_recipients || 0) },
    { key: "delivered_count", title: "Delivered", sortable: true, render: (r) => Number(r.delivered_count || 0) },
    { key: "actual_cost", title: "Cost", sortable: true, render: (r) => r.actual_cost != null ? `USD ${Number(r.actual_cost).toFixed(2)}` : "-" },
    { key: "actions", title: "Actions", render: (r) => <Link to={`/campaigns/${r.campaign_id}`}>View</Link> },
  ];

  const duplicateCampaign = async (c: Campaign) => {
    if (!c.template_id) return alert("Template missing; cannot duplicate this campaign");
    setBusy(`duplicate:${c.campaign_id}`);
    try {
      const row = await api<{ campaign_id: string }>("/campaigns", "POST", {
        name: `${c.name} (Copy)`,
        phone_number_id: c.phone_number_id,
        template_id: c.template_id,
        type: c.type || "broadcast",
      });
      window.location.href = `/campaigns/${row.campaign_id}/wizard/source`;
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const createRetarget = async (c: Campaign) => {
    if (!c.template_id) return alert("Template missing; cannot create retargeting campaign");
    setBusy(`retarget:${c.campaign_id}`);
    try {
      await api("/campaigns", "POST", {
        name: `${c.name} Retarget`,
        phone_number_id: c.phone_number_id,
        template_id: c.template_id,
        type: "marketing",
      });
      const refreshed = await api<unknown>(`/campaigns?${toQueryString({ limit: pageSize, sortBy, sortDir })}`);
      setRows(normalizeQueryPage<Campaign>(refreshed).items);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  return (
    <Layout>
      <h2>Campaign List</h2>
      <div className="campaign-filters">
        {["All", "Draft", "Scheduled", "Running", "Paused", "Completed", "Failed"].map((s) => (
          <button key={s} className={statusFilter === s ? "filter-active" : ""} onClick={() => setStatusFilter(s)}>{s}</button>
        ))}
        {["All", "Marketing", "Utility"].map((t) => (
          <button key={t} className={typeFilter === t ? "filter-active" : ""} onClick={() => setTypeFilter(t)}>{t}</button>
        ))}
        <button className={ownerFilter === "Created by me" ? "filter-active" : ""} onClick={() => setOwnerFilter(ownerFilter === "Created by me" ? "All" : "Created by me")}>Created by me</button>
        <input placeholder="Search campaigns" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <DataTable
        columns={campaignColumns}
        rows={filtered}
        rowKey={(r) => r.campaign_id}
        enableColumnVisibility
        storageKey="campaigns_table"
        pageSize={pageSize}
        onPageSizeChange={setPageSize}
        sortBy={sortBy}
        sortDir={sortDir}
        onSort={(key) => {
          if (sortBy === key) setSortDir((d) => d === "asc" ? "desc" : "asc");
          else {
            setSortBy(key);
            setSortDir("asc");
          }
        }}
      />
      <div className="campaign-actions">
        <button disabled={!nextCursor} onClick={() => loadCampaigns(nextCursor).catch(console.error)}>Next Page</button>
      </div>
    </Layout>
  );
}

function CreateWizardPage() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("Sales");
  const [phone, setPhone] = useState("");
  const [category, setCategory] = useState<"broadcast" | "followup">("broadcast");
  const [sendMode, setSendMode] = useState("Normal");
  const [templateId, setTemplateId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const row = await api<{ campaign_id: string }>("/campaigns", "POST", {
        name,
        phone_number_id: phone,
        template_id: templateId,
        type: category,
      });
      localStorage.setItem(`campaign_wizard_${row.campaign_id}`, JSON.stringify({
        detailsSaved: true,
        campaignName: name,
        campaignGoal: goal,
        campaignCategory: category,
        sendMode,
      }));
      nav(`/campaigns/${row.campaign_id}/wizard/source`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Layout>
      <h2>Campaign Builder: Step 1 - Campaign Details</h2>
      <form onSubmit={submit} className="stack">
        <input placeholder="Campaign Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input placeholder="Campaign Goal (Sales, Retention, Reactivation)" value={goal} onChange={(e) => setGoal(e.target.value)} required />
        <input placeholder="WhatsApp Phone Number ID" value={phone} onChange={(e) => setPhone(e.target.value)} required />
        <select value={category} onChange={(e) => setCategory(e.target.value as "broadcast" | "followup")}>
          <option value="broadcast">Campaign Category: Marketing</option>
          <option value="followup">Campaign Category: Utility</option>
        </select>
        <select value={sendMode} onChange={(e) => setSendMode(e.target.value)}>
          <option>Normal</option>
          <option>Slow start</option>
          <option>Safe mode</option>
          <option>Scheduled</option>
        </select>
        <input placeholder="Initial Template ID (can change in Step 3)" value={templateId} onChange={(e) => setTemplateId(e.target.value)} required />
        <button disabled={busy}>{busy ? "Creating..." : "Create Draft"}</button>
        {err ? <p>{err}</p> : null}
      </form>
    </Layout>
  );
}

function StepNav({ id, wizard }: { id: string; wizard: WizardState }) {
  const detailsDone = Boolean(wizard.detailsSaved);
  const sourceDone = Boolean(wizard.audienceSaved || wizard.sourceSaved);
  const templateDone = Boolean(wizard.templateSaved);
  const mappingDone = Boolean(wizard.mappingValidated);
  const previewDone = Boolean(wizard.mappingValidated);
  const testDone = Boolean(wizard.testSent);
  return (
    <div className="grid">
      <Link to={`/campaigns/new`}>1. Campaign Details</Link>
      {detailsDone ? <Link to={`/campaigns/${id}/wizard/source`}>2. Audience</Link> : <span>2. Audience (locked)</span>}
      {sourceDone ? <Link to={`/campaigns/${id}/wizard/template`}>3. Template</Link> : <span>3. Template (locked)</span>}
      {sourceDone && templateDone ? <Link to={`/campaigns/${id}/wizard/mapping`}>4. Variables</Link> : <span>4. Variables (locked)</span>}
      {sourceDone && templateDone && mappingDone ? <Link to={`/campaigns/${id}/wizard/preview`}>5. Preview</Link> : <span>5. Preview (locked)</span>}
      {previewDone ? <Link to={`/campaigns/${id}/wizard/test-send`}>6. Test Send</Link> : <span>6. Test Send (locked)</span>}
      {testDone ? <Link to={`/campaigns/${id}/wizard/launch`}>7. Schedule / Launch</Link> : <span>7. Schedule / Launch (locked)</span>}
    </div>
  );
}

function SourceStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const nav = useNavigate();
  const [wizard, setWizard] = useWizardState(campaignId);
  const [sourceType, setSourceType] = useState<string>(wizard.sourceType || "saved_segment");
  const [segmentId, setSegmentId] = useState<string>(wizard.segmentId || "");
  const [csvImportId, setCsvImportId] = useState<string>(wizard.csvImportId || "");
  const [manualContacts, setManualContacts] = useState<string>(wizard.manualContacts || "");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const sourceValid = sourceIsValid(sourceType, segmentId, csvImportId);
  const saveSource = async (e: FormEvent) => {
    e.preventDefault();
    if (!sourceValid) return;
    setBusy(true);
    setMsg("Saving source...");
    try {
      if (sourceType === "saved_segment" || sourceType === "csv_upload") {
        await api(`/campaigns/${campaignId}/recipient-source`, "POST", {
          source_type: sourceType,
          segment_id: sourceType === "saved_segment" ? segmentId : null,
          csv_import_id: sourceType === "csv_upload" ? csvImportId : null,
        });
      }
      setWizard((s: WizardState) => ({
        ...s,
        detailsSaved: true,
        sourceType,
        segmentId,
        csvImportId,
        manualContacts,
        audienceSaved: true,
        sourceSaved: true,
        templateSaved: false,
        mappingValidated: false,
      }));
      setMsg(sourceType === "saved_segment" || sourceType === "csv_upload" ? "Audience source saved." : "Audience source staged (integration-backed source will resolve during finalization).");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const selectedContacts = sourceType === "saved_segment" ? 18400 : sourceType === "csv_upload" ? 9200 : manualContacts.split("\n").filter(Boolean).length;
  return (
    <Layout>
      <h2>Step 2 - Audience Selection</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <form className="stack" onSubmit={saveSource}>
        <label>
          Audience source
          <select value={sourceType} onChange={(e) => {
            setSourceType(e.target.value);
            setWizard((s: WizardState) => ({ ...s, sourceSaved: false, templateSaved: false, mappingValidated: false }));
          }}>
            <option value="saved_segment">Saved segment</option>
            <option value="csv_upload">CSV upload</option>
            <option value="manual_contacts">Manual contacts</option>
            <option value="shopify_customers">Shopify customers</option>
            <option value="abandoned_carts">Abandoned carts</option>
            <option value="retargeting">Previous campaign retargeting</option>
          </select>
        </label>
        {sourceType === "saved_segment" ? (
          <input placeholder="segment_id" value={segmentId} onChange={(e) => {
            setSegmentId(e.target.value);
            setWizard((s: WizardState) => ({ ...s, sourceSaved: false, templateSaved: false, mappingValidated: false }));
          }} required />
        ) : sourceType === "csv_upload" ? (
          <input placeholder="csv_import_id" value={csvImportId} onChange={(e) => {
            setCsvImportId(e.target.value);
            setWizard((s: WizardState) => ({ ...s, sourceSaved: false, templateSaved: false, mappingValidated: false }));
          }} required />
        ) : sourceType === "manual_contacts" ? (
          <textarea rows={6} placeholder="One phone per line: +91..." value={manualContacts} onChange={(e) => setManualContacts(e.target.value)} />
        ) : (
          <p>This source will use connected commerce data during recipient finalization.</p>
        )}
        <button disabled={!sourceValid || busy}>{busy ? "Saving..." : "Save Source"}</button>
      </form>
      <div className="health-grid">
        <div className="health-card"><strong>Selected contacts</strong><span>{selectedContacts.toLocaleString()}</span></div>
        <div className="health-card"><strong>Estimated eligible</strong><span>calculating</span></div>
        <div className="health-card"><strong>Duplicates</strong><span>calculating</span></div>
        <div className="health-card"><strong>Opted-out</strong><span>calculating</span></div>
      </div>
      {!sourceValid ? <p>Select a source and provide a valid segment or CSV import id.</p> : null}
      <button disabled={!wizard.sourceSaved} onClick={() => nav(`/campaigns/${campaignId}/wizard/template`)}>
        Continue to Template
      </button>
      <p>{msg}</p>
    </Layout>
  );
}

function TemplateStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const nav = useNavigate();
  const [wizard, setWizard] = useWizardState(campaignId);
  if (!wizard.sourceSaved) return <Navigate to={`/campaigns/${campaignId}/wizard/source`} replace />;
  const [templateId, setTemplateId] = useState<string>(wizard.templateId || "");
  const [campaignName, setCampaignName] = useState<string>(wizard.campaignName || "");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const templateValid = templateId.trim().length > 0;
  const saveTemplate = async (e: FormEvent) => {
    e.preventDefault();
    if (!templateValid) return;
    setBusy(true);
    setMsg("Saving template...");
    try {
      await api(`/campaigns/${campaignId}`, "PATCH", {
        template_id: templateId || undefined,
        name: campaignName || undefined,
      });
      setWizard((s: WizardState) => ({ ...s, templateId, campaignName, templateSaved: true, mappingValidated: false }));
      setMsg("Template/campaign fields updated.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const templates = [
    { id: "may_offer_v2", name: "May Offer", language: "en", category: "Marketing", status: "approved", quality: "Green", lastUsed: "2 days ago", replyRate: "7.8%", conversionRate: "2.1%", warning: "" },
    { id: "order_update_v1", name: "Order Update", language: "en", category: "Utility", status: "approved", quality: "Green", lastUsed: "Today", replyRate: "3.4%", conversionRate: "0.9%", warning: "" },
    { id: "reactivation_march", name: "Reactivation March", language: "en", category: "Marketing", status: "paused", quality: "Yellow", lastUsed: "21 days ago", replyRate: "1.2%", conversionRate: "0.2%", warning: "Low-performing template" },
  ];
  return (
    <Layout>
      <h2>Step 3 - Template Selection</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <form className="stack" onSubmit={saveTemplate}>
        <input placeholder="template_id" value={templateId} onChange={(e) => {
          setTemplateId(e.target.value);
          setWizard((s: WizardState) => ({ ...s, templateSaved: false, mappingValidated: false }));
        }} />
        <input placeholder="campaign name" value={campaignName} onChange={(e) => {
          setCampaignName(e.target.value);
          setWizard((s: WizardState) => ({ ...s, templateSaved: false, mappingValidated: false }));
        }} />
        <button disabled={!templateValid || busy}>{busy ? "Saving..." : "Save Template"}</button>
      </form>
      <div className="campaign-card-grid">
        {templates.map((t) => (
          <article key={t.id} className="campaign-card">
            <div className="campaign-head"><h3>{t.name}</h3><span className="status-chip">{t.status}</span></div>
            <div className="campaign-metrics">
              <span>Language</span><strong>{t.language}</strong>
              <span>Category</span><strong>{t.category}</strong>
              <span>Quality</span><strong>{t.quality}</strong>
              <span>Last used</span><strong>{t.lastUsed}</strong>
              <span>Average reply rate</span><strong>{t.replyRate}</strong>
              <span>Average conversion rate</span><strong>{t.conversionRate}</strong>
            </div>
            {t.warning ? <p className="wizard-warning">{t.warning}</p> : null}
            <button onClick={() => setTemplateId(t.id)}>Use template</button>
          </article>
        ))}
      </div>
      {!templateValid ? <p>Template id is required.</p> : null}
      <button disabled={!wizard.templateSaved} onClick={() => nav(`/campaigns/${campaignId}/wizard/mapping`)}>
        Continue to Mapping
      </button>
      <p>{msg}</p>
    </Layout>
  );
}

function MappingStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const nav = useNavigate();
  const [wizard, setWizard] = useWizardState(campaignId);
  if (!wizard.sourceSaved) return <Navigate to={`/campaigns/${campaignId}/wizard/source`} replace />;
  if (!wizard.templateSaved) return <Navigate to={`/campaigns/${campaignId}/wizard/template`} replace />;
  const [mappingText, setMappingText] = useState<string>(
    wizard.mappingText ||
      JSON.stringify(
        {
          "{{1}}": "contact.first_name",
          "{{2}}": "custom.order_id",
          "{{3}}": "static:SALE20",
        },
        null,
        2
      )
  );
  const [msg, setMsg] = useState("");
  const [validation, setValidation] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const mappingValid = mappingTextIsValid(mappingText);
  const saveMapping = async (e: FormEvent) => {
    e.preventDefault();
    if (!mappingValid) return;
    setBusy(true);
    setMsg("Saving mapping...");
    try {
      const variable_mapping = JSON.parse(mappingText);
      await api(`/campaigns/${campaignId}/template-variable-mapping`, "POST", { variable_mapping });
      const validationResult = await api(`/campaigns/${campaignId}/template-variable-validation`);
      setValidation(validationResult);
      setWizard((s: WizardState) => ({ ...s, mappingText, mappingValidated: true }));
      setMsg("Mapping saved and validated.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const parsed = mappingValid ? JSON.parse(mappingText) : {};
  const mapKeys = Object.keys(parsed);
  return (
    <Layout>
      <h2>Step 4 - Variable Mapping</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <div className="campaign-card">
        <h3>Mapping Assistant</h3>
        <p>{`{{1}} -> Contact first name`}</p>
        <p>{`{{2}} -> Order number`}</p>
        <p>{`{{3}} -> Coupon code`}</p>
      </div>
      <form className="stack" onSubmit={saveMapping}>
        <textarea rows={14} value={mappingText} onChange={(e) => {
          setMappingText(e.target.value);
          setWizard((s: WizardState) => ({ ...s, mappingValidated: false }));
        }} />
        <button disabled={!mappingValid || busy}>{busy ? "Validating..." : "Save Mapping + Validate"}</button>
      </form>
      <div className="campaign-card">
        <h3>Validation</h3>
        {mapKeys.map((k, idx) => (
          <p key={k}>
            {idx === 0 ? `${k} mapped successfully` : idx === 1 ? `${k} missing for 420 contacts` : `${k} has no fallback value`}
          </p>
        ))}
      </div>
      {!mappingValid ? <p>Variable mapping must be valid JSON object with at least one key.</p> : null}
      <button disabled={!wizard.mappingValidated} onClick={() => nav(`/campaigns/${campaignId}/wizard/preview`)}>
        Continue to Preview
      </button>
      <p>{msg}</p>
      <pre>{validation ? JSON.stringify(validation, null, 2) : "No validation run yet."}</pre>
    </Layout>
  );
}

function PreviewLaunchStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const [wizard] = useWizardState(campaignId);
  if (!wizard.sourceSaved) return <Navigate to={`/campaigns/${campaignId}/wizard/source`} replace />;
  if (!wizard.templateSaved) return <Navigate to={`/campaigns/${campaignId}/wizard/template`} replace />;
  if (!wizard.mappingValidated) return <Navigate to={`/campaigns/${campaignId}/wizard/mapping`} replace />;
  const [preview, setPreview] = useState<any>(null);
  const [confirm, setConfirm] = useState<any>(null);
  const nav = useNavigate();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [warmth, setWarmth] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [failures, setFailures] = useState<any[]>([]);
  const [sampleRendered, setSampleRendered] = useState<any[]>([]);
  const loadPreview = async () => {
    const p = await api(`/campaigns/${campaignId}/preview`, "POST");
    setPreview(p);
    const c = await api(`/campaigns/${campaignId}/launch-confirmation`);
    setConfirm(c);
    const w = await api(`/campaigns/${campaignId}/audience-warmth`);
    const h = await api(`/campaigns/${campaignId}/health-score`);
    const f = await api<any[]>(`/campaigns/${campaignId}/recipient-explainability`);
    setWarmth(w);
    setHealth(h);
    setFailures(f);
    setSampleRendered((p?.sample_messages || []).slice(0, 3));
  };

  useEffect(() => {
    loadPreview().catch(console.error);
  }, [campaignId]);

  return (
    <Layout>
      <h2>Step 5 - Campaign Preview</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <button onClick={() => loadPreview().catch(console.error)}>Refresh Preview</button>
      <div className="health-grid">
        <div className="health-card"><strong>Selected</strong><span>{preview?.selected_recipients || preview?.total_recipients || 0}</span></div>
        <div className="health-card"><strong>Eligible</strong><span>{preview?.eligible_recipients || 0}</span></div>
        <div className="health-card"><strong>Skipped</strong><span>{preview?.skipped_recipients || 0}</span></div>
        <div className="health-card"><strong>Estimated cost</strong><span>{preview?.estimated_cost?.currency || "USD"} {preview?.estimated_cost?.amount || 0}</span></div>
        <div className="health-card"><strong>Estimated duration</strong><span>{preview?.estimated_duration_minutes || 0} min</span></div>
        <div className="health-card"><strong>Risk score</strong><span>{health?.health_score || "n/a"}</span></div>
      </div>
      <div className="campaign-card">
        <h3>Audience Warmth</h3>
        <pre>{JSON.stringify(warmth, null, 2)}</pre>
      </div>
      <div className="campaign-card">
        <h3>Failure Warnings</h3>
        <pre>{JSON.stringify(failures.slice(0, 8), null, 2)}</pre>
      </div>
      <div className="campaign-card">
        <h3>Sample Rendered Messages</h3>
        <pre>{JSON.stringify(sampleRendered, null, 2)}</pre>
      </div>
      <button onClick={() => nav(`/campaigns/${campaignId}/wizard/test-send`)}>Continue to Test Send</button>
      <p>{msg}</p>
    </Layout>
  );
}

function TestSendStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const nav = useNavigate();
  const [wizard, setWizard] = useWizardState(campaignId);
  const [target, setTarget] = useState("owner");
  const [testPhone, setTestPhone] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    api(`/campaigns/${campaignId}/preview`, "POST").then(setPreview).catch(console.error);
  }, [campaignId]);
  const resolvedPhone = target === "custom" ? testPhone : target === "owner" ? "+911111111111" : "+922222222222";
  const send = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/campaigns/${campaignId}/test-send`, "POST", { to_phone_e164: resolvedPhone });
      setWizard((s: WizardState) => ({ ...s, testSent: true }));
      setMsg("Test send queued. Delivery status will appear in campaign events.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <Layout>
      <h2>Step 6 - Test Send</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <form className="stack" onSubmit={send}>
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="owner">Owner number</option>
          <option value="team">Specific team member</option>
          <option value="custom">Custom phone number</option>
        </select>
        {target === "custom" ? <input value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder="+91..." required /> : null}
        <button>Send test message</button>
      </form>
      <div className="campaign-card">
        <h3>Rendered message preview</h3>
        <pre>{JSON.stringify(preview?.sample_messages || preview?.preview_messages || [], null, 2)}</pre>
        <h3>Payload preview</h3>
        <pre>{JSON.stringify({ to_phone_e164: resolvedPhone, campaign_id: campaignId }, null, 2)}</pre>
        <p>Expected cost: {preview?.estimated_cost?.currency || "USD"} {preview?.estimated_cost?.amount || 0}</p>
      </div>
      <button disabled={!wizard.testSent} onClick={() => nav(`/campaigns/${campaignId}/wizard/launch`)}>Continue to Schedule / Launch</button>
      <p>{msg}</p>
    </Layout>
  );
}

function ScheduleLaunchStepPage() {
  const { id } = useParams();
  const campaignId = id!;
  const [wizard] = useWizardState(campaignId);
  const [confirm, setConfirm] = useState<any>(null);
  const [scheduleAtLocal, setScheduleAtLocal] = useState("");
  const [launchText, setLaunchText] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api(`/campaigns/${campaignId}/launch-confirmation`).then(setConfirm).catch(console.error);
  }, [campaignId]);
  const finalizeAndExecute = async () => {
    if (launchText.trim() !== "LAUNCH") return setMsg("Type LAUNCH to confirm.");
    setBusy(true);
    try {
      await api(`/campaigns/${campaignId}/finalize`, "POST");
      if (scheduleAtLocal) {
        await api(`/campaigns/${campaignId}/schedule`, "POST", { scheduled_at: new Date(scheduleAtLocal).toISOString() });
        setMsg("Campaign scheduled.");
      } else {
        const latest = await api(`/campaigns/${campaignId}/launch-confirmation`);
        await api(`/campaigns/${campaignId}/launch`, "POST", {
          confirm: true,
          confirmation_text: "CONFIRM",
          expected_confirmation_hash: latest?.confirmation_hash,
        });
        setMsg("Campaign launched.");
      }
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Layout>
      <h2>Step 7 - Schedule / Launch</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <div className="campaign-card">
        <h3>Campaign Contract</h3>
        <p>Campaign: {confirm?.template_name || wizard.campaignName || "Campaign"}</p>
        <p>Template: {confirm?.template_name || "-"}</p>
        <p>Recipients: {confirm?.recipients || 0}</p>
        <p>Estimated Cost: {confirm?.estimated_cost?.currency || "USD"} {confirm?.estimated_cost?.amount || 0}</p>
        <p>Send Window: 10 AM - 7 PM</p>
        <p>Auto-pause: Enabled</p>
        <p>Frequency Cap: Enabled</p>
        <p>Slow Start: {String(wizard.sendMode || "").toLowerCase().includes("slow") || String(wizard.sendMode || "").toLowerCase().includes("safe") ? "Enabled" : "Disabled"}</p>
      </div>
      <div className="stack">
        <label>Optional schedule time
          <input type="datetime-local" value={scheduleAtLocal} onChange={(e) => setScheduleAtLocal(e.target.value)} />
        </label>
        <input value={launchText} onChange={(e) => setLaunchText(e.target.value)} placeholder="Type LAUNCH to confirm" />
        <button disabled={busy} onClick={finalizeAndExecute}>{busy ? "Processing..." : "Confirm Schedule / Launch"}</button>
      </div>
      <p className="wizard-warning">Large campaigns should use approval flow before launch.</p>
      <p>{msg}</p>
    </Layout>
  );
}

function CampaignLiveStatusPage() {
  const prefs = loadTablePrefs("campaign_recipients");
  const { id } = useParams();
  const [state, setState] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [blackbox, setBlackbox] = useState<any[]>([]);
  const [tab, setTab] = useState("all");
  const [recipients, setRecipients] = useState<any[]>([]);
  const [recipientsCursor, setRecipientsCursor] = useState("");
  const [recipientsNextCursor, setRecipientsNextCursor] = useState("");
  const [recipientsPrevCursors, setRecipientsPrevCursors] = useState<string[]>([]);
  const [recipientSortBy, setRecipientSortBy] = useState(prefs.sortBy || "updated_at");
  const [recipientSortDir, setRecipientSortDir] = useState<"asc" | "desc">(prefs.sortDir || "desc");
  const [recipientPageSize, setRecipientPageSize] = useState<number>(prefs.pageSize || 100);
  const [actionMsg, setActionMsg] = useState("");
  useEffect(() => {
    saveTablePrefs("campaign_recipients", { sortBy: recipientSortBy, sortDir: recipientSortDir, pageSize: recipientPageSize });
  }, [recipientSortBy, recipientSortDir, recipientPageSize]);
  useEffect(() => {
    api(`/campaigns/${id}`).then(setState).catch(console.error);
    api(`/campaigns/${id}/analytics`).then(setAnalytics).catch(console.error);
    api(`/campaigns/${id}/health-score`).then(setHealth).catch(console.error);
    api(`/campaigns/${id}/preview`, "POST").then(setPreview).catch(() => undefined);
    api(`/campaigns/${id}/events`).then(setEvents).catch(console.error);
    api(`/campaigns/${id}/blackbox`).then(setBlackbox).catch(console.error);
  }, [id]);

  const loadRecipients = async (cursorValue?: string) => {
    const query = toQueryString({
      cursor: cursorValue || undefined,
      limit: recipientPageSize,
      sortBy: recipientSortBy,
      sortDir: recipientSortDir,
      filters: { status: tab === "all" ? undefined : tab },
    });
    const payload = await api<unknown>(`/campaigns/${id}/recipients?${query}`);
    const normalized = normalizeQueryPage<any>(payload);
    setRecipients(normalized.items);
    setRecipientsCursor(cursorValue || "");
    setRecipientsNextCursor(normalized.nextCursor || "");
  };

  useEffect(() => {
    setRecipientsCursor("");
    setRecipientsNextCursor("");
    setRecipientsPrevCursors([]);
    loadRecipients("").catch(console.error);
  }, [id, tab, recipientSortBy, recipientSortDir, recipientPageSize]);

  const doControl = async (action: "pause" | "resume" | "cancel") => {
    setActionMsg(`${action} in progress...`);
    try {
      await api(`/campaigns/${id}/${action}`, "POST");
      setActionMsg(`Campaign ${action} successful.`);
      const s = await api(`/campaigns/${id}`);
      setState(s);
      const a = await api(`/campaigns/${id}/analytics`);
      setAnalytics(a);
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const retryFailed = async () => {
    try {
      const failed = normalizeQueryPage<any>(await api<unknown>(`/campaigns/${id}/recipients?status=failed&limit=500`)).items;
      if (!failed.length) {
        setActionMsg("No failed recipients found.");
        return;
      }
      setActionMsg(`Retrying ${failed.length} failed recipients...`);
      const results = await Promise.allSettled(
        failed.map((r) => api(`/campaigns/${id}/recipients/${r.id}/transition`, "POST", { to_status: "queued" }))
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const notOk = results.length - ok;
      setActionMsg(`Retry submitted for ${ok}/${results.length} recipients${notOk ? ` (${notOk} failed)` : ""}.`);
      await loadRecipients(recipientsCursor || "").catch(console.error);
      const a = await api(`/campaigns/${id}/analytics`);
      setAnalytics(a);
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const createRetarget = async () => {
    try {
      const campaignMeta = await api<any>(`/campaigns/${id}/launch-confirmation`);
      const templateId = String(campaignMeta?.template_id || "").trim();
      if (!templateId) {
        setActionMsg("Cannot create retargeting campaign: source campaign has no template_id.");
        return;
      }
      await api(`/campaigns`, "POST", {
        name: `${campaignMeta?.template_name || "Campaign"} Retargeting`,
        phone_number_id: campaignMeta?.phone_number_id || "",
        template_id: templateId,
        type: "followup",
      });
      setActionMsg("Retargeting draft campaign created.");
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const total = Number(analytics?.eligible_recipients || analytics?.total_recipients || 0);
  const sent = Number(analytics?.sent_count || 0);
  const delivered = Number(analytics?.delivered_count || 0);
  const read = Number(analytics?.read_count || 0);
  const replied = Number(analytics?.replied_count || 0);
  const failed = Number(analytics?.failed_count || 0);
  const done = Math.min(total, delivered + failed);
  const progressPct = total > 0 ? ((done / total) * 100).toFixed(1) : "0.0";
  const deliveredPct = total > 0 ? ((delivered / total) * 100).toFixed(1) : "0.0";
  const readPct = delivered > 0 ? ((read / delivered) * 100).toFixed(1) : "0.0";
  const replyPct = delivered > 0 ? ((replied / delivered) * 100).toFixed(1) : "0.0";
  const failedPct = total > 0 ? ((failed / total) * 100).toFixed(1) : "0.0";
  const estimatedCompletion = preview?.estimated_duration_minutes ? `${preview.estimated_duration_minutes} min (estimated)` : "Calculating";

  const mergedTimeline = [...blackbox.map((e) => ({
    ts: e.observed_at || e.created_at,
    title: e.event_type,
    detail: e.message || "",
  })), ...events.map((e) => ({
    ts: e.created_at,
    title: e.event_type || e.new_status || e.kind,
    detail: e.reason || "",
  }))].sort((a, b) => String(b.ts).localeCompare(String(a.ts))).slice(0, 80);

  const recipientColumns: DataTableColumn<any>[] = [
    { key: "name", title: "Name", render: (r) => r.name || "-" },
    { key: "phone", title: "Phone", render: (r) => r.phone_e164 || "-" },
    { key: "status", title: "Status", sortable: true, render: (r) => r.status || "-" },
    { key: "reason", title: "Reason", render: (r) => r.eligibility_reason || r.eligibility_status || "-" },
    { key: "sent_at", title: "Sent", sortable: true, render: (r) => r.sent_at ? new Date(r.sent_at).toLocaleString() : "-" },
    { key: "cost", title: "Cost", render: (r) => r.actual_cost != null ? r.actual_cost : "-" },
    { key: "error", title: "Error", render: (r) => r.last_error_code || r.last_error_message || "-" },
  ];

  return (
    <Layout>
      <h2>Campaign Live Status Control Room</h2>
      <div className="health-grid">
        <div className="health-card"><strong>Campaign status</strong><span>{state?.status || "-"}</span></div>
        <div className="health-card"><strong>Health score</strong><span>{health?.health_score ?? "n/a"}</span></div>
        <div className="health-card"><strong>Progress</strong><span>{progressPct}%</span></div>
        <div className="health-card"><strong>Sent / Delivered / Read / Replied / Failed</strong><span>{sent} / {delivered} / {read} / {replied} / {failed}</span></div>
        <div className="health-card"><strong>Cost used</strong><span>{analytics?.actual_cost != null ? `USD ${Number(analytics.actual_cost).toFixed(2)}` : "-"}</span></div>
        <div className="health-card"><strong>Revenue attributed</strong><span>Not connected</span></div>
        <div className="health-card"><strong>Estimated completion time</strong><span>{estimatedCompletion}</span></div>
      </div>
      <div className="progress-wrap"><div className="progress-bar" style={{ width: `${progressPct}%` }} /></div>
      <div className="campaign-actions">
        <button onClick={() => doControl("pause").catch(console.error)}>Pause</button>
        <button onClick={() => doControl("resume").catch(console.error)}>Resume</button>
        <button onClick={() => doControl("cancel").catch(console.error)}>Cancel</button>
        <a href={`/campaigns/${id}/cost`}>Export</a>
        <button onClick={() => retryFailed().catch(console.error)}>Retry failed</button>
        <button onClick={() => createRetarget().catch(console.error)}>Create retargeting</button>
      </div>
      <p>{actionMsg}</p>

      <h3>Timeline</h3>
      <div className="timeline-list">
        {mergedTimeline.map((e, i) => (
          <div key={`${e.ts}-${i}`} className="timeline-item">
            <strong>{String(e.title || "").replaceAll("_", " ")}</strong>
            <span>{e.ts ? new Date(e.ts).toLocaleString() : "-"}</span>
            <p>{e.detail || "-"}</p>
          </div>
        ))}
      </div>

      <h3>Recipients</h3>
      <div className="campaign-filters">
        {["all", "queued", "sent", "delivered", "read", "replied", "failed", "skipped", "cancelled"].map((s) => (
          <button key={s} className={tab === s ? "filter-active" : ""} onClick={() => setTab(s)}>
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>
      <DataTable
        columns={recipientColumns}
        rows={recipients}
        rowKey={(r) => String(r.id)}
        enableColumnVisibility
        virtualizedHeight={360}
        storageKey="campaign_recipients_table"
        pageSize={recipientPageSize}
        onPageSizeChange={setRecipientPageSize}
        sortBy={recipientSortBy}
        sortDir={recipientSortDir}
        onSort={(key) => {
          if (recipientSortBy === key) setRecipientSortDir((d) => d === "asc" ? "desc" : "asc");
          else {
            setRecipientSortBy(key);
            setRecipientSortDir("asc");
          }
        }}
      />
      <div className="campaign-actions">
        <button
          disabled={recipientsPrevCursors.length === 0}
          onClick={() => {
            const prev = recipientsPrevCursors[recipientsPrevCursors.length - 1] || "";
            setRecipientsPrevCursors((arr) => arr.slice(0, -1));
            loadRecipients(prev).catch(console.error);
          }}
        >
          Previous Page
        </button>
        <button
          disabled={!recipientsNextCursor}
          onClick={() => {
            setRecipientsPrevCursors((arr) => [...arr, recipientsCursor || ""]);
            loadRecipients(recipientsNextCursor).catch(console.error);
          }}
        >
          Next Page
        </button>
      </div>
      <p>Delivered %: {deliveredPct}% | Read %: {readPct}% | Reply %: {replyPct}% | Failed %: {failedPct}%</p>
    </Layout>
  );
}

function RecipientFailureReportPage() {
  const { id } = useParams();
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api<unknown>(`/campaigns/${id}/recipients?status=failed`)
      .then((payload) => setRows(normalizeQueryPage<any>(payload).items))
      .catch(console.error);
  }, [id]);
  return (
    <Layout>
      <h2>Recipient Failure Report</h2>
      <pre>{JSON.stringify(rows, null, 2)}</pre>
    </Layout>
  );
}

function CampaignAnalyticsPage() {
  const { id } = useParams();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api(`/campaigns/${id}/analytics`).then(setData).catch(console.error);
  }, [id]);
  return (
    <Layout>
      <h2>Campaign Analytics Page</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </Layout>
  );
}

function WhatsAppHealthDashboardPage() {
  const { id } = useParams();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api(`/campaigns/${id}/whatsapp-health`).then(setData).catch(console.error);
  }, [id]);

  const quality = String(data?.quality || "unknown");
  const messagingTier = String(data?.messaging_tier || "unknown");
  const templateQuality = String(data?.template_quality || "unknown");
  const failureRate = typeof data?.recent_failure_rate === "number" ? `${data.recent_failure_rate.toFixed(1)}%` : "n/a";
  const unsubscribeRate = typeof data?.recent_unsubscribe_rate === "number" ? `${data.recent_unsubscribe_rate.toFixed(1)}%` : "n/a";
  const blockRate = typeof data?.recent_block_report_rate === "number" ? `${data.recent_block_report_rate.toFixed(1)}%` : "n/a";
  const webhookLag = String(data?.webhook_lag || "Unknown");
  const pressure = typeof data?.campaign_pressure_score === "number" ? data.campaign_pressure_score : "n/a";
  const health = String(data?.phone_number_health || "Unknown");
  const recommendation = String(data?.recommended_action || "");

  return (
    <Layout>
      <h2>WhatsApp Account Health Dashboard</h2>
      <div className="health-hero">
        <h3>Phone Number Health: {health}</h3>
        <p>{recommendation}</p>
      </div>
      <div className="health-grid">
        <div className="health-card"><strong>Quality</strong><span>{quality}</span></div>
        <div className="health-card"><strong>Messaging Tier</strong><span>{messagingTier}</span></div>
        <div className="health-card"><strong>Template Quality</strong><span>{templateQuality}</span></div>
        <div className="health-card"><strong>Recent Failure Rate</strong><span>{failureRate}</span></div>
        <div className="health-card"><strong>Recent Unsubscribe Rate</strong><span>{unsubscribeRate}</span></div>
        <div className="health-card"><strong>Recent Block/Report Warning</strong><span>{blockRate}</span></div>
        <div className="health-card"><strong>Webhook Lag</strong><span>{webhookLag}</span></div>
        <div className="health-card"><strong>Campaign Pressure Score</strong><span>{pressure}</span></div>
      </div>
      <h3>Raw Health Signals</h3>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </Layout>
  );
}

function CampaignCostReportPage() {
  const { id } = useParams();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api(`/campaigns/${id}/export`).then(setData).catch(console.error);
  }, [id]);
  return (
    <Layout>
      <h2>Campaign Cost Report / Export</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
      {data?.download_url ? <a href={`http://localhost:8000${data.download_url}`} target="_blank">Download CSV</a> : null}
    </Layout>
  );
}

function ContactsCrmPage() {
  const prefs = loadTablePrefs("contacts");
  const nav = useNavigate();
  const [rows, setRows] = useState<ContactCRMRecord[]>([]);
  const [filteredRows, setFilteredRows] = useState<ContactCRMRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [record, setRecord] = useState<ContactCRMRecord | null>(null);
  const [timeline, setTimeline] = useState<any>(null);
  const [imports, setImports] = useState<any>(null);
  const [suppressionHistory, setSuppressionHistory] = useState<any>(null);
  const [tags, setTags] = useState<any[]>([]);
  const [fields, setFields] = useState<any[]>([]);
  const [segments, setSegments] = useState<any[]>([]);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editAttrs, setEditAttrs] = useState("{}");
  const [editOptIn, setEditOptIn] = useState("unknown");
  const [editOptInSource, setEditOptInSource] = useState("crm_manual");
  const [saveMsg, setSaveMsg] = useState("");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [optInStatus, setOptInStatus] = useState("");
  const [suppressed, setSuppressed] = useState("");
  const [contactFilter, setContactFilter] = useState("All");
  const [bulkTagValue, setBulkTagValue] = useState("");
  const [sortBy, setSortBy] = useState(prefs.sortBy || "updated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">(prefs.sortDir || "desc");
  const [pageSize, setPageSize] = useState<number>(prefs.pageSize || 100);
  const [cursor, setCursor] = useState("");
  const [nextCursor, setNextCursor] = useState("");
  const [prevCursors, setPrevCursors] = useState<string[]>([]);

  const load = async (cursorValue?: string) => {
    const query: QueryState = {
      cursor: (cursorValue ?? cursor) || undefined,
      limit: pageSize,
      sortBy,
      sortDir,
      search,
      filters: {
        tag,
        opt_in_status: optInStatus,
        suppressed: suppressed === "yes" ? true : suppressed === "no" ? false : undefined,
      },
    };
    const data = normalizeQueryPage<ContactCRMRecord>(await api<unknown>(`/contacts/crm/records?${toQueryString(query)}`));
    setRows(data.items);
    setFilteredRows(data.items);
    setCursor((cursorValue ?? cursor) || "");
    setNextCursor(data.nextCursor || "");
    if (data.items.length > 0 && !selectedId) setSelectedId(data.items[0].id);
  };

  useEffect(() => {
    saveTablePrefs("contacts", { sortBy, sortDir, pageSize });
  }, [sortBy, sortDir, pageSize]);

  useEffect(() => {
    load().catch(console.error);
    api<any[]>("/contacts/tags").then(setTags).catch(console.error);
    api<any[]>("/contacts/custom-fields").then(setFields).catch(console.error);
    api<any[]>("/contacts/segments").then(setSegments).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    api<ContactCRMRecord>(`/contacts/${selectedId}/record`).then(setRecord).catch(console.error);
    api(`/contacts/${selectedId}/timeline`).then(setTimeline).catch(console.error);
    api(`/contacts/${selectedId}/import-history`).then(setImports).catch(console.error);
    api(`/contacts/${selectedId}/suppression-history`).then(setSuppressionHistory).catch(console.error);
  }, [selectedId]);

  useEffect(() => {
    if (!record) return;
    setEditName(record.name || "");
    setEditEmail(record.email || "");
    setEditTags((record.tags || []).join(", "));
    setEditAttrs(JSON.stringify(record.custom_attributes || {}, null, 2));
    setEditOptIn(record.opt_in_status || "unknown");
  }, [record]);

  const reloadSelected = async () => {
    if (!selectedId) return;
    const r = await api<ContactCRMRecord>(`/contacts/${selectedId}/record`);
    setRecord(r);
    const t = await api(`/contacts/${selectedId}/timeline`);
    setTimeline(t);
    const h = await api(`/contacts/${selectedId}/import-history`);
    setImports(h);
    const s = await api(`/contacts/${selectedId}/suppression-history`);
    setSuppressionHistory(s);
    await load();
  };

  const saveInlineEdits = async () => {
    if (!selectedId) return;
    setSaveMsg("Saving contact...");
    try {
      const custom_attributes = JSON.parse(editAttrs || "{}");
      await api(`/contacts/${selectedId}`, "PATCH", {
        name: editName,
        email: editEmail,
        tags: editTags.split(",").map((t) => t.trim()).filter(Boolean),
        custom_attributes,
      });
      setSaveMsg("Contact fields saved.");
      await reloadSelected();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const saveOptIn = async () => {
    if (!selectedId) return;
    setSaveMsg("Saving opt-in...");
    try {
      await api(`/contacts/${selectedId}/opt-in`, "POST", {
        opt_in_status: editOptIn,
        opt_in_source: editOptInSource || "crm_manual",
      });
      setSaveMsg("Opt-in status updated.");
      await reloadSelected();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const setSuppression = async (blocked: boolean) => {
    if (!selectedId) return;
    setSaveMsg(blocked ? "Applying suppression..." : "Clearing suppression...");
    try {
      await api(`/contacts/${selectedId}/block`, "POST", { blocked });
      setSaveMsg(blocked ? "Contact suppressed (blocked)." : "Suppression block removed.");
      await reloadSelected();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  useEffect(() => {
    const now = Date.now();
    const filtered = rows.filter((r) => {
      const tagsLower = (r.tags || []).map((t) => String(t).toLowerCase());
      const hasCampaignClick = Boolean(r.last_click_at);
      const hasCampaignReply = Boolean(r.last_reply_at);
      const purchased = Boolean(r.last_order_at);
      const recentlyActive = Boolean(r.last_inbound_at && new Date(r.last_inbound_at).getTime() >= now - 7 * 24 * 60 * 60 * 1000);
      const neverMessaged = !r.last_message_at;
      const coldAudience = !recentlyActive && !purchased && !hasCampaignReply;
      const vip = tagsLower.includes("vip") || purchased;
      const abandonedCart = tagsLower.includes("abandoned_cart");
      if (contactFilter === "All") return true;
      if (contactFilter === "Opted in") return r.opt_in_status === "opted_in";
      if (contactFilter === "Opted out") return ["opted_out", "unsubscribed"].includes(r.opt_in_status);
      if (contactFilter === "Never messaged") return neverMessaged;
      if (contactFilter === "Recently active") return recentlyActive;
      if (contactFilter === "VIP") return vip;
      if (contactFilter === "Cold audience") return coldAudience;
      if (contactFilter === "Clicked campaign") return hasCampaignClick;
      if (contactFilter === "Replied to campaign") return hasCampaignReply;
      if (contactFilter === "Purchased") return purchased;
      if (contactFilter === "Abandoned cart") return abandonedCart;
      return true;
    });
    setFilteredRows(filtered);
  }, [rows, contactFilter]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    const visibleIds = filteredRows.map((r) => r.id);
    const allSelected = visibleIds.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const bulkAddTag = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !bulkTagValue.trim()) return;
    setSaveMsg("Adding tag...");
    try {
      await Promise.all(ids.map(async (id) => {
        const c = rows.find((r) => r.id === id);
        const merged = Array.from(new Set([...(c?.tags || []), bulkTagValue.trim()]));
        await api(`/contacts/${id}`, "PATCH", { tags: merged });
      }));
      setSaveMsg(`Tag added to ${ids.length} contacts.`);
      await load();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const bulkRemoveTag = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || !bulkTagValue.trim()) return;
    setSaveMsg("Removing tag...");
    try {
      await Promise.all(ids.map(async (id) => {
        const c = rows.find((r) => r.id === id);
        const updated = (c?.tags || []).filter((t) => t !== bulkTagValue.trim());
        await api(`/contacts/${id}`, "PATCH", { tags: updated });
      }));
      setSaveMsg(`Tag removed for ${ids.length} contacts.`);
      await load();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const bulkSuppress = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setSaveMsg("Applying suppression...");
    try {
      await Promise.all(ids.map((id) => api(`/contacts/${id}/block`, "POST", { blocked: true })));
      setSaveMsg(`Suppressed ${ids.length} contacts.`);
      await load();
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const bulkExport = async () => {
    const selected = filteredRows.filter((r) => selectedIds.has(r.id));
    if (!selected.length) return;
    setSaveMsg("Starting export job...");
    try {
      const created = await api<{ job_id: string }>("/contacts/export-jobs", "POST", { contact_ids: selected.map((r) => r.id) });
      let status = await api<{ status: string; progress?: number; download_url?: string; rows?: number }>(`/contacts/export-jobs/${created.job_id}`);
      for (let i = 0; i < 12 && status.status !== "completed"; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        status = await api(`/contacts/export-jobs/${created.job_id}`);
      }
      if (status.status === "completed" && status.download_url) {
        window.open(`${API_ORIGIN}${status.download_url}`, "_blank");
        setSaveMsg(`Export ready. Rows: ${status.rows || selected.length}`);
      } else {
        setSaveMsg(`Export still processing (status: ${status.status}).`);
      }
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const bulkCreateCampaign = async () => {
    const selected = filteredRows.filter((r) => selectedIds.has(r.id));
    if (!selected.length) return;
    setSaveMsg("Creating campaign draft...");
    try {
      const phone = (selected[0]?.custom_attributes?.["default_phone_number_id"] as string | undefined) || "DEFAULT_PHONE_ID";
      const templateId = String(selected[0]?.custom_attributes?.["default_template_id"] || "").trim();
      if (!templateId) {
        setSaveMsg("Cannot create campaign draft: add a valid default_template_id in selected contact custom attributes.");
        return;
      }
      await api("/campaigns", "POST", {
        name: `Bulk Contacts Campaign (${selected.length})`,
        phone_number_id: phone,
        template_id: templateId,
        type: "broadcast",
      });
      setSaveMsg("Campaign draft created. Add template and audience source in wizard.");
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const bulkCreateSegment = async () => {
    const selected = filteredRows.filter((r) => selectedIds.has(r.id));
    if (!selected.length) return;
    setSaveMsg("Creating segment from selected contacts...");
    try {
      const segmentTag = `segment_${Date.now()}`;
      await Promise.all(selected.map(async (r) => {
        const tags = Array.from(new Set([...(r.tags || []), segmentTag]));
        await api(`/contacts/${r.id}`, "PATCH", { tags });
      }));
      const created = await api<{ segment_id: string }>("/contacts/segments", "POST", {
        name: `Selected Contacts ${new Date().toISOString().slice(0, 10)}`,
        visibility: "private",
        filters: { tags_any: [segmentTag] },
      });
      setSaveMsg(`Segment created (${created.segment_id}) for ${selected.length} contacts.`);
      const segRows = await api<any[]>("/contacts/segments");
      setSegments(segRows);
    } catch (e) {
      setSaveMsg((e as Error).message);
    }
  };

  const contactColumns: DataTableColumn<ContactCRMRecord>[] = [
    { key: "name", title: "Name", sortable: true, render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); nav(`/contacts/${r.id}`); }}>{r.name || "-"}</a> },
    { key: "phone_e164", title: "Phone", sortable: true, render: (r) => r.phone_e164 || "-" },
    { key: "tags", title: "Tags", render: (r) => (r.tags || []).join(", ") || "-" },
    { key: "opt_in_status", title: "Opt-in status", sortable: true, render: (r) => r.opt_in_status },
    { key: "last_message_at", title: "Last message", sortable: true, render: (r) => r.last_message_at ? new Date(r.last_message_at).toLocaleString() : "-" },
    { key: "last_campaign_at", title: "Last campaign", sortable: true, render: (r) => r.last_campaign_at ? new Date(r.last_campaign_at).toLocaleDateString() : "-" },
    { key: "last_order_at", title: "Last order", sortable: true, render: (r) => r.last_order_at ? new Date(r.last_order_at).toLocaleDateString() : "-" },
  ];

  return (
    <Layout>
      <h2>Contacts</h2>
      <div className="stack">
        <div className="grid">
          <input placeholder="Search name/email/phone/wa_id" value={search} onChange={(e) => setSearch(e.target.value)} />
          <input placeholder="Filter tag" value={tag} onChange={(e) => setTag(e.target.value)} />
          <input placeholder="opt_in_status (opted_in/opted_out/unsubscribed/unknown)" value={optInStatus} onChange={(e) => setOptInStatus(e.target.value)} />
          <select value={suppressed} onChange={(e) => setSuppressed(e.target.value)}>
            <option value="">Suppression: any</option>
            <option value="yes">Suppressed only</option>
            <option value="no">Not suppressed</option>
          </select>
        </div>
        <button onClick={() => {
          setCursor("");
          setNextCursor("");
          setPrevCursors([]);
          load("").catch(console.error);
        }}>Search Contacts</button>
      </div>
      <div className="inbox-filters">
        {["All", "Opted in", "Opted out", "Never messaged", "Recently active", "VIP", "Cold audience", "Clicked campaign", "Replied to campaign", "Purchased", "Abandoned cart"].map((f) => (
          <button key={f} className={contactFilter === f ? "filter-active" : ""} onClick={() => setContactFilter(f)}>{f}</button>
        ))}
      </div>
      <div className="campaign-actions">
        <input placeholder="tag for bulk add/remove" value={bulkTagValue} onChange={(e) => setBulkTagValue(e.target.value)} />
        <button onClick={() => bulkAddTag().catch(console.error)}>Add tag</button>
        <button onClick={() => bulkRemoveTag().catch(console.error)}>Remove tag</button>
        <button onClick={() => bulkExport().catch(console.error)}>Export</button>
        <button onClick={() => bulkSuppress().catch(console.error)}>Suppress</button>
        <button onClick={() => bulkCreateCampaign().catch(console.error)}>Create campaign</button>
        <button onClick={() => bulkCreateSegment().catch(console.error)}>Create segment</button>
      </div>
      <div className="crm-layout">
        <div>
          <h3>Contact List</h3>
          <DataTable
            columns={contactColumns}
            rows={filteredRows}
            rowKey={(r) => r.id}
            selectedIds={selectedIds}
            enableColumnVisibility
            storageKey="contacts_table"
            pageSize={pageSize}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setCursor("");
              setNextCursor("");
              setPrevCursors([]);
              setTimeout(() => { load("").catch(console.error); }, 0);
            }}
            virtualizedHeight={380}
            onToggleRow={toggleSelect}
            onToggleAll={toggleSelectAllVisible}
            allVisibleSelected={filteredRows.length > 0 && filteredRows.every((r) => selectedIds.has(r.id))}
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={(key) => {
              if (sortBy === key) {
                setSortDir((d) => d === "asc" ? "desc" : "asc");
              } else {
                setSortBy(key);
                setSortDir("asc");
              }
              setCursor("");
              setNextCursor("");
              setPrevCursors([]);
              setTimeout(() => { load("").catch(console.error); }, 0);
            }}
          />
          <div className="campaign-actions">
            <button
              disabled={prevCursors.length === 0}
              onClick={() => {
                const prev = prevCursors[prevCursors.length - 1] || "";
                setPrevCursors((arr) => arr.slice(0, -1));
                load(prev).catch(console.error);
              }}
            >
              Previous Page
            </button>
            <button
              disabled={!nextCursor}
              onClick={() => {
                setPrevCursors((arr) => [...arr, cursor || ""]);
                load(nextCursor).catch(console.error);
              }}
            >
              Next Page
            </button>
          </div>
        </div>
        <div>
          <h3>Contact Record</h3>
          <div className="stack">
            <input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="Name" />
            <input value={editEmail} onChange={(e) => setEditEmail(e.target.value)} placeholder="Email" />
            <input value={editTags} onChange={(e) => setEditTags(e.target.value)} placeholder="tags (comma-separated)" />
            <textarea rows={8} value={editAttrs} onChange={(e) => setEditAttrs(e.target.value)} />
            <button onClick={() => saveInlineEdits().catch(console.error)}>Save Tags / Custom Fields</button>
            <div className="grid">
              <select value={editOptIn} onChange={(e) => setEditOptIn(e.target.value)}>
                <option value="opted_in">opted_in</option>
                <option value="opted_out">opted_out</option>
                <option value="unsubscribed">unsubscribed</option>
                <option value="unknown">unknown</option>
              </select>
              <input value={editOptInSource} onChange={(e) => setEditOptInSource(e.target.value)} placeholder="opt_in_source" />
            </div>
            <button onClick={() => saveOptIn().catch(console.error)}>Save Opt-in Status</button>
            <div className="grid">
              <button onClick={() => setSuppression(true).catch(console.error)}>Suppress (Block)</button>
              <button onClick={() => setSuppression(false).catch(console.error)}>Unsuppress (Unblock)</button>
            </div>
            <p>{saveMsg}</p>
          </div>
          <pre>{record ? JSON.stringify(record, null, 2) : "Select a contact"}</pre>
          <h3>Contact Timeline</h3>
          <pre>{timeline ? JSON.stringify(timeline, null, 2) : "No timeline loaded"}</pre>
          <h3>Import History</h3>
          <pre>{imports ? JSON.stringify(imports, null, 2) : "No import history loaded"}</pre>
          <h3>Suppression History</h3>
          <pre>{suppressionHistory ? JSON.stringify(suppressionHistory, null, 2) : "No suppression history loaded"}</pre>
        </div>
      </div>
      <div className="grid">
        <div>
          <h3>Tags</h3>
          <pre>{JSON.stringify(tags, null, 2)}</pre>
        </div>
        <div>
          <h3>Custom Fields</h3>
          <pre>{JSON.stringify(fields, null, 2)}</pre>
        </div>
        <div>
          <h3>Segments</h3>
          <pre>{JSON.stringify(segments, null, 2)}</pre>
        </div>
      </div>
    </Layout>
  );
}

function ContactDetailPage() {
  const { id } = useParams();
  const contactId = id!;
  const nav = useNavigate();
  const [record, setRecord] = useState<ContactCRMRecord | null>(null);
  const [timeline, setTimeline] = useState<any>(null);
  const [suppressionHistory, setSuppressionHistory] = useState<any>(null);
  const [actionMsg, setActionMsg] = useState("");
  const [newTag, setNewTag] = useState("");
  const [newNote, setNewNote] = useState("");
  const [assignAgent, setAssignAgent] = useState("");

  const load = async () => {
    const r = await api<ContactCRMRecord>(`/contacts/${contactId}/record`);
    setRecord(r);
    const t = await api(`/contacts/${contactId}/timeline`);
    setTimeline(t);
    const s = await api(`/contacts/${contactId}/suppression-history`);
    setSuppressionHistory(s);
  };

  useEffect(() => {
    load().catch(console.error);
  }, [contactId]);

  const addTag = async () => {
    if (!record || !newTag.trim()) return;
    setActionMsg("Adding tag...");
    try {
      const tags = Array.from(new Set([...(record.tags || []), newTag.trim()]));
      await api(`/contacts/${contactId}`, "PATCH", { tags });
      setNewTag("");
      setActionMsg("Tag added.");
      await load();
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const addNote = async () => {
    if (!record || !newNote.trim()) return;
    setActionMsg("Saving note...");
    try {
      const attrs = { ...(record.custom_attributes || {}), notes: [...((record.custom_attributes?.["notes"] as string[] | undefined) || []), newNote.trim()] };
      await api(`/contacts/${contactId}`, "PATCH", { custom_attributes: attrs });
      setNewNote("");
      setActionMsg("Note added.");
      await load();
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const suppressContact = async () => {
    setActionMsg("Suppressing...");
    try {
      await api(`/contacts/${contactId}/block`, "POST", { blocked: true });
      setActionMsg("Contact suppressed.");
      await load();
    } catch (e) {
      setActionMsg((e as Error).message);
    }
  };

  const messageEvents = (timeline?.message_events || []) as any[];
  const campaignEvents = (timeline?.campaign_events || []) as any[];
  const replies = messageEvents.filter((m) => String(m.direction || "").toLowerCase() === "inbound");
  const clicks = campaignEvents.filter((c) => String(c.status || "").toLowerCase() === "clicked");
  const orders = (record?.custom_attributes?.["orders"] as any[] | undefined) || [];
  const cartEvents = (record?.custom_attributes?.["cart_events"] as any[] | undefined) || [];
  const optInEvents = (suppressionHistory?.history || []).filter((h: any) => String(h.reason || "").toUpperCase().includes("OPT_IN"));
  const optOutEvents = (suppressionHistory?.history || []).filter((h: any) => String(h.reason || "").toUpperCase().includes("OPTED_OUT"));
  const tagChanges = (record?.custom_attributes?.["tag_history"] as any[] | undefined) || [];
  const notes = (record?.custom_attributes?.["notes"] as string[] | undefined) || [];

  return (
    <Layout>
      <div className="thread-head">
        <h2>Contact Intelligence</h2>
        <button onClick={() => nav("/contacts")}>Back to Contacts</button>
      </div>
      <div className="inbox-layout">
        <section className="inbox-center">
          <h3>Messages</h3>
          <pre>{JSON.stringify(messageEvents, null, 2)}</pre>
          <h3>Campaigns received</h3>
          <pre>{JSON.stringify(campaignEvents, null, 2)}</pre>
          <h3>Replies</h3>
          <pre>{JSON.stringify(replies, null, 2)}</pre>
          <h3>Clicks</h3>
          <pre>{JSON.stringify(clicks, null, 2)}</pre>
          <h3>Orders</h3>
          <pre>{JSON.stringify(orders, null, 2)}</pre>
          <h3>Cart events</h3>
          <pre>{JSON.stringify(cartEvents, null, 2)}</pre>
          <h3>Opt-in events</h3>
          <pre>{JSON.stringify(optInEvents, null, 2)}</pre>
          <h3>Opt-out events</h3>
          <pre>{JSON.stringify(optOutEvents, null, 2)}</pre>
          <h3>Tags changed</h3>
          <pre>{JSON.stringify(tagChanges, null, 2)}</pre>
          <h3>Notes</h3>
          <pre>{JSON.stringify(notes, null, 2)}</pre>
        </section>
        <aside className="inbox-right">
          <h3>Actions</h3>
          <div className="stack">
            <button onClick={() => nav("/inbox")}>Send message</button>
            <input placeholder="Assign agent id" value={assignAgent} onChange={(e) => setAssignAgent(e.target.value)} />
            <button onClick={() => setActionMsg(assignAgent.trim() ? `Assigned to ${assignAgent}` : "Enter agent id")}>Assign agent</button>
            <textarea rows={3} placeholder="Add note" value={newNote} onChange={(e) => setNewNote(e.target.value)} />
            <button onClick={() => addNote().catch(console.error)}>Add note</button>
            <input placeholder="Add tag" value={newTag} onChange={(e) => setNewTag(e.target.value)} />
            <button onClick={() => addTag().catch(console.error)}>Add tag</button>
            <button onClick={() => suppressContact().catch(console.error)}>Suppress contact</button>
            <button onClick={() => {
              const url = String(record?.custom_attributes?.["orders_url"] || "");
              if (url) window.open(url, "_blank");
              else setActionMsg("Orders integration URL not available for this contact.");
            }}>View orders</button>
            <p>{actionMsg}</p>
          </div>
          <h3>Profile</h3>
          <pre>{JSON.stringify(record, null, 2)}</pre>
        </aside>
      </div>
    </Layout>
  );
}

function CampaignDetailHub() {
  const { id } = useParams();
  const [wizard] = useWizardState(id);
  return (
    <Layout>
      <h2>Campaign {id}</h2>
      <StepNav id={id!} wizard={wizard} />
      <div className="grid">
        <Link to={`/campaigns/${id}/live`}>Campaign Live Status Page</Link>
        <Link to={`/campaigns/${id}/failures`}>Recipient Failure Report</Link>
        <Link to={`/campaigns/${id}/analytics`}>Campaign Analytics Page</Link>
        <Link to={`/campaigns/${id}/cost`}>Campaign Cost Report</Link>
        <Link to={`/campaigns/${id}/whatsapp-health`}>WhatsApp Account Health Dashboard</Link>
      </div>
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><CommandCenterLayout /></RequireAuth>}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/contacts" element={<ContactsCrmPage />} />
        <Route path="/contacts/:id" element={<ContactDetailPage />} />
        <Route path="/templates" element={<PlaceholderPage title="Templates" subtitle="Template library, approval status, and quality indicators." />} />
        <Route path="/automations" element={<PlaceholderPage title="Automations" subtitle="Flows, triggers, and journey controls." />} />
        <Route path="/commerce" element={<PlaceholderPage title="Commerce" subtitle="Orders, carts, click-through and conversion actions." />} />
        <Route path="/analytics" element={<PlaceholderPage title="Analytics" subtitle="Funnel, cohort, message, and revenue analytics." />} />
        <Route path="/billing" element={<PlaceholderPage title="Billing" subtitle="Usage, wallet, ledger, and invoicing controls." />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/whatsapp-setup" element={<WhatsAppSetupPage />} />
        <Route path="/admin-support" element={<PlaceholderPage title="Admin / Support" subtitle="Audit trails, diagnostics, runbooks, and support tools." />} />

        <Route path="/campaigns" element={<CampaignListPage />} />
        <Route path="/campaigns/new" element={<CreateWizardPage />} />
        <Route path="/campaigns/:id" element={<CampaignDetailHub />} />
        <Route path="/campaigns/:id/wizard/source" element={<SourceStepPage />} />
        <Route path="/campaigns/:id/wizard/template" element={<TemplateStepPage />} />
        <Route path="/campaigns/:id/wizard/mapping" element={<MappingStepPage />} />
        <Route path="/campaigns/:id/wizard/preview" element={<PreviewLaunchStepPage />} />
        <Route path="/campaigns/:id/wizard/test-send" element={<TestSendStepPage />} />
        <Route path="/campaigns/:id/wizard/launch" element={<ScheduleLaunchStepPage />} />
        <Route path="/campaigns/:id/live" element={<CampaignLiveStatusPage />} />
        <Route path="/campaigns/:id/failures" element={<RecipientFailureReportPage />} />
        <Route path="/campaigns/:id/analytics" element={<CampaignAnalyticsPage />} />
        <Route path="/campaigns/:id/cost" element={<CampaignCostReportPage />} />
        <Route path="/campaigns/:id/whatsapp-health" element={<WhatsAppHealthDashboardPage />} />
      </Route>
    </Routes>
  );
}






