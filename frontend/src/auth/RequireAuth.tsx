import { Navigate, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [loading, setLoading] = useState(true);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    apiClient("/auth/me")
      .then(() => setOk(true))
      .catch(() => setOk(false))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page"><main><p>Checking session...</p></main></div>;
  if (!ok) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}
