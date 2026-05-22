import { Navigate, Route, Routes } from "react-router-dom";
import RequireAuth from "./RequireAuth";
import CommandCenterLayout from "./CommandCenterLayout";
import { RequirePermission } from "./shared/rbac";
import LoginPage from "../domains/auth/LoginPage";
import WhatsAppSetupPage from "../domains/whatsapp-onboarding/WhatsAppSetupPage";
import EmbeddedSignupNextPage from "../domains/whatsapp-onboarding/EmbeddedSignupNextPage";
import InboxPage from "../domains/inbox/InboxPage";
import ContactsPage from "../domains/contacts/ContactsPage";
import TemplatesPage from "../domains/templates/TemplatesPage";
import BillingPage from "../domains/billing/BillingPage";
import {
  DashboardPage,
  ContactDetailPage,
  PlaceholderPage,
  SettingsPage,
  ShopifyOnboardingPage,
  OfflineOnboardingPage,
  DataSourcesPage,
  CustomerBookPage,
} from "../domains/core/pages";
import {
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
} from "../domains/campaigns/pages";

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><CommandCenterLayout /></RequireAuth>}>
        <Route path="/settings/whatsapp-setup" element={<RequirePermission permission="whatsapp.manage_setup"><WhatsAppSetupPage /></RequirePermission>} />
        <Route path="/embedded-signup" element={<WhatsAppSetupPage />} />
        <Route path="/embedded-signup/next" element={<EmbeddedSignupNextPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/contacts/:id" element={<ContactDetailPage />} />
        <Route path="/templates" element={<RequirePermission permission="templates.sync"><TemplatesPage /></RequirePermission>} />
        <Route path="/automations" element={<PlaceholderPage title="Automations" subtitle="Flows, triggers, and journey controls." />} />
        <Route path="/commerce" element={<PlaceholderPage title="Commerce" subtitle="Orders, carts, click-through and conversion actions." />} />
        <Route path="/analytics" element={<DashboardPage />} />
        <Route path="/billing" element={<RequirePermission permission="billing.read"><BillingPage /></RequirePermission>} />
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
        <Route path="/campaigns/:id/wizard/launch" element={<RequirePermission permission="campaigns.launch"><ScheduleLaunchStepPage /></RequirePermission>} />
        <Route path="/campaigns/:id/live" element={<CampaignLiveStatusPage />} />
        <Route path="/campaigns/:id/failures" element={<RecipientFailureReportPage />} />
        <Route path="/campaigns/:id/analytics" element={<CampaignAnalyticsPage />} />
        <Route path="/campaigns/:id/cost" element={<CampaignCostReportPage />} />
        <Route path="/campaigns/:id/whatsapp-health" element={<WhatsAppHealthDashboardPage />} />
      </Route>
    </Routes>
  );
}

