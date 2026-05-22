import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { apiClient } from "../api/client";

type TenantContextValue = {
  businessId: string | null;
  businessName: string | null;
  role: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const [businessId, setBusinessId] = useState<string | null>(null);
  const [businessName, setBusinessName] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const ctx = await apiClient<{ business_id?: string; business_name?: string; role?: string }>("/tenant/context");
      setBusinessId(ctx.business_id || null);
      setBusinessName(ctx.business_name || null);
      setRole(ctx.role || null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh().catch(() => setLoading(false));
  }, []);

  const value = useMemo(() => ({ businessId, businessName, role, loading, refresh }), [businessId, businessName, role, loading]);
  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant() {
  const ctx = useContext(TenantContext);
  if (!ctx) throw new Error("useTenant must be used within TenantProvider");
  return ctx;
}
