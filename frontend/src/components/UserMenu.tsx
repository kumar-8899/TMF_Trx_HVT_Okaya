/** Consolidated user control in the AppBar — the avatar opens a dropdown with the
 * signed-in identity, Log out, and (super_admin) Exit station. Folds what used to be a
 * separate SessionPanel + ExitButton into one control so the bar stays uncluttered.
 *
 * Exit station calls POST /system/shutdown — the full graceful backend shutdown (the
 * Python controller is stopped, instruments driven to safe state, bridge offline, DB
 * closed) then the process exits without relaunching. */
import { CheckCircleOutline, Logout, ManageAccountsOutlined, PowerSettingsNew } from "@mui/icons-material";
import {
  Avatar, Backdrop, Box, ButtonBase, Chip, CircularProgress, Divider, ListItemIcon,
  ListItemText, Menu, MenuItem, Stack, Typography,
} from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "./ui";

export function UserMenu() {
  const { principal, logout, can } = useAuth();
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const [confirm, setConfirm] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [stopped, setStopped] = useState(false);
  if (!principal) return null;

  const isAdmin = principal.role === "super_admin";
  const initials = principal.username.slice(0, 2).toUpperCase();
  const close = () => setAnchor(null);

  // The backend dies mid-shutdown, so poll /healthz until it stops answering (connection
  // refused) → the process is really down → show a terminal state instead of a spinner.
  const waitUntilDown = async () => {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      try { await fetch("/healthz", { cache: "no-store" }); } catch { setStopped(true); return; }
    }
    setStopped(true);
  };
  const doExit = async () => {
    setConfirm(false); setExiting(true);
    try { await api.post("/system/shutdown", {}); } catch { /* backend exits mid-request */ }
    waitUntilDown();
  };

  return (
    <>
      <ButtonBase onClick={(e) => setAnchor(e.currentTarget)} aria-label="user menu"
        sx={{
          display: "flex", alignItems: "center", gap: 1, pl: 0.5, pr: 1, py: 0.5, borderRadius: 2,
          color: "rgba(255,255,255,0.92)", "&:hover": { bgcolor: "rgba(255,255,255,0.08)" },
        }}>
        <Avatar sx={{ width: 30, height: 30, fontSize: 12, bgcolor: "primary.main", color: "primary.contrastText" }}>
          {initials}
        </Avatar>
        <Box sx={{ display: { xs: "none", sm: "block" }, textAlign: "left", lineHeight: 1.15 }}>
          <Typography variant="body2" fontWeight={600}>{principal.username}</Typography>
          <Typography variant="caption" sx={{ opacity: 0.72 }}>{principal.role}</Typography>
        </Box>
      </ButtonBase>

      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}>
        <Box sx={{ px: 2, py: 1 }}>
          <Typography variant="subtitle2" fontWeight={700}>{principal.username}</Typography>
          <Chip size="small" label={principal.role} sx={{ height: 18, fontSize: 11, mt: 0.5 }} />
        </Box>
        <Divider />
        {can("AUTH.MANAGE_USERS") && (
          <MenuItem onClick={() => { close(); navigate("/users"); }}>
            <ListItemIcon><ManageAccountsOutlined fontSize="small" /></ListItemIcon>
            <ListItemText>Manage users</ListItemText>
          </MenuItem>
        )}
        <MenuItem onClick={() => { close(); logout(); }}>
          <ListItemIcon><Logout fontSize="small" /></ListItemIcon>
          <ListItemText>Log out</ListItemText>
        </MenuItem>
        {isAdmin && [
          <Divider key="exit-divider" />,
          <MenuItem key="exit" onClick={() => { close(); setConfirm(true); }} sx={{ color: "error.main" }}>
            <ListItemIcon><PowerSettingsNew fontSize="small" color="error" /></ListItemIcon>
            <ListItemText>Exit station</ListItemText>
          </MenuItem>,
        ]}
      </Menu>

      <ConfirmDialog
        open={confirm}
        title="Exit the station?"
        body="Safely stops the controller (instruments are driven to safe state), closes the app, and does NOT restart it. Relaunch from the desktop shortcut to bring it back."
        confirmLabel="Exit"
        danger
        onConfirm={doExit}
        onClose={() => setConfirm(false)}
      />

      <Backdrop open={exiting} sx={{ zIndex: (t) => t.zIndex.drawer + 2, color: "#fff" }}>
        <Stack spacing={2} alignItems="center">
          {stopped ? (
            <>
              <CheckCircleOutline sx={{ fontSize: 48 }} />
              <Typography>Station stopped. You can close this window.</Typography>
            </>
          ) : (
            <>
              <CircularProgress color="inherit" />
              <Typography>Station is shutting down…</Typography>
            </>
          )}
        </Stack>
      </Backdrop>
    </>
  );
}
