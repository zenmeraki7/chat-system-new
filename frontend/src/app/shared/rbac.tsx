import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

export type Permission =
  | "contacts.export"
  | "contacts.bulk_suppress"
  | "contacts.bulk_tag"
  | "contacts.bulk_edit"
  | "whatsapp.manage_setup"
  | "templates.sync"
  | "campaigns.launch"
  | "billing.read"
  | "billing.view";

const ROLE_PERMISSIONS: Record<string, Permission[]> = {
  owner: ["contacts.export", "contacts.bulk_suppress", "contacts.bulk_tag", "contacts.bulk_edit", "whatsapp.manage_setup", "templates.sync", "campaigns.launch", "billing.read", "billing.view"],
  admin: ["contacts.export", "contacts.bulk_suppress", "contacts.bulk_tag", "contacts.bulk_edit", "whatsapp.manage_setup", "templates.sync", "campaigns.launch", "billing.read", "billing.view"],
  manager: ["contacts.export", "contacts.bulk_tag", "contacts.bulk_edit", "templates.sync", "campaigns.launch", "billing.read", "billing.view"],
  agent: ["contacts.bulk_tag"],
};

function getStoredPermissions(): Set<string> {
  try {
    const raw = sessionStorage.getItem("auth_permissions");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return new Set(parsed.map((x) => String(x)));
    }
  } catch {
    // no-op
  }
  const role = String(sessionStorage.getItem("auth_role") || "").toLowerCase();
  return new Set(ROLE_PERMISSIONS[role] || []);
}

export function hasPermission(permission: Permission): boolean {
  return getStoredPermissions().has(permission);
}

export function Can({ permission, children, fallback = null }: { permission: Permission; children: ReactNode; fallback?: ReactNode }) {
  return hasPermission(permission) ? <>{children}</> : <>{fallback}</>;
}

export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  const location = useLocation();
  if (!hasPermission(permission)) return <Navigate to="/dashboard" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}
