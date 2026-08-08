/** Exit the station safely (AppBar). Calls POST /system/shutdown, which runs the full
 * backend shutdown — the Python controller is stopped gracefully (instruments driven to
 * safe state), the bridge goes offline, the DB is closed — then the process exits without
 * relaunching. super_admin only (the endpoint is SYSTEM.SETTINGS-gated). */
import { PowerSettingsNew } from "@mui/icons-material";
import { Backdrop, CircularProgress, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import { useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "./ui";

export function ExitButton() {
  const { principal } = useAuth();
  const [confirm, setConfirm] = useState(false);
  const [exiting, setExiting] = useState(false);
  if (principal?.role !== "super_admin") return null;

  const doExit = async () => {
    setConfirm(false);
    setExiting(true);
    try { await api.post("/system/shutdown", {}); } catch { /* backend exits mid-request */ }
  };

  return (
    <>
      <Tooltip title="Exit the station safely">
        <IconButton size="small" aria-label="exit app" onClick={() => setConfirm(true)}
          sx={{ color: "rgba(255,255,255,0.85)" }}>
          <PowerSettingsNew fontSize="small" />
        </IconButton>
      </Tooltip>

      <ConfirmDialog
        open={confirm}
        title="Exit the station?"
        body="Safely stops the controller (instruments are driven to safe state), closes the app, and does NOT restart it. Relaunch from the desktop shortcut or dev.ps1 to bring it back."
        confirmLabel="Exit"
        danger
        onConfirm={doExit}
        onClose={() => setConfirm(false)}
      />

      <Backdrop open={exiting}
        sx={{ zIndex: (t) => t.zIndex.drawer + 2, color: "#fff" }}>
        <Stack spacing={2} alignItems="center">
          <CircularProgress color="inherit" />
          <Typography>Station is shutting down…</Typography>
        </Stack>
      </Backdrop>
    </>
  );
}
