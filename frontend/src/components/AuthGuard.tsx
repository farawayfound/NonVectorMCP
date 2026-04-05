import { Navigate } from "react-router-dom";
import type { User } from "../types";

interface Props {
  user: User | null;
  loading: boolean;
  requireAdmin?: boolean;
  children: React.ReactNode;
}

export function AuthGuard({ user, loading, requireAdmin, children }: Props) {
  if (loading) return <div className="loading">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (requireAdmin && user.role !== "admin") {
    return <div className="error-page">Admin access required.</div>;
  }
  return <>{children}</>;
}
