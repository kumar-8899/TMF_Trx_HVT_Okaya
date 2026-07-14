import { EnergySavingsLeaf, ArrowForward } from "@mui/icons-material";
import { Box, ButtonBase, CircularProgress, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";

/** "Relaunch to update" chip — shown in the AppBar when a signed update has been
 * applied (staged) and is waiting for a relaunch. Clicking it writes the launcher
 * marker + exits the backend (code 42); the launcher swaps the artifact and
 * restarts. Only meaningful under the launcher (a bare backend just stops). */
export function UpdateChip() {
  const [pending, setPending] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);

  const poll = () => api.get("/update/offers")
    .then((r) => setPending((r.offers || []).find((o: any) =>
      o.status === "apply_pending" || o.status === "relaunch_requested") || null))
    .catch(() => setPending(null));

  useEffect(() => {
    poll();
    const id = setInterval(poll, 15000);
    return () => clearInterval(id);
  }, []);

  if (!pending) return null;

  const relaunch = async () => {
    setBusy(true);
    try { await api.post(`/update/relaunch/${pending.release_id}`, {}); } catch { /* backend exits mid-request */ }
    // backend is going down; poll will resume when the launcher brings it back.
    setTimeout(poll, 8000);
  };

  return (
    <ButtonBase onClick={relaunch} disabled={busy}
      sx={{
        display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 0.75, borderRadius: 2,
        border: "1px solid", borderColor: "divider", bgcolor: "action.hover",
        "&:hover": { bgcolor: "action.selected" },
      }}>
      {busy ? <CircularProgress size={18} /> : <EnergySavingsLeaf fontSize="small" color="success" />}
      <Box sx={{ textAlign: "left", lineHeight: 1.1 }}>
        <Typography variant="body2" fontWeight={600}>
          {busy ? "Relaunching…" : "Relaunch to update"}
        </Typography>
        <Typography variant="caption" color="text.secondary">v{pending.version}</Typography>
      </Box>
      {!busy && <ArrowForward fontSize="small" color="action" />}
    </ButtonBase>
  );
}
