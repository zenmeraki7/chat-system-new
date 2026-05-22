import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api } from "../../../api";
import { DataTable, type DataTableColumn } from "../../../components/DataTable";
import { RemoteDataTable } from "../../../components/RemoteDataTable";
import { normalizeQueryPage, toQueryString, type QueryState, type SelectionState } from "../../../lib/queryContract";
import { ONBOARDING_SEQUENCE } from "../onboardingStateMachine";
import { useBusinessContext, useWidgetSettings } from "../../../app/shared/businessContext";
import { loadTablePrefs, saveTablePrefs } from "../../../app/shared/tablePrefs";
import { clearAuthStorage } from "../../../app/shared/authStorage";
import { safeDownloadUrl, safeLogClientError, toUserErrorMessage } from "../../../app/shared/clientSafety";

type Campaign = {
  [x: string]: number;
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

type WhatsAppTemplate = {
  id: string;
  waba_id: string;
  meta_template_id?: string | null;
  name: string;
  language: string;
  category?: string | null;
  status: string;
  components_json: Record<string, unknown>;
  rejection_reason?: string | null;
  last_synced_at?: string | null;
  created_at: string;
  updated_at: string;
};

type TemplateSummary = {
  total: number;
  approved_or_active: number;
  pending_or_in_review: number;
  rejected_or_paused: number;
  draft_or_unknown: number;
};

type TemplateSyncRun = {
  run_id: string;
  provider: string;
  sync_type: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  failure_reason?: string | null;
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
  created_at?: string | null;
  updated_at?: string | null;
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
  id?: string;
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
  onboarding_state: string;
  business_id?: string | null;
  waba_id?: string | null;
  phone_number_id?: string | null;
  display_phone_number?: string | null;
  verified_name?: string | null;
  display_name_status?: string | null;
  business_verification_status?: string | null;
  phone_number_quality_rating?: string | null;
  messaging_limit_tier?: string | null;
  cloud_api_registered?: boolean;
  two_step_verification_required?: boolean;
  webhook_subscribed?: boolean;
  test_message_passed?: boolean;
  message_test_passed?: boolean;
  blocking_reasons?: Array<{ code: string; title: string; recovery_action: string }>;
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
type CampaignPreviewResponse = {
  sample_messages?: unknown[];
  preview_messages?: unknown[];
  selected_recipients?: number;
  total_recipients?: number;
  eligible_recipients?: number;
  skipped_recipients?: number;
  estimated_cost?: { currency?: string; amount?: number };
  estimated_duration_minutes?: number;
};
type LaunchConfirmationResponse = {
  confirmation_hash?: string;
  template_name?: string;
  template_id?: string;
  phone_number_id?: string;
  recipients?: number;
  estimated_cost?: { currency?: string; amount?: number };
};
type SegmentDiagnosticsResponse = {
  campaign_id: string;
  original_count: number;
  safe_audience_count: number;
  expected_revenue_loss: string;
  quality_risk_reduction: string;
  issues: {
    unclear_opt_in: number;
    stale_engagement_180d: number;
    ignored_3plus_campaigns: number;
    complained_or_refunded_recently: number;
    outside_delivery_area: number;
  };
};
type CampaignEvent = {
  created_at?: string;
  event_type?: string;
  new_status?: string;
  kind?: string;
  reason?: string;
};
type CampaignBlackboxEvent = {
  observed_at?: string;
  created_at?: string;
  event_type?: string;
  message?: string;
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

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    const devBypassEnabled = import.meta.env.DEV && String(import.meta.env.VITE_DEV_AUTH_BYPASS || "false").toLowerCase() === "true";
    if (devBypassEnabled) {
      if (!sessionStorage.getItem("auth_business_name")) sessionStorage.setItem("auth_business_name", "Dev Business");
      if (!sessionStorage.getItem("auth_business_id")) sessionStorage.setItem("auth_business_id", "dev-business");      setAllowed(true);
      setChecking(false);
      return;
    }
    const token = sessionStorage.getItem("access_token") || sessionStorage.getItem("token") || sessionStorage.getItem("auth_token") || sessionStorage.getItem("jwt") || sessionStorage.getItem("bearer_token");
    if (!token) {
      setAllowed(false);
      setChecking(false);
      return;
    }
    api<MeProfile>("/auth/me")
      .then((profile) => {
        if (profile?.business_name) sessionStorage.setItem("auth_business_name", profile.business_name);
        if (profile?.id) {
          sessionStorage.setItem("auth_business_id", profile.id);
          sessionStorage.setItem("auth_user_id", profile.id);
        }
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

  const finishLogin = async (loginEmail: string, loginPassword: string) => {
    const result = await api<AuthLoginResponse>("/auth/login", "POST", { email: loginEmail.trim(), password: loginPassword });
    sessionStorage.setItem("access_token", result.access_token);    try {
      const me = await api<MeProfile>("/auth/me");
      if (me?.business_name) sessionStorage.setItem("auth_business_name", me.business_name);
      if (me?.id) {
          sessionStorage.setItem("auth_business_id", me.id);
          sessionStorage.setItem("auth_user_id", me.id);
        }
    } catch {
      // Ignore secondary profile bootstrap failure; token is already persisted.
    }
    const target = (location.state as { from?: string } | null)?.from || "/dashboard";
    nav(target, { replace: true });
  };

  useEffect(() => {
    const devBypassEnabled = import.meta.env.DEV && String(import.meta.env.VITE_DEV_AUTH_BYPASS || "false").toLowerCase() === "true";
    if (devBypassEnabled) {
      nav("/dashboard", { replace: true });
      return;
    }
    if (!import.meta.env.DEV) return;
    if (sessionStorage.getItem("dev_auto_login_attempted") === "1") return;
    sessionStorage.setItem("dev_auto_login_attempted", "1");
    const devEmail = (import.meta.env.VITE_DEV_AUTO_LOGIN_EMAIL as string | undefined) || "owner@test.com";
    const devPassword = (import.meta.env.VITE_DEV_AUTO_LOGIN_PASSWORD as string | undefined) || "StrongPass123!";
    setEmail(devEmail);
    setPassword(devPassword);
    setBusy(true);
    setErr("");
    finishLogin(devEmail, devPassword)
      .catch((e) => {
        setErr(toUserErrorMessage(e));
        clearAuthStorage();
      })
      .finally(() => setBusy(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await finishLogin(email, password);
    } catch (e) {
      setErr(toUserErrorMessage(e));
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

function RevenuePage() {
  const [overview, setOverview] = useState<any>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      api<any>("/analytics/overview"),
      api<unknown>("/campaigns?limit=200"),
    ])
      .then(([o, c]) => {
        if (!active) return;
        setOverview(o || null);
        setCampaigns(normalizeQueryPage<Campaign>(c).items);
      })
      .catch((e) => {
        if (!active) return;
        setErr(toUserErrorMessage(e) || "Unable to load revenue data");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const campaignCost = campaigns.reduce((sum, c) => sum + Number(c.actual_cost || 0), 0);
  const sent = campaigns.reduce((sum, c) => sum + Number(c.sent_count || 0), 0);
  const delivered = campaigns.reduce((sum, c) => sum + Number(c.delivered_count || 0), 0);
  const failed = campaigns.reduce((sum, c) => sum + Number(c.failed_count || 0), 0);
  const read = campaigns.reduce((sum, c) => sum + Number(c.read_count || 0), 0);
  const replied = campaigns.reduce((sum, c) => sum + Number(c.replied_count || 0), 0);
  const convRate = delivered > 0 ? (read / delivered) * 100 : 0;
  const replyRate = delivered > 0 ? (replied / delivered) * 100 : 0;

  return (
    <Layout>
      <h2>Revenue & Performance</h2>
      {loading ? <p>Loading revenue data...</p> : null}
      {err ? <p>{err}</p> : null}
      <section className="kpi-grid">
        <article className="kpi-card"><h4>Total campaign spend</h4><p>USD {campaignCost.toFixed(2)}</p></article>
        <article className="kpi-card"><h4>Messages sent</h4><p>{sent}</p></article>
        <article className="kpi-card"><h4>Delivered</h4><p>{delivered}</p></article>
        <article className="kpi-card"><h4>Failed</h4><p>{failed}</p></article>
        <article className="kpi-card"><h4>Read rate</h4><p>{convRate.toFixed(1)}%</p></article>
        <article className="kpi-card"><h4>Reply rate</h4><p>{replyRate.toFixed(1)}%</p></article>
      </section>
      <section className="panel">
        <h3>Live overview</h3>
        <p>Detailed diagnostics are restricted in merchant view.</p>
      </section>
    </Layout>
  );
}

function PlaceholderPage({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <Layout>
      <h2>{title}</h2>
      <p>{subtitle}</p>
      {title === "Automations" ? <WhatsAppSafetyScoreCard context="automation" /> : null}
    </Layout>
  );
}

type SafetyContext = "campaign" | "template" | "automation" | "segment" | "phone_number";

function WhatsAppSafetyScoreCard({ context }: { context: SafetyContext }) {
  const { id } = useParams();
  const [risk, setRisk] = useState<{ score?: number; risk_level?: string; reasons?: string[]; required_actions?: string[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams({ context });
    if (context === "campaign" && id) params.set("campaign_id", id);
    api(`/risk/whatsapp-safety-score?${params.toString()}`)
      .then((payload) => setRisk((payload as any) || null))
      .catch(() => setRisk(null))
      .finally(() => setLoading(false));
  }, [context, id]);

  return (
    <section className="signature-safety-card">
      <div className="signature-safety-head">
        <h3>WhatsApp Safety Score</h3>
        <span>{context.replace("_", " ")}</span>
      </div>
      <div className="signature-safety-score">{loading ? "--" : Number(risk?.score || 0)}<small>/100</small></div>
      <p className="signature-safety-note"><strong>Risk Level:</strong> {risk?.risk_level || "UNKNOWN"}</p>
      <div className="signature-safety-grid">
        <div><span>Reasons</span><strong>{(risk?.reasons || []).length}</strong></div>
        <div><span>Required Actions</span><strong>{(risk?.required_actions || []).length}</strong></div>
      </div>
      {(risk?.reasons || []).length ? <ul className="compact-list">{(risk?.reasons || []).slice(0, 3).map((r) => <li key={r}>{r}</li>)}</ul> : null}
      {(risk?.required_actions || []).length ? <ul className="compact-list">{(risk?.required_actions || []).slice(0, 3).map((a) => <li key={a}>{a}</li>)}</ul> : null}
    </section>
  );
}

function DashboardPage() {
  const nav = useNavigate();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [conversations, setConversations] = useState<ConversationInboxItem[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);
  const [failedSends, setFailedSends] = useState<any[]>([]);
  const [merchantMode, setMerchantMode] = useState<"shopify" | "offline">(
    () => (localStorage.getItem("merchant_mode") as "shopify" | "offline" | null) || "offline"
  );

  useEffect(() => {
    localStorage.setItem("merchant_mode", merchantMode);
  }, [merchantMode]);

  useEffect(() => {
    api<unknown>("/campaigns?limit=100")
      .then((payload) => setCampaigns(normalizeQueryPage<Campaign>(payload).items))
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<unknown>("/conversations?limit=100")
      .then((payload) => setConversations(normalizeQueryPage<ConversationInboxItem>(payload).items))
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, []);

  const primaryCampaignId = useMemo(() => {
    const running = campaigns.find((c) => ["queued", "running", "dispatching"].includes(String(c.status || "").toLowerCase()));
    return (running || campaigns[0])?.campaign_id || "";
  }, [campaigns]);

  useEffect(() => {
    if (!primaryCampaignId) return;
    api(`/campaigns/${primaryCampaignId}/whatsapp-health`).then(setHealth).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<CampaignAnalytics>(`/campaigns/${primaryCampaignId}/analytics`).then(setAnalytics).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<unknown>(`/campaigns/${primaryCampaignId}/recipients?status=failed&limit=5`)
      .then((payload) => setFailedSends(normalizeQueryPage<any>(payload).items))
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      <section className="merchant-mode-selector">
        <div className="merchant-mode-head">
          <h3>Choose Your Business Setup</h3>
          <p>Start with the path that matches your merchant operations.</p>
        </div>
        <div className="merchant-mode-grid">
          <article className={`merchant-mode-card ${merchantMode === "shopify" ? "active" : ""}`}>
            <strong>Connect with your Shopify store</strong>
            <span>Sync products, orders, and customer events automatically.</span>
            <button onClick={() => { setMerchantMode("shopify"); nav("/onboarding/shopify"); }}>Choose Shopify</button>
          </article>
          <article className={`merchant-mode-card ${merchantMode === "offline" ? "active" : ""}`}>
            <strong>I am running an offline business</strong>
            <span>Use CSV, Sheets, POS exports, and manual contact enrichment.</span>
            <button onClick={() => { setMerchantMode("offline"); nav("/onboarding/offline"); }}>Choose Offline</button>
          </article>
        </div>
      </section>
      <section className="analytics-hero">
        <div>
          <span>Live Command Analytics</span>
          <h2>Business performance control room</h2>
          <p>Campaign delivery, inbox pressure, phone health, webhook status, and revenue signals in one operational view.</p>
        </div>
        <button onClick={() => window.location.reload()}>Refresh data</button>
      </section>
      <div className="dashboard-kpis analytics-kpis">
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

      <div className="dashboard-widgets analytics-widgets">
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

function TemplateApprovalPage() {
  const nav = useNavigate();
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [summary, setSummary] = useState<TemplateSummary | null>(null);
  const [runs, setRuns] = useState<TemplateSyncRun[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => {
    const [templateRows, summaryRow, runRows] = await Promise.all([
      api<WhatsAppTemplate[]>(`/templates?${toQueryString({ search: search || undefined, limit: 200 })}`),
      api<TemplateSummary>("/templates/summary"),
      api<TemplateSyncRun[]>("/templates/sync/runs?limit=8"),
    ]);
    setTemplates(templateRows);
    setSummary(summaryRow);
    setRuns(runRows);
    if (templateRows.length && !selectedId) setSelectedId(templateRows[0].id);
  };

  useEffect(() => { load().catch((e) => setMsg(toUserErrorMessage(e))); }, []);

  const syncTemplates = async () => {
    setSyncing(true);
    setMsg("Syncing templates from Meta...");
    try {
      const res = await api<{ status: string; templates_fetched: number; templates_upserted: number; failure_reason?: string | null }>("/templates/sync", "POST", {});
      setMsg(res.failure_reason || `Sync ${res.status}: fetched ${res.templates_fetched}, updated ${res.templates_upserted}.`);
      await load();
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    } finally {
      setSyncing(false);
    }
  };

  const filtered = templates.filter((t) => {
    const normalized = String(t.status || "").toLowerCase();
    if (filter === "approved") return ["approved", "active"].includes(normalized);
    if (filter === "pending") return ["pending", "in_review", "submitted"].includes(normalized);
    if (filter === "rejected") return ["rejected", "paused", "disabled"].includes(normalized);
    if (filter === "draft") return !["approved", "active", "pending", "in_review", "submitted", "rejected", "paused", "disabled"].includes(normalized);
    return true;
  });
  const selected = templates.find((t) => t.id === selectedId) || filtered[0] || null;
  const lastSyncItems = templates.map((t) => t.last_synced_at).filter(Boolean).sort();
  const lastSync = lastSyncItems.length ? lastSyncItems[lastSyncItems.length - 1] : undefined;

  return (
    <div className="template-page">
      <aside className="template-sidebar">
        <div className="template-brand">Command Center<span>Template ops</span></div>
        <button onClick={() => nav('/dashboard')}>Dashboard</button><button onClick={() => nav('/contacts')}>Contacts</button><button onClick={() => nav('/inbox')}>Inbox</button><button className="active">Templates</button><button onClick={() => nav('/settings/whatsapp-setup')}>WhatsApp setup</button>
      </aside>
      <main className="template-main">
        <header className="template-hero"><div><span>WhatsApp template library</span><h1>Sync, review, and approve message templates before campaign launch.</h1><p>Keep the local CRM catalog aligned with Meta, catch rejected or pending templates, and promote approved templates into campaign workflows.</p></div><button onClick={() => syncTemplates().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} disabled={syncing}>{syncing ? "Syncing..." : "Sync from Meta"}</button></header>
        <WhatsAppSafetyScoreCard context="template" />
        <section className="template-stats"><article><span>Total</span><strong>{summary?.total ?? templates.length}</strong></article><article><span>Approved</span><strong className="ok">{summary?.approved_or_active ?? 0}</strong></article><article><span>In review</span><strong className="warn">{summary?.pending_or_in_review ?? 0}</strong></article><article><span>Rejected</span><strong className="bad">{summary?.rejected_or_paused ?? 0}</strong></article><article><span>Last sync</span><strong>{lastSync ? new Date(lastSync).toLocaleDateString() : "Never"}</strong></article></section>
        <section className="template-workbench"><div className="template-list-card"><div className="template-toolbar"><input placeholder="Search templates..." value={search} onChange={(e) => setSearch(e.target.value)} /><button onClick={() => load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Search</button></div><div className="template-filters">{[["all","All"],["approved","Approved"],["pending","Pending"],["rejected","Rejected"],["draft","Draft/unknown"]].map(([id,label]) => <button key={id} className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>{label}</button>)}</div><div className="template-list">{filtered.map((t) => <article key={t.id} className={selected?.id === t.id ? "active" : ""} onClick={() => setSelectedId(t.id)}><div><strong>{t.name}</strong><span>{t.category || "uncategorized"} · {t.language}</span></div><em className={`tpl-status ${String(t.status).toLowerCase()}`}>{t.status}</em></article>)}</div></div>
          <aside className="template-detail-card">{selected ? <><div className="detail-head"><span className={`tpl-status ${String(selected.status).toLowerCase()}`}>{selected.status}</span><h2>{selected.name}</h2><p>{selected.meta_template_id || selected.id}</p></div><div className="detail-grid"><div><span>WABA</span><strong>{selected.waba_id}</strong></div><div><span>Language</span><strong>{selected.language}</strong></div><div><span>Category</span><strong>{selected.category || "-"}</strong></div><div><span>Synced</span><strong>{selected.last_synced_at ? new Date(selected.last_synced_at).toLocaleString() : "Never"}</strong></div></div>{selected.rejection_reason ? <div className="template-reject"><strong>Rejection reason</strong><p>{selected.rejection_reason}</p></div> : null}<p>Template content is provider-managed and hidden in merchant view.</p><div className="template-actions"><button onClick={() => syncTemplates().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} disabled={syncing}>{syncing ? "Syncing..." : "Sync from Meta"}</button></div></> : <p>No template selected.</p>}</aside>
        </section>
        <section className="sync-runs"><div><h3>Recent sync runs</h3><p>{msg || "Provider-authoritative sync history from Meta template graph."}</p></div>{runs.map((r) => <article key={r.run_id}><strong>{r.status}</strong><span>{r.completed_at ? new Date(r.completed_at).toLocaleString() : r.started_at ? new Date(r.started_at).toLocaleString() : "Not started"}</span>{r.failure_reason ? <em>{r.failure_reason}</em> : null}</article>)}</section>
      </main>
    </div>
  );
}
function SettingsPage() {
  const widget = useWidgetSettings();
  const [widgetColor, setWidgetColor] = useState("#25D366");
  const [qrPrefillText, setQrPrefillText] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!widget) return;
    setWidgetColor(widget.widget_color || "#25D366");
    setQrPrefillText(widget.widget_title || "");
  }, [widget]);

  const save = async () => {
    if (!qrPrefillText.trim()) {
      setMsg("Default QR opt-in text is required.");
      return;
    }
    setSaving(true);
    setMsg("Saving settings...");
    try {
      await api("/business/me/widget", "PATCH", {
        widget_color: widgetColor,
        widget_title: qrPrefillText.trim(),
      });
      setMsg("Business settings saved.");
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Layout>
      <h2>Settings</h2>
      <p>Business, channel, policy, and integration settings.</p>
      <WhatsAppSafetyScoreCard context="phone_number" />
      <div className="stack">
        <label>Default QR Opt-in Text (from business settings)
          <input value={qrPrefillText} onChange={(e) => setQrPrefillText(e.target.value)} placeholder="e.g. START" />
        </label>
        <label>Widget color
          <input value={widgetColor} onChange={(e) => setWidgetColor(e.target.value)} placeholder="#25D366" />
        </label>
        <button disabled={saving} onClick={() => save().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>{saving ? "Saving..." : "Save Settings"}</button>
        {msg ? <p>{msg}</p> : null}
      </div>
      <div className="grid">
        <Link to="/settings/whatsapp-setup">WhatsApp Setup / Onboarding Checklist</Link>
      </div>
    </Layout>
  );
}

function WhatsAppSetupPage() {
  const nav = useNavigate();
  const { businessName } = useBusinessContext();
  const [status, setStatus] = useState<WhatsAppOnboardingStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<WhatsAppSetupDiagnostics | null>(null);
  const [err, setErr] = useState("");
  const [signupBusy, setSignupBusy] = useState(false);
  const [signupMsg, setSignupMsg] = useState("");

  useEffect(() => {
    api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status")
      .then(setStatus)
      .catch(() => setErr("Live diagnostics unlock after login. You can still start embedded signup here."));
    api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics")
      .then(setDiagnostics)
      .catch(() => setErr((prev) => prev || "Live diagnostics unlock after login. You can still start embedded signup here."));
  }, []);

  const scopes = new Set((status?.permissions_granted || []).map((s) => String(s).trim()));
  const requiredScopes = ["whatsapp_business_management", "whatsapp_business_messaging", "business_management"];
  const missingPermissions = requiredScopes.filter((s) => !scopes.has(s));
  const hasWaba = Boolean(status?.waba_id);
  const hasPhone = Boolean(status?.phone_number_id);
  const tokenExpired = status?.token_expires_at ? new Date(status.token_expires_at).getTime() <= Date.now() : false;
  const webhookHealthy = Boolean(status?.webhook_subscribed) && String(diagnostics?.webhook_heartbeat_status || "inactive").toLowerCase() === "healthy";
  const templatesSynced = String(diagnostics?.template_sync_status || "pending").toLowerCase() === "synced";
  const messageTestPassed = Boolean(status?.message_test_passed ?? status?.test_message_passed);
  const deliveryWebhookHealthy = String(diagnostics?.webhook_heartbeat_status || "inactive").toLowerCase() === "healthy";
  const onboardingState = String(status?.onboarding_state || "").toUpperCase();
  const readyToSend =
    onboardingState === "ONBOARDING_COMPLETE" &&
    Boolean(status?.cloud_api_registered) &&
    messageTestPassed &&
    deliveryWebhookHealthy;
  const sequenceIndex = ONBOARDING_SEQUENCE.indexOf(onboardingState as (typeof ONBOARDING_SEQUENCE)[number]);
  const steps = ONBOARDING_SEQUENCE.map((step, index) => ({
    label: step.replace(/_/g, " "),
    done: sequenceIndex >= index,
    detail: sequenceIndex >= index ? "Completed" : "Pending",
  }));
  const progress = Math.round((steps.filter((step) => step.done).length / steps.length) * 100);

  const recoveryConfig: Record<string, { message: string; cta: string }> = {
    PHONE_NUMBER_PENDING_VERIFICATION: { message: "Meta has detected the number but it is not ready for messaging.", cta: "Check phone verification" },
    TWO_STEP_PIN_REQUIRED: { message: "Cloud API registration requires a PIN.", cta: "Register number" },
    DISPLAY_NAME_REJECTED: { message: "Display name was rejected by Meta.", cta: "View rejection reason" },
    WEBHOOK_FAILED: { message: "Messages cannot be tracked until webhook delivery is healthy.", cta: "Run webhook test" },
    MESSAGE_TEST_REQUIRED: { message: "Send a test message before campaign launch.", cta: "Send test message" },
    REAUTH_REQUIRED: { message: "Permissions or token are invalid.", cta: "Reconnect Meta" },
  };
  const recovery = recoveryConfig[onboardingState];

  const runRecovery = async () => {
    if (!status?.phone_number_id && ["TWO_STEP_PIN_REQUIRED", "MESSAGE_TEST_REQUIRED", "PHONE_NUMBER_PENDING_VERIFICATION"].includes(onboardingState)) {
      setErr("Phone number is required for this recovery action.");
      return;
    }
    try {
      if (onboardingState === "PHONE_NUMBER_PENDING_VERIFICATION") {
        await api(`/whatsapp/phone-numbers/${status?.phone_number_id}/readiness`);
      } else if (onboardingState === "TWO_STEP_PIN_REQUIRED") {
        await api(`/whatsapp/phone-numbers/${status?.phone_number_id}/register`, "POST", {});
      } else if (onboardingState === "DISPLAY_NAME_REJECTED") {
        setErr((status?.blocking_reasons || []).map((b) => `${b.code}: ${b.recovery_action}`).join(" | ") || "Display name rejected by Meta.");
      } else if (onboardingState === "WEBHOOK_FAILED") {
        await api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics").then(setDiagnostics);
      } else if (onboardingState === "MESSAGE_TEST_REQUIRED") {
        await api(`/whatsapp/phone-numbers/${status?.phone_number_id}/test-message`, "POST", {});
      } else if (onboardingState === "REAUTH_REQUIRED") {
        localStorage.setItem("post_login_redirect", "/settings/whatsapp-setup");
        nav("/login", { state: { from: "/settings/whatsapp-setup" } });
        return;
      }
      const freshStatus = await api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status");
      setStatus(freshStatus);
      setErr("");
      setSignupMsg("Recovery action completed. Status refreshed.");
    } catch (e) {
      setErr(toUserErrorMessage(e));
    }
  };

  const loadFacebookSdk = (appId: string) => new Promise<void>((resolve, reject) => {
    const existing = document.getElementById("facebook-jssdk");
    if ((window as any).FB) {
      resolve();
      return;
    }
    (window as any).fbAsyncInit = () => {
      (window as any).FB.init({ appId, cookie: true, xfbml: false, version: "v21.0" });
      resolve();
    };
    if (existing) return;
    const script = document.createElement("script");
    script.id = "facebook-jssdk";
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Could not load Meta SDK"));
    document.body.appendChild(script);
  });

  const startEmbeddedSignup = async () => {
    const token = sessionStorage.getItem("access_token") || sessionStorage.getItem("token") || sessionStorage.getItem("auth_token") || sessionStorage.getItem("jwt") || sessionStorage.getItem("bearer_token");
    if (!token) {
      localStorage.setItem("post_login_redirect", "/settings/whatsapp-setup");
      nav("/login", { state: { from: "/settings/whatsapp-setup" } });
      return;
    }
    setSignupBusy(true);
    setSignupMsg("Preparing secure Meta signup session...");
    setErr("");
    try {
      let appId = String(import.meta.env.VITE_META_APP_ID || "");
      let configId = String(import.meta.env.VITE_META_CONFIG_ID || "");
      let graphVersion = "v21.0";
      try {
        const config = await api<{ app_id: string; config_id: string; oauth_dialog_url?: string }>("/whatsapp/embedded-signup/config");
        appId = config.app_id || appId;
        configId = config.config_id || configId;
        const match = config.oauth_dialog_url?.match(/facebook\.com\/([^/]+)\//);
        if (match?.[1]) graphVersion = match[1];
      } catch {
        // Local env values are enough for frontend SDK bootstrapping.
      }
      if (!appId || !configId || appId.includes("your-") || configId.includes("your-")) {
        throw new Error("Meta signup is not ready: replace your-app-id and your-config-id in frontend/.env and backend/.env, then restart both servers.");
      }
      const session = await api<{ state: string; onboarding_session_id: string }>("/whatsapp/embedded-signup/session", "POST", {
        expected_origin: window.location.origin,
        ttl_minutes: 15,
      });
      await loadFacebookSdk(appId);
      setSignupMsg("Opening Meta authorization...");
      await new Promise<void>((resolve, reject) => {
        (window as any).FB.login((response: any) => {
          const code = response?.authResponse?.code;
          if (!code) {
            reject(new Error(response?.status === "not_authorized" ? "Meta authorization was not completed." : "Meta did not return an OAuth code."));
            return;
          }
          setSignupMsg("Finalizing WhatsApp connection...");
          api("/whatsapp/connect", "POST", { code, state: session.state }).then(() => resolve()).catch(reject);
        }, {
          config_id: configId,
          response_type: "code",
          override_default_response_type: true,
          state: session.state,
          extras: {
            setup: {},
            featureType: "whatsapp_embedded_signup",
            sessionInfoVersion: "3",
          },
        });
      });
      setSignupMsg("WhatsApp connected. Refreshing readiness...");
      const freshStatus = await api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status");
      setStatus(freshStatus);
      api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics").then(setDiagnostics).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
      nav("/embedded-signup/next", { replace: true });
    } catch (e) {
      setErr(toUserErrorMessage(e));
      setSignupMsg("");
    } finally {
      setSignupBusy(false);
    }
  };

  return (
    <div className="signup-replica">
      <aside className="signup-sidebar">
        <div className="signup-brand"><span>Command Center</span><small>Embedded signup</small></div>
        <button onClick={() => nav('/dashboard')}>Dashboard</button><button onClick={() => nav('/contacts')}>Contacts</button><button onClick={() => nav('/inbox')}>Inbox</button><button className="active">WhatsApp Setup</button><button onClick={() => nav('/settings')}>Settings</button>
        <div className="signup-side-card"><strong>Setup quality</strong><p>Connect Meta once, then sync templates, webhooks, contacts, and campaign sending from one place.</p></div>
      </aside>
      <main className="signup-main">
        <header className="signup-topbar"><div><span>Public onboarding</span><b>WhatsApp embedded signup</b></div><div className="signup-top-actions"><span>{businessName}</span><button onClick={() => nav('/login')}>Login to CRM</button></div></header>
        <section className="signup-hero"><div className="signup-hero-copy"><span className="signup-eyebrow">Meta Business Platform</span><h1>Connect WhatsApp Business without leaving your command center.</h1><p>Guide merchants through Meta embedded signup, WABA selection, phone verification, permission checks, webhook health, and template readiness in a single polished flow.</p><div className="signup-cta-row"><button className="signup-primary" onClick={() => startEmbeddedSignup().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} disabled={signupBusy}>{signupBusy ? "Connecting..." : "Continue with Meta"}</button><button className="signup-secondary" onClick={() => { api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics").then(setDiagnostics).catch((e) => setErr(toUserErrorMessage(e))); }}>Run diagnostics</button>{recovery ? <button className="signup-secondary" onClick={() => runRecovery().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>{recovery.cta}</button> : null}</div>{signupMsg ? <div className="signup-status">{signupMsg}</div> : null}{err ? <div className="signup-error">{err}</div> : null}{recovery ? <div className="signup-error">{recovery.message}</div> : null}{(status?.blocking_reasons || []).length ? <div className="signup-error">{(status?.blocking_reasons || []).map((b) => `${b.code}: ${b.recovery_action}`).join(" | ")}</div> : null}</div><div className="signup-live-card"><div className="signup-card-head"><span>Live readiness</span><b>{readyToSend ? "Ready" : "Action required"}</b></div><div className="signup-progress"><span style={{ width: `${progress}%` }} /></div><div className="signup-checks">{steps.map((step) => <div key={step.label} className={step.done ? "done" : "todo"}><span>{step.done ? "OK" : "--"}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div></div>)}</div></div></section>
        <section className="signup-grid"><article className="signup-panel large"><div className="panel-kicker">Embedded flow</div><h2>What the merchant sees</h2><div className="flow-preview"><div><span>1</span><strong>Authorize Meta</strong><small>Business Manager login and scopes.</small></div><div><span>2</span><strong>Select assets</strong><small>Choose WABA, number, and display profile.</small></div><div><span>3</span><strong>Activate messaging</strong><small>Validate webhook, templates, and test send.</small></div></div></article><article className="signup-panel"><div className="panel-kicker">Permissions</div><h2>{missingPermissions.length ? `${missingPermissions.length} missing` : "Scopes ready"}</h2><p>{missingPermissions.length ? missingPermissions.join(', ') : "Required WhatsApp and business permissions are granted."}</p></article><article className="signup-panel"><div className="panel-kicker">Templates</div><h2>{templatesSynced ? "Synced" : "Pending sync"}</h2><p>{diagnostics?.template_approved_count || 0} approved of {diagnostics?.template_total_count || 0} templates.</p></article><article className="signup-panel"><div className="panel-kicker">Webhook</div><h2>{webhookHealthy ? "Healthy" : "Inactive"}</h2><p>{webhookHealthy ? "Events are arriving from Meta." : "Waiting for a successful webhook heartbeat."}</p></article></section>
      </main>
    </div>
  );
}
function EmbeddedSignupNextPage() {
  const nav = useNavigate();
  const [status, setStatus] = useState<WhatsAppOnboardingStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<WhatsAppSetupDiagnostics | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<WhatsAppOnboardingStatus>("/whatsapp/onboarding/status").then(setStatus).catch((e) => setErr(toUserErrorMessage(e)));
    api<WhatsAppSetupDiagnostics>("/whatsapp/setup-diagnostics").then(setDiagnostics).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, []);

  const connected = Boolean(status?.token_valid);
  const hasWaba = Boolean(status?.waba_id);
  const hasPhone = Boolean(status?.phone_number_id);
  const webhookHealthy = Boolean(status?.webhook_subscribed) && String(diagnostics?.webhook_heartbeat_status || "inactive").toLowerCase() === "healthy";
  const templateCount = diagnostics?.template_total_count || 0;
  const approvedTemplates = diagnostics?.template_approved_count || 0;
  const ready = String(status?.onboarding_state || "").toUpperCase() === "ONBOARDING_COMPLETE";

  return (
    <div className="signup-next-page">
      <section className="signup-next-hero">
        <span className="signup-eyebrow">Meta connection result</span>
        <h1>{ready ? "WhatsApp is connected. Your CRM is ready for activation." : "Meta signup is complete. Finish the operational checks."}</h1>
        <p>{err || "Review the connected WABA, sender phone, webhook health, and templates before launching live customer messaging."}</p>
        <div className="signup-cta-row"><button className="signup-primary" onClick={() => nav('/contacts')}>Open CRM contacts</button><button className="signup-secondary" onClick={() => nav('/campaigns')}>Create campaign</button><button className="signup-secondary" onClick={() => nav('/settings/whatsapp-setup')}>Back to setup</button></div>
      </section>
      <section className="signup-next-grid">
        <article><span>Business connection</span><strong>{connected ? "Connected" : "Needs attention"}</strong><p>{status?.onboarding_state || "No live status returned yet."}</p></article>
        <article><span>WABA</span><strong>{hasWaba ? status?.waba_id : "Not selected"}</strong><p>WhatsApp Business Account attached to this tenant.</p></article>
        <article><span>Sender phone</span><strong>{hasPhone ? status?.display_phone_number || status?.phone_number_id : "Missing"}</strong><p>{status?.display_name_status || "Phone status unavailable."}</p></article>
        <article><span>Webhook</span><strong>{webhookHealthy ? "Healthy" : "Inactive"}</strong><p>{diagnostics?.webhook_heartbeat_status || "Waiting for event heartbeat."}</p></article>
        <article><span>Templates</span><strong>{approvedTemplates}/{templateCount}</strong><p>Approved templates available for campaign launch.</p></article>
        <article><span>Next action</span><strong>{ready ? "Launch safely" : "Run diagnostics"}</strong><p>{ready ? "You can import contacts and create your first campaign." : ((status?.blocking_reasons || []).map((b) => b.recovery_action).join(" | ") || "Resolve lifecycle blockers.")}</p></article>
      </section>
    </div>
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
    const payload = await api<unknown>("/conversations?limit=200");
    const rows = normalizeQueryPage<ConversationInboxItem>(payload).items;
    setConversations(rows);
    if (rows.length && !selectedId) setSelectedId(String(rows[0].public_id));
  };

  useEffect(() => {
    loadList().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [filter]);

  useEffect(() => {
    if (!selectedId) return;
    api(`/conversations/${selectedId}`).then(setDetail).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<any[]>(`/conversations/${selectedId}/timeline`).then(setTimeline).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId("");
      setDetail(null);
      setMessages([]);
      setTimeline([]);
      return;
    }
    const exists = filtered.some((c) => String(c.public_id) === selectedId);
    if (!exists) setSelectedId(String(filtered[0].public_id));
  }, [filtered, selectedId]);

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
      setActionMsg(toUserErrorMessage(e));
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
      setActionMsg(toUserErrorMessage(e));
    }
  };

  const quickReplies = ["Thanks for reaching out. We are checking this now.", "Can you share your order ID?", "We have escalated this and will update shortly."];
  const templateReplies = ["Address change policy", "Escalate to logistics", "Ask for address"];
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
  const selectedConversation = filtered.find((c) => String(c.public_id) === selectedId) || null;
  const initials = (name?: string | null) => {
    const n = (name || "Unknown").trim();
    const parts = n.split(/\s+/).slice(0, 2);
    return parts.map((p) => p[0]?.toUpperCase() || "").join("") || "UN";
  };
  const relTime = (value?: string | null) => {
    if (!value) return "-";
    const ms = Date.now() - new Date(value).getTime();
    const m = Math.max(1, Math.round(ms / 60000));
    if (m < 60) return `${m}m`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h`;
    const d = Math.round(h / 24);
    return `${d}d`;
  };

  return (
    <Layout>
      <div className="meta-shell">
        <div className="meta-inbox">
          <div className="meta-tabs">
            {["All", "Mine", "Unassigned", "Unread", "Waiting", "Resolved", "Campaign replies", "VIP customers", "SLA breached"].map((f) => (
              <button key={f} className={`meta-tab ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>{f}</button>
            ))}
          </div>
          <div className="meta-conv-list">
            {!filtered.length ? <p className="muted">No conversations match this filter yet.</p> : null}
            {filtered.map((c) => (
              <div key={String(c.public_id)} className={`meta-conv-item ${selectedId === String(c.public_id) ? "active" : ""}`} onClick={() => setSelectedId(String(c.public_id))}>
                <div className="meta-avatar">{initials(c.visitor_name)}<span className="resolved-tick">?</span></div>
                <div className="meta-conv-info">
                  <div className="meta-conv-name">{c.visitor_name || "Unknown"}</div>
                  <div className="meta-conv-preview">{c.status} Â· {(c.unread_count || 0)} unread</div>
                </div>
                <div className="meta-conv-time">{relTime(c.last_message_at)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="meta-chat">
          <div className="meta-chat-header">
            <div className="meta-avatar">{initials(selectedConversation?.visitor_name || detail?.visitor_name)}</div>
            <div>
              <div className="meta-chat-name">{selectedConversation?.visitor_name || detail?.visitor_name || "Conversation"}</div>
              <div className="meta-chat-sub">{detail?.visitor_email || "WhatsApp conversation"}</div>
            </div>
            <span className="status-pill"><span className="status-dot"></span>{selectedConversation?.status || "Open"}</span>
          </div>
          <div className="meta-chat-messages">
            {messages.length ? messages.map((m) => (
              <div key={m.public_id} className={`meta-msg ${m.direction === "outbound" ? "out" : "in"}`}>
                <div>{m.content_text || "(no text payload)"}</div>
                <div className="msg-time">{new Date(m.created_at).toLocaleTimeString()}</div>
              </div>
            )) : <p className="muted">No messages yet.</p>}
          </div>
          <div className="quick-replies">
            {templateReplies.map((t) => <button key={t} className="qr-chip" onClick={() => setComposer(t)}>{t}</button>)}
          </div>
          <div className="meta-chat-input">
            <input className="chat-input" placeholder="Type reply..." value={composer} onChange={(e) => setComposer(e.target.value)} />
            <button onClick={() => setComposer("")}>Send</button>
          </div>
        </div>
        <aside className="meta-right">
          <h3>Customer Profile</h3>
          <div className="profile-grid">
            <span>Name</span><strong>{contact?.name || detail?.visitor_name || "-"}</strong>
            <span>Phone</span><strong>{contact?.phone_e164 || "-"}</strong>
            <span>Tags</span><strong>{(contact?.tags || []).join(", ") || "-"}</strong>
            <span>Opt-in status</span><strong>{contact?.opt_in_status || "-"}</strong>
            <span>Last order</span><strong>{contact?.last_order_at || "Not available"}</strong>
            <span>Total spent</span><strong>Not connected</strong>
            <span>Notes</span><strong>{timeline.filter((t) => t.event_type === "conversation.internal_note.added").length} internal notes</strong>
          </div>
          <div className="note-box">
            <input placeholder="Assign user UUID" value={assignUserId} onChange={(e) => setAssignUserId(e.target.value)} />
            <button onClick={() => assignConversation().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Assign</button>
            <textarea rows={2} placeholder="Add internal note..." value={noteText} onChange={(e) => setNoteText(e.target.value)} />
            <button onClick={() => postInternalNote().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add note</button>
            <p>{actionMsg}</p>
          </div>
        </aside>
      </div>
    </Layout>
  );
}

function InboxReplicaPage() {
  const nav = useNavigate();
  const location = useLocation();
  const [tab, setTab] = useState<"today" | "week">("today");
  const [scope, setScope] = useState<"all" | "mine" | "pending" | "resolved">("all");
  const [workspaceView, setWorkspaceView] = useState<"inbox" | "contacts" | "broadcasts" | "analytics" | "botflows" | "settings">("inbox");
  const [conversations, setConversations] = useState<ConversationInboxItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [contact, setContact] = useState<ContactCRMRecord | null>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [searchText, setSearchText] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [purchaseItem, setPurchaseItem] = useState("");
  const [purchaseAmount, setPurchaseAmount] = useState("");
  const [followUpText, setFollowUpText] = useState("");
  const [agentNote, setAgentNote] = useState("");
  const [campaignQueue, setCampaignQueue] = useState<Campaign[]>([]);
  const [queueLoading, setQueueLoading] = useState(false);
  const [draftName, setDraftName] = useState("Weekend VIP Winback");
  const [draftType, setDraftType] = useState<"marketing" | "utility">("marketing");
  const [draftPriority, setDraftPriority] = useState<"high" | "normal">("high");
  const [draftPhoneId, setDraftPhoneId] = useState("");
  const [draftTemplateId, setDraftTemplateId] = useState("");
  const [draftBusy, setDraftBusy] = useState(false);
  const currentUserId = sessionStorage.getItem("auth_user_id") || "";
  const allowedViews = new Set(["inbox", "contacts", "broadcasts", "analytics", "botflows", "settings"]);

  useEffect(() => {
    const params = new URLSearchParams(location.search || "");
    const requested = String(params.get("view") || "inbox").toLowerCase();
    const nextView = (allowedViews.has(requested) ? requested : "inbox") as "inbox" | "contacts" | "broadcasts" | "analytics" | "botflows" | "settings";
    setWorkspaceView((prev) => (prev === nextView ? prev : nextView));
  }, [location.search]);

  useEffect(() => {
    const params = new URLSearchParams(location.search || "");
    const current = String(params.get("view") || "inbox").toLowerCase();
    if (current === workspaceView) return;
    params.set("view", workspaceView);
    const nextSearch = `?${params.toString()}`;
    nav({ pathname: "/inbox", search: nextSearch }, { replace: true });
  }, [workspaceView, location.search, nav]);

  useEffect(() => {
    api<unknown>("/conversations?limit=200")
      .then((payload) => {
        const rows = normalizeQueryPage<ConversationInboxItem>(payload).items;
        setConversations(rows);
        if (rows.length && !selectedId) setSelectedId(String(rows[0].public_id));
      })
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    api(`/conversations/${selectedId}`).then(setDetail).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<unknown>(`/conversations/${selectedId}/messages?${toQueryString({ limit: 50, sortBy: "created_at", sortDir: "asc" })}`)
      .then((payload) => setMessages(normalizeQueryPage<AgentMessage>(payload).items))
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<any[]>(`/conversations/${selectedId}/timeline`).then(setTimeline).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [selectedId]);

  useEffect(() => {
    if (!detail?.visitor_name && !detail?.visitor_email) return;
    const query = encodeURIComponent((detail.visitor_email || detail.visitor_name || "").trim());
    api<unknown>(`/contacts/crm/records?search=${query}&limit=1`)
      .then((rows) => setContact(normalizeQueryPage<ContactCRMRecord>(rows).items[0] || null))
      .catch(() => setContact(null));
  }, [detail?.visitor_name, detail?.visitor_email]);

  useEffect(() => {
    if (workspaceView !== "broadcasts") return;
    setQueueLoading(true);
    api<unknown>(`/campaigns?${toQueryString({ limit: 8, sortBy: "updated_at", sortDir: "desc" })}`)
      .then((payload) => setCampaignQueue(normalizeQueryPage<Campaign>(payload).items))
      .catch(() => setCampaignQueue([]))
      .finally(() => setQueueLoading(false));
  }, [workspaceView]);

  const agentVisibleConversations = conversations.filter((c) => {
    const status = String(c.status || "").toLowerCase();
    const assigned = String(c.assigned_user_id || "").trim();
    const isPending = status === "pending";
    if (isPending && !assigned) return true;
    if (!currentUserId) return false;
    return assigned === currentUserId;
  });
  const filtered = agentVisibleConversations.filter((c) => {
    const status = String(c.status || "").toLowerCase();
    const isResolved = ["resolved", "closed"].includes(status);
    const isMine = Boolean(c.assigned_user_id && String(c.assigned_user_id) === currentUserId);
    const isPending = status === "pending";
    if (scope === "mine" && !isMine) return false;
    if (scope === "pending" && !isPending) return false;
    if (scope === "resolved" && !isResolved) return false;
    const q = searchText.trim().toLowerCase();
    if (!q) return true;
    return [c.visitor_name, c.status, ...(c.tags || [])].some((value) => String(value || "").toLowerCase().includes(q));
  });

  useEffect(() => {
    if (!filtered.length) return;
    if (!filtered.some((c) => String(c.public_id) === selectedId)) setSelectedId(String(filtered[0].public_id));
  }, [filtered, selectedId]);

  const selectedConversation = filtered.find((c) => String(c.public_id) === selectedId) || null;
  const embeddedContacts = useMemo(
    () =>
      agentVisibleConversations.map((c) => ({
        id: String(c.public_id),
        name: c.visitor_name || "Unknown",
        status: String(c.status || "open"),
        unread: Number(c.unread_count || 0),
        lastMessageAt: c.last_message_at,
      })),
    [agentVisibleConversations]
  );
  const inboxMetrics = useMemo(() => {
    const total = agentVisibleConversations.length;
    const mine = agentVisibleConversations.filter((c) => String(c.assigned_user_id || "") === currentUserId).length;
    const pending = agentVisibleConversations.filter((c) => String(c.status || "").toLowerCase() === "pending").length;
    const resolved = agentVisibleConversations.filter((c) => ["resolved", "closed"].includes(String(c.status || "").toLowerCase())).length;
    return { total, mine, pending, resolved };
  }, [agentVisibleConversations, currentUserId]);
  const initials = (name?: string | null) => {
    const n = (name || "Unknown").trim();
    const parts = n.split(/\s+/).slice(0, 2);
    return parts.map((p) => p[0]?.toUpperCase() || "").join("") || "UN";
  };
  const relTime = (value?: string | null) => {
    if (!value) return "-";
    const ms = Date.now() - new Date(value).getTime();
    const m = Math.max(1, Math.round(ms / 60000));
    if (m < 60) return `${m}m`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h`;
    return `${Math.round(h / 24)}d`;
  };
  const reloadConversation = async () => {
    if (!selectedId) return;
    const d = await api(`/conversations/${selectedId}`);
    setDetail(d);
    const payload = await api<unknown>("/conversations?limit=200");
    setConversations(normalizeQueryPage<ConversationInboxItem>(payload).items);
  };
  const reopenConversation = async () => {
    if (!selectedId) return;
    setActionMsg("Reopening conversation...");
    try {
      await api(`/conversations/${selectedId}/reopen`, "POST", {});
      setActionMsg("Conversation reopened.");
      await reloadConversation();
    } catch (e) {
      setActionMsg(toUserErrorMessage(e));
    }
  };
  const exportTranscript = () => {
    const name = selectedConversation?.visitor_name || detail?.visitor_name || "conversation";
    const lines = messages.map((m) => `[${new Date(m.created_at).toLocaleString()}] ${m.direction}: ${m.content_text || "(no text payload)"}`);
    const blob = new Blob([`Transcript: ${name}\n\n${lines.join("\n") || "No messages yet."}`], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${String(name).replace(/[^a-z0-9]+/gi, "_").toLowerCase()}_transcript.txt`;
    a.click();
    URL.revokeObjectURL(url);
    setActionMsg("Transcript exported.");
  };
  const saveAgentCapture = async (nextTags: string[] = []) => {
    if (!contact?.id) {
      setActionMsg("No matched CRM contact. Create/import contact first.");
      return;
    }
    try {
      let eventType = "add_note";
      const tags = new Set((nextTags || []).map((t) => String(t || "").trim().toLowerCase()).filter(Boolean));
      if (tags.has("purchase")) eventType = "add_purchase";
      else if (tags.has("enquiry")) eventType = "add_enquiry";
      else if (tags.has("follow_up")) eventType = "add_follow_up";
      else if (tags.has("hot_lead")) eventType = "mark_hot_lead";
      else if (tags.has("existing_customer")) eventType = "mark_existing_customer";
      else if (tags.has("walk_in_customer")) eventType = "mark_walk_in_customer";
      else if (tags.has("converted")) eventType = "mark_converted";
      else if (tags.size > 0) eventType = "add_tag";
      const firstTag = tags.values().next().value as string | undefined;
      const parsedAmount = purchaseAmount.trim() ? Number(String(purchaseAmount).replace(/[^0-9.]/g, "")) : NaN;
      const amountValue = Number.isFinite(parsedAmount) ? parsedAmount : undefined;
      await api(
        `/contacts/${contact.id}/agent-capture`,
        "POST",
        {
          event_type: eventType,
          tag: eventType === "add_tag" ? firstTag : undefined,
          purchased_item: purchaseItem.trim() || undefined,
          amount: amountValue,
          next_follow_up: followUpText.trim() || undefined,
          note: agentNote.trim() || undefined,
          captured_at: new Date().toISOString(),
        },
        { headers: { "Idempotency-Key": `agent-capture-${contact.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` } },
      );
      setActionMsg("Agent capture saved to CRM.");
      setPurchaseItem("");
      setPurchaseAmount("");
      setFollowUpText("");
      setAgentNote("");
    } catch (e) {
      setActionMsg(toUserErrorMessage(e));
    }
  };
  const createBroadcastDraft = async () => {
    if (!draftName.trim() || !draftPhoneId.trim() || !draftTemplateId.trim()) {
      setActionMsg("Provide campaign name, phone number id, and template id.");
      return;
    }
    setDraftBusy(true);
    setActionMsg("Creating broadcast draft...");
    try {
      await api("/campaigns", "POST", {
        name: draftName.trim(),
        phone_number_id: draftPhoneId.trim(),
        template_id: draftTemplateId.trim(),
        type: draftType,
        priority: draftPriority,
      });
      setActionMsg("Broadcast draft created.");
      const payload = await api<unknown>(`/campaigns?${toQueryString({ limit: 8, sortBy: "updated_at", sortDir: "desc" })}`);
      setCampaignQueue(normalizeQueryPage<Campaign>(payload).items);
    } catch (e) {
      setActionMsg(toUserErrorMessage(e));
    } finally {
      setDraftBusy(false);
    }
  };

  return (
    <div className="meta-replica">
      <h2 className="sr-only">Resolved conversations - closed tickets with CSAT ratings, resolution details, and reopen option</h2>
      <div className="shell">
        <div className="sidebar">
          <div className="sidebar-logo">
            <div className="logo-icon">
              <svg viewBox="0 0 24 24"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91C2.13 13.66 2.59 15.36 3.45 16.86L2.05 22L7.3 20.62C8.75 21.41 10.38 21.83 12.04 21.83C17.5 21.83 21.95 17.38 21.95 11.92C21.95 9.27 20.92 6.78 19.05 4.91C17.18 3.03 14.69 2 12.04 2ZM12.05 3.67C14.25 3.67 16.31 4.53 17.87 6.09C19.42 7.65 20.28 9.72 20.28 11.92C20.28 16.46 16.58 20.15 12.04 20.15C10.56 20.15 9.11 19.76 7.85 19.02L7.55 18.85L4.43 19.65L5.24 16.61L5.05 16.29C4.24 14.99 3.8 13.47 3.8 11.91C3.81 7.37 7.5 3.67 12.05 3.67Z"/></svg>
            </div>
            <div><div className="logo-text">MetaCRM</div><div className="logo-badge">WhatsApp Business</div></div>
          </div>
          <div className="nav-section">
            <div className="nav-label">Inbox</div>
            <div className={`nav-item ${scope === "all" ? "active" : ""}`} onClick={() => setScope("all")}>All conversations <span className="badge-count">{agentVisibleConversations.length}</span></div>
            <div className={`nav-item ${scope === "mine" ? "active" : ""}`} onClick={() => setScope("mine")}>Assigned to me</div>
            <div className={`nav-item ${scope === "pending" ? "active" : ""}`} onClick={() => setScope("pending")}>Pending</div>
            <div className={`nav-item ${scope === "resolved" ? "active" : ""}`} onClick={() => setScope("resolved")}>Resolved</div>
          </div>
          <div className="nav-section">
            <div className="nav-label">Tools</div>
            <div className={`nav-item ${workspaceView === "contacts" ? "active" : ""}`} onClick={() => setWorkspaceView("contacts")}>Contacts</div>
            <div className={`nav-item ${workspaceView === "broadcasts" ? "active" : ""}`} onClick={() => setWorkspaceView("broadcasts")}>Broadcasts</div>
            <div className={`nav-item ${workspaceView === "analytics" ? "active" : ""}`} onClick={() => setWorkspaceView("analytics")}>Analytics</div>
            <div className={`nav-item ${workspaceView === "botflows" ? "active" : ""}`} onClick={() => setWorkspaceView("botflows")}>Bot flows</div>
            <div className={`nav-item ${workspaceView === "settings" ? "active" : ""}`} onClick={() => setWorkspaceView("settings")}>Settings</div>
          </div>
          <div className="sidebar-footer">
            <div className="agent-row">
              <div className="agent-avatar">AJ</div>
              <div><div className="agent-name">Arjun J.</div><div className="agent-role">Support agent</div></div>
            </div>
          </div>
        </div>
        <div className="main">
          <div className="topbar">
            <div className="topbar-title">
              {scope === "mine" ? "Assigned to me" : scope === "pending" ? "Pending conversations" : scope === "resolved" ? "Resolved conversations" : "All conversations"}
            </div>
            <input className="search-box" placeholder="Search" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
            <button className="btn-top" onClick={() => setActionMsg(`Showing ${filtered.length} conversation${filtered.length === 1 ? "" : "s"} in this scope.`)}>Filter</button>
            <button className="btn-top btn-green" onClick={() => nav("/campaigns/new")}>New</button>
          </div>
          <div className="resolved-stats-strip">
            <span><i className="green-dot" />{filtered.length} resolved today</span>
            <span><span className="star-on">*</span> Avg CSAT: 4.6 / 5</span>
            <span>Avg resolution: 22m</span>
            <span className="resolved-showing">Showing: Today</span>
          </div>
          <div className="content">
            {workspaceView !== "inbox" ? (
              <div className="chat-area" style={{ width: "100%", padding: 14 }}>
                {workspaceView === "contacts" ? (
                  <div className="embedded-workspace">
                    <div className="embedded-workspace-head">
                      <div className="panel-title">Inbox Contacts</div>
                      <p>Agent-scoped contacts inside inbox workspace.</p>
                    </div>
                    <div className="embedded-contact-list">
                      {embeddedContacts.map((c) => (
                        <article className="embedded-contact-card" key={c.id}>
                          <div className="embedded-contact-avatar">{initials(c.name)}</div>
                          <div className="embedded-contact-main">
                            <div className="embedded-contact-name">{c.name}</div>
                            <div className="embedded-contact-meta">{c.status} · {c.lastMessageAt ? relTime(c.lastMessageAt) : "-"}</div>
                          </div>
                          <div className="embedded-contact-unread">{c.unread}</div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}
                {workspaceView === "broadcasts" ? (
                  <div className="embedded-workspace">
                    <div className="embedded-workspace-head">
                      <div className="panel-title">Broadcast Workbench</div>
                      <p>Create, stage, and monitor campaigns without leaving inbox operations.</p>
                    </div>
                    <div className="embedded-broadcast-grid">
                      <section className="embedded-broadcast-card">
                        <div className="embedded-broadcast-card-head">
                          <h4>New Broadcast</h4>
                          <span>Draft setup</span>
                        </div>
                        <div className="embedded-broadcast-form">
                          <input placeholder="Campaign name" value={draftName} onChange={(e) => setDraftName(e.target.value)} />
                          <div className="embedded-broadcast-row">
                            <select value={draftType} onChange={(e) => setDraftType(e.target.value as "marketing" | "utility")}>
                              <option value="marketing">Type: Marketing</option>
                              <option value="utility">Type: Utility</option>
                            </select>
                            <select value={draftPriority} onChange={(e) => setDraftPriority(e.target.value as "high" | "normal")}>
                              <option value="high">Priority: High</option>
                              <option value="normal">Priority: Normal</option>
                            </select>
                          </div>
                          <div className="embedded-broadcast-row">
                            <input placeholder="Phone number ID" value={draftPhoneId} onChange={(e) => setDraftPhoneId(e.target.value)} />
                            <input placeholder="Template ID" value={draftTemplateId} onChange={(e) => setDraftTemplateId(e.target.value)} />
                          </div>
                          <div className="embedded-broadcast-row">
                            <button className="btn-top btn-green" disabled={draftBusy} onClick={() => createBroadcastDraft().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>{draftBusy ? "Creating..." : "Create Draft"}</button>
                            <button className="btn-top" onClick={() => nav("/campaigns/new")}>Open Full Builder</button>
                          </div>
                        </div>
                      </section>
                      <section className="embedded-broadcast-card">
                        <div className="embedded-broadcast-card-head">
                          <h4>Open Campaign Queue</h4>
                          <span>Live status</span>
                        </div>
                        <div className="embedded-queue-list">
                          {queueLoading ? <article><strong>Loading...</strong><span>Fetching campaign queue</span></article> : null}
                          {!queueLoading && campaignQueue.length === 0 ? <article><strong>No campaigns</strong><span>Create a draft to start queueing.</span></article> : null}
                          {!queueLoading && campaignQueue.map((c) => (
                            <article key={c.campaign_id}>
                              <strong>{c.name || c.campaign_id}</strong>
                              <span>{String(c.status || "draft")} · {(Number(c.total_recipients || c.eligible_recipients || 0)).toLocaleString()} recipients</span>
                            </article>
                          ))}
                        </div>
                        <button className="btn-top" onClick={() => nav("/campaigns")}>Open Campaign Queue</button>
                      </section>
                    </div>
                    <section className="embedded-offline-data">
                      <div className="embedded-broadcast-card-head">
                        <h4>Offline-First Merchant Data Collection</h4>
                        <span>Foundations</span>
                      </div>
                      <p className="embedded-offline-copy">For offline merchants, ingest from practical real-world sources first, then enrich over time.</p>
                      <div className="embedded-offline-grid">
                        <article>
                          <strong>Data Sources</strong>
                          <ul>
                            {["POS / billing software", "CSV import", "manual contact upload", "WhatsApp conversations", "Google Sheets", "customer tags", "order forms", "loyalty system", "QR code opt-ins", "agent-entered notes", "payment links", "invoices"].map((x) => <li key={x}>{x}</li>)}
                          </ul>
                        </article>
                        <article>
                          <strong>Supported Ingestion</strong>
                          <ul>
                            {["CSV / Excel", "Google Sheets sync", "manual add contact", "bulk paste contacts", "POS integration", "WhatsApp chat import-style enrichment"].map((x) => <li key={x}>{x}</li>)}
                          </ul>
                        </article>
                        <article>
                          <strong>Minimum Offline Fields</strong>
                          <ul>
                            {["customer name", "phone number", "last purchase date", "product/category bought", "bill amount", "location", "salesperson", "notes"].map((x) => <li key={x}>{x}</li>)}
                          </ul>
                        </article>
                      </div>
                      <div className="embedded-contact-model">
                        <div className="embedded-broadcast-card-head">
                          <h4>Minimum Contact Model</h4>
                          <span>v1</span>
                        </div>
                        <div className="embedded-contact-model-grid">
                          {["name", "phone", "city", "tags", "source", "opt_in_status", "last_seen_at", "last_message_at", "total_orders", "total_spend", "last_purchase_at", "custom_fields"].map((field) => (
                            <div key={field}><code>{field}</code></div>
                          ))}
                        </div>
                      </div>
                    </section>
                  </div>
                ) : null}
                {workspaceView === "analytics" ? (
                  <div className="panel-section">
                    <div className="panel-title">Inbox Analytics</div>
                    <div className="metric-row">
                      <div className="metric-box"><div className="metric-num">{inboxMetrics.total}</div><div className="metric-lbl">Visible</div></div>
                      <div className="metric-box"><div className="metric-num">{inboxMetrics.mine}</div><div className="metric-lbl">Assigned to me</div></div>
                      <div className="metric-box"><div className="metric-num">{inboxMetrics.pending}</div><div className="metric-lbl">Pending</div></div>
                      <div className="metric-box"><div className="metric-num">{inboxMetrics.resolved}</div><div className="metric-lbl">Resolved</div></div>
                    </div>
                  </div>
                ) : null}
                {workspaceView === "botflows" ? (
                  <div className="panel-section">
                    <div className="panel-title">Bot Flow Controls</div>
                    <p style={{ color: "var(--color-text-tertiary)" }}>Pause or route automation from inbox operations.</p>
                    <div className="quick-actions">
                      <button>Pause FAQ bot</button>
                      <button>Escalate refund intents</button>
                      <button>Enable VIP handoff</button>
                    </div>
                  </div>
                ) : null}
                {workspaceView === "settings" ? (
                  <div className="panel-section">
                    <div className="panel-title">Inbox Settings</div>
                    <div className="field-label">Agent visibility mode</div>
                    <div className="field-val">Strict: only my assigned + unassigned pending</div>
                    <div className="field-label">Notification profile</div>
                    <div className="field-val">High-priority only</div>
                  </div>
                ) : null}
              </div>
            ) : (
            <>
            <div className="inbox">
              <div className="resolved-tabs">
                <button className={tab === "today" ? "active" : ""} onClick={() => setTab("today")}>Today ({filtered.length})</button>
                <button className={tab === "week" ? "active" : ""} onClick={() => setTab("week")}>This week ({Math.max(filtered.length, conversations.length)})</button>
              </div>
              <div className="conv-list">
                {filtered.map((c) => (
                  <div key={String(c.public_id)} className={`conv-item ${selectedId === String(c.public_id) ? "active" : ""}`} onClick={() => setSelectedId(String(c.public_id))}>
                    <div className="conv-avatar" style={{ background: "#E7F9EE", color: "#1B7A42" }}>{initials(c.visitor_name)}<span className="resolved-tick">✓</span></div>
                    <div className="conv-info">
                      <div className="conv-name">{c.visitor_name || "Unknown"}</div>
                      <div className="conv-preview">Resolved conversation</div>
                    </div>
                    <div className="conv-meta">
                      <div className="conv-time">{relTime(c.last_message_at)}</div>
                      <span className="star-row"><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span></span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="chat-area">
              <div className="chat-header">
                <div className="conv-avatar chat-avatar" style={{ width: 36, height: 36, background: "#E7F9EE", color: "#1B7A42" }}>{initials(selectedConversation?.visitor_name || detail?.visitor_name)}<span className="resolved-tick">✓</span></div>
                <div style={{ flex: 1 }}><div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-secondary)" }}>{selectedConversation?.visitor_name || detail?.visitor_name || "Conversation"}</div><div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>Resolved · {relTime(selectedConversation?.last_message_at)} · by Arjun J.</div></div>
                <span className="resolved-pill">✓ Resolved</span><button className="reopen-btn" onClick={() => reopenConversation().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Reopen</button>
              </div>
              <div className="resolved-summary-strip">✓ Resolved in <strong>{relTime(selectedConversation?.last_message_at)}</strong> · {messages.length} messages · CSAT: <strong>5/5 *</strong></div>
              <div className="chat-messages">
                {messages.length ? messages.map((m) => (
                  <div key={m.public_id} style={m.direction === "outbound" ? { alignSelf: "flex-end", textAlign: "right" } : undefined}>
                    <div className={`msg ${m.direction === "outbound" ? "msg-out" : "msg-in"}`}>{m.content_text || "(no text payload)"}</div>
                    <div className="msg-time">{new Date(m.created_at).toLocaleTimeString()}</div>
                  </div>
                )) : <div className="msg msg-in">No messages yet.</div>}
                <div className="resolved-card"><div className="resolved-card-icon">✓</div><div className="resolved-card-title">Conversation resolved</div><div className="resolved-card-copy">by Arjun J. · Duration: {relTime(selectedConversation?.last_message_at)}</div><div className="resolved-card-rating"><div>Customer rated this conversation</div><span className="star-row"><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span></span></div></div>
              </div><div className="closed-chat-row"><span>Lock</span><span>This conversation is closed. Reopen to send a message.</span><button onClick={() => reopenConversation().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Reopen</button>
              </div>
            </div>
            <div className="right-panel">
              <div className="panel-section">
                <div style={{ textAlign: "center", marginBottom: 12 }}>
                  <div style={{ width: 44, height: 44, borderRadius: "50%", background: "#FAEEDA", color: "#854F0B", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 500, margin: "0 auto 6px" }}>{initials(contact?.name || detail?.visitor_name)}</div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{contact?.name || detail?.visitor_name || "Unknown"}</div>
                  <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{contact?.phone_e164 || detail?.visitor_email || "-"}</div>
                </div>
                <div className="metric-row"><div className="metric-box"><div className="metric-num">{timeline.length}</div><div className="metric-lbl">Events</div></div><div className="metric-box"><div className="metric-num">{messages.length}</div><div className="metric-lbl">Messages</div></div><div className="metric-box"><div className="metric-num metric-green">5/5</div><div className="metric-lbl">CSAT</div></div></div>
              </div>
              <div className="panel-section">
                <div className="panel-title">Resolution details</div><div className="field-label">Resolved by</div><div className="field-val">Arjun J.</div><div className="field-label">Resolution type</div><div className="field-val">Customer issue solved</div>{actionMsg ? <div className="field-val">{actionMsg}</div> : null}
              </div>
              <div className="panel-section"><div className="panel-title">CSAT feedback</div><div className="csat-box"><span className="star-row"><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span><span className="star-on">*</span></span><div>Great support and quick resolution.</div></div></div><div className="panel-section"><div className="panel-title">Tags</div><div className="tag-list"><span className="tag tag-resolved">Resolved</span><span className="tag tag-blue">Refund</span></div></div>
              <div className="panel-section">
                <div className="panel-title">Quick actions</div>
                <div className="quick-actions">
                  <button onClick={() => reopenConversation().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Reopen conversation</button><button onClick={exportTranscript}>Export transcript</button><button onClick={() => nav("/campaigns/new")}>Send broadcast</button>
                </div>
              </div>
              <div className="panel-section">
                <div className="panel-title">Agent Data Capture</div>
                <div className="quick-actions">
                  <button onClick={() => saveAgentCapture(["tag_added"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add tag</button>
                  <button onClick={() => saveAgentCapture(["purchase"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add purchase</button>
                  <button onClick={() => saveAgentCapture(["enquiry"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add enquiry</button>
                  <button onClick={() => saveAgentCapture(["follow_up"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add follow-up</button>
                  <button onClick={() => saveAgentCapture(["note"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add note</button>
                  <button onClick={() => saveAgentCapture(["hot_lead"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Mark as hot lead</button>
                  <button onClick={() => saveAgentCapture(["existing_customer"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Mark as existing customer</button>
                  <button onClick={() => saveAgentCapture(["walk_in_customer"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Mark as walk-in customer</button>
                  <button onClick={() => saveAgentCapture(["converted"]).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Mark as converted</button>
                </div>
                <div className="stack" style={{ marginTop: 8 }}>
                  <input placeholder="Bought item (e.g. silk saree)" value={purchaseItem} onChange={(e) => setPurchaseItem(e.target.value)} />
                  <input placeholder="Amount (e.g. ₹4,800)" value={purchaseAmount} onChange={(e) => setPurchaseAmount(e.target.value)} />
                  <input placeholder="Next follow-up (e.g. wedding blouse stitching)" value={followUpText} onChange={(e) => setFollowUpText(e.target.value)} />
                  <textarea rows={2} placeholder="Agent note (e.g. customer visited store today)" value={agentNote} onChange={(e) => setAgentNote(e.target.value)} />
                  <button onClick={() => saveAgentCapture().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Save Visit Log</button>
                </div>
              </div>
            </div>
            </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CommandCenterLayout() {
  const nav = useNavigate();
  const location = useLocation();
  const { businessName, wabaLabel } = useBusinessContext();
  const doLogout = () => {
    clearAuthStorage();
    nav("/login", { replace: true });
  };
  if (location.pathname === "/inbox" || location.pathname === "/contacts") return <Outlet />;
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
          <span>WABA: {wabaLabel}</span>
          <span>Range: Last 7 days</span>
          <button className="top-context-logout" onClick={doLogout}>Logout</button>
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
  const me = sessionStorage.getItem("auth_user_id") || "";
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
    loadCampaigns().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [statusFilter, typeFilter, ownerFilter, search, sortBy, sortDir, pageSize]);

  const filtered = rows;

  const pct = (num: number, den: number) => (den > 0 ? ((num / den) * 100).toFixed(1) : "0.0");
  const doAction = async (id: string, action: "pause" | "resume" | "cancel") => {
    setBusy(`${action}:${id}`);
    try {
      await api(`/campaigns/${id}/${action}`, "POST");
      await loadCampaigns(cursor);
    } catch (e) {
      alert(toUserErrorMessage(e));
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
      alert(toUserErrorMessage(e));
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
      alert(toUserErrorMessage(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Layout>
      <h2>Campaign List</h2>
      <WhatsAppSafetyScoreCard context="campaign" />
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
        <button disabled={!nextCursor} onClick={() => loadCampaigns(nextCursor).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Next Page</button>
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
      setErr(toUserErrorMessage(e));
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
      setMsg(toUserErrorMessage(e));
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
      setMsg(toUserErrorMessage(e));
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
      setMsg(toUserErrorMessage(e));
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
  const [preview, setPreview] = useState<CampaignPreviewResponse | null>(null);
  const [confirm, setConfirm] = useState<LaunchConfirmationResponse | null>(null);
  const nav = useNavigate();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [warmth, setWarmth] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [failures, setFailures] = useState<any[]>([]);
  const [sampleRendered, setSampleRendered] = useState<any[]>([]);
  const [segmentDiagnostics, setSegmentDiagnostics] = useState<SegmentDiagnosticsResponse | null>(null);
  const loadPreview = async () => {
    const p = await api<CampaignPreviewResponse>(`/campaigns/${campaignId}/preview`, "POST");
    setPreview(p);
    const c = await api<LaunchConfirmationResponse>(`/campaigns/${campaignId}/launch-confirmation`);
    setConfirm(c);
    const w = await api(`/campaigns/${campaignId}/audience-warmth`);
    const h = await api(`/campaigns/${campaignId}/health-score`);
    const f = await api<any[]>(`/campaigns/${campaignId}/recipient-explainability`);
    const d = await api<SegmentDiagnosticsResponse>(`/campaigns/${campaignId}/segment-diagnostics`);
    setWarmth(w);
    setHealth(h);
    setFailures(f);
    setSegmentDiagnostics(d);
    setSampleRendered((p.sample_messages || []).slice(0, 3));
  };

  useEffect(() => {
    loadPreview().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [campaignId]);

  return (
    <Layout>
      <h2>Step 5 - Campaign Preview</h2>
      <StepNav id={campaignId} wizard={wizard} />
      <WhatsAppSafetyScoreCard context="campaign" />
      <button onClick={() => loadPreview().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Refresh Preview</button>
      <div className="health-grid">
        <div className="health-card"><strong>Selected</strong><span>{preview?.selected_recipients || preview?.total_recipients || 0}</span></div>
        <div className="health-card"><strong>Eligible</strong><span>{preview?.eligible_recipients || 0}</span></div>
        <div className="health-card"><strong>Skipped</strong><span>{preview?.skipped_recipients || 0}</span></div>
        <div className="health-card"><strong>Estimated cost</strong><span>{preview?.estimated_cost?.currency || "USD"} {preview?.estimated_cost?.amount || 0}</span></div>
        <div className="health-card"><strong>Estimated duration</strong><span>{preview?.estimated_duration_minutes || 0} min</span></div>
        <div className="health-card"><strong>Risk score</strong><span>{health?.health_score || "n/a"}</span></div>
      </div>
      <section className="segment-doctor">
        <div className="segment-doctor-head">
          <h3>Anti-Spam Segment Doctor</h3>
          <span className="segment-doctor-risk">
            {(segmentDiagnostics?.safe_audience_count || 0) < (segmentDiagnostics?.original_count || 0) ? "This segment is dangerous" : "Segment risk is controlled"}
          </span>
        </div>
        <p className="segment-doctor-sub">Before sending, scan the segment and explain why it is bad.</p>
        <div className="segment-doctor-problems">
          <article><strong>{(segmentDiagnostics?.issues.unclear_opt_in || 0).toLocaleString()}</strong><span>contacts never opted in clearly</span></article>
          <article><strong>{(segmentDiagnostics?.issues.stale_engagement_180d || 0).toLocaleString()}</strong><span>contacts have not engaged in 180 days</span></article>
          <article><strong>{(segmentDiagnostics?.issues.ignored_3plus_campaigns || 0).toLocaleString()}</strong><span>previously ignored 3+ campaigns</span></article>
          <article><strong>{(segmentDiagnostics?.issues.complained_or_refunded_recently || 0).toLocaleString()}</strong><span>complained/refunded recently</span></article>
          <article><strong>{(segmentDiagnostics?.issues.outside_delivery_area || 0).toLocaleString()}</strong><span>outside your delivery area</span></article>
        </div>
        <div className="segment-doctor-clean">
          <h4>Clean segment</h4>
          <div className="segment-doctor-clean-grid">
            <div><span>Original</span><strong>{(segmentDiagnostics?.original_count || 0).toLocaleString()}</strong></div>
            <div><span>Safe audience</span><strong>{(segmentDiagnostics?.safe_audience_count || 0).toLocaleString()}</strong></div>
            <div><span>Expected revenue loss from cleaning</span><strong>{segmentDiagnostics?.expected_revenue_loss || "n/a"}</strong></div>
            <div><span>Quality risk reduction</span><strong>{segmentDiagnostics?.quality_risk_reduction || "n/a"}</strong></div>
          </div>
          <p className="segment-doctor-note">This becomes a trust product.</p>
        </div>
      </section>
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
  const [preview, setPreview] = useState<CampaignPreviewResponse | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    api<CampaignPreviewResponse>(`/campaigns/${campaignId}/preview`, "POST").then(setPreview).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [campaignId]);
  const resolvedPhone = target === "custom" ? testPhone : target === "owner" ? "+911111111111" : "+922222222222";
  const send = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/campaigns/${campaignId}/test-send`, "POST", { to_phone_e164: resolvedPhone });
      setWizard((s: WizardState) => ({ ...s, testSent: true }));
      setMsg("Test send queued. Delivery status will appear in campaign events.");
    } catch (e) {
      setMsg(toUserErrorMessage(e));
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
  const [confirm, setConfirm] = useState<LaunchConfirmationResponse | null>(null);
  const [scheduleAtLocal, setScheduleAtLocal] = useState("");
  const [launchText, setLaunchText] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<LaunchConfirmationResponse>(`/campaigns/${campaignId}/launch-confirmation`).then(setConfirm).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
        const latest = await api<LaunchConfirmationResponse>(`/campaigns/${campaignId}/launch-confirmation`);
        await api(`/campaigns/${campaignId}/launch`, "POST", {
          confirm: true,
          confirmation_text: "CONFIRM",
          expected_confirmation_hash: latest?.confirmation_hash,
        });
        setMsg("Campaign launched.");
      }
    } catch (e) {
      setMsg(toUserErrorMessage(e));
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
  const [preview, setPreview] = useState<CampaignPreviewResponse | null>(null);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [blackbox, setBlackbox] = useState<CampaignBlackboxEvent[]>([]);
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
    api(`/campaigns/${id}`).then(setState).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/campaigns/${id}/analytics`).then(setAnalytics).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/campaigns/${id}/health-score`).then(setHealth).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<CampaignPreviewResponse>(`/campaigns/${id}/preview`, "POST").then(setPreview).catch(() => undefined);
    api<CampaignEvent[]>(`/campaigns/${id}/events`).then(setEvents).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<CampaignBlackboxEvent[]>(`/campaigns/${id}/blackbox`).then(setBlackbox).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
    loadRecipients("").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      setActionMsg(toUserErrorMessage(e));
    }
  };

  const retryFailed = async () => {
    try {
      const failed = normalizeQueryPage<any>(await api<unknown>(`/campaigns/${id}/recipients?status=failed&limit=100`)).items;
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
      await loadRecipients(recipientsCursor || "").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
      const a = await api(`/campaigns/${id}/analytics`);
      setAnalytics(a);
    } catch (e) {
      setActionMsg(toUserErrorMessage(e));
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
      setActionMsg(toUserErrorMessage(e));
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
        <button onClick={() => doControl("pause").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Pause</button>
        <button onClick={() => doControl("resume").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Resume</button>
        <button onClick={() => doControl("cancel").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Cancel</button>
        <a href={`/campaigns/${id}/cost`}>Export</a>
        <button onClick={() => retryFailed().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Retry failed</button>
        <button onClick={() => createRetarget().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Create retargeting</button>
      </div>
      <p>{actionMsg}</p>

      <h3>Timeline</h3>
      <div className="timeline-list">
        {mergedTimeline.map((e, i) => (
          <div key={`${e.ts}-${i}`} className="timeline-item">
            <strong>{String(e.title || "").split("_").join(" ")}</strong>
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
            loadRecipients(prev).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
          }}
        >
          Previous Page
        </button>
        <button
          disabled={!recipientsNextCursor}
          onClick={() => {
            setRecipientsPrevCursors((arr) => [...arr, recipientsCursor || ""]);
            loadRecipients(recipientsNextCursor).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      .catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
    api(`/campaigns/${id}/analytics`).then(setData).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
    api(`/campaigns/${id}/whatsapp-health`).then(setData).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      <WhatsAppSafetyScoreCard context="phone_number" />
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
    api(`/campaigns/${id}/export`).then(setData).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [id]);
  return (
    <Layout>
      <h2>Campaign Cost Report / Export</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
      {data?.download_url ? <a href={`${safeDownloadUrl(data.download_url) || "#"}`} target="_blank" rel="noopener noreferrer">Download CSV</a> : null}
    </Layout>
  );
}

function ContactsCrmPage() {
  const prefs = loadTablePrefs("contacts");
  const nav = useNavigate();
  const [rows, setRows] = useState<ContactCRMRecord[]>([]);
  const [filteredRows, setFilteredRows] = useState<ContactCRMRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [selection, setSelection] = useState<SelectionState>({ mode: "explicit", ids: [] });
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
  const [appliedQueryHash, setAppliedQueryHash] = useState("");
  const [totalApprox, setTotalApprox] = useState<number | undefined>(undefined);

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
    setAppliedQueryHash(data.appliedQueryHash || "");
    setTotalApprox(data.totalApprox);
    setCursor((cursorValue ?? cursor) || "");
    setNextCursor(data.nextCursor || "");
    if (data.items.length > 0 && !selectedId) setSelectedId(data.items[0].id);
  };

  const currentQueryForSelection = useMemo(() => ({
    search: search || null,
    tag: tag || null,
    opt_in_status: optInStatus || null,
    suppressed: suppressed === "yes" ? true : suppressed === "no" ? false : null,
    segment_id: null,
    sort_by: sortBy,
    sort_dir: sortDir,
  }), [search, tag, optInStatus, suppressed, sortBy, sortDir]);

  useEffect(() => {
    saveTablePrefs("contacts", { sortBy, sortDir, pageSize });
  }, [sortBy, sortDir, pageSize]);

  useEffect(() => {
    load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<any[]>("/contacts/tags").then(setTags).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<any[]>("/contacts/custom-fields").then(setFields).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api<any[]>("/contacts/segments").then(setSegments).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    api<ContactCRMRecord>(`/contacts/${selectedId}/record`).then(setRecord).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/contacts/${selectedId}/timeline`).then(setTimeline).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/contacts/${selectedId}/import-history`).then(setImports).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/contacts/${selectedId}/suppression-history`).then(setSuppressionHistory).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      setSaveMsg(toUserErrorMessage(e));
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
      setSaveMsg(toUserErrorMessage(e));
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
      setSaveMsg(toUserErrorMessage(e));
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
    setSelection((prev) => {
      if (prev.mode === "all_matching_query") {
        const ex = new Set(prev.excludedIds);
        if (ex.has(id)) ex.delete(id);
        else ex.add(id);
        return { ...prev, excludedIds: Array.from(ex) };
      }
      const ids = new Set(prev.ids);
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      return { mode: "explicit", ids: Array.from(ids) };
    });
  };

  const toggleSelectAllVisible = () => {
    const visibleIds = filteredRows.map((r) => r.id);
    const allSelected = visibleIds.every((id) => {
      if (selection.mode === "all_matching_query") return !selection.excludedIds.includes(id);
      return selection.ids.includes(id);
    });
    setSelection((prev) => {
      if (prev.mode === "all_matching_query") {
        const ex = new Set(prev.excludedIds);
        if (allSelected) visibleIds.forEach((id) => ex.add(id));
        else visibleIds.forEach((id) => ex.delete(id));
        return { ...prev, excludedIds: Array.from(ex) };
      }
      const ids = new Set(prev.ids);
      if (allSelected) visibleIds.forEach((id) => ids.delete(id));
      else visibleIds.forEach((id) => ids.add(id));
      return { mode: "explicit", ids: Array.from(ids) };
    });
  };

  const isRowSelected = (id: string) => {
    if (selection.mode === "all_matching_query") return !selection.excludedIds.includes(id);
    return selection.ids.includes(id);
  };
  const selectedIdsSet = useMemo(() => {
    const set = new Set<string>();
    for (const r of filteredRows) {
      if (isRowSelected(r.id)) set.add(r.id);
    }
    return set;
  }, [filteredRows, selection]);
  const selectAllMatchingQuery = async () => {
    if (!appliedQueryHash) return;
    try {
      const snap = await api<{ query_snapshot_id: string; query_hash: string }>("/contacts/query-snapshots", "POST", {
        query: currentQueryForSelection,
      });
      setSelection({
        mode: "all_matching_query",
        queryHash: snap.query_hash || appliedQueryHash,
        querySnapshotId: snap.query_snapshot_id,
        excludedIds: [],
      });
      setSaveMsg("Selection mode: all matching current query (snapshot frozen).");
    } catch (e) {
      setSaveMsg(toUserErrorMessage(e));
    }
  };
  const clearSelection = () => setSelection({ mode: "explicit", ids: [] });

  const bulkAddTag = async () => {
    if (selection.mode !== "explicit") {
      setSaveMsg("Bulk tag operations currently support explicit selection only.");
      return;
    }
    const ids = Array.from(selection.ids);
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
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const bulkRemoveTag = async () => {
    if (selection.mode !== "explicit") {
      setSaveMsg("Bulk tag operations currently support explicit selection only.");
      return;
    }
    const ids = Array.from(selection.ids);
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
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const bulkSuppress = async () => {
    if (selection.mode === "explicit" && selection.ids.length === 0) return;
    setSaveMsg("Applying suppression...");
    try {
      const response = await api<{ status: string; suppressed_count?: number }>("/contacts/bulk-suppress", "POST", {
        selection,
        queryHash: selection.mode === "all_matching_query" ? selection.queryHash : appliedQueryHash,
        querySnapshotId: selection.mode === "all_matching_query" ? selection.querySnapshotId : undefined,
        query: currentQueryForSelection,
      });
      setSaveMsg(`Suppressed ${response.suppressed_count || 0} contacts.`);
      await load();
    } catch (e) {
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const bulkExport = async () => {
    if (selection.mode === "explicit" && selection.ids.length === 0) return;
    setSaveMsg("Starting export job...");
    try {
      const created = await api<{ job_id: string }>("/contacts/export-jobs", "POST", {
        resource: "contacts",
        columns: ["name", "phone_e164", "opt_in_status"],
        selection,
        queryHash: selection.mode === "all_matching_query" ? selection.queryHash : appliedQueryHash,
        querySnapshotId: selection.mode === "all_matching_query" ? selection.querySnapshotId : undefined,
        query: currentQueryForSelection,
      });
      let status = await api<{ status: string; progress?: number; download_url?: string; rows?: number }>(`/contacts/export-jobs/${created.job_id}`);
      for (let i = 0; i < 12 && status.status !== "completed"; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        status = await api(`/contacts/export-jobs/${created.job_id}`);
      }
      if (status.status === "completed" && status.download_url) {
        window.open(`${API_ORIGIN}${status.download_url}`, "_blank");
        setSaveMsg(`Export ready. Rows: ${status.rows || 0}`);
      } else {
        setSaveMsg(`Export still processing (status: ${status.status}).`);
      }
    } catch (e) {
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const bulkCreateCampaign = async () => {
    const selected = filteredRows.filter((r) => isRowSelected(r.id));
    if (!selected.length) return;
    setSaveMsg("Creating campaign draft...");
    try {
      const phone = String(selected[0]?.custom_attributes?.["default_phone_number_id"] || "").trim();
      const templateId = String(selected[0]?.custom_attributes?.["default_template_id"] || "").trim();
      if (!phone) {
        setSaveMsg("Cannot create campaign draft: add default_phone_number_id in selected contact custom attributes.");
        return;
      }
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
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const bulkCreateSegment = async () => {
    const selected = filteredRows.filter((r) => isRowSelected(r.id));
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
      setSaveMsg(toUserErrorMessage(e));
    }
  };

  const contactColumns: DataTableColumn<ContactCRMRecord>[] = [
    { key: "name", title: "Name", sortable: true, render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); nav(`/contacts/${r.id}`); }}>{r.name || "-"}</a> },
    { key: "phone_e164", title: "Phone", sortable: true, render: (r) => r.phone_e164 || "-" },
    { key: "city", title: "City", render: (r) => String(r.custom_attributes?.["city"] || "-") },
    { key: "last_product", title: "Last product", render: (r) => String(r.custom_attributes?.["last_product"] || "-") },
    { key: "total_spend", title: "Total spend", render: (r) => (r.custom_attributes?.["total_spend"] != null ? String(r.custom_attributes?.["total_spend"]) : "-") },
    { key: "last_purchase_at", title: "Last purchase", render: (r) => String(r.custom_attributes?.["last_purchase_at"] || "-") },
    { key: "tags", title: "Tags", render: (r) => (r.tags || []).join(", ") || "-" },
    { key: "opt_in_status", title: "Opt-in status", sortable: true, render: (r) => r.opt_in_status },
    { key: "last_message_at", title: "Last message", sortable: true, render: (r) => r.last_message_at ? new Date(r.last_message_at).toLocaleString() : "-" },
    { key: "last_campaign_at", title: "Last campaign", sortable: true, render: (r) => r.last_campaign_at ? new Date(r.last_campaign_at).toLocaleDateString() : "-" },
    { key: "last_order_at", title: "Last order", sortable: true, render: (r) => r.last_order_at ? new Date(r.last_order_at).toLocaleDateString() : "-" },
  ];

  return (
    <Layout>
      <h2>Contacts</h2>
      <WhatsAppSafetyScoreCard context="segment" />
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
          load("").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
        }}>Search Contacts</button>
      </div>
      <div className="inbox-filters">
        {["All", "Opted in", "Opted out", "Never messaged", "Recently active", "VIP", "Cold audience", "Clicked campaign", "Replied to campaign", "Purchased", "Abandoned cart"].map((f) => (
          <button key={f} className={contactFilter === f ? "filter-active" : ""} onClick={() => setContactFilter(f)}>{f}</button>
        ))}
      </div>
      <div className="campaign-actions">
        <input placeholder="tag for bulk add/remove" value={bulkTagValue} onChange={(e) => setBulkTagValue(e.target.value)} />
        <button onClick={() => selectAllMatchingQuery().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} disabled={!appliedQueryHash}>Select all matching query</button>
        <button onClick={clearSelection}>Clear selection</button>
        <button onClick={() => bulkAddTag().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add tag</button>
        <button onClick={() => bulkRemoveTag().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Remove tag</button>
        <button onClick={() => bulkExport().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Export</button>
        <button onClick={() => bulkSuppress().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Suppress</button>
        <button onClick={() => bulkCreateCampaign().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Create campaign</button>
        <button onClick={() => bulkCreateSegment().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Create segment</button>
      </div>
      <div className="crm-layout">
        <div>
          <h3>Contact List</h3>
          <RemoteDataTable
            columns={contactColumns}
            rows={filteredRows}
            rowKey={(r) => r.id}
            loading={false}
            selectedIds={selectedIdsSet}
            selection={selection}
            visibleSelectedCount={selectedIdsSet.size}
            totalApprox={totalApprox}
            storageKey="contacts_table"
            pageSize={pageSize}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setCursor("");
              setNextCursor("");
              setPrevCursors([]);
              setTimeout(() => { load("").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV })); }, 0);
            }}
            onToggleRow={toggleSelect}
            onToggleAllVisible={toggleSelectAllVisible}
            onSelectAllMatching={selectAllMatchingQuery}
            onClearSelection={clearSelection}
            allVisibleSelected={filteredRows.length > 0 && filteredRows.every((r) => isRowSelected(r.id))}
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
              setTimeout(() => { load("").catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV })); }, 0);
            }}
          >
            <div className="campaign-actions">
              <button
                disabled={prevCursors.length === 0}
                onClick={() => {
                  const prev = prevCursors[prevCursors.length - 1] || "";
                  setPrevCursors((arr) => arr.slice(0, -1));
                  load(prev).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
                }}
              >
                Previous Page
              </button>
              <button
                disabled={!nextCursor}
                onClick={() => {
                  setPrevCursors((arr) => [...arr, cursor || ""]);
                  load(nextCursor).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
                }}
              >
                Next Page
              </button>
            </div>
          </RemoteDataTable>
        </div>
        <div>
          <h3>Contact Record</h3>
          <div className="stack">
            <input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="Name" />
            <input value={editEmail} onChange={(e) => setEditEmail(e.target.value)} placeholder="Email" />
            <input value={editTags} onChange={(e) => setEditTags(e.target.value)} placeholder="tags (comma-separated)" />
            <textarea rows={8} value={editAttrs} onChange={(e) => setEditAttrs(e.target.value)} />
            <button onClick={() => saveInlineEdits().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Save Tags / Custom Fields</button>
            <div className="grid">
              <select value={editOptIn} onChange={(e) => setEditOptIn(e.target.value)}>
                <option value="opted_in">opted_in</option>
                <option value="opted_out">opted_out</option>
                <option value="unsubscribed">unsubscribed</option>
                <option value="unknown">unknown</option>
              </select>
              <input value={editOptInSource} onChange={(e) => setEditOptInSource(e.target.value)} placeholder="opt_in_source" />
            </div>
            <button onClick={() => saveOptIn().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Save Opt-in Status</button>
            <div className="grid">
              <button onClick={() => setSuppression(true).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Suppress (Block)</button>
              <button onClick={() => setSuppression(false).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Unsuppress (Unblock)</button>
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


function ContactsCommandCenterPage() {
  const nav = useNavigate();
  const { businessName, wabaLabel } = useBusinessContext();
  const [rows, setRows] = useState<ContactCRMRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [optInStatus, setOptInStatus] = useState("");
  const [suppressed, setSuppressed] = useState("");
  const [contactFilter, setContactFilter] = useState("All");
  const [bulkTagValue, setBulkTagValue] = useState("");
  const [record, setRecord] = useState<ContactCRMRecord | null>(null);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editOptIn, setEditOptIn] = useState("unknown");
  const [saveMsg, setSaveMsg] = useState("");

  const load = async () => {
    const query: QueryState = {
      limit: 100,
      sortBy: "updated_at",
      sortDir: "desc",
      search,
      filters: {
        tag,
        opt_in_status: optInStatus,
        suppressed: suppressed === "yes" ? true : suppressed === "no" ? false : undefined,
      },
    };
    const data = normalizeQueryPage<ContactCRMRecord>(await api<unknown>(`/contacts/crm/records?${toQueryString(query)}`));
    setRows(data.items);
    if (data.items.length && !selectedId) setSelectedId(data.items[0].id);
  };

  useEffect(() => { load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV })); }, []);
  useEffect(() => {
    if (!selectedId) return;
    api<ContactCRMRecord>(`/contacts/${selectedId}/record`).then(setRecord).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [selectedId]);
  useEffect(() => {
    if (!record) return;
    setEditName(record.name || "");
    setEditEmail(record.email || "");
    setEditTags((record.tags || []).join(", "));
    setEditOptIn(record.opt_in_status || "unknown");
  }, [record]);

  const filteredRows = useMemo(() => {
    const now = Date.now();
    return rows.filter((r) => {
      const tagsLower = (r.tags || []).map((t) => String(t).toLowerCase());
      const purchased = Boolean(r.last_order_at);
      const recentlyActive = Boolean(r.last_inbound_at && new Date(r.last_inbound_at).getTime() >= now - 7 * 24 * 60 * 60 * 1000);
      if (contactFilter === "All") return true;
      if (contactFilter === "Opted in") return r.opt_in_status === "opted_in";
      if (contactFilter === "Opted out") return ["opted_out", "unsubscribed"].includes(r.opt_in_status);
      if (contactFilter === "Never messaged") return !r.last_message_at;
      if (contactFilter === "Recently active") return recentlyActive;
      if (contactFilter === "VIP") return tagsLower.includes("vip") || purchased;
      if (contactFilter === "Cold audience") return !recentlyActive && !purchased && !r.last_reply_at;
      if (contactFilter === "Clicked campaign") return Boolean(r.last_click_at);
      if (contactFilter === "Replied to campaign") return Boolean(r.last_reply_at);
      if (contactFilter === "Purchased") return purchased;
      if (contactFilter === "Abandoned cart") return tagsLower.includes("abandoned_cart") || tagsLower.includes("cart");
      return true;
    });
  }, [rows, contactFilter]);

  const initials = (name?: string | null) => (name || "Unknown").trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() || "").join("") || "UN";
  const rel = (value?: string | null) => {
    if (!value) return "-";
    const mins = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  };
  const optInCount = rows.filter((r) => r.opt_in_status === "opted_in").length;
  const optOutCount = rows.filter((r) => ["opted_out", "unsubscribed"].includes(r.opt_in_status)).length;
  const unknownCount = Math.max(0, rows.length - optInCount - optOutCount);
  const selected = record || rows.find((r) => r.id === selectedId) || null;

  const saveContact = async () => {
    if (!selectedId) return;
    setSaveMsg("Saving contact...");
    try {
      await api(`/contacts/${selectedId}`, "PATCH", { name: editName, email: editEmail, tags: editTags.split(",").map((t) => t.trim()).filter(Boolean) });
      await api(`/contacts/${selectedId}/opt-in`, "POST", { opt_in_status: editOptIn, opt_in_source: "crm_manual" });
      setSaveMsg("Contact saved.");
      await load();
    } catch (e) { setSaveMsg(toUserErrorMessage(e)); }
  };

  return (
    <div className="contacts-replica">
      <h2 className="sr-only">Merchant Command Center - Contacts page with search filters, segment chips, bulk actions, contact list table, and contact record form</h2>
      <div className="shell">
        <aside className="sidebar"><div className="sidebar-top"><div className="sidebar-brand">Command Center</div><div className="sidebar-sub">WhatsApp Business Platform</div></div><div className="nav-group"><div className="nav-label">Main</div><div className="nav-item" onClick={() => nav('/dashboard')}>Dashboard</div><div className="nav-item" onClick={() => nav('/inbox')}>Inbox</div><div className="nav-item active">Contacts</div><div className="nav-item" onClick={() => nav('/campaigns')}>Campaigns</div><div className="nav-item" onClick={() => nav('/templates')}>Templates</div></div><div className="nav-group"><div className="nav-label">Tools</div><div className="nav-item" onClick={() => nav('/automations')}>Automations</div><div className="nav-item" onClick={() => nav('/commerce')}>Commerce</div><div className="nav-item" onClick={() => nav('/analytics')}>Analytics</div><div className="nav-item" onClick={() => nav('/billing')}>Billing</div></div><div className="nav-group"><div className="nav-label">Account</div><div className="nav-item" onClick={() => nav('/settings')}>Settings</div><div className="nav-item" onClick={() => nav('/admin-support')}>Admin / Support</div></div><div className="sidebar-footer"><div className="biz-name">{businessName}</div><div className="biz-info">WABA: {wabaLabel}<br />Range: Last 7 days</div></div></aside>
        <main className="main"><div className="topbar"><div className="topbar-crumb">Command Center › <span>Contacts</span></div><div className="topbar-meta"><div className="meta-chip">{businessName}</div><div className="meta-chip">WABA: {wabaLabel}</div><div className="meta-chip">Last 7 days</div><button className="btn-logout" onClick={() => { clearAuthStorage(); nav('/login', { replace: true }); }}>Logout</button></div></div>
          <div className="page-header"><div><div className="page-title">Contacts</div><div className="page-subtitle">Search, segment, and manage your WhatsApp contacts</div></div><div className="stat-row"><div className="stat-box"><div className="stat-num">{rows.length}</div><div className="stat-lbl">Total</div></div><div className="stat-box"><div className="stat-num green">{optInCount}</div><div className="stat-lbl">Opted in</div></div><div className="stat-box"><div className="stat-num red">{optOutCount}</div><div className="stat-lbl">Opted out</div></div><div className="stat-box"><div className="stat-num amber">{unknownCount}</div><div className="stat-lbl">Unknown</div></div></div></div>
          <div className="body"><section className="contacts-panel"><div className="filter-card"><div className="filter-row"><input className="filter-input" placeholder="Search name / email / phone / wa_id..." value={search} onChange={(e) => setSearch(e.target.value)} /><input className="filter-input narrow" placeholder="Filter tag..." value={tag} onChange={(e) => setTag(e.target.value)} /></div><div className="filter-row"><input className="filter-input" placeholder="opt_in_status (opted_in / opted_out / unknown)..." value={optInStatus} onChange={(e) => setOptInStatus(e.target.value)} /><select className="filter-select" value={suppressed} onChange={(e) => setSuppressed(e.target.value)}><option value="">Suppression: any</option><option value="yes">Suppressed</option><option value="no">Not suppressed</option></select></div><button className="btn-search" onClick={() => load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Search Contacts</button><div className="segment-row">{["All", "Opted in", "Opted out", "Never messaged", "Recently active", "VIP", "Cold audience", "Clicked campaign", "Replied to campaign", "Purchased", "Abandoned cart"].map((f) => <button key={f} className={`seg-chip ${contactFilter === f ? 'active' : ''}`} onClick={() => setContactFilter(f)}>{f}</button>)}</div></div>
            <div className="actions-row"><input className="action-tag-input" placeholder="tag for bulk add/remove..." value={bulkTagValue} onChange={(e) => setBulkTagValue(e.target.value)} /><button className="act-btn">Select all matching</button><button className="act-btn">Clear selection</button><button className="act-btn green">Add tag</button><button className="act-btn red">Remove tag</button><button className="act-btn">Export</button><button className="act-btn red">Suppress</button><button className="act-btn blue">Create campaign</button><button className="act-btn teal">Create segment</button></div>
            <div className="table-section"><div className="table-topbar"><div className="table-topbar-title">Contact list <span>{filteredRows.length} results</span></div><select className="page-select"><option>100 / page</option><option>50 / page</option><option>25 / page</option></select><div className="col-toggles">{["Name", "Phone", "City", "Last product", "Total spend", "Last purchase", "Tags", "Opt-in", "Last msg", "Last campaign", "Last order"].map((c) => <label key={c} className="col-toggle"><input type="checkbox" defaultChecked /> <span>{c}</span></label>)}</div></div><table><thead><tr><th><input type="checkbox" /></th><th>Name</th><th>Phone</th><th>City</th><th>Last product</th><th>Total spend</th><th>Last purchase</th><th>Tags</th><th>Opt-in status</th><th>Last message</th><th>Last campaign</th><th>Last order</th></tr></thead><tbody>{filteredRows.map((r) => <tr key={r.id} className={selectedId === r.id ? "selected" : ""} onClick={() => setSelectedId(r.id)}><td><input type="checkbox" /></td><td><div className="name-cell"><div className="c-avatar">{initials(r.name)}</div>{r.name || "Unknown"}</div></td><td>{r.phone_e164 || r.wa_id || "-"}</td><td>{String(r.custom_attributes?.["city"] || "-")}</td><td>{String(r.custom_attributes?.["last_product"] || "-")}</td><td>{r.custom_attributes?.["total_spend"] != null ? String(r.custom_attributes?.["total_spend"]) : "-"}</td><td>{String(r.custom_attributes?.["last_purchase_at"] || "-")}</td><td>{(r.tags || []).slice(0, 2).map((t) => <span key={t} className="tag-pill">{t}</span>)}</td><td><span className={`optin-pill ${r.opt_in_status === 'opted_in' ? 'ok' : r.opt_in_status === 'unknown' ? 'warn' : 'bad'}`}>{r.opt_in_status || "unknown"}</span></td><td>{rel(r.last_message_at)}</td><td>{rel(r.last_campaign_at)}</td><td>{r.last_order_at ? rel(r.last_order_at) : "-"}</td></tr>)}</tbody></table></div></section>
            <aside className="right-panel"><div className="rp-header"><div className="rp-title">Contact record</div><div className="rp-sub">Create or edit the selected contact</div></div><div className="rp-body"><div className="stat-row"><div className="stat-box"><div className="stat-num">{selected?.tags?.length || 0}</div><div className="stat-lbl">Tags</div></div><div className="stat-box"><div className="stat-num">{selected?.last_message_at ? '1' : '0'}</div><div className="stat-lbl">Threads</div></div></div><label className="form-field"><span className="form-label">Name</span><input className="form-input" value={editName} onChange={(e) => setEditName(e.target.value)} /></label><label className="form-field"><span className="form-label">Phone</span><input className="form-input" value={selected?.phone_e164 || ''} readOnly /></label><label className="form-field"><span className="form-label">Email</span><input className="form-input" value={editEmail} onChange={(e) => setEditEmail(e.target.value)} /></label><label className="form-field"><span className="form-label">Tags</span><input className="form-input" value={editTags} onChange={(e) => setEditTags(e.target.value)} /></label><label className="form-field"><span className="form-label">Opt-in status</span><select className="form-input" value={editOptIn} onChange={(e) => setEditOptIn(e.target.value)}><option value="opted_in">opted_in</option><option value="opted_out">opted_out</option><option value="unsubscribed">unsubscribed</option><option value="unknown">unknown</option></select></label>{saveMsg && <div className="save-msg">{saveMsg}</div>}</div><div className="rp-footer"><button className="btn-full primary" onClick={() => saveContact().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Save Contact</button><button className="btn-full">Open Detail</button><button className="btn-full danger">Suppress Contact</button></div></aside>
          </div>
        </main>
      </div>
    </div>
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
    load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
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
      setActionMsg(toUserErrorMessage(e));
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
      setActionMsg(toUserErrorMessage(e));
    }
  };

  const suppressContact = async () => {
    setActionMsg("Suppressing...");
    try {
      await api(`/contacts/${contactId}/block`, "POST", { blocked: true });
      setActionMsg("Contact suppressed.");
      await load();
    } catch (e) {
      setActionMsg(toUserErrorMessage(e));
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
            <button onClick={() => addNote().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add note</button>
            <input placeholder="Add tag" value={newTag} onChange={(e) => setNewTag(e.target.value)} />
            <button onClick={() => addTag().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Add tag</button>
            <button onClick={() => suppressContact().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Suppress contact</button>
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

function ShopifyOnboardingPage() {
  const nav = useNavigate();
  return (
    <Layout>
      <h2>Shopify Onboarding</h2>
      <p>Connect your Shopify store to sync customers, orders, products, and events.</p>
      <div className="grid">
        <article className="campaign-card"><h3>1. Connect store</h3><p>Authorize Shopify and grant app scopes.</p></article>
        <article className="campaign-card"><h3>2. Sync data</h3><p>Import customers, order history, and purchase behavior.</p></article>
        <article className="campaign-card"><h3>3. Activate campaigns</h3><p>Use synced segments for WhatsApp broadcasts.</p></article>
      </div>
      <div className="campaign-actions">
        <button onClick={() => nav("/settings/whatsapp-setup")}>Start Connection</button>
        <button onClick={() => nav("/dashboard")}>Back to Dashboard</button>
      </div>
    </Layout>
  );
}

function OfflineOnboardingPage() {
  const nav = useNavigate();
  const { businessName } = useBusinessContext();
  const widget = useWidgetSettings();
  const [fileName, setFileName] = useState("");
  const [rawCsv, setRawCsv] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({
    phone_e164: "",
    name: "",
    city: "",
    total_spend: "",
    last_product: "",
    last_purchase_at: "",
  });
  const [importTag, setImportTag] = useState(`offline_import_${new Date().toISOString().slice(0, 10)}`);
  const [optInSource, setOptInSource] = useState("offline_store_visit");
  const [jobId, setJobId] = useState("");
  const [jobState, setJobState] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [qrBranch, setQrBranch] = useState("");
  const [qrMessage, setQrMessage] = useState("");
  const [qrPhoneNumber, setQrPhoneNumber] = useState("919876543210");
  const [qrPreviewPhone, setQrPreviewPhone] = useState("+919876543210");
  const [qrCaptureName, setQrCaptureName] = useState("");
  const [regType, setRegType] = useState("warranty");
  const [regPhone, setRegPhone] = useState("+919912345678");
  const [regName, setRegName] = useState("Mixer Buyer");
  const [regBranch, setRegBranch] = useState("");
  const [regProduct, setRegProduct] = useState("mixer_grinder");
  const [regPurchaseDate, setRegPurchaseDate] = useState(new Date().toISOString().slice(0, 10));
  const [regWarrantyDate, setRegWarrantyDate] = useState("");
  const [regServiceReminder, setRegServiceReminder] = useState("");
  const [regConsent, setRegConsent] = useState<"YES" | "NO">("YES");

  useEffect(() => {
    if (!widget?.widget_title) return;
    setQrMessage((prev) => prev || widget.widget_title);
  }, [widget]);

  const detectHeaders = (csvText: string) => {
    const firstLine = (csvText.split(/\r?\n/).find((line) => line.trim().length > 0) || "").trim();
    const cols = firstLine.split(",").map((x) => x.trim().replace(/^"|"$/g, ""));
    setHeaders(cols);
    const auto = (needle: string[]) => cols.find((c) => needle.some((n) => c.toLowerCase().includes(n))) || "";
    setMapping({
      phone_e164: auto(["mobile", "phone", "number"]),
      name: auto(["name", "customer"]),
      city: auto(["city", "location"]),
      total_spend: auto(["amount", "spend", "bill"]),
      last_product: auto(["item", "product", "category"]),
      last_purchase_at: auto(["date", "purchase", "bill date"]),
    });
  };

  const onFileSelected = async (file: File | null) => {
    if (!file) return;
    const text = await file.text();
    setRawCsv(text);
    setFileName(file.name);
    detectHeaders(text);
    setMsg("CSV uploaded and columns detected.");
  };

  const toCanonicalCsv = () => {
    if (!rawCsv.trim()) return "";
    const lines = rawCsv.split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length < 2) return "";
    const srcHeaders = lines[0].split(",").map((x) => x.trim().replace(/^"|"$/g, ""));
    const indexMap: Record<string, number> = {};
    srcHeaders.forEach((h, i) => {
      indexMap[h] = i;
    });
    const out: string[] = [];
    out.push("phone_e164,name,city,last_product,total_spend,last_purchase_at,tags");
    const cityHeader = mapping.city;
    const spendHeader = mapping.total_spend;
    const productHeader = mapping.last_product;
    const purchaseHeader = mapping.last_purchase_at;
    for (const line of lines.slice(1)) {
      const cols = line.split(",").map((x) => x.trim().replace(/^"|"$/g, ""));
      const phone = mapping.phone_e164 && indexMap[mapping.phone_e164] !== undefined ? (cols[indexMap[mapping.phone_e164]] || "") : "";
      const name = mapping.name && indexMap[mapping.name] !== undefined ? (cols[indexMap[mapping.name]] || "") : "";
      const city = cityHeader && indexMap[cityHeader] !== undefined ? (cols[indexMap[cityHeader]] || "") : "";
      const spend = spendHeader && indexMap[spendHeader] !== undefined ? (cols[indexMap[spendHeader]] || "") : "";
      const product = productHeader && indexMap[productHeader] !== undefined ? (cols[indexMap[productHeader]] || "") : "";
      const purchase = purchaseHeader && indexMap[purchaseHeader] !== undefined ? (cols[indexMap[purchaseHeader]] || "") : "";
      const tags = [importTag, city ? `city_${city.toLowerCase().replace(/\s+/g, "_")}` : "", product ? `product_${product.toLowerCase().replace(/\s+/g, "_")}` : "", spend ? `spend_${spend}` : "", purchase ? `purchase_${purchase}` : "", optInSource ? `optin_${optInSource.toLowerCase().replace(/\s+/g, "_")}` : ""].filter(Boolean).join(",");
      out.push([phone, name, city, product, spend, purchase, tags].map((v) => `"${String(v || "").replace(/"/g, '""')}"`).join(","));
    }
    return out.join("\n");
  };

  const pollJob = async (id: string) => {
    const data = await api(`/contacts/import/jobs/${id}`);
    setJobState(data);
    if (["completed", "completed_with_errors", "failed", "not_found"].includes(String(data?.status || ""))) return;
    setTimeout(() => {
      pollJob(id).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    }, 2000);
  };

  const runImport = async () => {
    if (!rawCsv.trim()) {
      setMsg("Upload a CSV file first.");
      return;
    }
    if (!mapping.phone_e164) {
      setMsg("Map a phone column first.");
      return;
    }
    setBusy(true);
    setMsg("Running server-side CSV import...");
    try {
      const csvText = toCanonicalCsv();
      const started = await api<{ job_id: string; status: string; created: number; updated: number; error_rows: number }>("/contacts/import/execute", "POST", {
        csv_text: csvText,
        source_file_name: fileName,
      });
      setJobId(started.job_id);
      await pollJob(started.job_id);
      setMsg("CSV import completed. Review status and errors below.");
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const createSegmentFromImport = async () => {
    if (!importTag.trim()) {
      setMsg("Set an import tag first.");
      return;
    }
    try {
      const created = await api<{ segment_id: string }>("/contacts/segments", "POST", {
        name: `Imported Contacts - ${importTag}`,
        visibility: "private",
        filters: { tags_any: [importTag] },
      });
      setMsg(`Segment created: ${created.segment_id}`);
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    }
  };

  const qrJoinUrl = `https://wa.me/${qrPhoneNumber.replace(/\D/g, "")}?text=${encodeURIComponent(qrMessage.trim() || "START")}`;
  const qrImageUrl = `https://api.qrserver.com/v1/create-qr-code/?size=340x340&data=${encodeURIComponent(qrJoinUrl)}`;
  const simulateQrOptIn = async () => {
    if (!qrBranch.trim()) {
      setMsg("Set store branch before QR opt-in capture.");
      return;
    }
    if (!qrMessage.trim()) {
      setMsg("Set prefilled QR message before capture.");
      return;
    }
    try {
      const res = await api<{ status: string; contact_id: string; opt_in_status: string }>(
        "/contacts/qr-opt-ins/capture",
        "POST",
        {
          phone_e164: qrPreviewPhone.trim(),
          name: qrCaptureName.trim() || undefined,
          branch: qrBranch.trim(),
          source: "in_store_qr",
          prefilled_message: qrMessage.trim(),
          tags: ["walk_in_customer"],
        },
        { headers: { "Idempotency-Key": `qr-optin-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` } },
      );
      setMsg(`QR opt-in captured: ${res.contact_id} (${res.opt_in_status})`);
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    }
  };
  const submitOfflineRegistration = async () => {
    if (!regBranch.trim()) {
      setMsg("Set store branch before saving registration.");
      return;
    }
    try {
      const res = await api<{ status: string; contact_id: string; opt_in_status: string; future_campaign_eligible: boolean }>(
        "/contacts/offline-registrations/capture",
        "POST",
        {
          phone_e164: regPhone.trim(),
          name: regName.trim(),
          branch: regBranch.trim(),
          registration_type: regType,
          product_purchased: regProduct.trim() || undefined,
          purchase_date: regPurchaseDate ? new Date(`${regPurchaseDate}T10:00:00+05:30`).toISOString() : undefined,
          warranty_until: regWarrantyDate ? new Date(`${regWarrantyDate}T10:00:00+05:30`).toISOString() : undefined,
          service_reminder_at: regServiceReminder ? new Date(`${regServiceReminder}T10:00:00+05:30`).toISOString() : undefined,
          consent_reply: regConsent,
        },
        { headers: { "Idempotency-Key": `offline-reg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` } },
      );
      setMsg(`Registration saved: ${res.contact_id} | opt-in=${res.opt_in_status} | eligible=${res.future_campaign_eligible ? "yes" : "no"}`);
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    }
  };

  return (
    <Layout>
      <section className="offline-onboarding-hero">
        <div>
          <span>Offline-first import</span>
          <h2>CSV import is mandatory for offline merchants</h2>
          <p>Build campaigns for {businessName} from Excel-first customer data with cleaning, dedupe, opt-in capture, and instant segmentation.</p>
        </div>
        <button onClick={() => nav("/contacts")}>Open Contacts Import</button>
        <button onClick={() => nav("/data-sources")}>Open Data Sources</button>
      </section>

      <section className="offline-pipeline">
        <article className="offline-step"><strong>1. Upload CSV</strong><span>Your exported customer CSV file</span></article>
        <article className="offline-step"><strong>2. Auto-detect columns</strong><span>Suggest field mapping by header + sample values</span></article>
        <article className="offline-step"><strong>3. Map columns</strong><span>Phone, name, city, spend, product, purchase date</span></article>
        <article className="offline-step"><strong>4. Clean phone numbers</strong><span>E.164 normalization + country fallback</span></article>
        <article className="offline-step"><strong>5. Deduplicate + validate</strong><span>Merge duplicates, isolate invalid numbers</span></article>
        <article className="offline-step"><strong>6. Consent + tagging</strong><span>Opt-in source, import tag, create segment</span></article>
      </section>

      <section className="offline-mapping">
        <div className="offline-mapping-head">
          <h3>Detected Mapping</h3>
          <span>Uploaded: {fileName || "No file selected"}</span>
        </div>
        <div className="campaign-actions">
          <input type="file" accept=".csv,text/csv" onChange={(e) => onFileSelected(e.target.files?.[0] || null).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} />
        </div>
        <div className="offline-mapping-grid">
          <div><span>Phone column</span><strong>{mapping.phone_e164 || "Select below"}</strong></div>
          <div><span>Name column</span><strong>{mapping.name || "Select below"}</strong></div>
          <div><span>City column</span><strong>{mapping.city || "Select below"}</strong></div>
          <div><span>Spend column</span><strong>{mapping.total_spend || "Select below"}</strong></div>
          <div><span>Product column</span><strong>{mapping.last_product || "Select below"}</strong></div>
          <div><span>Purchase date column</span><strong>{mapping.last_purchase_at || "Select below"}</strong></div>
        </div>
        <div className="offline-minimum-grid" style={{ marginTop: 10 }}>
          {["phone_e164", "name", "city", "total_spend", "last_product", "last_purchase_at"].map((field) => (
            <div key={field}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>{field}</div>
              <select value={mapping[field] || ""} onChange={(e) => setMapping((prev) => ({ ...prev, [field]: e.target.value }))}>
                <option value="">-- choose column --</option>
                {headers.map((h) => <option key={`${field}:${h}`} value={h}>{h}</option>)}
              </select>
            </div>
          ))}
        </div>
        <div className="campaign-actions">
          <input placeholder="Opt-in source" value={optInSource} onChange={(e) => setOptInSource(e.target.value)} />
          <input placeholder="Import tag" value={importTag} onChange={(e) => setImportTag(e.target.value)} />
        </div>
        <div className="offline-mapping-grid">
          <div><span>Mobile Number</span><strong>phone</strong></div>
          <div><span>Customer Name</span><strong>name</strong></div>
          <div><span>City</span><strong>city</strong></div>
          <div><span>Purchase Amount</span><strong>total_spend</strong></div>
          <div><span>Item</span><strong>last_product</strong></div>
          <div><span>Bill Date</span><strong>last_purchase_at</strong></div>
        </div>
      </section>

      <section className="offline-minimum">
        <h3>Minimum Offline Data Supported</h3>
        <div className="offline-minimum-grid">
          {["customer name", "phone number", "last purchase date", "product/category bought", "bill amount", "location", "salesperson", "notes"].map((f) => (
            <div key={f}>{f}</div>
          ))}
        </div>
      </section>

      <section className="offline-contact-model">
        <h3>Minimum Contact Model</h3>
        <div className="offline-contact-fields">
          {["name", "phone", "city", "tags", "source", "opt_in_status", "last_seen_at", "last_message_at", "total_orders", "total_spend", "last_purchase_at", "custom_fields"].map((field) => (
            <code key={field}>{field}</code>
          ))}
        </div>
      </section>

      <section className="offline-sheets-sync">
        <div className="offline-mapping-head">
          <h3>Google Sheets Sync</h3>
          <span>Offline CRM accelerator</span>
        </div>
        <p className="offline-sheets-copy">Many offline businesses already run customer operations on Sheets. Sync it directly instead of forcing CRM migration first.</p>
        <div className="offline-sheets-flow">
          <article><strong>1. Connect Google Sheet</strong><span>Authorize read/write access for merchant workspace.</span></article>
          <article><strong>2. Choose worksheet</strong><span>Select target tab for contacts and follow-ups.</span></article>
          <article><strong>3. Map columns</strong><span>Map Name, Phone, City, Product, Bill Amount, Follow-up Date, Staff.</span></article>
          <article><strong>4. Auto-sync schedule</strong><span>Every 15 minutes or hourly.</span></article>
          <article><strong>5. Detect new rows</strong><span>Create new contacts from appended rows.</span></article>
          <article><strong>6. Update contacts</strong><span>Apply edits to tags, spend, reminders, and attributes.</span></article>
          <article><strong>7. Log sync errors</strong><span>Track invalid phones, missing columns, and permission issues.</span></article>
        </div>
        <div className="offline-sheets-example">
          <div className="offline-sheets-example-head">
            <strong>Example Sheet</strong>
            <span>Name | Phone | City | Product | Bill Amount | Follow-up Date | Staff</span>
          </div>
          <p>Your app converts this into contacts, segments, reminders, and campaigns.</p>
        </div>
      </section>

      <section className="offline-convo-enrichment">
        <div className="offline-mapping-head">
          <h3>WhatsApp Conversation Enrichment</h3>
          <span>Auto CRM from chat text</span>
        </div>
        <p className="offline-sheets-copy">When offline merchants do not have structured records, profile fields are learned from live WhatsApp conversations.</p>
        <div className="offline-enrichment-grid">
          <article>
            <strong>Detect from chat text</strong>
            <ul>
              {["name", "location", "product interest", "budget", "purchase intent", "complaint", "language preference", "size preference", "delivery area", "payment preference"].map((x) => <li key={x}>{x}</li>)}
            </ul>
          </article>
          <article className="offline-enrichment-example">
            <strong>Example message</strong>
            <p>"Do you have XL black kurti under 1500? I am from Kochi."</p>
          </article>
          <article>
            <strong>Saved into CRM automatically</strong>
            <ul>
              <li>Interest: kurti</li>
              <li>Size: XL</li>
              <li>Color: black</li>
              <li>Budget: under ₹1500</li>
              <li>Location: Kochi</li>
              <li>Intent: high</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="offline-qr-optin">
        <div className="offline-mapping-head">
          <h3>QR Code Opt-in Poster</h3>
          <span>Consent-first in-store acquisition</span>
        </div>
        <p className="offline-sheets-copy">Print this at the counter. Customer scans, WhatsApp opens, prefilled "{qrMessage || "START"}" message is sent, and CRM captures consent with branch and source.</p>
        <div className="offline-qr-grid">
          <article className="offline-qr-poster">
            <span>Scan to get offers on WhatsApp</span>
            <strong>Join VIP customer list</strong>
            <img src={qrImageUrl} alt="Store QR opt-in" />
            <small>Also used for warranty registration, bill updates, and new collection alerts.</small>
          </article>
          <article className="offline-qr-config">
            <label>Business WhatsApp Number (digits only)<input value={qrPhoneNumber} onChange={(e) => setQrPhoneNumber(e.target.value)} placeholder="919876543210" /></label>
            <label>Prefilled Message (from Business Settings)<input value={qrMessage} onChange={(e) => setQrMessage(e.target.value)} placeholder="e.g. START" /></label>
            <label>Store Branch<input value={qrBranch} onChange={(e) => setQrBranch(e.target.value)} placeholder="Branch name" /></label>
            <label>Sample Customer Phone<input value={qrPreviewPhone} onChange={(e) => setQrPreviewPhone(e.target.value)} placeholder="+919876543210" /></label>
            <label>Sample Customer Name<input value={qrCaptureName} onChange={(e) => setQrCaptureName(e.target.value)} placeholder="Customer name" /></label>
            <div className="campaign-actions">
              <a href={qrJoinUrl} target="_blank" rel="noreferrer">Open WhatsApp Join Link</a>
              <button onClick={() => window.print()}>Print Poster</button>
              <button onClick={() => simulateQrOptIn().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Simulate "{qrMessage || "START"}" Capture</button>
            </div>
            <div className="offline-qr-meta">
              <code>source: in_store_qr</code>
              <code>tag: walk_in_customer</code>
              <code>branch: {qrBranch || "not set"}</code>
            </div>
          </article>
        </div>
      </section>

      <section className="offline-campaigns">
        <h3>Campaigns You Can Launch Immediately</h3>
        <ul>
          <li>Send to customers who bought sarees in last 60 days</li>
          <li>Send to customers from a selected branch/city</li>
          <li>Send to customers with bill value above ₹2,000</li>
          <li>Send to gold customers</li>
          <li>Send to customers tagged "wedding enquiry"</li>
        </ul>
      </section>
      <section className="offline-registration-flow">
        <div className="offline-mapping-head">
          <h3>Digital Bill / Warranty Registration</h3>
          <span>Consent-first counter flow</span>
        </div>
        <p className="offline-sheets-copy">Use in-store actions to collect verified WhatsApp opt-ins with purchase context and follow-up lifecycle fields.</p>
        <div className="offline-reg-grid">
          <article>
            <strong>Use cases</strong>
            <ul>
              {["Send digital bill on WhatsApp", "Register warranty", "Join loyalty program", "Get exchange policy", "Get styling tips", "Get next offer", "Book service appointment"].map((x) => <li key={x}>{x}</li>)}
            </ul>
          </article>
          <article className="offline-reg-form">
            <label>Flow type<select value={regType} onChange={(e) => setRegType(e.target.value)}>
              <option value="digital_bill">Digital bill</option><option value="warranty">Warranty</option><option value="loyalty">Loyalty</option><option value="exchange_policy">Exchange policy</option><option value="styling_tips">Styling tips</option><option value="next_offer">Next offer</option><option value="service_appointment">Service appointment</option>
            </select></label>
            <label>Customer phone<input value={regPhone} onChange={(e) => setRegPhone(e.target.value)} /></label>
            <label>Customer name<input value={regName} onChange={(e) => setRegName(e.target.value)} /></label>
            <label>Branch<input value={regBranch} onChange={(e) => setRegBranch(e.target.value)} /></label>
            <label>Product purchased<input value={regProduct} onChange={(e) => setRegProduct(e.target.value)} /></label>
            <label>Purchase date<input type="date" value={regPurchaseDate} onChange={(e) => setRegPurchaseDate(e.target.value)} /></label>
            <label>Warranty until<input type="date" value={regWarrantyDate} onChange={(e) => setRegWarrantyDate(e.target.value)} /></label>
            <label>Service reminder<input type="date" value={regServiceReminder} onChange={(e) => setRegServiceReminder(e.target.value)} /></label>
            <label>Consent reply<select value={regConsent} onChange={(e) => setRegConsent((e.target.value === "NO" ? "NO" : "YES"))}><option value="YES">YES</option><option value="NO">NO</option></select></label>
            <div className="offline-reg-preview">Reply prompt: "Reply YES to receive warranty updates and service reminders on WhatsApp."</div>
            <button onClick={() => submitOfflineRegistration().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Save Registration</button>
          </article>
          <article>
            <strong>Captured outcome</strong>
            <ul>
              <li>opt-in: {regConsent === "YES" ? "captured" : "not captured"}</li>
              <li>product purchased: {regProduct || "-"}</li>
              <li>purchase date: {regPurchaseDate || "-"}</li>
              <li>warranty date: {regWarrantyDate || "-"}</li>
              <li>service reminder: {regServiceReminder || "-"}</li>
              <li>future campaign eligibility: {regConsent === "YES" ? "eligible" : "restricted"}</li>
            </ul>
          </article>
        </div>
      </section>

      <div className="campaign-actions">
        <button disabled={busy} onClick={() => runImport().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>{busy ? "Importing..." : "Run CSV Import"}</button>
        <button onClick={() => createSegmentFromImport().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Create Segment from Import Tag</button>
        <button onClick={() => nav("/contacts")}>Open Contacts</button>
        <button onClick={() => nav("/campaigns/new")}>Create Campaign from Segment</button>
        <button onClick={() => nav("/dashboard")}>Back to Dashboard</button>
      </div>
      {msg ? <p>{msg}</p> : null}
      {jobId ? <p>Import Job ID: {jobId}</p> : null}
      {jobState ? <pre>{JSON.stringify(jobState, null, 2)}</pre> : null}
    </Layout>
  );
}

function DataSourcesPage() {
  const nav = useNavigate();
  const [rows, setRows] = useState<ContactCRMRecord[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [dupSuggestions, setDupSuggestions] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    (async () => {
      try {
        const payload = await api<unknown>("/contacts?limit=500");
        setRows(normalizeQueryPage<ContactCRMRecord>(payload).items);
      } catch (e) {
        setMsg(`Contacts load failed: ${toUserErrorMessage(e)}`);
      }
      try {
        const l = await api<any>("/integrations/google-sheets/logs");
        setLogs(Array.isArray(l) ? l : Array.isArray(l?.items) ? l.items : []);
      } catch {
        setLogs([]);
      }
      try {
        const d = await api<any[]>("/contacts/duplicates/suggestions?limit=400");
        setDupSuggestions(Array.isArray(d) ? d : []);
      } catch {
        setDupSuggestions([]);
      }
    })().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, []);

  const toSource = (r: ContactCRMRecord) => String(r.custom_attributes?.["source"] || "").toLowerCase();
  const scoreFor = (subset: ContactCRMRecord[]) => {
    if (!subset.length) return 0;
    const validPhone = subset.filter((r) => Boolean(r.phone_e164 && String(r.phone_e164).startsWith("+"))).length;
    const opted = subset.filter((r) => r.opt_in_status === "opted_in").length;
    const named = subset.filter((r) => Boolean((r.name || "").trim())).length;
    return Math.round(((validPhone / subset.length) * 0.45 + (opted / subset.length) * 0.35 + (named / subset.length) * 0.2) * 100);
  };
  const bySource = (keys: string[]) => rows.filter((r) => keys.some((k) => toSource(r).includes(k)));
  const fmtLast = (subset: ContactCRMRecord[]) => {
    const values = subset.map((r) => r.updated_at || r.last_seen_at || r.last_message_at).filter(Boolean) as string[];
    if (!values.length) return "No sync yet";
    const latest = values.sort().at(-1);
    return latest ? new Date(latest).toLocaleString() : "No sync yet";
  };
  const calc = (label: string, subset: ContactCRMRecord[], errors = 0, duplicatesRemoved = 0) => ({
    label,
    contactsImported: subset.length,
    lastSync: fmtLast(subset),
    errors,
    duplicatesRemoved,
    optInStatus: subset.length ? `${subset.filter((r) => r.opt_in_status === "opted_in").length}/${subset.length} opted in` : "No contacts",
    qualityScore: scoreFor(subset),
  });

  const sheetsErrors = logs.filter((x) => String(x?.status || "").toLowerCase() === "failed").length;
  const sources = [
    calc("WhatsApp conversations", bySource(["whatsapp", "conversation"])),
    calc("CSV uploads", bySource(["csv_import", "import"])),
    calc("Google Sheets", bySource(["offline_sheet_import", "google_sheets"]), sheetsErrors),
    calc("Manual contacts", bySource(["crm_manual", "manual"])),
    calc("QR opt-ins", bySource(["in_store_qr"])),
    calc("POS imports", bySource(["pos"])),
    calc("Payment links", bySource(["payment_link"])),
    calc("Order forms", bySource(["order_form"])),
    calc("Web forms", bySource(["web_form", "website_form"])),
    calc("Agent-created records", bySource(["agent", "offline_counter_registration"])),
  ];

  const missingName = rows.filter((r) => !String(r.name || "").trim()).length;
  const invalidPhone = rows.filter((r) => {
    const p = String(r.phone_e164 || "").trim();
    return !p || !/^\+[1-9]\d{7,14}$/.test(p);
  }).length;
  const unknownOptInSource = rows.filter((r) => !String(r.opt_in_source || "").trim()).length;
  const noPurchaseHistory = rows.filter((r) => {
    const a = r.custom_attributes || {};
    return !(a["total_spend"] || a["last_purchase_at"] || a["product_purchased"] || a["last_product"]);
  }).length;
  const duplicateDetected = dupSuggestions.length;
  const total = Math.max(rows.length, 1);
  const qualityScore = Math.max(
    0,
    Math.round(
      100 -
      ((missingName / total) * 22 +
        (invalidPhone / total) * 28 +
        (unknownOptInSource / total) * 20 +
        (noPurchaseHistory / total) * 18 +
        (duplicateDetected / total) * 12) * 100
    )
  );

  const mergeDuplicatesOneClick = async () => {
    try {
      const safe = dupSuggestions.filter((s) => s.safe_to_merge).slice(0, 50);
      if (!safe.length) {
        setMsg("No safe duplicate pairs available for one-click merge.");
        return;
      }
      let merged = 0;
      for (const item of safe) {
        await api("/contacts/merge", "POST", {
          source_contact_id: item.source_contact_id,
          target_contact_id: item.target_contact_id,
        });
        merged += 1;
      }
      setMsg(`Merged ${merged} safe duplicate pairs.`);
      const refreshed = await api<unknown>("/contacts?limit=500");
      setRows(normalizeQueryPage<ContactCRMRecord>(refreshed).items);
      const d = await api<any[]>("/contacts/duplicates/suggestions?limit=400");
      setDupSuggestions(Array.isArray(d) ? d : []);
    } catch (e) {
      setMsg(`Merge failed: ${toUserErrorMessage(e)}`);
    }
  };

  return (
    <Layout>
      <section className="offline-onboarding-hero">
        <div>
          <span>Operational visibility</span>
          <h2>Data Sources</h2>
          <p>Track import quality and consent hygiene across every offline acquisition channel.</p>
        </div>
        <button onClick={() => nav("/customer-book")}>Open Customer Book</button>
      </section>
      <section className="data-quality-score">
        <div className="data-quality-head">
          <h3>Customer Data Quality: {qualityScore}/100</h3>
          <span>Offline data quality monitor</span>
        </div>
        <div className="data-quality-problems">
          <article><strong>{missingName.toLocaleString()}</strong><span>contacts have no name</span></article>
          <article><strong>{invalidPhone.toLocaleString()}</strong><span>contacts have invalid phone numbers</span></article>
          <article><strong>{unknownOptInSource.toLocaleString()}</strong><span>contacts have unknown opt-in source</span></article>
          <article><strong>{noPurchaseHistory.toLocaleString()}</strong><span>contacts have no purchase history</span></article>
          <article><strong>{duplicateDetected.toLocaleString()}</strong><span>duplicate numbers detected</span></article>
        </div>
        <div className="campaign-actions">
          <button onClick={() => nav("/onboarding/offline")}>Clean phone numbers</button>
          <button onClick={() => mergeDuplicatesOneClick().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Merge duplicates</button>
          <button onClick={() => nav("/inbox")}>Ask customers to update profile</button>
          <button onClick={() => nav("/onboarding/offline")}>Create opt-in QR campaign</button>
          <button onClick={() => nav("/onboarding/offline")}>Import purchase history</button>
        </div>
      </section>
      <section className="data-sources-grid">
        {sources.map((s) => (
          <article key={s.label} className="data-source-card">
            <div className="data-source-head">
              <h3>{s.label}</h3>
              <strong>{s.qualityScore}/100</strong>
            </div>
            <div className="data-source-metrics">
              <div><span>Contacts imported</span><strong>{s.contactsImported.toLocaleString()}</strong></div>
              <div><span>Last sync</span><strong>{s.lastSync}</strong></div>
              <div><span>Errors</span><strong>{s.errors}</strong></div>
              <div><span>Duplicates removed</span><strong>{s.duplicatesRemoved}</strong></div>
              <div><span>Opt-in status</span><strong>{s.optInStatus}</strong></div>
              <div><span>Data quality score</span><strong>{s.qualityScore}/100</strong></div>
            </div>
          </article>
        ))}
      </section>
      {msg ? <p>{msg}</p> : null}
    </Layout>
  );
}

function CustomerBookPage() {
  const nav = useNavigate();
  const [rows, setRows] = useState<ContactCRMRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [record, setRecord] = useState<ContactCRMRecord | null>(null);
  const [timeline, setTimeline] = useState<any>(null);
  const [search, setSearch] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    const query: QueryState = { limit: 150, sortBy: "updated_at", sortDir: "desc", search };
    const data = normalizeQueryPage<ContactCRMRecord>(await api<unknown>(`/contacts/crm/records?${toQueryString(query)}`));
    setRows(data.items);
    if (!selectedId && data.items.length) setSelectedId(data.items[0].id);
  };

  useEffect(() => { load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV })); }, []);
  useEffect(() => {
    if (!selectedId) return;
    api<ContactCRMRecord>(`/contacts/${selectedId}/record`).then(setRecord).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
    api(`/contacts/${selectedId}/timeline`).then(setTimeline).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }));
  }, [selectedId]);

  const rel = (value?: string | null) => {
    if (!value) return "-";
    const mins = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  };
  const filtered = useMemo(() => rows.filter((r) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [r.name, r.phone_e164, r.wa_id, (r.tags || []).join(","), String(r.custom_attributes?.["assigned_staff"] || "")]
      .some((x) => String(x || "").toLowerCase().includes(q));
  }), [rows, search]);

  const messageEvents = (timeline?.message_events || []) as any[];
  const inbound = messageEvents.filter((m) => String(m.direction || "").toLowerCase() === "inbound");
  const outbound = messageEvents.filter((m) => String(m.direction || "").toLowerCase() === "outbound");
  const attrs = (record?.custom_attributes || {}) as Record<string, unknown>;
  const notes = (attrs["notes"] as string[] | undefined) || [];
  const followUps = [attrs["next_follow_up"], ...(Array.isArray(attrs["offline_visit_logs"]) ? (attrs["offline_visit_logs"] as any[]).map((x) => x?.next_follow_up) : [])].filter(Boolean);
  const orders = (attrs["orders"] as any[] | undefined) || [];
  const enquiryHistory = (attrs["enquiry_history"] as any[] | undefined) || [];
  const purchaseHistory = orders.length ? orders : (attrs["offline_visit_logs"] as any[] | undefined)?.filter((x) => x?.purchased_item || x?.amount) || [];
  const lifetimeValue = (() => {
    if (attrs["total_spend"] != null && !Number.isNaN(Number(attrs["total_spend"]))) return Number(attrs["total_spend"]);
    const fromOrders = orders.reduce((sum, o) => sum + (Number(o?.amount || 0) || 0), 0);
    return fromOrders || 0;
  })();
  const assignedStaff = String(attrs["assigned_staff"] || attrs["salesperson"] || "-");
  const lastInteraction = record?.last_message_at || record?.last_seen_at || record?.last_campaign_at || null;

  const setAssignedStaff = async (staff: string) => {
    if (!record) return;
    try {
      const next = { ...(record.custom_attributes || {}), assigned_staff: staff.trim() || null };
      await api(`/contacts/${record.id}`, "PATCH", { custom_attributes: next });
      setMsg("Assigned staff updated.");
      const r = await api<ContactCRMRecord>(`/contacts/${record.id}/record`);
      setRecord(r);
      await load();
    } catch (e) {
      setMsg(toUserErrorMessage(e));
    }
  };

  return (
    <Layout>
      <section className="offline-onboarding-hero">
        <div>
          <span>Offline CRM Core</span>
          <h2>Customer Book</h2>
          <p>Digital customer book for offline merchants: replaces notebook, Excel, and scattered phone contacts.</p>
        </div>
        <div className="campaign-actions">
          <button onClick={() => nav("/data-sources")}>Data Sources</button>
          <button onClick={() => nav("/onboarding/offline")}>Offline Onboarding</button>
        </div>
      </section>
      <section className="customer-book-arch">
        <h3>Offline Architecture</h3>
        <div className="customer-book-arch-flow">
          {["Offline Data Sources", "CSV / Sheets / POS / QR / Manual / WhatsApp", "Contact Import Pipeline", "Phone normalization + dedupe + opt-in capture", "Customer Profile", "Segments", "Campaigns / Automations / Inbox / Follow-ups"].map((s) => <article key={s}>{s}</article>)}
        </div>
      </section>
      <section className="customer-book-layout">
        <article className="customer-book-list">
          <div className="customer-book-list-head">
            <h3>All Customers</h3>
            <input placeholder="Search name/phone/tag/staff" value={search} onChange={(e) => setSearch(e.target.value)} />
            <button onClick={() => load().catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))}>Refresh</button>
          </div>
          <div className="customer-book-table">
            <table>
              <thead>
                <tr><th>Customer</th><th>Tags</th><th>LTV</th><th>Opt-in</th><th>Last Interaction</th><th>Staff</th></tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const a = (r.custom_attributes || {}) as Record<string, unknown>;
                  const ltv = a["total_spend"] != null ? Number(a["total_spend"]) : 0;
                  const staff = String(a["assigned_staff"] || a["salesperson"] || "-");
                  const li = r.last_message_at || r.last_seen_at || r.last_campaign_at;
                  return (
                    <tr key={r.id} className={selectedId === r.id ? "selected" : ""} onClick={() => setSelectedId(r.id)}>
                      <td>{r.name || "Unknown"}<div className="cb-sub">{r.phone_e164 || r.wa_id || "-"}</div></td>
                      <td>{(r.tags || []).slice(0, 3).join(", ") || "-"}</td>
                      <td>{ltv ? `₹${ltv}` : "-"}</td>
                      <td>{r.opt_in_status}</td>
                      <td>{rel(li)}</td>
                      <td>{staff}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </article>
        <aside className="customer-book-detail">
          <h3>Customer Profile</h3>
          {!record ? <p>Select a customer.</p> : (
            <>
              <div className="customer-book-kpis">
                <div><span>Purchase history</span><strong>{purchaseHistory.length}</strong></div>
                <div><span>Enquiry history</span><strong>{enquiryHistory.length || inbound.length}</strong></div>
                <div><span>WhatsApp history</span><strong>{messageEvents.length}</strong></div>
                <div><span>Notes</span><strong>{notes.length}</strong></div>
                <div><span>Follow-ups</span><strong>{followUps.length}</strong></div>
                <div><span>Lifetime value</span><strong>{lifetimeValue ? `₹${lifetimeValue}` : "-"}</strong></div>
                <div><span>Opt-in status</span><strong>{record.opt_in_status}</strong></div>
                <div><span>Assigned staff</span><strong>{assignedStaff}</strong></div>
              </div>
              <div className="customer-book-panels">
                <article><h4>Purchase History</h4><pre>{JSON.stringify(purchaseHistory, null, 2)}</pre></article>
                <article><h4>Enquiry History</h4><pre>{JSON.stringify(enquiryHistory.length ? enquiryHistory : inbound, null, 2)}</pre></article>
                <article><h4>WhatsApp History</h4><pre>{JSON.stringify({ inbound, outbound }, null, 2)}</pre></article>
                <article><h4>Notes</h4><pre>{JSON.stringify(notes, null, 2)}</pre></article>
                <article><h4>Follow-ups</h4><pre>{JSON.stringify(followUps, null, 2)}</pre></article>
                <article>
                  <h4>Staff Assignment</h4>
                  <div className="campaign-actions">
                    <input placeholder="assigned staff" defaultValue={assignedStaff === "-" ? "" : assignedStaff} onBlur={(e) => setAssignedStaff(e.target.value).catch((e) => safeLogClientError("ui_async_failed", e, { exposeToConsole: import.meta.env.DEV }))} />
                  </div>
                </article>
              </div>
              <p>{msg}</p>
              <div className="cb-meta">Last interaction: {lastInteraction ? new Date(lastInteraction).toLocaleString() : "-"}</div>
            </>
          )}
        </aside>
      </section>
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/settings/whatsapp-setup" element={<WhatsAppSetupPage />} />
      <Route path="/embedded-signup" element={<WhatsAppSetupPage />} />
      <Route path="/embedded-signup/next" element={<EmbeddedSignupNextPage />} />
      <Route element={<RequireAuth><CommandCenterLayout /></RequireAuth>}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/inbox" element={<InboxReplicaPage />} />
        <Route path="/contacts" element={<ContactsCommandCenterPage />} />
        <Route path="/contacts/:id" element={<ContactDetailPage />} />
        <Route path="/templates" element={<TemplateApprovalPage />} />
        <Route path="/automations" element={<PlaceholderPage title="Automations" subtitle="Flows, triggers, and journey controls." />} />
        <Route path="/commerce" element={<PlaceholderPage title="Commerce" subtitle="Orders, carts, click-through and conversion actions." />} />
        <Route path="/analytics" element={<DashboardPage />} />
        <Route path="/billing" element={<RevenuePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin-support" element={<PlaceholderPage title="Admin / Support" subtitle="Audit trails, diagnostics, runbooks, and support tools." />} />
        <Route path="/onboarding/shopify" element={<ShopifyOnboardingPage />} />
        <Route path="/onboarding/offline" element={<OfflineOnboardingPage />} />
        <Route path="/data-sources" element={<DataSourcesPage />} />
        <Route path="/customer-book" element={<CustomerBookPage />} />

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


















export {
  RequireAuth,
  CommandCenterLayout,
  LoginPage,
  WhatsAppSetupPage,
  EmbeddedSignupNextPage,
  InboxReplicaPage,
  ContactsCommandCenterPage,
  TemplateApprovalPage,
  RevenuePage,
  DashboardPage,
  ContactDetailPage,
  PlaceholderPage,
  SettingsPage,
  ShopifyOnboardingPage,
  OfflineOnboardingPage,
  DataSourcesPage,
  CustomerBookPage,
  CampaignListPage,
  CreateWizardPage,
  CampaignDetailHub,
  SourceStepPage,
  TemplateStepPage,
  MappingStepPage,
  PreviewLaunchStepPage,
  TestSendStepPage,
  ScheduleLaunchStepPage,
  CampaignLiveStatusPage,
  RecipientFailureReportPage,
  CampaignAnalyticsPage,
  CampaignCostReportPage,
  WhatsAppHealthDashboardPage,
};















