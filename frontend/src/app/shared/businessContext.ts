import { api } from "../../api";
import { useEffect, useState } from "react";

export type BusinessProfile = {
  public_id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type WidgetSettings = {
  widget_color: string;
  widget_title: string;
  updated_at: string;
};

export type WhatsAppOnboardingStatusLite = {
  waba_id?: string | null;
  display_phone_number?: string | null;
};

export function useBusinessContext() {
  const [businessName, setBusinessName] = useState<string>("");
  const [wabaLabel, setWabaLabel] = useState<string>("");
  useEffect(() => {
    api<BusinessProfile>("/business/me")
      .then((b) => {
        if (b?.name) {
          setBusinessName(b.name);
          sessionStorage.setItem("auth_business_name", b.name);
        }
      })
      .catch(() => {});
    api<WhatsAppOnboardingStatusLite>("/whatsapp/onboarding/status")
      .then((s) => {
        const label = s?.display_phone_number || s?.waba_id || "";
        if (label) setWabaLabel(label);
      })
      .catch(() => {});
  }, []);
  return { businessName: businessName || "Business", wabaLabel: wabaLabel || "Not connected" };
}

export function useWidgetSettings() {
  const [widget, setWidget] = useState<WidgetSettings | null>(null);
  useEffect(() => {
    api<WidgetSettings>("/business/me/widget").then(setWidget).catch(() => {});
  }, []);
  return widget;
}
