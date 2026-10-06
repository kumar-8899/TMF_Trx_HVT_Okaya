/** Loud prompt when a finished run's result could NOT be delivered to MES.
 * Driven by persisted state (GET /mes/alerts), not a one-shot WebSocket frame — the stream hub is
 * latest-wins with no replay, so a frame could be missed. Polled every few seconds, and immediately when
 * a screen dispatches `tmf:mes-refresh` (e.g. on run-finished). Retry re-sends (the row is rebuilt from the
 * run record); Dismiss gives up on delivery and is audited on the backend. No-op when MES isn't loaded. */
import { ErrorOutline } from "@mui/icons-material";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "./ui";
import { MONO_STACK } from "../theme/theme";

interface MesFailure { run_id: string; serial: string; result?: string; error: string; ts: number }

export const MES_REFRESH_EVENT = "tmf:mes-refresh";
const POLL_MS = 5000;

export function MesAlertDialog() {
  const { can } = useAuth();
  const allowed = can("TEST.RUN");
  const [items, setItems] = useState<MesFailure[]>([]);
  const [snoozed, setSnoozed] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<MesFailure | null>(null);

  const poll = useCallback(async (): Promise<boolean> => {
    try {
      const r = await api.get("/mes/alerts");
      setItems(r?.items ?? []);
      return true;
    } catch (e: any) {
      return !(e?.status === 404 || e?.status === 403);   // MES not loaded / not permitted: stop polling
    }
  }, []);

  useEffect(() => {
    if (!allowed) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      const keepGoing = await poll();
      if (alive && keepGoing) timer = setTimeout(loop, POLL_MS);
    };
    loop();
    const onRefresh = () => { poll(); };
    window.addEventListener(MES_REFRESH_EVENT, onRefresh);
    return () => { alive = false; if (timer) clearTimeout(timer); window.removeEventListener(MES_REFRESH_EVENT, onRefresh); };
  }, [allowed, poll]);

  const retry = async (f: MesFailure) => {
    setBusy(f.run_id);
    try {
      const r = await api.post(`/mes/alerts/${encodeURIComponent(f.run_id)}/retry`);
      if (!r?.ok) setRetryError((m) => ({ ...m, [f.run_id]: r?.detail || "still failing" }));
      else setRetryError((m) => { const { [f.run_id]: _x, ...rest } = m; return rest; });
    } catch (e: any) {
      setRetryError((m) => ({ ...m, [f.run_id]: e.message }));
    } finally { setBusy(null); await poll(); }
  };
  const dismiss = async (f: MesFailure) => {
    setConfirm(null);
    try { await api.post(`/mes/alerts/${encodeURIComponent(f.run_id)}/dismiss`); } finally { await poll(); }
  };

  const fresh = items.filter((i) => !snoozed.includes(i.run_id));
  if (!allowed || fresh.length === 0) return null;

  return (
    <>
      <Dialog open maxWidth="sm" fullWidth aria-labelledby="mes-fail-title">
        <DialogTitle id="mes-fail-title" sx={{ display: "flex", alignItems: "center", gap: 1, color: "error.main" }}>
          <ErrorOutline /> {items.length === 1 ? "A test result was NOT sent to MES" : `${items.length} test results were NOT sent to MES`}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The next station will not see {items.length === 1 ? "this unit" : "these units"} until the result is delivered.
            Fix the cause (database reachable? table / columns changed?), then press <b>Retry</b>.
          </Typography>
          <Stack spacing={1.5}>
            {items.map((f) => (
              <Alert key={f.run_id} severity="error" sx={{ alignItems: "flex-start" }}
                action={
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="contained" color="error" disabled={busy === f.run_id} onClick={() => retry(f)}>Retry</Button>
                    <Button size="small" color="inherit" disabled={busy === f.run_id} onClick={() => setConfirm(f)}>Dismiss</Button>
                  </Stack>
                }>
                <Box>
                  <Typography variant="subtitle2" sx={{ fontFamily: MONO_STACK }}>
                    {f.serial || f.run_id}{f.result ? ` · ${f.result}` : ""}
                  </Typography>
                  <Typography variant="body2">{retryError[f.run_id] ?? f.error}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    run {f.run_id} · {new Date(f.ts * 1000).toLocaleString()}
                  </Typography>
                </Box>
              </Alert>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSnoozed(items.map((i) => i.run_id))}>Remind me later</Button>
        </DialogActions>
      </Dialog>
      <ConfirmDialog open={Boolean(confirm)} title="Dismiss without delivering?"
        body={`The result for ${confirm?.serial || confirm?.run_id} will NOT be sent to MES. This is recorded in the audit log.`}
        confirmLabel="Dismiss" danger onConfirm={() => confirm && dismiss(confirm)} onClose={() => setConfirm(null)} />
    </>
  );
}
