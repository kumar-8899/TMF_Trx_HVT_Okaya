/** Shared UI primitives — the visual vocabulary every screen reuses. */
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogContentText,
  DialogTitle, Paper, Stack, Typography, useTheme,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { ReactNode } from "react";

import type { StatusPalette } from "../theme/theme";

// --- status -----------------------------------------------------------------

export type StatusKind = keyof StatusPalette; // pass | fail | running | idle | info

// Used when a component renders outside our ThemeProvider (e.g. unit tests with
// the default MUI theme, which has no palette.status).
const FALLBACK_STATUS: StatusPalette = {
  pass: "#22c55e", fail: "#ef4444", running: "#f59e0b", idle: "#64748b", info: "#38bdf8",
};

const KIND_BY_WORD: Record<string, StatusKind> = {
  pass: "pass", passed: "pass", ok: "pass", ready: "pass", online: "pass",
  loaded: "pass", active: "pass", finished: "pass", open: "pass", written: "pass",
  connected: "pass",
  fail: "fail", failed: "fail", error: "fail", offline: "fail", aborted: "fail",
  locked: "fail", critical: "fail", disconnected: "fail", "link down": "fail",
  running: "running", busy: "running", "in_progress": "running", warning: "running",
  pending: "running", password_reset_required: "running", degraded: "running", draft: "running",
  idle: "idle", stopped: "idle", inactive: "idle", skipped: "idle", unknown: "idle",
  "not ready": "fail", notready: "fail",
};

/** Map a backend status string to a StatusKind (falls back to idle). */
export function statusKind(value: string | undefined | null): StatusKind {
  if (!value) return "idle";
  return KIND_BY_WORD[value.toLowerCase().trim()] ?? "idle";
}

export function StatusChip({
  label, kind, size = "small",
}: { label: string; kind?: StatusKind; size?: "small" | "medium" }) {
  const t = useTheme();
  const k = kind ?? statusKind(label);
  const color = (t.palette.status ?? FALLBACK_STATUS)[k];
  return (
    <Chip
      size={size}
      label={label}
      sx={{
        color,
        bgcolor: alpha(color, 0.14),
        border: `1px solid ${alpha(color, 0.45)}`,
        "& .MuiChip-label": { fontWeight: 600 },
      }}
    />
  );
}

/** A small status lamp (dot) for dense rows / cards. */
export function StatusDot({ kind, size = 10 }: { kind: StatusKind; size?: number }) {
  const t = useTheme();
  const color = (t.palette.status ?? FALLBACK_STATUS)[kind];
  return (
    <Box
      component="span"
      sx={{
        width: size, height: size, borderRadius: "50%", display: "inline-block",
        bgcolor: color, boxShadow: `0 0 0 3px ${alpha(color, 0.2)}`,
      }}
    />
  );
}

// --- layout helpers ---------------------------------------------------------

export function PageHeader({
  title, subtitle, actions,
}: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      justifyContent="space-between"
      alignItems={{ xs: "flex-start", sm: "center" }}
      spacing={1}
      sx={{ mb: 2.5 }}
    >
      <Box>
        <Typography variant="h5">{title}</Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary">{subtitle}</Typography>
        )}
      </Box>
      {actions && <Stack direction="row" spacing={1} flexWrap="wrap">{actions}</Stack>}
    </Stack>
  );
}

export function Section({
  title, subtitle, actions, children, sx, bodyPad = 2,
}: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode;
  children: ReactNode; sx?: object; bodyPad?: number;
}) {
  const t = useTheme();
  // Section/chart headers are dark-navy bars (fallback for tests without our theme).
  const headerBg = t.palette.sectionHeader ?? "#1E3A5F";
  const onNavy = t.palette.onNavy ?? "#FFFFFF";
  return (
    <Paper sx={{ overflow: "hidden", ...sx }}>
      {(title || actions) && (
        <Box sx={{
          bgcolor: headerBg, color: onNavy, px: 2, py: 1.25,
          display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1,
        }}>
          <Box sx={{ minWidth: 0 }}>
            {title && (
              <Typography variant="subtitle1" fontWeight={600} sx={{ color: onNavy, lineHeight: 1.25 }}>
                {title}
              </Typography>
            )}
            {subtitle && (
              <Typography variant="caption" sx={{ color: alpha(onNavy, 0.72) }}>{subtitle}</Typography>
            )}
          </Box>
          {actions && <Stack direction="row" spacing={1} alignItems="center">{actions}</Stack>}
        </Box>
      )}
      <Box sx={{ p: bodyPad }}>{children}</Box>
    </Paper>
  );
}

export function EmptyState({
  message, icon, action,
}: { message: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <Stack alignItems="center" spacing={1.5} sx={{ py: 6, color: "text.secondary" }}>
      {icon}
      <Typography variant="body2">{message}</Typography>
      {action}
    </Stack>
  );
}

export function ConfirmDialog({
  open, title, body, confirmLabel = "Confirm", danger, onConfirm, onClose,
}: {
  open: boolean; title: string; body?: ReactNode; confirmLabel?: string;
  danger?: boolean; onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      {body && (
        <DialogContent>
          <DialogContentText component="div">{body}</DialogContentText>
        </DialogContent>
      )}
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          color={danger ? "error" : "primary"}
          onClick={() => { onConfirm(); onClose(); }}
        >
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
