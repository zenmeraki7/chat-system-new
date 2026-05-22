import { Navigate } from "react-router-dom";
import { useTenant } from "../tenant/useTenant";

export default function RequireRole({ allow, children }: { allow: string[]; children: React.ReactNode }) {
  const { role, loading } = useTenant();
  if (loading) return <div className="page"><main><p>Loading role...</p></main></div>;
  if (!role || !allow.includes(role)) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
