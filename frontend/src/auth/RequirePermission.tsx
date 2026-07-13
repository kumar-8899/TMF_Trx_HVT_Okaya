import { Alert } from "@mui/material";

import { useAuth } from "./AuthContext";

// Cosmetic guard — hides UI the principal lacks. The API still enforces.
export function RequirePermission({ perm, children }: { perm: string; children: React.ReactNode }) {
  const { can } = useAuth();
  if (!can(perm)) {
    return <Alert severity="warning">You lack the <code>{perm}</code> permission.</Alert>;
  }
  return <>{children}</>;
}

// Role guard — restricts a page to a specific role (e.g. super_admin). Cosmetic; the
// API still enforces via require_role.
export function RequireRole({ role, children }: { role: string; children: React.ReactNode }) {
  const { principal } = useAuth();
  if (principal?.role !== role) {
    return <Alert severity="warning">This page requires the <code>{role}</code> role.</Alert>;
  }
  return <>{children}</>;
}
