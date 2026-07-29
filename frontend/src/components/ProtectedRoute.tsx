import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore } from "@/auth/useAuthStore";

interface ProtectedRouteProps {
  children: ReactNode;
  /** UX-only convenience — hides/redirects away from screens a role has no use for.
   * The server enforces every actual permission check independently (see
   * backend/app/dependencies.py::require_permission); this never substitutes for that. */
  requiredRoles?: string[];
}

export function ProtectedRoute({ children, requiredRoles }: ProtectedRouteProps) {
  const { accessToken, user } = useAuthStore();

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRoles && user && !requiredRoles.includes(user.role_code)) {
    return <Navigate to="/calls" replace />;
  }

  return <>{children}</>;
}
