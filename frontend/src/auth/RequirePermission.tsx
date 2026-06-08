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
